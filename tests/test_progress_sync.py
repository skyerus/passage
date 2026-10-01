import copy
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import archive_backup
from collector import Store as HighlightStore, initialize
import desktop
import lua_settings
import progress_setup
import progress_sync as sync
import setup


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.store = sync.Store(self.root/'positions.sqlite3')
        self.account = sync.credentials(self.root)
        self.server = sync.server(self.store,self.account,'127.0.0.1',0)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.item = {'document':'a'*32,'progress':'/body/DocFragment[5]/body/p[3]/text().0','percentage':0.45,'device':'Kindle','device_id':'kindle-fixture'}
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self, method, path, item=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=2)
        try:
            body = json.dumps(item) if item is not None else None
            client.request(method,path,body,{**sync.auth_headers(self.account),'Content-Type':'application/json',**(headers or {})})
            response=client.getresponse();return response.status,json.loads(response.read())
        finally: client.close()
    def test_native_client_roundtrip_latest_upload_wins_even_when_rereading(self):
        self.assertEqual(self.request('GET','/users/auth')[0],200)
        self.assertEqual(self.request('GET','/syncs/progress/'+'a'*32)[0],404)
        self.assertEqual(self.request('PUT','/syncs/progress',self.item)[0],200)
        code,row=self.request('GET','/syncs/progress/'+'a'*32)
        self.assertEqual((code,row['progress'],row['device']), (200,self.item['progress'],'Kindle'))
        earlier=dict(self.item,progress='/body/DocFragment[2]/body/p[1]/text().0',percentage=.1,device='CrossPoint',device_id='crosspoint-reader')
        self.assertEqual(self.request('PUT','/syncs/progress',earlier)[0],200)
        row=self.request('GET','/syncs/progress/'+'a'*32)[1]
        self.assertEqual(row['percentage'],.1);self.assertEqual(row['device'],'CrossPoint')
        self.assertEqual(sync.Store(self.store.path).get('a'*32),row)
        self.assertEqual(len(sync.read_uploads(self.store.path)),2)
    def test_authentication_registration_and_invalid_payloads_never_write(self):
        self.assertEqual(self.request('PUT','/syncs/progress',self.item,{'x-auth-key':'wrong'})[0],401)
        self.assertEqual(self.request('POST','/users/create',{'username':'stranger','password':'key'})[0],403)
        for changed in [{'document':'../other'},{'percentage':float('nan')},{'percentage':1.5},{'percentage':True},{'progress':''},{'device_id':None}]:
            self.assertEqual(self.request('PUT','/syncs/progress',{**self.item,**changed})[0],400)
        self.assertEqual(sync.read_archive(self.store.path),[])
        self.assertEqual(self.request('PUT','/syncs/progress',{**self.item,'progress':'x'*70000})[0],413)
    def test_migration_keeps_original_timestamp_and_restore_keeps_current_state(self):
        item={**self.item,'timestamp':100}
        self.assertEqual(self.store.seed([item]),1)
        self.assertEqual(self.store.get('a'*32)['timestamp'],100)
        self.assertEqual(sync.read_uploads(self.store.path),[],'Migration must not claim real device traffic')
        newer=dict(item,percentage=.6,timestamp=200)
        self.store.seed([newer]);self.assertEqual(self.store.get('a'*32)['percentage'],.45)
        self.store.seed([newer],newer=True);self.assertEqual(self.store.get('a'*32)['percentage'],.6)
        self.store.seed([item],newer=True);self.assertEqual(self.store.get('a'*32)['timestamp'],200)
    def test_backups_include_positions_without_credentials_and_restore_both(self):
        app=self.root/'app';data,_=initialize(app/'collector/data');HighlightStore(data/'inbox.sqlite3')
        positions=sync.Store(app/'progress_sync/positions.sqlite3');positions.put(self.item)
        account=sync.credentials(app/'progress_sync')
        destination=self.root/'backups';destination.mkdir()
        receipt=archive_backup.snapshot(data/'inbox.sqlite3',app,destination,app/'cloud_backup')
        manifest,_=archive_backup.read_snapshot(receipt['path'])
        self.assertEqual(manifest['version'],2)
        self.assertEqual(manifest['positions'][0]['progress'],self.item['progress'])
        self.assertNotIn(account['password'],json.dumps(manifest));self.assertNotIn(account['username'],json.dumps(manifest))
        positions.put(dict(self.item,percentage=.7))
        archive_backup.restore(receipt['path'],data/'inbox.sqlite3',app)
        self.assertEqual(positions.get('a'*32)['percentage'],.7)
        other=self.root/'other';other_data,_=initialize(other/'collector/data');HighlightStore(other_data/'inbox.sqlite3')
        archive_backup.restore(receipt['path'],other_data/'inbox.sqlite3',other)
        self.assertEqual(sync.read_archive(other/'progress_sync/positions.sqlite3')[0]['percentage'],.45)
        self.assertFalse((other/'progress_sync/credentials.json').exists())
    def test_credentials_survive_restart_and_are_private(self):
        self.assertEqual(sync.credentials(self.root),self.account)
        self.assertEqual((self.root/'credentials.json').stat().st_mode & 0o777,0o600)


class LuaSettingsTests(unittest.TestCase):
    def test_roundtrip_preserves_literal_settings_without_executing_code(self):
        text='-- saved settings\nreturn { ["settings"] = { custom_server="https://example.org", auto_sync=true, ["other"]={ [1]="café\\010quote\\\"", [2]=false }, }, ["keep"]=2.3e-5 }'
        value=lua_settings.loads(text)
        self.assertEqual(lua_settings.loads(lua_settings.dumps(value)),value)
        for payload in ['return os.execute("bad")','return {} os.execute("bad")','return {x=function() end}','return {["x"]=1,["x"]=2}']:
            with self.assertRaises(ValueError): lua_settings.loads(payload)


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.bridge=desktop.Desktop(self.root/'app',agent_dir=self.root/'agents')
        self.bridge.state['progress_sync']={'enabled':True,'port':8085,'endpoint':'http://192.168.1.20:8085'}
        self.account=sync.credentials(self.bridge.progress_directory())
        self.kind=self.root/'Kindle';self.kor=self.kind/'koreader';(self.kor/'settings').mkdir(parents=True);(self.kor/'reader.lua').write_text('fixture')
        self.path=self.kor/'settings/kosync.lua'
        self.original={'settings':{'username':'old','userkey':'old-hash','custom_server':'https://sync.crosspointreader.com','auto_sync':False,'checksum_method':0,'sync_forward':2,'unknown':'keep'}}
        self.path.write_text(lua_settings.dumps(self.original))
        (self.kind/'fixture.epub').write_bytes(b'epub fixture bytes')
        self.document=next(iter(progress_setup.book_documents(self.kind)))
        self.item={'document':self.document,'progress':'/body/DocFragment[3]/body/p[2].0','percentage':.3,'device':'CrossPoint','device_id':'crosspoint-reader','timestamp':100}
    def tearDown(self): self.temp.cleanup()
    def test_migration_seeds_public_positions_and_keeps_other_settings_and_local_book(self):
        def http(url,**kw):
            return json.dumps({'username':'old'} if url.endswith('/users/auth') else self.item).encode()
        with patch.object(self.bridge,'progress_authenticated',return_value=True),patch.object(setup,'http',side_effect=http): self.bridge.pair_progress_kindle(str(self.kind))
        now=lua_settings.loads(self.path.read_text())['settings']
        self.assertEqual(now['custom_server'],'http://192.168.1.20:8085');self.assertEqual(now['username'],self.account['username'])
        self.assertFalse(now['auto_sync']);self.assertEqual(now['unknown'],'keep');self.assertEqual(now['sync_forward'],2)
        self.assertEqual(sync.read_archive(self.bridge.progress_directory()/'positions.sqlite3')[0]['timestamp'],100)
        self.assertEqual((self.kind/'fixture.epub').read_bytes(),b'epub fixture bytes')
        self.assertTrue(any(self.original['settings']['userkey'] in p.read_text() for p in (self.bridge.app/'backups').glob('*kosync.lua')))
    def test_failed_old_server_leaves_reader_settings_unchanged(self):
        before=self.path.read_bytes()
        with patch.object(self.bridge,'progress_authenticated',return_value=True),patch.object(setup,'http',side_effect=OSError('offline')):
            with self.assertRaises(setup.SetupError):self.bridge.pair_progress_kindle(str(self.kind))
        self.assertEqual(before,self.path.read_bytes());self.assertNotIn('kindle',self.bridge.state['progress_sync'])
    def test_queued_position_newer_than_server_is_migrated_but_same_account_repair_keeps_queue(self):
        queue_path=self.kor/'settings/kosync_queue.lua'
        queue_path.write_text(lua_settings.dumps({1:{**self.item,'progress':'later','queued_at':200}}))
        with patch.object(self.bridge,'progress_authenticated',return_value=True),patch.object(setup,'http',return_value=json.dumps(self.item).encode()):self.bridge.pair_progress_kindle(str(self.kind))
        self.assertEqual(sync.read_archive(self.bridge.progress_directory()/'positions.sqlite3')[0]['progress'],'later')
        self.assertEqual(lua_settings.loads(queue_path.read_text()),{})
        queue_path.write_text(lua_settings.dumps({1:{**self.item,'progress':'offline-new','queued_at':300}}))
        before=queue_path.read_bytes()
        with patch.object(self.bridge,'progress_authenticated',return_value=True),patch.object(setup,'http',side_effect=AssertionError('No external requests on re-pair')):self.bridge.pair_progress_kindle(str(self.kind))
        self.assertEqual(queue_path.read_bytes(),before)
    def test_xteink_configuration_preserves_behavior_and_separates_highlights(self):
        self.bridge.state['progress_sync']['kindle']={'endpoint':self.bridge.state['progress_sync']['endpoint']}
        card=self.root/'card';(card/'.crosspoint').mkdir(parents=True)
        config=card/'.crosspoint/koreader.json';config.write_text(json.dumps({'password_obf':'old','syncBehavior':0,'extra':'keep'}))
        highlights=card/'.crosspoint/highlight-sync.json';highlights.write_text('unchanged highlight token')
        with patch.object(self.bridge,'progress_authenticated',return_value=True):self.bridge.pair_progress_xteink(mount=str(card))
        value=json.loads(config.read_text());self.assertEqual(value['syncBehavior'],0);self.assertEqual(value['extra'],'keep')
        self.assertNotIn('password_obf',value);self.assertEqual(value['password'],self.account['password']);self.assertEqual(value['matchMethod'],1)
        self.assertEqual(highlights.read_text(),'unchanged highlight token')

    def test_different_xteink_account_cannot_silently_lose_its_remote_positions(self):
        self.bridge.state['progress_sync']['kindle']={'endpoint':self.bridge.state['progress_sync']['endpoint']}
        self.bridge.state['progress_sync']['migration_source']={'username':'old','server':'https://sync.crosspointreader.com'}
        card=self.root/'card';(card/'.crosspoint').mkdir(parents=True)
        config=card/'.crosspoint/koreader.json'
        original=json.dumps({'cfgVersion':2,'username':'different-account','password_obf':'private','serverUrl':'https://sync.crosspointreader.com'})
        config.write_text(original)
        with patch.object(self.bridge,'progress_authenticated',return_value=True):
            with self.assertRaises(setup.SetupError):self.bridge.pair_progress_xteink(mount=str(card))
        self.assertEqual(config.read_text(),original)

    def test_filename_matching_migrates_to_matching_binary_ids(self):
        self.original['settings']['checksum_method']=1
        self.path.write_text(lua_settings.dumps(self.original))
        old_document=hashlib.md5(b'fixture.epub').hexdigest()
        requested=[]
        def http(url,**kwargs):
            requested.append(url)
            return json.dumps({'username':'old'} if url.endswith('/users/auth') else dict(self.item,document=old_document)).encode()
        with patch.object(self.bridge,'progress_authenticated',return_value=True),patch.object(setup,'http',side_effect=http):self.bridge.pair_progress_kindle(str(self.kind))
        self.assertTrue(any(url.endswith('/'+old_document) for url in requested))
        rows=sync.read_archive(self.bridge.progress_directory()/'positions.sqlite3')
        self.assertEqual(rows[0]['document'],self.document)
        self.assertEqual(lua_settings.loads(self.path.read_text())['settings']['checksum_method'],0)

    def test_status_does_not_initialize_storage_and_unowned_port_is_rejected(self):
        empty=desktop.Desktop(self.root/'empty',agent_dir=self.root/'empty-agents')
        self.assertEqual(empty.progress_status()['book_count'],0)
        self.assertFalse(empty.app.exists())
        with patch.object(setup,'available',return_value=False):
            with self.assertRaises(setup.SetupError):empty.check_port('progress_sync',8085)
