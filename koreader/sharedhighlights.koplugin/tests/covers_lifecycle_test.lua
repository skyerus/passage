-- Exercise the real Plugin:syncCover boundary with a synchronous fork mock.
local scheduled, request, reply={},nil,nil
local function encode(v) return v.unavailable and "UNAVAILABLE" or v.sha256 and "STORED" or "OTHER" end
local function decode(s)
    if s=="HTTP" then return reply end
    if s=="STORED" then return {sha256=string.rep("a",64)} end
    if s=="UNAVAILABLE" then return {unavailable=true} end
end
local manager={scheduleIn=function(_,_,f) scheduled[#scheduled+1]=f; f() end,unschedule=function() end}
local mode="image"
local original="\255\216\255colour"
local pointer_mt={}
pointer_mt.__add=function(p,n) return setmetatable({bytes=p.bytes,offset=p.offset+n},pointer_mt) end
local doc={file="book.epub",loadDocument=function() return true end,close=function() end,
    _document={getCoverPageImageData=function()
        if mode=="none" then return end
        return setmetatable({bytes=original,offset=0},pointer_mt),#original
    end}}
local open=io.open
io.open=function(path,access)
    if mode=="diskfail" and path:match("%.image$") and access=="wb" then return nil,"disk full" end
    return open(path,access)
end
local modules={
    ["ui/widget/container/widgetcontainer"]={extend=function(_,t) return t end},["ui/uimanager"]=manager,
    ["ui/widget/inputdialog"]={},["ui/widget/infomessage"]={},["ui/network/manager"]={},["datastorage"]={},
    ["json"]={encode=encode,decode=decode},["ffi/sha2"]={md5=function(s) return s end},
    ["libs/libkoreader-lfs"]={attributes=function(path,key) if path:match("%.image$") then return key=="size" and #original or "file" end return "file" end},
    ["document/documentregistry"]={openDocument=function() return doc end},
    ["ffi"]={cast=function(_,p) return p end,string=function(p,n) return p.bytes:sub(p.offset+1,p.offset+n) end,C={free=function() end}},
    ["ltn12"]={source={file=function(f) return function() local x=f:read("*a"); f:close(); return x end end}},
    ["socket.http"]={request=function(t) request=t; assert(t.source()==original); assert(t.headers["Content-Length"]==tostring(#original)); assert(t.headers["Content-Type"]=="image/jpeg"); t.sink("HTTP"); return 1,200,{} end},
}
modules["ffi/util"]={runInSubProcess=function(f) f(); return 1 end,isSubProcessDone=function() return true end,
    terminateSubProcess=function() end,fsyncOpenedFile=function() return true end,fsyncDirectory=function() return true end}
for name,module in pairs(modules) do package.preload[name]=function() return module end end
local Plugin=dofile(arg[0]:match("(.*/)").."../main.lua")
local path="/tmp/sharedhighlights-cover-boundary.json"
local function run(http_reply, expected, requested_mode)
    reply=http_reply; request=nil; mode=requested_mode or "image"
    os.remove(path); os.remove(path..".tmp")
    local p=setmetatable({path_state=path,state={pending={},covers={c={id="c",target="u\0t",file="book.epub",title="Café",author="Å",revision="1"}}},
        config={url="u",token="t"},ui={},tick=function() end},{__index=Plugin})
    p:syncCover(p.state.covers.c,false)
    if expected~=nil then assert((p.state.covers.c.stored=="1")==expected) end
    return p
end
local p=run({status="stored",sha256=string.rep("a",64)},true)
assert(request.url=="u/v1/covers" and request.headers["X-Book-Title"]=="Caf%C3%A9" and request.headers["X-Book-Author"]=="%C3%85")
run({status="stored",sha256=string.rep("A",64)},false)
modules["socket.http"].request=function(t) request=t; assert(t.source()==original); assert(t.headers["Content-Length"]==tostring(#original)); assert(t.headers["Content-Type"]=="image/jpeg"); t.sink("HTTP"); return 1,401,{} end
p=run({status="stored",sha256=string.rep("a",64)},false); assert(p.state.covers.c.next_attempt)
modules["socket.http"].request=function(t) request=t; assert(t.source()==original); assert(t.headers["Content-Length"]==tostring(#original)); assert(t.headers["Content-Type"]=="image/jpeg"); t.sink("HTTP"); return 1,503,{} end
p=run({status="stored",sha256=string.rep("a",64)},false); assert(p.state.covers.c.next_attempt)
modules["socket.http"].request=function(t) request=t; assert(t.source()==original); assert(t.headers["Content-Length"]==tostring(#original)); assert(t.headers["Content-Type"]=="image/jpeg"); t.sink("HTTP"); return 1,200,{} end
p=run({status="stored",sha256=string.rep("a",64)},nil,"diskfail"); assert(p.state.covers.c.next_attempt)
mode="none"
-- Existing readable file with no artwork is terminal for this revision.
reply={status="stored",sha256=string.rep("a",64)}
os.remove(path); os.remove(path..".tmp")
local q=setmetatable({path_state=path,state={pending={},covers={c={id="c",target="u\0t",file="book.epub",title="Café",author="Å",revision="2"}}},config={url="u",token="t"},ui={},tick=function() end},{__index=Plugin})
q:syncCover(q.state.covers.c,false); assert(q.state.covers.c.unavailable=="2")
os.remove(path); os.remove(path..".tmp")
-- A successful other job must not strand a previously backed-off cover.
local seen_delay
manager.scheduleIn=function(_,delay) seen_delay=delay end
local queued=setmetatable({state={pending={},covers={c={target="u\0t",revision="1",next_attempt=os.time()+42}}},
    config={url="u",token="t"},tick=function() end},{__index=Plugin})
queued:scheduleWork(); assert(seen_delay==42)
queued.state.pending.one={}; queued:scheduleWork(); assert(seen_delay==1)
io.open=open
print("cover lifecycle tests passed: original colour bytes, encoded headers, strict ack, HTTP failure/disk backoff, terminal no-cover")
