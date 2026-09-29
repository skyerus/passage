return function(url)
    if type(url)~="string" then return false end
    local host, port = url:match("^http://([%w%.%-]+):(%d+)$")
    if not host then host=url:match("^http://([%w%.%-]+)$") end
    if not host or (port and (tonumber(port)<1 or tonumber(port)>65535)) then return false end
    host=host:lower()
    if host=="localhost" or host:match("^[%w%-]+%.local$") then return true end
    local a,b,c,d=host:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    if not a then return false end
    a,b,c,d=tonumber(a),tonumber(b),tonumber(c),tonumber(d)
    if a>255 or b>255 or c>255 or d>255 then return false end
    return a==10 or a==127 or (a==192 and b==168) or (a==172 and b>=16 and b<=31)
end
