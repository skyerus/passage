-- Blocking work runs only inside a KOReader subprocess, with a bounded lifetime.
local M = {}
function M.quote(value) return "'" .. value:gsub("'", "'\\''") .. "'" end
function M.asin(name)
    local id = name:match("_([A-Z0-9]+)%.kfx$")
    return id and #id == 10 and id or nil
end
function M.safeFilename(name)
    return type(name)=="string" and #name<=240 and name:match("%.epub$")
        and not name:find("[/\\%c]") and name~=".epub"
end
function M.run(config, paths, api)
    local http, ltn12, json, lfs, sha256 = api.http, api.ltn12, api.json, api.lfs, api.sha256
    http.TIMEOUT = 20
    local function read(path)
        local f=io.open(path,"rb"); if not f then return {} end
        local data=f:read("*a"); f:close()
        return json.decode(data)
    end
    local function write(path, value)
        local f=assert(io.open(path..".tmp","wb"))
        assert(f:write(json.encode(value))); assert(f:flush()); assert(api.fsync(f)); assert(f:close())
        assert(os.rename(path..".tmp",path))
    end
    local state=read(paths.state)
    state.downloaded=state.downloaded or {}
    state.failed=state.failed or {}
    state.fail_attempts=state.fail_attempts or {}
    local base_url=config.url
    local function request(path, headers, source, sink)
        headers=headers or {}
        headers.Authorization="Bearer "..config.token
        local chunks, count={},0
        local _,code=http.request{url=base_url..path,method=source and "POST" or "GET",
            redirect=false,headers=headers,source=source,sink=sink or function(chunk)
                if chunk then
                    count=count+#chunk
                    if count>1024*1024 then return nil,"Response too large" end
                    chunks[#chunks+1]=chunk
                end
                return 1
            end}
        assert(code and tonumber(code),"Mac library unavailable")
        if sink then return tonumber(code) end
        local ok,reply=pcall(json.decode,table.concat(chunks))
        assert(ok and type(reply)=="table","Invalid library response")
        return tonumber(code),reply
    end
    local function hashFile(path)
        local f=assert(io.open(path,"rb")); local hash=sha256()
        while true do local chunk=f:read(65536); if not chunk then break end; hash(chunk) end
        f:close(); return hash()
    end
    local function acknowledge(book)
        local record=state.downloaded[book.asin]
        if record and not record.acknowledged then
            local body=json.encode{sha256=book.sha256}
            local status=request("/v1/received/"..book.asin,
                {["Content-Type"]="application/json",["Content-Length"]=tostring(#body)},ltn12.source.string(body))
            assert(status==200,"Delivery receipt will retry")
            record.acknowledged=true
            write(paths.state,state)
        end
    end
    -- Receive first, so an incompatible new purchase cannot block ready books.
    local available,code,catalog=pcall(request,"/v1/books")
    if not available and config.fallback_url then
        base_url=config.fallback_url
        available,code,catalog=pcall(request,"/v1/books")
    end
    assert(available,"Mac library unavailable")
    assert(code==200 and type(catalog.books)=="table","Mac library unavailable")
    for _,book in ipairs(catalog.books) do
        assert(type(book.asin)=="string" and #book.asin==10 and book.asin:match("^[A-Z0-9]+$")
            and M.safeFilename(book.filename) and type(book.sha256)=="string"
            and #book.sha256==64 and book.sha256:match("^[0-9a-f]+$")
            and type(book.size)=="number" and book.size>0 and book.size<=256*1024*1024,"Invalid book entry")
        local previous=state.downloaded[book.asin]
        local target=previous and previous.path or paths.books.."/"..book.filename
        local attributes=lfs.attributes(target)
        if not (previous and previous.sha256==book.sha256 and attributes and attributes.size==book.size) then
            if attributes then
                assert(hashFile(target)==book.sha256,"Existing EPUB differs; preserved without replacement")
            else
                lfs.mkdir(paths.books)
                local f=assert(io.open(target..".part","wb"))
                local hash,received=sha256(),0
                local ok,status=pcall(request,"/v1/download/"..book.asin,nil,nil,function(chunk)
                    if chunk then
                        received=received+#chunk
                        if received>book.size then return nil,"Download too large" end
                        hash(chunk); return f:write(chunk) and 1
                    end
                    return 1
                end)
                local flushed=f:flush(); local synced=api.fsync(f); local closed=f:close()
                if not (ok and status==200 and received==book.size and hash()==book.sha256
                        and flushed and synced and closed) then
                    os.remove(target..".part"); error("EPUB download incomplete; will retry")
                end
                assert(os.rename(target..".part",target))
            end
            state.downloaded[book.asin]={path=target,sha256=book.sha256}
            state.failed[book.asin]=nil
            state.fail_attempts[book.asin]=nil
            write(paths.state,state)
            acknowledge(book)
            return "EPUB saved to your books folder"
        end
        acknowledge(book)
    end
    local candidates,visited={},0
    local waiting=false
    local function scan(directory,depth)
        if depth>6 then return end
        for name in lfs.dir(directory) do
            visited=visited+1
            if visited>10000 then return end
            if name:sub(1,1)~="." then
                local path=directory.."/"..name
                local attr=lfs.symlinkattributes(path)
                if attr and attr.mode=="directory" and not name:match("%.sdr$") then
                    scan(path,depth+1)
                elseif attr and attr.mode=="file" then
                    local asin=M.asin(name)
                    if asin and not state.downloaded[asin] and not (state.ignored and state.ignored[asin]) then
                        if os.time()-attr.modification>=60 and (state.failed[asin] or 0)<os.time() then
                            candidates[#candidates+1]={asin=asin,path=path}
                        else waiting=true end
                    end
                end
            end
        end
    end
    scan(paths.documents,0)
    table.sort(candidates,function(a,b) return a.asin<b.asin end)
    for _,book in ipairs(candidates) do
        local status,reply=request("/v1/status/"..book.asin)
        assert(status==200,"Cannot check import status")
        if reply.state=="missing" then
            -- The device tool is supplied independently. Never use the stock
            -- KFX as an EPUB, or change Amazon files, firmware, or OTA blockers.
            lfs.mkdir(paths.exports)
            -- Exporter releases differ: some keep the input basename, older
            -- releases use only ASIN. Accept only these exact expected names.
            local basename=assert(book.path:match("([^/]+)%.kfx$"))
            local outputs={paths.exports.."/"..basename..".kfx-zip",paths.exports.."/"..book.asin..".kfx-zip"}
            for _,path in ipairs(outputs) do os.remove(path) end
            local command="sh "..M.quote(config.runner).." dedrm "..M.quote(book.path).." "
                ..M.quote(paths.exports).." > /dev/null 2>&1" -- Tool stdout contains device secrets.
            local result=os.execute(command)
            local output,exported
            for _,path in ipairs(outputs) do
                local attr=lfs.attributes(path)
                if attr and attr.mode=="file" and attr.size>0 then output=path; exported=attr; break end
            end
            if not (result==0 or result==true) or not exported or exported.size==0 then
                state.fail_attempts[book.asin]=(state.fail_attempts[book.asin] or 0)+1
                state.failed[book.asin]=os.time()+math.min(3600,60*2^(state.fail_attempts[book.asin]-1))
                write(paths.state,state)
                return "One Kindle export failed; other books will continue syncing"
            end
            assert(exported.size<=256*1024*1024,"Export exceeds size limit")
            local digest=hashFile(output)
            local input=assert(io.open(output,"rb"))
            local ok,accepted=pcall(request,"/v1/import/"..book.asin,
                {["Content-Type"]="application/zip",["Content-Length"]=tostring(exported.size),
                 ["X-Content-SHA256"]=digest}, ltn12.source.file(input))
            pcall(function() input:close() end)
            assert(ok and accepted==202,"Upload incomplete; will retry")
            state.failed[book.asin]=nil; state.fail_attempts[book.asin]=nil
            write(paths.state,state)
            os.remove(output)
            return "Book sent to your Mac for conversion"
        end
        waiting=true
    end
    if waiting then return "Book import is pending; will check again" end
    return "Book inbox is up to date"
end
return M
