-- Pure queue logic; acknowledgement applies only to the exact sent revision.
local Q = {}
local function scalar(v)
    if type(v) ~= "table" then return type(v)..":"..#tostring(v or "")..":"..tostring(v or "") end
    local keys, out = {}, {}
    for k in pairs(v) do keys[#keys+1] = k end
    table.sort(keys, function(a,b) return tostring(a)<tostring(b) end)
    for _, k in ipairs(keys) do out[#out+1] = scalar(k)..scalar(v[k]) end
    return table.concat(out, ";")
end
function Q.capture(state, annotations, props, file, hash, encode, authoritative)
    if type(annotations)~="table" then return end -- unavailable is never an empty book
    state.books=state.books or {} -- Migration preserves existing sent and pending revisions.
    local title = props.title
    if not title or title == "" then title = file:match("([^/]+)$") or file end
    local author = props.authors or ""
    local book = hash(file.."\0"..title.."\0"..author)
    local known, present = state.books[book] or {}, {}
    for _, a in ipairs(annotations) do
        if a.drawer and type(a.text)=="string" then
            local id = hash(table.concat({title,author,a.datetime or "",scalar(a.pos0 or a.page),scalar(a.pos1)}, "\0"))
            local deleted_revision=hash(scalar{id=id,deleted=true})
            local stale_deleted = not authoritative and (state.sent[id]==deleted_revision
                or (state.pending[id] and state.pending[id].row.deleted))
            if not stale_deleted then
                present[id]=known[id] or true -- Invalid/oversized live content is not a deletion.
                local row = {id=id,book_title=title,author=author,text=a.text,note=a.note,
                    created_at=a.datetime,location=type(a.page)=="table" and scalar(a.page) or tostring(a.page or "")}
                local revision = hash(scalar(row))
                if a.text:match("%S") and #a.text<=65536 and #title<=4096 and #author<=4096 and #(row.note or "")<=65536 and #row.location<=4096
                    and #(row.created_at or "")<=128 then
                    present[id]={book_title=title,author=author,text=a.text}
                    if state.pending[id] or state.sent[id] ~= revision then
                        state.pending[id] = {row=row,revision=revision}
                    end
                end
            end
        end
    end
    if authoritative then
        for id in pairs(known) do
            if not present[id] then
                local row={id=id,deleted=true}
                local revision=hash(scalar(row))
                if type(known[id])=="table" then
                    row.book_title, row.author, row.text = known[id].book_title, known[id].author, known[id].text
                end
                state.pending[id]={row=row,revision=revision}
            end
        end
        state.books[book]=present
    else
        -- Historical snapshots may be stale. They can seed tracking, never remove it.
        for id, metadata in pairs(present) do known[id]=metadata end
        state.books[book]=known
    end
end
-- Cover transfer has its own durable state. A thumbnail must never affect
-- highlight acknowledgement or deletion handling.
function Q.coverCapture(state, annotations, props, file, target, revision, hash)
    if type(annotations) ~= "table" or not target or not revision then return end
    local has_highlight=false
    for _, a in ipairs(annotations) do
        if a.drawer and type(a.text)=="string" and a.text:match("%S") and #a.text<=65536 then has_highlight=true; break end
    end
    if not has_highlight then return end
    state.covers=state.covers or {}
    local title=props.title
    if not title or title=="" then title=file:match("([^/]+)$") or file end
    local author=props.authors or ""
    -- Header values are percent-encoded bytes. Keep their worst case below
    -- ordinary collector header limits rather than creating an un-sendable row.
    if #title>1024 or #author>1024 then return end
    local id=hash(title.."\0"..author.."\0"..target)
    local old=state.covers[id]
    if old and (old.stored==revision or old.unavailable==revision) then return end
    state.covers[id]={id=id,target=target,file=file,title=title,author=author,revision=revision,
        stored=old and old.stored,unavailable=old and old.unavailable,
        next_attempt=old and old.next_attempt,backoff=old and old.backoff}
end
function Q.coverBatch(state, target, now)
    local wait
    now=now or 0
    for _, item in pairs(state.covers or {}) do
        if item.target==target and item.stored~=item.revision and item.unavailable~=item.revision then
            local due=(item.next_attempt or 0)-now
            if due<=0 then return item end
            if not wait or due<wait then wait=due end
        end
    end
    return nil,wait
end
function Q.coverAck(state, id, revision, sha256, unavailable)
    local item=state.covers and state.covers[id]
    if not item or item.revision~=revision then return end
    if unavailable then item.unavailable=revision
    elseif type(sha256)=="string" and sha256:match("^[0-9a-f]+$") and #sha256==64 then item.stored=revision end
    item.next_attempt=nil; item.backoff=nil
end
function Q.coverFail(state,id,revision,now)
    local item=state.covers and state.covers[id]
    if not item or item.revision~=revision then return end
    item.backoff=math.min((item.backoff or 15)*2,300)
    item.next_attempt=now+item.backoff
end
function Q.batch(state, encode)
    local rows, versions, size = {}, {}, 0
    for id, item in pairs(state.pending) do
        local n = #encode(item.row)
        if #rows < 16 and size+n < 524288 then
            rows[#rows+1], versions[id], size = item.row, item.revision, size+n
        end
    end
    return rows, versions
end
function Q.ack(state, accepted, versions)
    for _, id in ipairs(accepted or {}) do
        if type(id)=="string" and versions[id] then
            state.sent[id] = versions[id]
            if state.pending[id] and state.pending[id].revision == versions[id] then state.pending[id] = nil end
        end
    end
end
return Q
