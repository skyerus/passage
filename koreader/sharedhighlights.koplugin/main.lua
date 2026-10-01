local WidgetContainer = require("ui/widget/container/widgetcontainer")
local UIManager = require("ui/uimanager")
local InputDialog = require("ui/widget/inputdialog")
local InfoMessage = require("ui/widget/infomessage")
local NetworkMgr = require("ui/network/manager")
local DataStorage = require("datastorage")
local json = require("json")
local ffiUtil = require("ffi/util")
local lfs = require("libs/libkoreader-lfs")
local hash = require("ffi/sha2").md5
local plugin_dir = debug.getinfo(1, "S").source:sub(2):match("(.*/)")
local Q = dofile(plugin_dir .. "queue.lua")
local Cover = dofile(plugin_dir .. "cover.lua")
local Process = dofile(plugin_dir .. "process.lua")
local validURL = dofile(plugin_dir .. "url.lua")
local active_owner
local Plugin = WidgetContainer:extend{name="sharedhighlights"}
local function target(url, token) return hash(url.."\0"..token) end
local function revision(file)
    local a=lfs.attributes(file)
    return a and tostring(a.modification or "")..":"..tostring(a.size or "")
end
local function read(path)
    local f = io.open(path,"rb")
    if not f then return end
    local s = f:read("*a"); f:close()
    local ok, value = pcall(json.decode,s)
    if ok and type(value)=="table" then return value end
    error("Shared highlights: invalid state file; preserve it and restore a backup")
end
local function write(path,value,private)
    local f = assert(io.open(path..".tmp","wb"))
    if private then
        local ffi=require("ffi")
        ffi.C.fchmod(ffi.C.fileno(f),384) -- 0600 where supported; FAT may ignore permissions.
    end
    assert(f:write(json.encode(value))); assert(f:flush()); assert(ffiUtil.fsyncOpenedFile(f)); assert(f:close())
    assert(os.rename(path..".tmp",path)); assert(ffiUtil.fsyncDirectory(path:match("(.+)/")))
end
function Plugin:init()
    if active_owner then active_owner:stop(true) end
    active_owner=self
    self.path_state = DataStorage:getSettingsDir() .. "/sharedhighlights-queue.json"
    self.state = read(self.path_state) or {pending={},sent={}}
    self.path_config = DataStorage:getSettingsDir() .. "/sharedhighlights-config.json"
    self.config = read(self.path_config) or {}
    if not self.config.device_id then
        self.config.device_id = "koreader-" .. hash(tostring(os.time()) .. tostring({}))
        self:saveConfig()
    end
    self.ui.menu:registerToMainMenu(self)
    self.tick = function() self:sync(false) end
    UIManager:scheduleIn(5,self.tick)
end
function Plugin:saveConfig()
    write(self.path_config,self.config,true)
end
function Plugin:capture(keep_loaded)
    if not keep_loaded then self.state = read(self.path_state) or self.state end
    if self.ui.annotation and self.ui.document then
        Q.capture(self.state,self.ui.annotation.annotations,self.ui.doc_props or {},self.ui.document.file,hash,json.encode,true)
        Q.coverCapture(self.state,self.ui.annotation.annotations,self.ui.doc_props or {},self.ui.document.file,
            self.config.url and self.config.token and target(self.config.url,self.config.token),revision(self.ui.document.file),hash)
    end
    write(self.path_state,self.state)
end
function Plugin:history()
    self:capture()
    local BookList = require("ui/widget/booklist")
    for _, item in ipairs(require("readhistory").hist) do
        if not item.dim and not (self.ui.document and self.ui.document.file==item.file)
            and BookList.hasBookBeenOpened(item.file) then
            local settings = BookList.getDocSettings(item.file)
            local props=require("apps/filemanager/filemanagerbookinfo").extendProps(settings:readSetting("doc_props",{}),item.file)
            local annotations=settings:readSetting("annotations")
            Q.capture(self.state,annotations,props,item.file,hash,json.encode)
            Q.coverCapture(self.state,annotations,props,item.file,self.config.url and self.config.token and target(self.config.url,self.config.token),revision(item.file),hash)
        end
    end
    self:capture(true) -- Live annotations override older sidecar content.
end
function Plugin:message(text)
    UIManager:show(InfoMessage:new{text=text,timeout=4})
end
function Plugin:sync(manual)
    if self.closed or self.suspended then return end
    self:capture()
    if self.process and not self.process.done then return end
    if not self.config.url or not self.config.token or self.config.token == "" then
        if manual then self:message("Set the collector URL and token first.") end
        return
    end
    if not validURL(self.config.url) then
        if manual then self:message("Use a trusted LAN HTTP collector URL; this build does not support verified HTTPS.") end
        return
    end
    if not NetworkMgr:isConnected() then
        if manual then self:message("Highlights saved. Connect Wi-Fi to sync.") end
        return
    end
    if not self.scanned then self:history(); self.scanned=true end
    local rows, versions = Q.batch(self.state,json.encode)
    local cover, cover_wait = Q.coverBatch(self.state,target(self.config.url,self.config.token),os.time())
    if #rows == 0 then
        if cover then return self:syncCover(cover,manual) end
        if cover_wait then self:scheduleSync(math.max(1,cover_wait)); return end
        self.retry_delay=nil
        if manual then self:message("All highlights are stored on the collector.") end
        return
    end
    local body = json.encode{source="koreader",device_id=self.config.device_id,highlights=rows}
    local response_path = self.path_state .. ".result-" .. tostring(os.time()) .. "-" .. hash(tostring({}))
    local url, token = self.config.url, self.config.token
    local pid = ffiUtil.runInSubProcess(function()
        -- All blocking I/O and timeout changes live only in this forked child.
        local http = require("socket.http")
        local ltn12 = require("ltn12")
        http.TIMEOUT = 8
        local chunks, received = {}, 0
        local ok, _, code = pcall(http.request,{
            url=url.."/v1/highlights",method="POST",redirect=false,
            headers={["Authorization"]="Bearer "..token,["Content-Type"]="application/json",["Content-Length"]=tostring(#body)},
            source=ltn12.source.string(body),
            sink=function(chunk)
                if chunk then received=received+#chunk; if received>65536 then return nil,"response too large" end; chunks[#chunks+1]=chunk end
                return 1
            end,
        })
        local success, result = pcall(json.decode,table.concat(chunks))
        if ok and tonumber(code)==200 and success and type(result)=="table" and type(result.accepted)=="table" then
            write(response_path,{accepted=result.accepted})
        end
    end)
    if not pid then
        if manual then self:message("Highlights saved; sync could not start.") end
        self:retry(); return
    end
    self.process = Process.watch(pid, {
        time=os.time,
        schedule=function(delay, callback) UIManager:scheduleIn(delay,callback) end,
        unschedule=function(callback) UIManager:unschedule(callback) end,
        done=ffiUtil.isSubProcessDone,
        kill=ffiUtil.terminateSubProcess,
        cleanup=function() os.remove(response_path); os.remove(response_path..".tmp") end,
    }, function(completed)
        local result=completed and read(response_path)
        if result then self.state = read(self.path_state) or self.state; Q.ack(self.state,result.accepted,versions); write(self.path_state,self.state) end
        if manual then self:message(result and "Highlights stored on the collector." or "Collector unavailable. Highlights remain queued.") end
        local progress=false
        if result then
            for _, id in ipairs(result.accepted) do if versions[id] then progress=true; break end end
        end
        if progress then
            self.retry_delay=nil
            self:scheduleWork()
        elseif next(self.state.pending) then self:retry() end
    end)
end
function Plugin:scheduleWork()
    if next(self.state.pending) then self:scheduleSync(1); return end
    local cover, wait=Q.coverBatch(self.state,target(self.config.url,self.config.token),os.time())
    if cover then self:scheduleSync(1)
    elseif wait then self:scheduleSync(math.max(1,wait)) end
end
function Plugin:syncCover(cover,manual)
    local response_path=self.path_state..".cover-result-"..tostring(os.time()).."-"..hash(tostring({}))
    local image_path=response_path..".image"
    local url,token=self.config.url,self.config.token
    local live_document=(self.ui.document and self.ui.document.file==cover.file) and self.ui.document or nil
    local pid=ffiUtil.runInSubProcess(function()
        -- Extraction and network I/O are confined to the child. Screen rendering
        -- would discard the original colour on a monochrome Kindle.
        pcall(function()
            if lfs.attributes(cover.file,"mode")~="file" then return end -- removable storage may be temporarily absent
            local mime,size=Cover.write(live_document,cover.file,image_path)
            if not mime then write(response_path,{unavailable=true}); return end
            if lfs.attributes(image_path,"size")~=size then return end
            local http,ltn12=require("socket.http"),require("ltn12")
            http.TIMEOUT=8
            local function pct(s) return (s:gsub("[^%w%-%.%_~]",function(c) return string.format("%%%02X",string.byte(c)) end)) end
            local chunks,received={},0
            local request_ok,_,code=pcall(http.request,{url=url.."/v1/covers",method="POST",redirect=false,
                headers={Authorization="Bearer "..token,["Content-Type"]=mime,["Content-Length"]=tostring(size),
                    ["X-Book-Title"]=pct(cover.title),["X-Book-Author"]=pct(cover.author)},
                source=ltn12.source.file(assert(io.open(image_path,"rb"))),sink=function(chunk)
                    if chunk then received=received+#chunk; if received>65536 then return nil,"response too large" end; chunks[#chunks+1]=chunk end
                    return 1
                end})
            local decoded,reply=pcall(json.decode,table.concat(chunks))
            if request_ok and tonumber(code)==200 and decoded and type(reply)=="table" and reply.status=="stored"
                and type(reply.sha256)=="string" and reply.sha256:match("^[0-9a-f]+$") and #reply.sha256==64 then
                write(response_path,{sha256=reply.sha256})
            end
        end)
        os.remove(image_path); os.remove(image_path..".tmp")
    end)
    if not pid then
        Q.coverFail(self.state,cover.id,cover.revision,os.time())
        write(self.path_state,self.state)
        self:scheduleWork()
        return
    end
    self.process=Process.watch(pid,{time=os.time,schedule=function(delay,callback) UIManager:scheduleIn(delay,callback) end,
        unschedule=function(callback) UIManager:unschedule(callback) end,done=ffiUtil.isSubProcessDone,kill=ffiUtil.terminateSubProcess,
        cleanup=function() os.remove(response_path); os.remove(response_path..".tmp"); os.remove(image_path) end},function(completed)
        local result=completed and read(response_path)
        if result then
            self.state=read(self.path_state) or self.state
            Q.coverAck(self.state,cover.id,cover.revision,result.sha256,result.unavailable)
            write(self.path_state,self.state)
        end
        if result then self.retry_delay=nil; self:scheduleWork()
        else
            self.state=read(self.path_state) or self.state
            Q.coverFail(self.state,cover.id,cover.revision,os.time())
            write(self.path_state,self.state)
            self:scheduleWork()
        end
    end)
end
function Plugin:configure(key,title)
    local dialog
    dialog=InputDialog:new{title=title,input=self.config[key] or "",text_type=key=="token" and "password" or nil,
        buttons={{{text="Cancel",callback=function() UIManager:close(dialog) end},
            {text="Save",callback=function()
                local value=dialog:getInputText():gsub("%s+$",""):gsub("^%s+","")
                if key=="url" then
                    value=value:gsub("/+$","")
                    if not validURL(value) then self:message("Use http://hostname:8084 on a trusted LAN, with no path."); return end
                elseif value:find("[\r\n]") then self:message("Token must be one line."); return end
                self.config[key]=value; self:saveConfig(); UIManager:close(dialog)
            end}}}}
    UIManager:show(dialog); dialog:onShowKeyboard()
end
function Plugin:addToMainMenu(menu)
    menu.sharedhighlights={text="Shared highlights",sorting_hint="more_tools",sub_item_table={
        {text="Sync highlights",callback=function() self:history(); self.scanned=true; self:sync(true) end},
        {text="Collector URL",callback=function() self:configure("url","Collector URL (for example http://mac.local:8084)") end},
        {text="Collector token",callback=function() self:configure("token","Collector token") end},
    }}
end
function Plugin:retry()
    self.retry_delay=math.min((self.retry_delay or 15)*2,300)
    self:scheduleSync(self.retry_delay)
end
function Plugin:scheduleSync(delay)
    UIManager:unschedule(self.tick)
    if not self.closed and not self.suspended then UIManager:scheduleIn(delay,self.tick) end
end
function Plugin:stop(closed)
    self.closed = closed or self.closed
    UIManager:unschedule(self.tick)
    if self.process then self.process:cancel() end
end
function Plugin:onAnnotationsModified() if not self.closed then self:capture(); self:scheduleSync(2) end end
function Plugin:onReaderReady() if not self.closed then self:capture(); self:scheduleSync(2) end end
function Plugin:onCloseDocument()
    if not self.closed then self:capture() end
    self:stop(true) -- File manager's new instance resumes the durable queue.
end
function Plugin:onCloseWidget() self:stop(true) end
function Plugin:onSuspend()
    if not self.closed then self:capture() end
    self.suspended=true
    self:stop(false)
end
function Plugin:onResume() self.suspended=false; self:scheduleSync(5) end
function Plugin:onNetworkConnected() self:scheduleSync(2) end
return Plugin
