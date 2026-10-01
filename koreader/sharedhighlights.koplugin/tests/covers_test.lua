local Q=dofile(arg[0]:match("(.*/)").."../queue.lua")
local function hash(s) return s end
local state={pending={},sent={}}
local props={title="A Book",authors="An Author"}
local highlight={{drawer="lighten",text="A quote"}}
local target="collector-a"
Q.coverCapture(state,highlight,props,"book.epub",target,"10:100",hash)
local item=Q.coverBatch(state,target)
assert(item and item.file=="book.epub")
-- A malformed response cannot mark an upload complete.
Q.coverAck(state,item.id,item.revision,"BAD",false)
assert(Q.coverBatch(state,target))
Q.coverAck(state,item.id,item.revision,string.rep("a",64),false)
assert(not Q.coverBatch(state,target))
-- The same book is independently queued if the endpoint/token target changes.
Q.coverCapture(state,highlight,props,"book.epub","collector-b","10:100",hash)
assert(Q.coverBatch(state,"collector-b"))
-- A missing cover is terminal only for this file revision; replacement retries.
local other=Q.coverBatch(state,"collector-b")
Q.coverAck(state,other.id,other.revision,nil,true)
assert(not Q.coverBatch(state,"collector-b"))
Q.coverCapture(state,highlight,props,"book.epub","collector-b","11:120",hash)
assert(Q.coverBatch(state,"collector-b"))
-- No valid first highlight means no cover work.
local empty={pending={},sent={}}
Q.coverCapture(empty,{{drawer="lighten",text="   "}},props,"book.epub",target,"10:100",hash)
assert(not Q.coverBatch(empty,target))
-- Backing off one bad file must let another queued book make progress, and
-- state survives persistence because timing lives in the item itself.
local retry={pending={},sent={}}
Q.coverCapture(retry,highlight,{title="First",authors="A"},"first.epub",target,"1:1",hash)
Q.coverCapture(retry,highlight,{title="Second",authors="B"},"second.epub",target,"1:1",hash)
local first=Q.coverBatch(retry,target,100)
Q.coverFail(retry,first.id,first.revision,100)
local next=Q.coverBatch(retry,target,101)
assert(next and next.id~=first.id)
Q.coverFail(retry,next.id,next.revision,101)
local none,wait=Q.coverBatch(retry,target,102)
assert(not none and wait and wait>0)
Q.coverCapture(retry,highlight,{title=string.rep("x",1025),authors="A"},"long.epub",target,"1:1",hash)
assert(not retry.covers[string.rep("x",1025).."\0A\0"..target])
print("cover queue tests passed: per-target dedup, strict ack, unavailable revision, first highlight gate, fair persisted backoff")
