local base=arg[0]:match("(.*/)").."../"
local S=dofile(base.."sync.lua")
assert(S.asin("A title_B012345678.kfx")=="B012345678")
assert(not S.asin("resource.kfx"))
assert(not S.asin("personal_0123456789ABCDEF.kfx"))
assert(not S.asin("book_B012345678.kfx.part"))
assert(S.quote("a'b") == "'a'\\''b'")
for _,name in ipairs{"A title - B012345678.epub","界.epub"} do assert(S.safeFilename(name)) end
for _,name in ipairs{"../book.epub","/book.epub","folder\\book.epub","bad\n.epub","book.kfx"} do
    assert(not S.safeFilename(name),name)
end
print("book inbox filename tests passed")
