# Hand-drawn met4 power grid + macro binding for the Azara TT tile. Sourced
# right after pdngen succeeds (before write_views) via the pdngen command
# wrapper installed at the end of pdn_cfg.tcl.
#
# pdngen owns ONLY the met1 followpin rails. Everything met4 is drawn here
# verbatim: pdngen silently relocates straps it cannot place as specified to
# the leftmost free met4 track (tile39-41), and its macro via stacks punch
# met3 landing pads into the bands' dense pin-strip met3. The macros' power is
# bound by same-layer met4 merging onto their own met4 (band power risers,
# array VPWR strip); the one exception is the array VGND strip (met1), reached
# by three small met1->met4 via stacks in coordinate-verified clear zones.
# Rail-to-strap via stacks (which add_pdn_connect would only create for
# pdngen-owned stripes) are placed explicitly at every rail/strap crossing.
#
# FLOORPLAN (mirrored so the ARRAY STAYS N -- its Magic maskhints only hold
# for unmirrored instantiation; every mirror path breaks them: instance flips
# unmirror the hint coordinates, paint-baked mirrors lose the hint records):
#   array N @ (102.4, 101.9) -- WL pins on its WEST edge facing the west
#   logic block; band_p FS @ (85.715, 6); band_n FS @ (23.715, 6).
# All coordinates in um, derived from the abstract LEFs + macro_tile.cfg +
# the tt_analog_1x2 template pin map. If any change, re-derive every number.

set block [ord::get_db_block]
set tech  [ord::get_db_tech]
proc um {v} { return [expr {int(round($v * 1000.0))}] }
foreach {var name} {M1 met1 M2 met2 M3 met3 M4 met4} {
    set $var [$tech findLayer $name]
    if { [set $var] eq "NULL" } { puts "\[ERROR\] pdn_patch: layer $name missing"; exit 1 }
}

proc pdn_swire {netname} {
    set net [[ord::get_db_block] findNet $netname]
    if { $net eq "NULL" || $net eq "" } { puts "\[ERROR\] pdn_patch: net $netname missing"; exit 1 }
    set sws [$net getSWires]
    if { [llength $sws] == 0 } { return [odb::dbSWire_create $net ROUTED] }
    return [lindex $sws 0]
}
set swP [pdn_swire VDPWR]
set swG [pdn_swire VGND]

proc pbox {sw layer x1 y1 x2 y2} {
    odb::dbSBox_create $sw $layer [um $x1] [um $y1] [um $x2] [um $y2] STRIPE
}

# ---------------------------------------------------------------------------
# Vertical met4 straps (full die height; x threads the template pin-stub
# fences: top digital pins at 2.75 pitch +-0.15, bottom ua pins +-0.45):
#   VPWR c6.30 (1.2, the TT VDPWR power pin) / VGND c11.80 (1.2, the TT
#        VGND power pin): west margin -- the TT spec wants met4 >=1.2 within
#        10um of both edges; the west margin has no routing-lane pressure, powering the west logic
#        block; clear of band_n (23.715) and the ua[7] bottom stub (17).
#   VPWR c84.35 (0.9): the inter-band gap -- keep it narrow: its rail-stack
#        met3 pads at 1.2 wide choke the gap's south-crossing met3 lane and
#        DRT then drills nets through band_p (tile60).
#   VPWR c139.85 / VGND c145.35 (0.9, PARTIAL y 0..101): under the array --
#        full height would cross its riser field / VPWR strip. They power the
#        band_p east region and belt/corridor rails; clear of band_p's VGND
#        riser2 (135.65..136.83).
#   VPWR c148.35 / VGND c150.35 (1.6, PARTIAL y 0..101): east belt, inside
#        the ena(146.7)..ua[0](152.26) stub window; their rail stacks tie the
#        east-belt decap row segments (145..155.5). The east top-strip rows
#        (y>199.8) are full-width rails reaching the west straps, so no
#        full-height east power is needed.
#   VPWR c153.98 (0.5): the array riser-strap, threading the gap between the
#        UNSENSED east dummy-column risers (r29 body ends 153.4, r30 via pads
#        -- which bulge 0.24 past the LEF -- start 154.56; 0.33 clear both
#        sides). Merges the array's met4 VPWR top strip where it crosses --
#        binding array VPWR. It touches NO riser: a dummy bitline tied to
#        power would crowbar through the ROM cells when its wordline fires.
#   VGND c157.90 (0.5): east sliver (rows soft-blocked), right of the array
#        met4 (ends 156.9); gives the top VGND bar its strap merge.
# ---------------------------------------------------------------------------
pbox $swP $M4   5.70 0.0   6.90 225.76
pbox $swG $M4  11.20 0.0  12.40 225.76
pbox $swP $M4  83.90 0.0  84.80 225.76
pbox $swP $M4 139.40 0.0 140.30 101.0
pbox $swG $M4 144.90 0.0 145.80 101.0
pbox $swP $M4 147.55 0.0 149.15 101.0
pbox $swG $M4 149.55 0.0 151.15 101.0
pbox $swP $M4 153.73 0.0 154.23 225.76
pbox $swG $M4 157.65 0.0 158.15 225.76

# discover the straps back from the db (single source of truth for the bars'
# gap logic and the asserts); entries are {x1 x2 y1 y2}
proc strap_xs {sw} {
    set out {}
    foreach b [$sw getWires] {
        if { [$b isVia] } { continue }
        set L [$b getTechLayer]
        if { $L eq "NULL" || [$L getName] ne "met4" } { continue }
        set dx [expr {[$b xMax] - [$b xMin]}]
        set dy [expr {[$b yMax] - [$b yMin]}]
        if { $dy > 50000 && $dx < 2500 } {
            lappend out [list [expr {[$b xMin] / 1000.0}] [expr {[$b xMax] / 1000.0}] \
                              [expr {[$b yMin] / 1000.0}] [expr {[$b yMax] / 1000.0}]]
        }
    }
    return $out
}

# horizontal met4 bar x0..x1 at y0..y1, gapped around `avoid` ({{a b}...}) with
# 0.4 clearance; skips segments shorter than 0.8.
proc hbar {sw x0 x1 y0 y1 avoid} {
    set edges {}
    foreach iv $avoid {
        lassign $iv a b
        set a [expr {$a - 0.4}]; set b [expr {$b + 0.4}]
        if { $b <= $x0 || $a >= $x1 } { continue }
        lappend edges [list $a $b]
    }
    set cur $x0
    foreach iv [lsort -real -index 0 $edges] {
        lassign $iv a b
        if { $a - $cur >= 0.8 } { pbox $sw $::M4 $cur $y0 $a $y1 }
        if { $b > $cur } { set cur $b }
    }
    if { $x1 - $cur >= 0.8 } { pbox $sw $::M4 $cur $y0 $x1 $y1 }
}

set vpwr_straps [strap_xs $swP]
set vgnd_straps [strap_xs $swG]
puts "pdn_patch: VDPWR straps at $vpwr_straps"
puts "pdn_patch: VGND  straps at $vgnd_straps"
if { [llength $vpwr_straps] != 5 || [llength $vgnd_straps] != 4 } {
    puts "\[ERROR\] pdn_patch: expected exactly 5 VPWR / 4 VGND straps"; exit 1
}

# tripwires against plan drift: no strap may sit in the array met4 zone
# (N @ x=102.4: risers + full-width VPWR top strip span x 102.0..157.25 --
# except the c153.98 riser-strap threading the dummy gap by design), on the
# opposite net's band risers, or on a template pin stub.
set vdd_riser_x  {{41.825 43.005} {60.325 61.505} {103.825 105.005} {122.325 123.505}}
set vgnd_riser_x {{32.950 34.130} {73.650 74.830} {94.950 96.130} {135.650 136.830}}
proc assert_clear {what straps zones} {
    foreach s $straps {
        lassign $s a b
        foreach z $zones {
            lassign $z c d
            if { $b + 0.35 > $c && $a - 0.35 < $d } {
                puts "\[ERROR\] pdn_patch: $what strap ($a..$b) collides with zone ($c..$d)"; exit 1
            }
        }
    }
}
set pin_zones {}
foreach x {30.8 33.6 36.3 39.1 41.9 44.6 47.4 50.1 52.9 55.7 58.4 61.2 63.9
           66.7 69.5 72.2 75.0 77.7 80.5 83.3 86.0 88.8 91.5 94.3 97.1 99.8
           102.6 105.3 108.1 110.9 113.6 116.4 119.1 121.9 124.7 127.4 130.2
           132.9 135.7 138.5 141.2 144.0 146.7} {
    lappend pin_zones [list [expr {$x - 0.17}] [expr {$x + 0.17}]]
}
foreach x {17.0 36.3 55.7 75.0 94.3 113.6 132.9 152.3} {
    lappend pin_zones [list [expr {$x - 0.47}] [expr {$x + 0.47}]]
}
# the ARRAY zone applies only to FULL-height straps (partials stop at y 101,
# below the array); the riser-strap c153.98 is exempt by design. Band-riser
# and pin-fence zones apply to all.
proc fulls {straps} {
    set out {}
    foreach s $straps {
        lassign $s a b y1 y2
        if { $y2 - $y1 > 200.0 } { lappend out $s }
    }
    return $out
}
set vpwr_full_check {}
foreach s [fulls $vpwr_straps] {
    lassign $s a b
    set c [expr {($a + $b) / 2.0}]
    if { $c < 153.5 || $c > 154.5 } { lappend vpwr_full_check $s }
}
assert_clear VDPWR $vpwr_full_check {{102.0 157.25}}
assert_clear VGND  [fulls $vgnd_straps] {{102.0 157.25}}
assert_clear VDPWR $vpwr_straps [concat $vgnd_riser_x $pin_zones]
assert_clear VGND  $vgnd_straps [concat $vdd_riser_x $pin_zones]

# ---------------------------------------------------------------------------
# Rail binding: a met1->met4 via stack at every followpin-rail / same-net
# strap crossing (pdngen's add_pdn_connect only serves its own stripes).
# Vias are the PDK's fixed *_PR tech vias (single-cut, ~0.33-0.43 pads: fit
# every strap width and the 0.48 rails); a 0.55 met3 square per stack keeps
# the isolated met3 pad above the m3.6 min-area rule.
# ---------------------------------------------------------------------------
proc find_via {bot top} {
    set cand ""
    foreach v [[ord::get_db_tech] getVias] {
        set b [$v getBottomLayer]; set t [$v getTopLayer]
        if { $b eq "NULL" || $t eq "NULL" } { continue }
        if { [$b getName] ne $bot || [$t getName] ne $top } { continue }
        if { [string match "*_PR" [$v getName]] } { return $v }
        if { $cand eq "" } { set cand $v }
    }
    if { $cand ne "" } { return $cand }
    puts "\[ERROR\] pdn_patch: no $bot->$top tech via found"
    exit 1
}
set v12 [find_via met1 met2]
set v23 [find_via met2 met3]
set v34 [find_via met3 met4]

proc rail_stacks {sw straps} {
    set n 0
    foreach b [$sw getWires] {
        if { [$b isVia] } { continue }
        set L [$b getTechLayer]
        if { $L eq "NULL" || [$L getName] ne "met1" } { continue }
        set dy [expr {[$b yMax] - [$b yMin]}]
        set dx [expr {[$b xMax] - [$b xMin]}]
        if { $dy > 1000 || $dx < 5000 } { continue }
        set ry [expr {([$b yMin] + [$b yMax]) / 2}]
        foreach s $straps {
            lassign $s a b2 sy1 sy2
            if { $ry < [um $sy1] || $ry > [um $sy2] } { continue }
            set cx [um [expr {($a + $b2) / 2.0}]]
            if { $cx > [$b xMin] + 500 && $cx < [$b xMax] - 500 } {
                odb::dbSBox_create $sw $::v12 $cx $ry STRIPE
                odb::dbSBox_create $sw $::v23 $cx $ry STRIPE
                odb::dbSBox_create $sw $::v34 $cx $ry STRIPE
                # met3 landing pad: the tech-via met3 enclosure alone is
                # 0.14 um2, under the met3 min-area rule (m3.6, 0.24 um2)
                odb::dbSBox_create $sw $::M3 [expr {$cx - 275}] [expr {$ry - 275}] \
                    [expr {$cx + 275}] [expr {$ry + 275}] STRIPE
                incr n
            }
        }
    }
    return $n
}
set nP [rail_stacks $swP $vpwr_straps]
set nG [rail_stacks $swG $vgnd_straps]
puts "pdn_patch: rail stacks: VDPWR $nP, VGND $nG"
if { $nP < 20 || $nG < 20 } {
    puts "\[ERROR\] pdn_patch: too few rail stacks (rails missing?)"; exit 1
}

# ---------------------------------------------------------------------------
# Band binding: power bars INSIDE the band belt, merging the bands' met4
# risers by same-layer overlap (no vias over the bands: their met3 is dense
# pin strips with no room for landing pads). Placed in the belt rather than
# the corridor: the corridor is the bitline/hit descent zone and full-width
# met4 bars there forced DRT into shorts (tile29).
# VDPWR bar y 43.0..44.6: VDD risers (y 6.25..61.0) merged; BELOW the VGND
# risers (start 46.0) and ABOVE the band OBS met4 blobs (end 42.595), so only
# VGND straps need gaps.
# ---------------------------------------------------------------------------
hbar $swP 2.0 158.0 43.0 44.6 $vgnd_straps
# VGND bar y 74.0..75.6: VGND risers merged; VDD risers end at y 61.0, so only
# VPWR straps need gaps.
hbar $swG 2.0 158.0 74.0 75.6 $vpwr_straps

# ---------------------------------------------------------------------------
# Array VGND: met1 strip (abs 102.4..156.9 x 199.2..199.6) -> three met1->met4
# stacks -> met4 bar above the array -> merges the VGND straps crossing it
# (c157.9; c145.35/c150.35 also in span). Stack sites clear PRE_N (met3, abs
# x 118.085..118.495) and the riser-strap. The met3->met4 hop happens at
# y 200.4, ABOVE the VPWR met4 strip (ends 199.55), so the met4 pad clears it
# by > 0.4.
# (Array VPWR binding: the c153.98 riser-strap merges the met4 VPWR top strip
# directly.)
# ---------------------------------------------------------------------------
# avoid list = FULL-height VPWR straps only (partials stop at y 101)
hbar $swG 102.0 158.5 200.0 201.6 [fulls $vpwr_straps]
set merged 0
foreach s [fulls $vgnd_straps] { lassign $s a b; if { $b > 102.0 && $a < 158.5 } { incr merged } }
if { !$merged } { puts "\[ERROR\] pdn_patch: no VGND strap crosses the top bar (102..158.5)"; exit 1 }

foreach x {110.0 130.0 148.0} {
    # met3 riser bridging the strip level to above the VPWR strip
    pbox $swG $M3 [expr {$x - 0.3}] 199.2 [expr {$x + 0.3}] 200.8
    odb::dbSBox_create $swG $v12 [um $x] [um 199.4] STRIPE
    odb::dbSBox_create $swG $v23 [um $x] [um 199.4] STRIPE
    odb::dbSBox_create $swG $v34 [um $x] [um 200.4] STRIPE
}

# --- surgical well taps for the short band-belt row segments. Rows in the
# odb are FULL-WIDTH (only cells avoid the macros), so target fixed site-
# aligned x positions on every belt row: the inter-band gap (x ~83.7, whose
# filler nwells otherwise float: 13x LVS FILLER_*/VPB + magic nwell.4) and
# two east-belt spots (x ~147.2 / ~152.7, whose 10um segments the 12um tap
# grid skips: 260x magic LU.3/LU.2). The tool's taps/endcaps are already
# placed when this runs, so each target searches +-8 sites for a free slot.
set tap_master [[ord::get_db] findMaster sky130_fd_sc_hd__tapvpwrvgnd_1]
if { $tap_master eq "NULL" } { puts "\[ERROR\] pdn_patch: tap master missing"; exit 1 }
set tw [$tap_master getWidth]
# occupancy map: existing instance x-ranges per row-origin y
array set occ {}
foreach inst [$block getInsts] {
    set bb [$inst getBBox]
    lappend occ([$bb yMin]) [list [$bb xMin] [$bb xMax]]
}
set ntap 0
foreach row [$block getRows] {
    set rb [$row getBBox]
    if { [$rb yMin] < [um 5.9] || [$rb yMax] > [um 79.1] } { continue }
    # rows are CUT into segments around the macros: place each target only on
    # the segment that contains it, clamped inside the segment bounds
    set ry [$rb yMin]
    set existing [expr {[info exists occ($ry)] ? $occ($ry) : {}}]
    foreach {tx lo hi} [list 83.72 83.05 85.66 147.20 145.30 155.40 152.72 145.30 155.40] {
        if { [um $tx] < [$rb xMin] || [um $tx] > [$rb xMax] } { continue }
        set slo [expr {max([um $lo], [$rb xMin])}]
        set shi [expr {min([um $hi], [$rb xMax])}]
        set placed 0
        foreach k {0 1 -1 2 -2 3 -3 4 -4 5 -5 6 -6 7 -7 8 -8} {
            set x [um [expr {$tx + $k * 0.46}]]
            if { $x < $slo || [expr {$x + $tw}] > $shi } { continue }
            set free 1
            foreach iv $existing {
                lassign $iv a b
                if { $x < $b && [expr {$x + $tw}] > $a } { set free 0; break }
            }
            if { $free } {
                set inst [odb::dbInst_create $block $tap_master "ANKHDJET_BTAP_$ntap"]
                $inst setOrient [$row getOrient]
                $inst setLocation $x $ry
                $inst setPlacementStatus FIRM
                lappend occ($ry) [list $x [expr {$x + $tw}]]
                set existing $occ($ry)
                incr ntap
                set placed 1
                break
            }
        }
    }
}
puts "pdn_patch: belt taps placed: $ntap"
if { $ntap < 20 } { puts "\[ERROR\] pdn_patch: expected ~78 belt taps, got $ntap"; exit 1 }

# NOTE: do NOT paint special wires on routed SIGNAL nets here (e.g. met3 tip
# fills for the bands' VREF/STROBE strip entries): GRT treats snet-bearing
# signal nets as pre-routed and SKIPS them (guides=0 despite 33 terminals in
# tile35) -- they would reach DRT unrouted and end up as opens. Signal-side
# DRC cosmetics belong AFTER routing (post-flow GDS paint), never before.

puts "pdn_patch: done (9 straps, [expr {$nP + $nG}] rail stacks, 2 belt bars, 3 VGND stacks, top bar)"
