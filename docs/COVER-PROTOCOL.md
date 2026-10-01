# Device cover transfer

Updated clients send highlights independently via `/v1/highlights`. A book with at least one highlight queues one artwork transfer per source file revision and configured collector. Completion is persisted on the reader; network failures retain queued work. Missing/unsupported artwork stops retries for that revision. Cover work does not change radio ownership, suspend, or retry lifecycle.

Both clients extract the original embedded JPEG/PNG. KOReader uses the document engine's raw cover API before screen rendering, so a monochrome Kindle does not turn colour artwork into a grayscale thumbnail. Unsupported engines or artwork formats keep a placeholder.

`POST /v1/covers` uses the same `Authorization: Bearer …` as highlights. Send the raw JPEG or PNG, `Content-Type: image/jpeg` or `image/png`, and a single `Content-Length` up to 5 MiB. Set `X-Book-Title` and `X-Book-Author` to percent-encoded UTF-8 strings matching highlight metadata; an empty author is valid. Metadata is limited to 4096 decoded UTF-8 bytes per field. Redirects are not followed.

A successful response is `200 {"status":"stored","sha256":"<64 lowercase hex characters>"}`. Only that acknowledgement completes the job. Bad authentication is 401, unsupported media is 415, oversized data is 413, invalid image/metadata is 400, and unavailable storage is 503. Clients retry failures with backoff independently of quote delivery. Cancellation on suspend must not acknowledge an unfinished job.

The collector validates format/dimensions, atomically writes and fsyncs a content-addressed image under its private `data/covers` directory, then commits book metadata in SQLite before responding. Concurrent uploads cannot lose another book’s metadata. Duplicate delivery is safe. The first usable device cover is retained for a normalized book identity, so delayed retries and another reader’s thumbnail cannot replace it. The response hash identifies the retained image. Choose a manual cover to replace artwork; a missing cached image can be uploaded again. The app reads that local metadata without a remote image fetch; a manually chosen cover takes precedence. Book identity uses the same normalized title/author grouping as the archive.

The wire protocol sends no book text or full EPUB. Native Kindle/Amazon highlights are outside this device protocol; Kindle users run the bundled plugin in KOReader. Books without supported embedded artwork retain a placeholder. Underlines remain in their source reader; the archive collects highlight text.
