set target_part "xczu3eg-sbva484-1-e"
set matches [get_parts -quiet $target_part]
set count [llength $matches]
puts "TARGET_PART=$target_part"
puts "TARGET_PART_COUNT=$count"
if {$count != 1} {
    exit 2
}
exit 0
