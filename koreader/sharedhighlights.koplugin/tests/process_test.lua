local base=arg[0]:match("(.*/)").."../"
local Process=dofile(base.."process.lua")
local now, scheduled, processes, killed, finished, cleaned=0,{}, {}, {}, {}, {}
local function watch(pid)
    processes[pid]="running"
    return Process.watch(pid,{
        time=function() return now end,
        schedule=function(_,f) scheduled[f]=true end,
        unschedule=function(f) scheduled[f]=nil end,
        done=function(p) assert(p); return processes[p]=="exited" end,
        kill=function(p) killed[p]=(killed[p] or 0)+1; processes[p]="dying" end,
        cleanup=function() cleaned[pid]=true end,
    },function(ok) finished[pid]=ok and "success" or "failed" end)
end
local function tick(task) scheduled[task.poll]=nil; task.poll() end
local timeout=watch(10)
now=21; tick(timeout)
assert(killed[10]==1 and not timeout.done and scheduled[timeout.poll])
tick(timeout); assert(not timeout.done and killed[10]==1)
processes[10]="exited"; tick(timeout)
assert(timeout.done and finished[10]=="failed" and cleaned[10])
-- Suspend/close cancel owner callbacks; only the captured old PID is reaped.
local old=watch(11); old:cancel(); old:cancel()
local replacement=watch(12)
assert(killed[11]==1 and not old.done and not killed[12])
processes[11]="exited"; tick(old)
assert(old.done and not finished[11] and cleaned[11] and not replacement.done)
processes[12]="exited"; tick(replacement)
assert(finished[12]=="success" and cleaned[12])
old.poll(); assert(not finished[11])
local valid=dofile(base.."url.lua")
for _,url in ipairs{"http://192.168.1.20:8084","http://mac.local:8084","http://localhost:8084","http://10.0.0.1","http://172.16.0.1"} do assert(valid(url),url) end
for _,url in ipairs{"https://mac.local","http://example.com","http://8.8.8.8","http://192.168.300.1","http://mac.local:0","http://user@mac.local","http://mac.local/path"} do assert(not valid(url),url) end
print("process tests passed: async SIGKILL reaping, repeated cancel, instance transition isolation, bounded LAN URLs")
