# wavelens_types.tcl — the types of a Questa design for WaveLens: a VCD has none (an enum comes as `reg [2:0]`, a
# packed struct as one vector), so this writes them next to the dump, by the path of each signal.
#
#   vsim -voptargs=+acc work.tb                       (+acc: the signals stay visible, as for the VCD itself)
#   source /path/to/wavelens/tools/questa/wavelens_types.tcl
#   wavelens_types tb.types.json                      (any time after the design is loaded: before or after run)
#   wavelens_types tb.types.json /tb/u_dut            (only under that instance)
#   vsim -c -view old.wlf, then source it and: wavelens_types old.types.json old:/tb   (a saved WLF, its dataset
#                                                       named after the file: no simulation needed)
#
# Name it as the dump with .types.json (tb.vcd -> tb.types.json): make html, the viewer's Sources… and the VS Code tab
# then find it. The file holds Questa's own words: `describe` of every signal and the module of every instance;
# WaveLens reads them (tools/svtypes.py, the page's twin). Check it against the dump: python3 tools/svtypes.py check
# tb.types.json tb.vcd.

namespace eval ::wavelens {}

# a JSON string
proc ::wavelens::str {s} {
    return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $s]\""
}

# Questa's object path -> the dump's: sim:/tb/gen[0]/u_l/state (old-run:/tb/… of a WLF) -> tb.gen[0].u_l.state; an escaped
# identifier (\a-b ) loses its backslash and the space that ends it, as Questa's VCD writes it
proc ::wavelens::path {p} {
    regsub {^[^/]*:/} $p / p
    set out {}
    foreach c [split [string trimleft $p /] /] {
        if {[string index $c 0] eq "\\"} {
            set c [string trimright [string range $c 1 end]]
        }
        lappend out $c
    }
    return [join $out .]
}

proc wavelens_types {file {root /*}} {
    if {[string index $root end] ne "*"} {
        set root "[string trimright $root /]/*"
    }
    set tool Questa
    catch {set tool [string trim [vsimVersionString]]}
    # the instances: path -> module (`find instances` says "/tb/u_rx (uart_rx)")
    set inst {}
    set top [string range $root 0 end-2]
    if {$top ne "" && [string index $top end] ne ":"} {
        foreach i [find instances $top] {
            lappend inst $i
        }
    }
    foreach i [find instances -r $root] {
        lappend inst $i
    }
    set rows {}
    foreach i [lsort -unique $inst] {
        if {[regexp {^(\S+) \((.*)\)$} $i -> p m] && ![string match *#* $p] && $m ne "std"} {
            lappend rows "    [::wavelens::str [::wavelens::path $p]]: [::wavelens::str $m]"
        }
    }
    # the signals: path -> what `describe` says (its return value: describe in a loop prints nothing)
    set sigs {}
    set n 0
    foreach s [lsort -unique [find signals -r $root]] {
        if {[string match *#* $s]} {
            continue
        }
        if {[catch {describe $s} d]} {
            set d "describe failed: $d"
        }
        lappend sigs "    [::wavelens::str [::wavelens::path $s]]: [::wavelens::str [string trim $d]]"
        incr n
    }
    set fh [open $file w]
    puts $fh "\{"
    puts $fh "  \"wavelens\": \"types\", \"version\": 1,"
    puts $fh "  \"producer\": \{\"tool\": [::wavelens::str $tool], \"by\": \"tools/questa/wavelens_types.tcl\",\
        \"root\": [::wavelens::str $root], \"date\": [::wavelens::str [clock format [clock seconds] -format %Y-%m-%dT%H:%M:%S]]\},"
    puts $fh "  \"instances\": \{\n[join $rows ",\n"]\n  \},"
    puts $fh "  \"describe\": \{\n[join $sigs ",\n"]\n  \}"
    puts $fh "\}"
    close $fh
    puts "wavelens_types: $n signals, [llength $rows] instances -> $file"
}
