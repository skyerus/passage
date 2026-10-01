local Q=dofile(arg[0]:match("(.*/)").."../queue.lua")
local function hash(s) return s end -- identity hash makes expectations inspectable
local function encode(row) return string.rep("x",#row.text+100) end
local state={pending={},sent={}}
local a={drawer="lighten",text="A quote",datetime="2026-09-29 10:00:00",pos0="/body/p[1]",pos1="/body/p[2]",page="/body/p[1]"}
local function capture() Q.capture(state,{a,{text="page bookmark"}},{title="Book",authors="Author"},"book.epub",hash,encode) end
capture()
local rows,versions=Q.batch(state,encode)
assert(#rows==1 and rows[1].text=="A quote")
assert(rows[1].created_at==a.datetime) -- Original creation time, not upload time.
Q.ack(state,{"unrelated"},versions); assert(next(state.pending))
-- Editing while an upload runs must survive acknowledgement of the old revision.
a.note="my note"; capture()
Q.ack(state,{rows[1].id},versions); assert(next(state.pending))
rows,versions=Q.batch(state,encode); assert(rows[1].note=="my note")
Q.ack(state,{rows[1].id},versions); assert(not next(state.pending))
capture(); assert(not next(state.pending))
-- Path changes do not duplicate an otherwise identical annotation.
Q.capture(state,{a},{title="Book",authors="Author"},"moved/book.epub",hash,encode)
assert(not next(state.pending))
-- Reverting to an acknowledged revision must replace an offline or in-flight edit.
a.note="B"; capture()
local sent_b, versions_b=Q.batch(state,encode)
a.note="my note"; capture()
assert(state.pending[sent_b[1].id].row.note=="my note")
Q.ack(state,{sent_b[1].id},versions_b)
assert(state.pending[sent_b[1].id].row.note=="my note")
rows,versions=Q.batch(state,encode)
Q.ack(state,{rows[1].id},versions)
assert(not next(state.pending))
for i=1,40 do state.pending[tostring(i)]={row={id=tostring(i),text=string.rep("x",40000)},revision="r"} end
rows=Q.batch(state,encode); assert(#rows<=16 and #rows*40100<524288)
local before=state.pending["1"]
Q.ack(state,{},{}); assert(state.pending["1"]==before)
print("queue tests passed: dedup, note edit race, unknown/empty ack, path stability, byte/count limits")
