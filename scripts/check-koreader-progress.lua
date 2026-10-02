local patchfile=assert(arg[1]);local native=assert(arg[2])
local scheduled,patch,clock={},nil,1000
local config={version=1,endpoint='http://192.168.1.20:8085',username='fixture'}
local files={}
local stores={open=function(_,path)
 local t=path:match('config.lua$') and config or files
 return {readSetting=function(_,k,d) return t[k] or d end,saveSetting=function(_,k,v)t[k]=v end,flush=function()end}
end}
local queue={}
local Queue={load=function()return queue end,save=function(_,q)queue=q end,push=function(_,i)queue[#queue+1]=i end,count=function()return #queue end}
local UI={getElapsedTimeSinceBoot=function()clock=clock+30;return clock end,
 nextTick=function(_,f)scheduled[#scheduled+1]=f end,scheduleIn=function(_,_,f)scheduled[#scheduled+1]=f end,
 show=function()end,unschedule=function()end}
local remote={document=string.rep('a',32),progress='original',percentage=.3,device='CrossPoint',device_id='xteink',timestamp=50,reader_bridge_revision='a'}
local requests={};local force_error
local function protocol(payload)
 requests[#requests+1]=payload
 local control=payload.metadata and payload.metadata.reader_bridge
 if force_error then return {status=503,body={}} end
 if not control or (not control.force and control.base_revision~=remote.reader_bridge_revision) then return {status=409,body={reader_bridge_conflict=true,current=remote}} end
 remote={document=payload.document,progress=payload.progress,percentage=payload.percentage,device=payload.device,device_id=payload.device_id,timestamp=100,reader_bridge_revision=remote.reader_bridge_revision..'x'}
 return {status=200,body={reader_bridge_revision=remote.reader_bridge_revision}}
end
local Spore={new_from_spec=function(path)
 assert(path:match('readerbridge%-api.json$'),'guard must use conflict-aware spec')
 return {reset_middlewares=function()end,enable=function()end,
 get_progress=function()return {status=200,body=remote} end,
 update_progress=function(_,payload)return protocol(payload) end}
end}
local Widget={new=function(_,o)return o end,extend=function(_,o)return o end}
local no=function()end
local modules={
 datastorage={getSettingsDir=function()return '/test/settings'end},luasettings=stores,
 ['ui/uimanager']=UI, ['ui/widget/container/widgetcontainer']=Widget,
 ['ui/widget/confirmbox']=Widget,['ui/widget/infomessage']=Widget,['ui/widget/inputdialog']=Widget,['ui/widget/multiinputdialog']=Widget,
 ['ui/widget/notification']={}, ['ui/event']={new=function(_,kind,value)return {kind=kind,value=value}end},
 ['ui/network/manager']={isOnline=function()return true end,willRerunWhenOnline=function()return false end},
 device={model='Kindle',hasWifiManager=function()return false end},dispatcher={},logger={dbg=no,warn=no,info=no},
 optmath={roundPercent=function(p)return math.floor(p*10000)/10000 end},
 ['ffi/sha2']={md5=function(s)return s end},['ui/time']={s=function(n)return n end},
 util={splitFilePathName=function(p)return '',p end},['ffi/util']={template=function(s)return s end},gettext=function(s)return s end,
 userpatch={registerPatchPluginFunc=function(_,fn)patch=fn end},KOSyncQueue=Queue,
 socketutil={set_timeout=no,reset_timeout=no},Spore=Spore,
}
for name,m in pairs(modules)do package.preload[name]=function()return m end end
package.preload.KOSyncClient=function()return dofile(native..'/KOSyncClient.lua')end
local Plugin=dofile(native..'/main.lua')
dofile(patchfile);patch(Plugin)
local owner=setmetatable({settings={username='fixture',userkey='hash',custom_server=config.endpoint,send_metadata=true,sync_forward=2,sync_backward=1},
 path=native,device_id='kindle',position='original',percentage=.3,push_timestamp=0,pull_timestamp=0,last_page_turn_timestamp=0,
 view={document={file='fixture.epub'}},ui={document={file='fixture.epub',info={has_pages=false}},doc_props={display_title='Fixture',authors='Author'}}}, {__index=Plugin})
owner.ui.handleEvent=function(_,event)owner.position=event.value;owner.percentage=remote.percentage end
owner.getDocumentDigest=function()return remote.document end
owner.getLastProgress=function()return owner.position end
owner.getLastPercent=function()return owner.percentage end
owner:getProgress(false,false)
assert(files.accounts[config.endpoint..'\nfixture'].books[remote.document]=='a')
owner.position='old-offline';owner.percentage=.35;force_error=true;owner:updateProgress(false,false);force_error=nil
assert(#queue==1,'actual native callback must retain failed send')
remote={document=remote.document,progress='xteink-new',percentage=.6,device='CrossPoint',device_id='xteink',timestamp=200,reader_bridge_revision='b'}
owner:_onNetworkConnected()
while #scheduled>0 do local fn=table.remove(scheduled,1);fn() end
assert(remote.progress=='xteink-new','actual native queue overwrote latest progress')
assert(owner.position=='xteink-new','actual native pull failed after rejection')
assert(#queue==0 and #files.accounts[config.endpoint..'\nfixture'].conflicts==1)
owner.position='intentional-earlier';owner.percentage=.1;owner:updateProgress(true,true)
assert(remote.progress=='intentional-earlier' and requests[#requests].metadata.reader_bridge.force)
print('Real installed KOSync main.lua and KOSyncClient.lua passed reconnect, stale queue, automatic pull, and explicit backward push')
