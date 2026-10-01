-- Preserve the embedded artwork, before KOReader adapts it to the device screen.
-- Call only in the cancellable worker: crengine owns extraction and allocates
-- the returned buffer; release it even when writing the temporary file fails.
local Cover = {MAX_BYTES = 5 * 1024 * 1024}

function Cover.write(document, file, path)
    local ffi = require("ffi")
    local owned = not document or document.file ~= file
    local doc, data, output = document
    local ok, mime, size = pcall(function()
        if owned then doc = require("document/documentregistry"):openDocument(file) end
        if not doc then error("Cover document could not be opened") end
        if doc.loadDocument and not doc:loadDocument(false) then error("Cover metadata could not be loaded") end
        local engine = doc._document
        if not engine or not engine.getCoverPageImageData then return end
        local length
        data, length = engine:getCoverPageImageData()
        length = tonumber(length)
        if not data or not length or length <= 0 or length > Cover.MAX_BYTES then return end
        local bytes = ffi.cast("const unsigned char*", data)
        local header = ffi.string(bytes, math.min(length, 8))
        local kind
        if header:sub(1, 3) == "\255\216\255" then kind = "image/jpeg"
        elseif header == "\137PNG\r\n\26\n" then kind = "image/png"
        else return end
        output = assert(io.open(path, "wb"))
        for offset = 0, length - 1, 65536 do
            assert(output:write(ffi.string(bytes + offset, math.min(65536, length - offset))))
        end
        assert(output:flush())
        local closed = output:close()
        output = nil
        assert(closed)
        return kind, length
    end)
    if output then pcall(output.close, output) end
    if data then ffi.C.free(data) end
    if owned and doc then
        local closed, close_error = pcall(doc.close, doc)
        if not closed and ok then ok, mime = false, close_error end
    end
    if not ok or not mime then os.remove(path) end
    if not ok then error(mime) end
    return mime, size
end

return Cover
