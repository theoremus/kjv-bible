-- Convert legacy scripture references ([Book][Chapter]) to the format
-- accepted by current versions of the LaTeX scripture package ([Book Chapter]).
function RawBlock(block)
    if block.format ~= "latex" and block.format ~= "tex" then
        return nil
    end

    block.text = block.text:gsub(
        "\\begin{scripture}%[(.-)%]%[(%d+)%]",
        "\\begin{scripture}[%1 %2]"
    )
    return block
end
