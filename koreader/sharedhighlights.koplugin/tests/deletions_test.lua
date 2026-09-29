local Q=dofile(arg[0]:match("(.*/)").."../queue.lua")
local function hash(s) return s end
local function encode(row) return row.text or row.id end
local props={title="Book",authors="Author"}
local row={drawer="lighten",text="quote",datetime="today",pos0="start",pos1="end"}
local s={sent={},pending={}}
local function capture(rows,auth) Q.capture(s,rows,props,"book.epub",hash,encode,auth) end
local function batch() return Q.batch(s,encode) end
capture({row},true)
local initial,initial_v=batch(); local id=initial[1].id
Q.ack(s,{id},initial_v)
-- Removing the only live highlight queues a tombstone, including after restart.
local restored=s; s=restored
capture({},true)
assert(s.pending[id].row.deleted==true and s.pending[id].row.text=="quote" and s.pending[id].row.book_title=="Book")
local removed,removed_v=batch()
-- A stale historical sidecar must not overwrite queued deletion.
capture({row},false); assert(s.pending[id].row.deleted==true)
-- Recreate while delete is in flight; deleting ACK must not drop latest upsert.
capture({row},true); assert(s.pending[id].row.text=="quote")
Q.ack(s,{id},removed_v); assert(s.pending[id].row.text=="quote")
local recreated,recreated_v=batch()
-- Delete while upsert is in flight; upsert ACK must not drop tombstone.
capture({},true); Q.ack(s,{id},recreated_v)
assert(s.pending[id].row.deleted)
local final,final_v=batch(); Q.ack(s,{id},final_v); assert(not next(s.pending))
capture({row},false); assert(not next(s.pending)) -- stale history cannot resurrect an acknowledged delete
-- Unavailable annotations never mean an empty book.
s={sent={},pending={}}
capture({row},false); local seeded,seeded_v=batch(); id=seeded[1].id; Q.ack(s,{id},seeded_v)
capture(nil,true); capture({},false); assert(not next(s.pending))
capture({},true); assert(s.pending[id].row.deleted)
-- Legacy state with only sent revisions seeds from a live snapshot before deletion.
s={sent={[id]=seeded_v[id]},pending={}}
capture({row},true); assert(not next(s.pending)); capture({},true); assert(s.pending[id].row.deleted)
-- Missing legacy book identities cannot be inferred and must not be guessed.
s={sent={[id]=seeded_v[id]},pending={}}
capture({},true); assert(not next(s.pending))
-- Oversized/invalid content that is still present is never considered removed.
s={sent={},pending={}}; capture({row},true)
local old,oldv=batch(); Q.ack(s,{old[1].id},oldv)
row.text=string.rep("x",65537); capture({row},true); assert(not next(s.pending))
-- Distinct files with the same title/author have separate authoritative sets.
row.text="quote"; s={sent={},pending={}}; capture({row},true)
local same,samev=batch(); id=same[1].id; Q.ack(s,{id},samev)
Q.capture(s,{},props,"other-edition.epub",hash,encode,true)
assert(not next(s.pending))
-- Moving a file retains upload IDs, then seeds deletion tracking for its new path.
Q.capture(s,{row},props,"moved/book.epub",hash,encode,true)
assert(not next(s.pending))
Q.capture(s,{},props,"moved/book.epub",hash,encode,true)
assert(s.pending[id].row.deleted)
print("deletion tests passed: authoritative snapshots, migration, unavailable history, stale sidecar and ACK races")
