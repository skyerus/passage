-- Real file writes and sync control flow with deterministic transport/exporter.
local S=dofile(arg[0]:match("(.*/)").."../sync.lua")
local root=os.tmpname(); os.remove(root)
local execute=os.execute
assert(execute("mkdir -p "..S.quote(root.."/documents").." "..S.quote(root.."/books").." "..S.quote(root.."/exports")))
local paths={state=root.."/state",books=root.."/books",documents=root.."/documents",exports=root.."/exports",log=root.."/export.log"}
local config={url="http://mac.local:8086",token=string.rep("t",40),runner="/exporter"}
local function put(path,text) local f=assert(io.open(path,"wb")); f:write(text); f:close() end
local function exists(path) local f=io.open(path,"rb"); if f then f:close(); return true end end
local function clone(t) if type(t)~="table" then return t end; local c={}; for k,v in pairs(t) do c[k]=clone(v) end; return c end
local saved={}
local json={encode=function(value) local key="json:"..tostring(#saved+1); saved[#saved+1]=clone(value); return key end,
    decode=function(text) local i=tonumber(text:match("^json:(%d+)$")); assert(i); return clone(saved[i]) end}
local function state(value) put(paths.state,json.encode(value)) end
local payload="complete synthetic epub bytes"
local digest=string.rep("a",64)
local function hash()
    local chunks={}
    return function(chunk)
        if chunk then chunks[#chunks+1]=chunk; return end
        return table.concat(chunks)==payload and digest or string.rep("b",64)
    end
end
local entries,books,export_calls,uploads,receipts={}, {},0,0,0
local fail_export,truncated=false,false
local function attributes(path)
    local f=io.open(path,"rb"); if not f then return end
    local size=f:seek("end"); f:close()
    return {mode="file",size=size,modification=os.time()-120}
end
local lfs={attributes=attributes,symlinkattributes=attributes,mkdir=function() return true end,
    dir=function() local i=0; return function() i=i+1; return entries[i] end end}
local function stringSource(value) return function() local v=value; value=nil; return v end end
local ltn12={source={string=stringSource,file=function(f) return function()
    local chunk=f:read(4096); if not chunk then f:close() end; return chunk
end end}}
local http={request=function(request)
    local response
    local code=200
    if request.url:match('/v1/books$') then response=json.encode{books=books}
    elseif request.url:find('/v1/download/') then response=truncated and payload:sub(1,3) or payload
    elseif request.url:find('/v1/received/') then receipts=receipts+1; response=json.encode{status="stored"}
    elseif request.url:find('/v1/status/') then response=json.encode{state="missing"}
    elseif request.url:find('/v1/import/') then
        uploads=uploads+1; while request.source() do end
        response=json.encode{state="queued"}; code=202
    else error(request.url) end
    assert(request.sink(response)); assert(request.sink(nil)); return 1,code
end}
local api={http=http,ltn12=ltn12,json=json,lfs=lfs,sha256=hash,fsync=function() return true end}
local book={asin="B000000001",filename="Test - B000000001.epub",sha256=digest,size=#payload}
os.execute=function(command)
    export_calls=export_calls+1
    if fail_export then return 1 end
    local asin=assert(command:match('_(B%d+)%.kfx'))
    put(paths.exports.."/Second_"..asin..".kfx-zip",payload)
    return 0
end
local ok,error_message=pcall(function()
    state({}); books={book}; truncated=true
    assert(not pcall(S.run,config,paths,api))
    assert(not exists(paths.books.."/"..book.filename))
    assert(not exists(paths.books.."/"..book.filename..".part"))
    assert(receipts==0)
    truncated=false
    assert(S.run(config,paths,api)=="EPUB saved to your books folder")
    assert(exists(paths.books.."/"..book.filename) and receipts==1)
    assert(S.run(config,paths,api)=="Book inbox is up to date")
    assert(receipts==1 and export_calls==0,"Delivered book must not repeat export/download/receipt")

    -- A previously existing unequal EPUB is never replaced.
    state({}); put(paths.books.."/"..book.filename,"existing different book")
    assert(not pcall(S.run,config,paths,api))
    local f=assert(io.open(paths.books.."/"..book.filename)); assert(f:read("*a")=="existing different book"); f:close()

    books={}; state({ignored={B000000003=true}})
    entries={"First_B000000002.kfx","Baseline_B000000003.kfx","Second_B000000004.kfx"}
    for _,name in ipairs(entries) do put(paths.documents.."/"..name,"native") end
    fail_export=true
    assert(S.run(config,paths,api):match("export failed")); assert(uploads==0)
    local all_entries=entries; entries={entries[1]}
    assert(S.run(config,paths,api)=="Book import is pending; will check again")
    entries=all_entries
    fail_export=false
    assert(S.run(config,paths,api)=="Book sent to your Mac for conversion")
    assert(export_calls==2 and uploads==1,"Failed/baseline titles must not block another purchase")
end)
os.execute=execute
execute("rm -rf "..S.quote(root))
assert(ok,error_message)
print("book inbox transfer tests passed: truncation, receipts, preservation, failed export, baseline and retry")
