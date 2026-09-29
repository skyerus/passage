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
