set target "xczu3eg-sbva484-1-e"
set found [get_parts -quiet $target]
puts "TARGET_COUNT=[llength $found] TARGET=$found"
if {[llength $found] != 1} { exit 2 }
exit 0
