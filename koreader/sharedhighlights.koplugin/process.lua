-- One child per tracker. Cancellation detaches owner callbacks, but keeps a
-- nonblocking reaper scheduled until waitpid has collected the killed child.
local Process = {}
function Process.watch(pid, api, on_finish)
    local task = {pid=pid, started=api.time(), on_finish=on_finish}
    local function schedule() api.schedule(0.5, task.poll) end
    function task:cancel()
        self.on_finish=nil
        api.unschedule(self.poll)
        if self.done then return end
        if not self.killed then api.kill(self.pid); self.killed=true end
        self.poll()
    end
    task.poll = function()
        if task.done then return end
        if not api.done(task.pid) then
            if not task.killed and api.time()-task.started>=20 then
                api.kill(task.pid)
                task.killed=true
                -- SIGKILL is asynchronous. Keep the PID until waitpid reaps it.
            end
            schedule()
            return
        end
        task.done=true
        local callback=task.on_finish
        task.on_finish=nil
        if callback then callback(not task.killed) end
        api.cleanup()
    end
    schedule()
    return task
end
return Process
