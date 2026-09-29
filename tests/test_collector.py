import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import collector
from db import merge, quote_key, load_tombstones


def batch(text="First highlight", ident="one", device="kindle"):
    return {"source": "koreader", "device_id": device, "highlights": [{"id": ident, "book_title": "A Book", "author": "An Author", "text": text}]}


def quote(text="First highlight"):
    return {"highlight": text, "book_title": "A Book", "author": "An Author", "cover_url": ""}


def deletion():
    return {"source": "koreader", "device_id": "kindle", "highlights": [{"id": "one", "deleted": True}]}


class MemoryGitHub:
    def __init__(self, quotes=()):
        self.current = list(quotes)
        self.deleted = set()
    def read(self):
        return copy.deepcopy(self.current), set(self.deleted), "snapshot"
    def write(self, quotes, tombstones, snapshot):
        self.current = quotes
        self.deleted = set(tombstones)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = collector.Store(self.path / "inbox.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_durable_retry_and_edit(self):
        self.assertEqual(self.store.accept(batch()), ["one"])
        self.store.accept(batch())
        reopened = collector.Store(self.path / "inbox.sqlite3")
        rows = reopened.pending()
        self.assertEqual(len(rows), 1)
        reopened.accept(batch("Edited highlight"))
        reopened.acknowledge(rows)  # concurrent edit cannot be acknowledged by an older publish
        self.assertEqual(json.loads(reopened.pending()[0][3])["text"], "Edited highlight")
        reopened.acknowledge(reopened.pending())
        reopened.accept(batch("Edited highlight"))
        self.assertEqual(reopened.pending(), [])

    def test_invalid_batch_is_atomic(self):
        data = batch()
        data["highlights"].append({"id": "bad"})
        with self.assertRaises(ValueError):
            self.store.accept(data)
        self.assertEqual(self.store.pending(), [])
        for field, value in (("text", " " ), ("text", "a" * 65537), ("location", 123), ("id", None)):
            data = batch()
            data["highlights"][0][field] = value
            with self.assertRaises(ValueError):
                self.store.accept(data)

    def test_merge_compatibility_and_book_identity(self):
        old = [{"highlight": "First highlight", "book_title": "A Book", "author": "An Author", "cover_url": "cover"}]
        incoming = collector.archive_rows(self._accept(batch(" First  highlight\n", device="xteink")))
        self.assertEqual(merge(old, incoming), old)
        incoming[0]["book_title"] = "Other Book"
        self.assertEqual(len(merge(old, incoming)), 2)
        incoming[0]["book_title"] = "A Book"
        incoming[0]["highlight"] = "A second highlight"
        self.assertEqual(merge(old, incoming)[1]["cover_url"], "cover")
        self.assertEqual(set(incoming[0]), {"highlight", "book_title", "author", "cover_url"})
        self.assertNotIn("annotations", old[0])

    def _accept(self, payload):
        self.store.accept(payload)
        return self.store.pending()

    def test_conflict_rereads_preserves_latest_and_retries_without_duplication(self):
        self.store.accept(batch())
        class FakeGitHub:
            def __init__(self):
                self.current = [{"highlight": "Amazon quote", "book_title": "Amazon", "author": "Author", "cover_url": ""}]
                self.reads = 0
                self.write_shas = []
            def read(self):
                self.reads += 1
                return copy.deepcopy(self.current), set(), str(self.reads)
            def write(self, quotes, tombstones, sha):
                self.write_shas.append(sha)
                if self.reads == 1:
                    self.current.append({"highlight": "Concurrent quote", "book_title": "Amazon", "author": "Author", "cover_url": ""})
                    raise RuntimeError("conflict")
                self.current = quotes
        github = FakeGitHub()
        self.assertEqual(collector.publish_once(self.store, github), 1)
        self.assertEqual(len(github.current), 3)
        self.assertEqual(github.reads, 2)
        self.assertEqual(github.write_shas, ["1", "2"])
        self.assertEqual(self.store.pending(), [])
        self.store.accept(batch())
        self.assertEqual(collector.publish_once(self.store, github), 0)

    def test_remote_commit_with_lost_response_retries_without_duplicate(self):
        self.store.accept(batch())
        class LostResponseGitHub:
            def __init__(self):
                self.current = []
                self.reads = 0
                self.writes = 0
            def read(self):
                self.reads += 1
                return copy.deepcopy(self.current), set(), str(self.writes)
            def write(self, quotes, tombstones, sha):
                self.current = copy.deepcopy(quotes)
                self.writes += 1
                raise OSError("response lost after remote commit")
        github = LostResponseGitHub()
        self.assertEqual(collector.publish_once(self.store, github), 1)
        self.assertEqual(github.reads, 2)
        self.assertEqual(github.writes, 1)
        self.assertEqual([q["highlight"] for q in github.current], ["First highlight"])
        self.assertEqual(self.store.pending(), [])

    def test_edit_after_publication_preserves_previous_quote_and_adds_new(self):
        class MemoryGitHub:
            def __init__(self):
                self.current = []
                self.writes = 0
            def read(self):
                return copy.deepcopy(self.current), set(), str(self.writes)
            def write(self, quotes, tombstones, sha):
                self.current = copy.deepcopy(quotes)
                self.writes += 1
        github = MemoryGitHub()
        self.store.accept(batch())
        self.assertEqual(collector.publish_once(self.store, github), 1)
        original = copy.deepcopy(github.current[0])
        self.store.accept(batch("Edited highlight"))
        self.assertEqual(collector.publish_once(self.store, github), 1)
        self.assertEqual(github.current[0], original)
        self.assertEqual([q["highlight"] for q in github.current], ["First highlight", "Edited highlight"])
        self.assertEqual(self.store.pending(), [])
        self.store.accept(batch("Edited highlight"))
        self.assertEqual(collector.publish_once(self.store, github), 0)
        self.assertEqual(github.writes, 2)

    def test_failed_publication_retains_pending(self):
        self.store.accept(batch())
        class Offline:
            def read(self):
                raise RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            collector.publish_once(self.store, Offline())
        self.assertEqual(len(self.store.pending()), 1)

    def test_http_auth_and_acknowledgement(self):
        httpd = collector.server(self.store, "t" * 32, "127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever)
        thread.start()
        try:
            def post(data, token):
                conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
                conn.request("POST", "/v1/highlights", json.dumps(data), {"Content-Type": "application/json", "Authorization": "Bearer " + token})
                response = conn.getresponse()
                result = response.status, json.loads(response.read())
                conn.close()
                return result
            self.assertEqual(post(batch(), "wrong")[0], 401)
            self.assertEqual(self.store.pending(), [])
            self.assertEqual(post(batch(), "t" * 32), (200, {"accepted": ["one"], "status": "stored"}))
            self.assertEqual(len(self.store.pending()), 1)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()

    def test_delete_before_publish_and_stale_replay(self):
        self.store.accept(batch())
        self.store.accept(deletion())
        self.store.accept(batch())
        self.store = collector.Store(self.path / "inbox.sqlite3")
        self.assertTrue(json.loads(self.store.pending()[0][3])["deleted"])
        github = MemoryGitHub()
        collector.publish_once(self.store, github)
        self.assertEqual(github.current, [])
        self.assertEqual(github.deleted, {quote_key(quote())})
        self.assertNotIn("First highlight", self.store.pending().__repr__())
        with self.store.connect() as con:
            self.assertNotIn("First highlight", con.execute("SELECT payload FROM inbox").fetchone()[0])

    def test_delete_after_publish_preserves_unrelated_and_all_annotation_versions(self):
        other = quote("Unrelated")
        same_text_other_book = dict(quote(), book_title="Other Book")
        github = MemoryGitHub([other, same_text_other_book])
        self.store.accept(batch())
        collector.publish_once(self.store, github)
        self.store.accept(batch("Edited"))
        collector.publish_once(self.store, github)
        self.assertEqual(len(github.current), 4)
        self.store.accept(deletion())
        collector.publish_once(self.store, github)
        self.assertEqual(github.current, [other, same_text_other_book])
        self.store.accept(batch(device="other-reader"))
        collector.publish_once(self.store, github)
        self.assertEqual(github.current, [other, same_text_other_book])
        self.assertEqual(len(github.deleted), 2)

    def test_global_delete_scrubs_duplicate_payload_but_preserves_newer_other_text(self):
        self.store.accept(batch())
        self.store.accept(batch(device="duplicate"))
        self.store.accept(batch(device="edited-device"))
        self.store.accept(batch("Different new excerpt", device="edited-device"))
        self.store.accept(deletion())
        with self.store.connect() as con:
            payloads = {device: json.loads(payload) for device, payload in con.execute("SELECT device,payload FROM inbox")}
        self.assertEqual(payloads["duplicate"], {"id": "one", "deleted": True})
        self.assertEqual(payloads["edited-device"]["text"], "Different new excerpt")
        self.assertNotIn(quote_key(quote("Different new excerpt")), self.store.tombstones())

    def test_globally_deleted_upsert_does_not_delete_unrelated_history(self):
        self.store.accept(batch("Unrelated earlier version", device="other"))
        self.store.accept(batch())
        self.store.accept(deletion())
        self.store.accept(batch(device="other"))
        self.assertNotIn(quote_key(quote("Unrelated earlier version")), self.store.tombstones())
        with self.store.connect() as con:
            payload = json.loads(con.execute("SELECT payload FROM inbox WHERE device=?", ("other",)).fetchone()[0])
        self.assertEqual(payload["text"], "Unrelated earlier version")
        self.store.accept(batch("Unrelated earlier version", device="other"))
        github = MemoryGitHub()
        collector.publish_once(self.store, github)
        self.assertEqual(github.current, [quote("Unrelated earlier version")])
        self.assertNotIn(quote_key(quote("Unrelated earlier version")), self.store.tombstones())

    def test_remote_tombstone_scrubs_duplicate_payload(self):
        self.store.accept(batch())
        self.store.remember_tombstones({quote_key(quote())})
        with self.store.connect() as con:
            self.assertEqual(json.loads(con.execute("SELECT payload FROM inbox").fetchone()[0]), {"id": "one", "deleted": True})

    def test_unknown_delete_then_stale_original_removes_existing_amazon_quote(self):
        github = MemoryGitHub([quote()])
        self.store.accept(deletion())
        collector.publish_once(self.store, github)
        self.assertEqual(github.current, [quote()])  # ID alone cannot identify an unseen quote.
        self.store.accept(batch())
        self.assertTrue(self.store.tombstones(pending=True))
        collector.publish_once(self.store, github)
        self.assertEqual(github.current, [])
        self.store.accept(batch())
        self.assertEqual(collector.publish_once(self.store, github), 0)

    def test_unknown_delete_with_metadata_removes_existing_quote_immediately(self):
        github = MemoryGitHub([quote()])
        data = batch()
        data["highlights"][0]["deleted"] = True
        self.store.accept(data)
        collector.publish_once(self.store, github)
        self.assertEqual(github.current, [])
        partial = deletion()
        partial["highlights"][0]["text"] = "partial"
        with self.assertRaises(ValueError):
            self.store.accept(partial)

    def test_remote_delete_wins_conflicting_stale_publish(self):
        github = MemoryGitHub([quote("Other")])
        original_write = github.write
        def conflict(quotes, deleted, snapshot):
            github.deleted.add(quote_key(quote()))
            github.current.append(quote("Concurrent"))
            github.write = original_write
            raise RuntimeError("concurrent deletion")
        github.write = conflict
        self.store.accept(batch())
        collector.publish_once(self.store, github)
        self.assertEqual(github.current, [quote("Other"), quote("Concurrent")])
        self.assertIn(quote_key(quote()), self.store.tombstones())

    def test_delete_during_publish_remains_pending(self):
        github = MemoryGitHub()
        original_write = github.write
        def concurrent_delete(quotes, deleted, snapshot):
            self.store.accept(deletion())
            original_write(quotes, deleted, snapshot)
        github.write = concurrent_delete
        self.store.accept(batch())
        collector.publish_once(self.store, github)
        self.assertEqual(len(self.store.pending()), 1)
        github.write = original_write
        collector.publish_once(self.store, github)
        self.assertEqual(github.current, [])

    def test_migration_backfills_legacy_inbox(self):
        import sqlite3
        legacy = self.path / "legacy.sqlite3"
        with sqlite3.connect(legacy) as con:
            con.execute("CREATE TABLE inbox (source TEXT,device TEXT,id TEXT,payload TEXT NOT NULL,revision TEXT NOT NULL,published TEXT,PRIMARY KEY(source,device,id))")
            con.execute("INSERT INTO inbox VALUES(?,?,?,?,?,?)", ("koreader", "kindle", "one", json.dumps(batch()["highlights"][0]), "v1", "v1"))
        store = collector.Store(legacy)
        self.assertEqual(store.pending(), [])
        store.accept(deletion())
        self.assertEqual(store.tombstones(), {quote_key(quote())})

    def test_merge_tombstones_and_corruption(self):
        deleted = quote_key(quote())
        self.assertEqual(merge([quote(), quote("Other")], [quote()], {deleted}), [quote("Other")])
        self.assertEqual(quote_key(quote(" First   highlight ")), deleted)
        path = self.path / "highlight-tombstones.json"
        self.assertEqual(load_tombstones(path), set())
        path.write_text(json.dumps([deleted]))
        self.assertEqual(load_tombstones(path), {deleted})
        path.write_text('["bad"]')
        with self.assertRaises(ValueError):
            load_tombstones(path)

    def test_github_commit_atomically_updates_both_files_without_force(self):
        client = collector.GitHub("owner/repo", "main")
        with patch.object(client, "api", side_effect=[{"sha": "newtree"}, {"sha": "newcommit"}, {}]) as api:
            client.write([quote()], {quote_key(quote("Deleted"))}, {"head": "oldhead", "tree": "oldtree"})
        entries = api.call_args_list[0].args[2]
        self.assertEqual(entries["base_tree"], "oldtree")
        self.assertEqual({e["path"] for e in entries["tree"]}, {"highlights.json", "highlight-tombstones.json"})
        self.assertEqual(api.call_args_list[1].args[2]["parents"], ["oldhead"])
        self.assertEqual(api.call_args_list[2].args[2], {"sha": "newcommit", "force": False})

    def test_concurrent_status_writes_are_atomic(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: collector.publication_status(self.path, str(n)), range(40)))
        status_path = self.path / "publication-status.json"
        self.assertIn(int(json.loads(status_path.read_text())["status"]), range(40))
        self.assertEqual(status_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.path.glob(".publication-status-*")), [])

    def test_status_write_failure_does_not_stop_publisher_retry(self):
        class StopAfterTwo:
            iterations = 0
            def is_set(self):
                return self.iterations == 2
            def wait(self, interval):
                self.iterations += 1
        with patch.object(collector, "publish_once", side_effect=[RuntimeError("offline"), 1]) as publish:
            with patch.object(collector.tempfile, "NamedTemporaryFile", side_effect=PermissionError("readonly")):
                with self.assertLogs("collector", level="WARNING"):
                    collector.publisher_loop(self.store, object(), self.path, StopAfterTwo(), 60)
        self.assertEqual(publish.call_count, 2)

    def test_token_permissions_and_stability(self):
        directory, token = collector.initialize(self.path / "private")
        self.assertEqual((directory / "token").stat().st_mode & 0o777, 0o600)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(collector.initialize(directory)[1], token)


if __name__ == "__main__":
    unittest.main()
