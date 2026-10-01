-- Test original-byte extraction without any screen renderer, including cleanup.
local payload, declared_size, freed, closed, loads, largest_chunk = nil,nil,0,0,0,0
local pointer_mt = {}
pointer_mt.__add = function(p,n) return setmetatable({bytes=p.bytes,offset=p.offset+n},pointer_mt) end
local function pointer(bytes) return setmetatable({bytes=bytes,offset=0},pointer_mt) end
package.preload.ffi=function() return {
    cast=function(_,p) return p end,
    string=function(p,n) largest_chunk=math.max(largest_chunk,n); return p.bytes:sub(p.offset+1,p.offset+n) end,
    C={free=function() freed=freed+1 end},
} end
local doc={file='book.epub',_document={getCoverPageImageData=function()
    return payload and pointer(payload),declared_size or (payload and #payload)
end},loadDocument=function(_,full) assert(full==false); loads=loads+1; return true end,
close=function() closed=closed+1 end}
package.preload['document/documentregistry']=function() return {openDocument=function(_,file) assert(file==doc.file); return doc end} end
local Cover=dofile(arg[0]:match('(.*/)')..'../cover.lua')
local path=os.tmpname(); os.remove(path)
local function read() local f=assert(io.open(path,'rb')); local s=f:read('*a'); f:close(); return s end
-- Colour image bytes pass through unchanged even though there is no renderer.
payload='\255\216\255'..string.rep('\0\255\128\64',40000)..'\255\217'
local mime,size=Cover.write(doc,doc.file,path)
assert(mime=='image/jpeg' and size==#payload and read()==payload)
assert(freed==1 and closed==0 and largest_chunk<=65536)
payload='\137PNG\r\n\26\n'..'original-colour-image'
mime,size=Cover.write(nil,doc.file,path)
assert(mime=='image/png' and size==#payload and read()==payload)
assert(freed==2 and closed==1 and loads==2)
-- Missing, oversized and unsupported artwork is terminal without an upload.
payload=nil; assert(not Cover.write(nil,doc.file,path)); assert(closed==2 and freed==2)
payload='GIF89a'; assert(not Cover.write(nil,doc.file,path)); assert(closed==3 and freed==3)
payload='\255\216\255'; declared_size=Cover.MAX_BYTES+1
assert(not Cover.write(nil,doc.file,path)); assert(closed==4 and freed==4)
assert(not io.open(path,'rb')); declared_size=nil
-- A failed write is retryable and frees the engine buffer/owned document.
local open=io.open
io.open=function(p,m) if p==path and m=='wb' then return nil,'disk full' end return open(p,m) end
assert(not pcall(Cover.write,nil,doc.file,path)); assert(closed==5 and freed==5)
io.open=open
local close=doc.close
doc.close=function() close(); error('close failed') end
assert(not pcall(Cover.write,nil,doc.file,path)); assert(freed==6 and closed==6)
assert(not io.open(path,'rb')); doc.close=close
local load=doc.loadDocument
doc.loadDocument=function() return false end
assert(not pcall(Cover.write,nil,doc.file,path)); assert(freed==6 and closed==7)
doc.loadDocument=load
-- Unsupported engines do not accidentally render a monochrome thumbnail.
local engine=doc._document; doc._document=nil
assert(not Cover.write(nil,doc.file,path)); assert(closed==8)
doc._document=engine
os.remove(path)
print('original cover tests passed: byte-identical JPEG/PNG, bounded copying, size limits, failure cleanup, document ownership')
