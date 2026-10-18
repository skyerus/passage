local WidgetContainer=require("ui/widget/container/widgetcontainer")
local UIManager=require("ui/uimanager")
local InfoMessage=require("ui/widget/infomessage")
local NetworkMgr=require("ui/network/manager")
local DataStorage=require("datastorage")
local ffiUtil=require("ffi/util")
local json=require("json")
local plugin_dir=debug.getinfo(1,"S").source:sub(2):match("(.*/)")
local Sync=dofile(plugin_dir.."sync.lua")
local owner,worker
local Plugin=WidgetContainer:extend{name="bookinbox"}
local function read(path)
    local f=io.open(path,"rb"); if not f then return end
    local data=f:read("*a"); f:close()
    local ok,value=pcall(json.decode,data)
    if ok and type(value)=="table" then return value end
end
local function validURL(url)
    if type(url)~="string" then return false end
    local host,port=url:match("^http://([%w%.%-]+):(%d+)$")
    if not host or tonumber(port)<1 or tonumber(port)>65535 then return false end
    if host:match("^[%w%-]+%.local$") then return true end
    local a,b,c,d=host:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    if not a then return false end
    a,b,c,d=tonumber(a),tonumber(b),tonumber(c),tonumber(d)
    return a<=255 and b<=255 and c<=255 and d<=255
        and (a==10 or (a==192 and b==168) or (a==172 and b>=16 and b<=31))
end
function Plugin:message(text) UIManager:show(InfoMessage:new{text=text,timeout=5}) end
function Plugin:init()
    if owner then owner:stop(true) end
    owner=self
    self.settings=DataStorage:getSettingsDir()
    self.config=read(self.settings.."/bookinbox-config.json")
    self.tick=function() self:sync(false) end
    self.ui.menu:registerToMainMenu(self)
    self:schedule(10)
end
function Plugin:schedule(delay)
    UIManager:unschedule(self.tick)
    if not self.closed and not self.suspended then UIManager:scheduleIn(delay,self.tick) end
end
function Plugin:sync(manual)
    if self.closed or self.suspended then return end
    self:schedule(60)
    if worker then
        if manual then self:message("Book sync is running.") end
        return
    end
    local config=self.config
    if not config or not validURL(config.url) or (config.fallback_url and not validURL(config.fallback_url))
        or type(config.token)~="string" or #config.token<32
        or type(config.runner)~="string" or type(config.books)~="string" then
        if manual then self:message("Pair Book inbox with your Mac first.") end
        return
    end
    if not NetworkMgr:isConnected() then
        if manual then self:message("Connect Wi-Fi to sync books.") end
        return
    end
    local paths={state=self.settings.."/bookinbox-state.json",books=config.books,
        documents="/mnt/us/documents",exports="/mnt/us/bookinbox-exports"}
    local result_path=self.settings.."/bookinbox-result.json"
    os.remove(result_path)
    local pid=ffiUtil.runInSubProcess(function()
        local ok,message=pcall(Sync.run,config,paths,{
            http=require("socket.http"),ltn12=require("ltn12"),json=json,
            lfs=require("libs/libkoreader-lfs"),sha256=require("ffi/sha2").sha256,
            fsync=ffiUtil.fsyncOpenedFile,
        })
        local result={ok=ok,message=ok and message or "Book sync interrupted; will retry",
            detail=not ok and tostring(message):sub(1,1000) or nil,time=os.time()}
        local body=json.encode(result)
        local f=io.open(result_path..".tmp","wb")
        if f then
            f:write(body)
            f:flush(); ffiUtil.fsyncOpenedFile(f); f:close(); os.rename(result_path..".tmp",result_path)
        end
        local http,ltn12=require("socket.http"),require("ltn12")
        http.TIMEOUT=5
        for _,url in ipairs{config.url,config.fallback_url} do
            local _,code=http.request{url=url.."/v1/device-status",method="POST",redirect=false,
                headers={Authorization="Bearer "..config.token,["Content-Type"]="application/json",
                    ["Content-Length"]=tostring(#body)},source=ltn12.source.string(body),sink=function() return 1 end}
            if tonumber(code)==200 then break end
        end
    end)
    if not pid then return end
    local task={pid=pid,started=os.time(),owner=self,manual=manual}
    worker=task
    task.poll=function()
        if not ffiUtil.isSubProcessDone(pid) then
            if not task.cancelled and os.time()-task.started>300 then
                task.cancelled=true; ffiUtil.terminateSubProcess(pid)
            end
            UIManager:scheduleIn(0.5,task.poll); return
        end
        if worker==task then worker=nil end
        if not task.cancelled and not self.closed and not self.suspended then
            local result=read(result_path)
            if manual then self:message(result and result.message or "Book sync will retry") end
            self:schedule(result and result.ok and
                (result.message=="Book sent to your Mac for conversion" or result.message=="EPUB saved to your books folder") and 10 or 60)
        end
    end
    UIManager:scheduleIn(0.5,task.poll)
end
function Plugin:stop(closed)
    self.closed=closed or self.closed
    UIManager:unschedule(self.tick)
    if worker and worker.owner==self and not worker.cancelled then
        worker.cancelled=true
        ffiUtil.terminateSubProcess(worker.pid) -- Kills exporter grandchildren too.
    end
end
function Plugin:addToMainMenu(menu)
    menu.bookinbox={text="Sync purchased books",sorting_hint="more_tools",callback=function() self:sync(true) end}
end
function Plugin:onSuspend() self.suspended=true; self:stop(false) end
function Plugin:onResume() self.suspended=false; self:schedule(10) end
function Plugin:onNetworkConnected() self:schedule(5) end
function Plugin:onCloseDocument() self:stop(true) end
function Plugin:onCloseWidget() self:stop(true) end
return Plugin
