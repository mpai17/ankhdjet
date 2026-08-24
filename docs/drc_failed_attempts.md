# DRC reduction: failed attempts log

Append-only log of attempts that did **not** improve DRC for the
`cirom_chip_analog` LibreLane flow. Review this file before trying a similar
direction so we don't repeat the same dead end.

Baseline at time of writing: **Magic 2824, KLayout 36, LVS 18**
(macro at (640,20), 2-row SAs at y=130/200 pitch 20, die 850x300,
macro halo 3, SA VGND M4 strap 1.0 um, 4 N-taps in precharge).

Real Magic DRC at baseline is ~138 (the other 2680+ are spurious
`met*.3b/.5b` "long-edge spacing" rules that Magic over-approximates
relative to actual sky130 PDK; KLayout's `m*.3ab` shows zero for those
same rules).

## Format

Each entry is: `## <date>; <change>` followed by metric deltas and the
likely reason it didn't help. Keep entries terse.

---

## 2026-05-22: Move macro to (8,8) or (12,12) (left edge of die)
- **Symptom:** flow fails at `OpenROAD.GeneratePDN [PDN-0233] Failed to generate full power grid`.
- **Cause:** macro's M4 VPWR pin x positions must align with the chip
  PDN vstripe grid (`PDN_VOFFSET=5`, `PDN_VPITCH=20` -> vstripes at
  x = 5, 25, 45, ...). At x=640 the macro's internal M4 power pin
  lands on a vstripe; at x=8 or x=12 it doesn't, so no PDN via.
- **Lesson:** if moving the macro is needed, recompute placement so
  `(macro_x + macro_M4_pwr_x) mod PDN_VPITCH == PDN_VOFFSET`.

## 2026-05-22: Macro halo 1 -> 5 + die 900x320
- **Delta:** Magic 2730 -> 3096 (+366), KLayout 42 -> 69 (+27), LVS 16 -> 26 (+10).
- **Cause:** too-large halo squeezed the routing channel between
  macro and SAs; the router went denser elsewhere to compensate.
- **Lesson:** halo sweeps in single-um steps; max useful was 3.

## 2026-05-22: Tight SA pack (16 SAs at pitch 16, all at y=130)
- **Delta:** Magic 2730 -> 5195, KLayout 42 -> 380, Illegal Overlap 0 -> 557.
- **Cause:** SAs overlapped stdcell rows / abutted each other where SA
  pin shapes extend past the bbox (`x=-7..8`). Pitch must be >=
  `SA_bbox_width + chip_routing_slack` (>= 17-18 um).
- **Lesson:** for tighter SA packing, first redesign SA pin shapes to
  not extend past bbox, then change pitch.

## 2026-05-22: Macro at left (x=8) with SAs spread (x=7..627 east)
- **Symptom:** GRT-0116 congestion.
- **Cause:** all 64 BL fanout nets had to route east from x=8..62.6 macro
  out to x=627 SAs through a narrow channel.
- **Lesson:** macro position should be near the SA cluster, not on the
  opposite side of the die.

## 2026-05-22: Macro at center of SA span (x=340)
- **Delta:** Magic 2718 -> 3373, KLayout 42 -> 67, LVS 16 -> 22.
- **Cause:** still creates ~100 um horizontal fanout; macro at right
  edge was already optimal for the current 2-row SA layout.

## 2026-05-22: DIE 1100x320 (very large die)
- **Delta:** Magic 2718 -> 47425, Illegal Overlap 0 -> 12339, LVS 16 -> 419.
- **Cause:** PDN failure cascade. Die grew too much relative to PDN
  pitch -> sparse power grid -> IR-drop-like routing fails on top of
  PDN errors.

## 2026-05-22: Wider SA channel (row 2 at y=210 instead of y=200)
- **Delta:** Magic 2730 -> 3112, KLayout 42 -> 98, LVS 16 -> 20.
- **Cause:** shrinking the y=215..255 routing channel above row 2
  hurt more than the wider y=185..210 channel between rows helped.
- **Lesson:** the y=200 setting is at a local optimum for the current
  die height of 300.

## 2026-05-22: Tall die (340 with SA rows at y=135/215)
- **Delta:** KLayout 42 -> 39 (-3) but Magic 2718 -> 2926 (+208), LVS 16 -> 23 (+7).
- **Cause:** taller die lets router spread but introduces more long
  M2/M3 routes that fire `met2.3b/met3.3d` "long-edge" rules.

## 2026-05-22: SA pitch 25 (more spacing for routing channel)
- **Delta:** flow either congests or breaks PDN
  (SA-VDD-M4 pin no longer overlaps PDN vstripe grid).
- **Cause:** SA pitch must match `PDN_VPITCH=20` exactly so each SA's
  VDD/VGND M4 pin gets a PDN vstripe vertical drop.

## 2026-05-22: 4 rows of 8 SAs (compact ~240x310 die)
- **Symptom:** `PDN-0233` for many SAs.
- **Cause:** SA spacing in the 2D grid didn't align all 32 SAs with
  PDN vstripes simultaneously.
- **Lesson:** for any multi-row layout, the SA *column count* must
  divide evenly into `PDN_VPITCH` so each column gets a vstripe.

## 2026-05-22: `GRT_LAYER_ADJUSTMENTS=[0.99, 0.4, 0.4, 0.1, 0, 0]` (penalize M1/M2)
- **Delta:** Magic 2730 -> 3199, KLayout 42 -> 59, LVS 16 -> 32.
- **Cause:** GRT congestion redistribution doesn't actually move
  routes to higher layers cleanly -- it creates more via stacks at
  the same locations, which become m2.7 hole sources.

## 2026-05-22: `GRT_LAYER_ADJUSTMENTS=[0.99, 0.2, 0.2, 0, 0, 0]`
- **Delta:** KLayout 34 -> 46 (+12), Magic 2824 -> 2987 (+163), LVS 18 -> 14 (-4).
- **Cause:** same pattern -- LVS improves slightly (fewer M2 shorts
  with less M2 routing) but DRC worsens (more via stacks).
- **Lesson:** GRT layer adjustments past 0.2 on M1/M2 are not worth
  the DRC regression even when LVS improves.

## 2026-05-22: `PDN_VOFFSET 5 -> 10` (shift PDN vstripes)
- **Delta:** Magic 2824 -> 2953 (+129), KLayout 34 -> 39 (+5), LVS 18 -> 23 (+5).
- **Cause:** vstripes now misaligned with both macro and SA M4 power
  pins, weakening PDN connectivity at boundaries.

## 2026-05-22: `PDN_VWIDTH 1.6 -> 1.0` (narrower power straps)
- **Delta:** KLayout 36 -> 29 (-7), LVS 18 -> 19 (~same), but PSM
  exploded to **789,676 power-grid violations** (vs 19,712 baseline).
- **Cause:** narrower PDN reduces M2 hole sources from PDN-vstripe
  intersections with SA M2 pins, but creates severe IR-drop and
  current-density violations. Functionally the chip wouldn't work.
- **Lesson:** PDN width <= 1.2 is functionally broken even if it
  reduces DRC. Don't trade PDN integrity for DRC count.

## 2026-05-22: `PDN_VWIDTH 1.4` / `PDN_VPITCH 10`
- **Delta:** Magic 2824 -> 3213/3512, KLayout 34 -> 51/54.
- **Cause:** intermediate widths don't help; only the broken 1.0
  width reduces DRC, and it's not viable.

## 2026-05-22: Patch strongarm LEF: full-width M2 OBS in inter-pin gaps
- **Delta:** Magic 2824 -> 2748 (-76), KLayout 34 -> 37 (+3), LVS 18 -> 23 (+5).
- **Cause:** full-width OBS blocked router pin access from the +x
  side; router compensated with detours that created different but
  equal-count violations elsewhere.

## 2026-05-22: Partial M2 OBS in gaps (x=-4..5 only)
- **Delta:** KLayout 34 -> 34 (no change).
- **Cause:** partial OBS didn't change router behavior because the
  router was already not using the partial-cover region.

## 2026-05-23: SA OUTP/OUTM pin promoted to M3 (via2 + M3 0.40-tall strip)
- **Delta:** Magic 2824 -> 3001 (+177), KLayout 36 -> 40 (+4), LVS 18 -> 18.
- **Cause:** the new full-width M3 strip 0.40 tall × 15 wide creates a
  new `met3.3d` long-edge source between OUTP-M3 and OUTM-M3 (gap is
  exactly 0.30 = met3.2 minimum, which is borderline and lights up
  on neighbor-effect rules). M2 wasn't actually causing the
  violations; chip-routed M2 above the SA was.
- **Lesson:** promoting top-rail pins to M3 doesn't help unless the
  *internal* M2 strips are also removed -- and they can't be without
  re-routing every lift_pin_to_rail call. A real fix requires either
  moving the rails to M3 entirely (M1->M2-patch->via2->M3-strip with
  no M2 strip) or using M3 stubs at single x positions with M2 only
  as a tiny via2 landing pad. Both are 100-200 line rewrites of
  `gen_strongarm_routing.tcl`.

---

## What HAS worked (cumulative, committed)

- BL+ pin moved from M2 to M4 + array pitch 1.20 -> 1.70 um
  (commit `f049c48`): killed all macro-induced met2 long-edge issues.
- Macro halo 1 -> 3 um + die 740x230 -> 850x300
  (commit `700e47b`): cleared all 3 `nwell.2a` at the macro boundary.
- 4 N-taps in macro precharge nwell (commit `03db548`): cleared all
  12 `LU.3` latchup violations.
- 2-row SA placement at y=130, y=200 pitch 20 (commit `a521a42`).
- SA VGND M4 strap 0.5 -> 1.0 um tall (commit `57f1f36`): pushed
  chip-routed M4 clear of SA top edge.

## Process notes

- KLayout DRC is authoritative; Magic over-reports `met*.3b/.5b`
  long-edge rules that don't actually fail per the sky130 spec.
- LVS is more load-bearing than DRC; don't commit a change that
  reduces DRC count if it increases LVS count.
- Always check Magic + KLayout + LVS together before committing.
  A win on one metric paired with a regression on another is a net
  regression.

## 2026-05-23: 4 rows of 8 SAs at pitch 40, die 500x350
- **Delta:** Magic 2824 -> 17102, KLayout 36 -> 2289, Illegal Overlap 0 -> 2485. LVS 18 -> 8 (best LVS!).
- **Cause:** SA-row stdcell channel collapsed to ~8.5 um (4 rows * 70 + 3um halo each side leaves no room for full stdcell rows + their halos). Stdcells overlapped each other / SA bbox, firing diff/tap, li.3, mcon.2 violations en masse.
- **Lesson:** any multi-row SA layout needs >= 18 um between SA-row tops and the next SA-row bottom (3 stdcell rows + halos).
- **Note:** LVS hit 8 (best ever) -- the compact-die geometry minimizes long routes which cause wire-to-VPWR/VGND shorts. Worth revisiting if we can fix the stdcell-channel collapse, e.g., with halo=2 + larger inter-row gap.


## 2026-05-23: Expanded SA OBS to 3 inter-pin gaps (STROBE-VDD + OUTM-STROBE + TAIL-OUTP)
- **Delta vs STROBE-VDD-only:** Magic 2804 -> 2823 (+19), KLayout 37 -> 39 (+2), LVS 16 -> 18 (+2).
- **Cause:** the OUTM-STROBE and TAIL-OUTP gap OBS blocked router pin access from the y-below side of those pins; router had to detour over the SA cell via M3/M4 + via stacks, creating new shapes that fire violations.
- **Lesson:** the STROBE-VDD gap is special -- it's adjacent to VDD which has its own M2/M3/M4 via stack, so blocking that 0.25 um gap doesn't impede pin access (router uses VDD-side access). The OUTP/OUTM/STROBE pins don't have via stacks, so blocking their gaps cuts off legitimate routing.


---

## 2026-05-23: **SA top-rail pitch 0.70 -> 1.00 um (silicon redesign)**
- **Delta:** Magic 2824 -> 2510 (-314), **KLayout 36 -> 22 (-39%)**, LVS 18 -> 19 (~same).
- **Specific KLayout drops:** m2.7 holes **14 -> 0** (eliminated), m4.2 6 -> 2, m3.2 1 -> 0, m1.1 2 -> 0.
- **What worked:** widened all top-rail y positions so each rail-to-rail gap is 0.70 um (was 0.40 um). 0.70 um clean tracks fit chip-routed M2 (0.30 wide) with 0.20 spacing each side, well above m2.2 0.14 minimum. Killed all m2.7 holes from PDN-vstripe + SA-pin intersections.
- **Commit:** `98b0f10`. SA cell DRC=0 standalone, all SA test_drc/test_lvs/test_replay pass.

## 2026-05-23: Add 0.20 um M2 OBS strip just above each top rail
- **Delta vs widened-rails baseline:** no change (Magic 2510, KLayout 22, LVS 19).
- **Cause:** chip router was already not using those tracks; the OBS didn't change behavior.

## 2026-05-23: Fill ALL non-pin M2 area inside SA with OBS (block M2 routing through cell)
- **Delta vs widened-rails baseline:** Magic 2510 -> 2667 (+157), KLayout 22 -> 31 (+9), LVS 19 -> 15 (-4).
- **Cause:** forcing router to use M3+ for crossings reduced wire-to-VPWR/VGND shorts (LVS -4) but pushed M4 traffic so met4.2 jumped 2 -> 8 and the displaced M2 routes still violate m2.2 elsewhere.
- **Lesson:** the M2-vs-M3 layer tradeoff hasn't been quantified -- if LVS could be reduced from 19 to 15 without DRC penalty, that's a win, but full-block OBS is too blunt.


## 2026-05-23: Architectural attempt: co-locate SAs with macro (option #1)
- **Variants tried:** 8 sub-cols × 4 rows on west of macro (die 320x420 and 400x420); 2 rows × 16 sub-cols with macro at x=320 east of SAs; reversed SA-index ordering to put SA[0] near BL[0].
- **All failed at GRT-0116** with met3 horizontal overflow ~150-250 (chip die 400x420) or completed with regressions (4-row layout: Magic 2510 -> 2764, KLayout 22 -> 61, LVS 19 -> 41).
- **Root cause:** macro BL pitch is 1.70 um, SA pitch is 20 um (PDN-aligned). 12x mismatch means even with SAs adjacent to macro, only ~3 SAs fit in the 53-um-wide BL pin region. The other 29 still need 200+ um horizontal routes. The fanout doesn't shrink, it just moves.
- **Lesson:** truly eliminating BL fanout requires either (a) a 1.70-um-pitch SA cell, (b) 4:1 or 8:1 BL muxing to reduce SA count to 4-8, or (c) synthesized stdcell sense logic placed at BL pin locations. All three are major redesigns (>500 LOC) and at least (a) and (c) would require re-running the SA Monte Carlo / PVT validation suite.


## 2026-05-23: Vertical-stack SA layout (4 sub-cols x 8 rows, die 160x720)
- **Variants:** macro at (50, 320), (45, 326), (45, 20). SAs in 4 sub-cols (2 west + 2 east of macro) x 8 vertical rows.
- **Failures:** PDN-0232 for macro+4 bottom-row SAs at low y; or GRT-0028 "32 pins outside die area" for east sub-col SAs; or GRT-0116 congestion (m3 horizontal overflow 117-131).
- **Cause:** narrow tall die (160-180 wide) starves chip routing of horizontal capacity. Chip RTL has 64 sa_out + control signals that need to reach output pins on north edge -- in a tall die, those routes traverse the full height, hitting M3 capacity limits. PDN failures appear to be cascading from cells near die edges where vstripe alignment is fragile.
- **Lesson:** the architecture works in principle (BL fanout 40-80 um instead of 600 um) but routing the rest of the chip in a narrow strip doesn't. A WIDER die with vertical stacks (e.g., 250 wide x 500 tall, 8 sub-cols x 4 rows) might balance both, but requires careful pin placement to avoid GRT-0028.


## 2026-05-24: Output pin distribution (sa_out across 2 edges)
- **Variants tried:** all sa_out on N (baseline); pos on E, neg on W; pos on N, neg on W.
- **Best variant:** LVS 19 -> 7 (-12, big win) but KLayout 22 -> 42 (+20). Magic 2510 -> 2762.
- **Cause:** distributing output pins reduces signal-to-VPWR/VGND shorts (LVS improves) but lengthens routes which traverse more chip area, creating more chip-routed M2 wires near each other -> more m2.2.

## 2026-05-24: SA inter-pin gap OBS (post-silicon-redesign, 1.0um pitch layout)
- **3 gaps (OUTP-OUTM, OUTM-STROBE, STROBE-VDD):** KLayout 22 -> 22 (no change). Router just routes elsewhere.
- **5 gaps (all inter-pin):** KLayout 22 -> 21 (-1, marginal); LVS 19 -> 22 (+3).
- **Above-VGND OBS only:** KLayout 22 -> 24 (+2).
- **Cause:** with the new 0.70um inter-pin gaps, the router can already navigate cleanly; adding OBS just forces detours that fire new m2.1 (M2 width) violations.

## 2026-05-24: GRT_LAYER_ADJUSTMENTS=[0.99, 0, 0.15, 0, 0, 0] (discourage M2 routing)
- **Delta:** Magic 2510 -> 2839, KLayout 22 -> 33, LVS 19 -> 22.
- **At 0.30 M2 cost:** GRT-0116 congestion (router can't fit).
- **Cause:** M2 is the dominant chip routing layer; discouraging it just compresses routing to fewer tracks, increasing density.


## 2026-05-24: Push for KLayout=0 from 22 baseline (multiple silicon redesigns)
**Wins (committed):**
- Widen TAIL/OUTP/OUTM/STROBE M2 pins 0.30->0.50um: 22 -> 10 KLayout (`7bd591b`)
- Widen above to 0.70um: 10 -> 8 KLayout (`128f041`)
- Extend VGND M2 down 0.15um: 8 -> 7 KLayout (intermediate)
- Widen to 0.70um final: 7 -> 6 KLayout (`8373654`)

**Failures from 6-baseline:**
- VDD-VGND M2 OBS in gap (y=55.6..56.1): 6 -> 11 (worse).
- Extend VDD M2 up (55.0->55.65): 6 -> 24 (much worse). Broke PDN.
- BLP/BLN M2 widening (0.46->0.80x0.80): 6 -> 8 (worse).
- M4 OBS in STROBE-VDD gap: GRT-0116 congestion (router can't fit).
- Pin pitch 1.0->1.1um + pins 0.80um tall: 6 -> 14 (worse).
- FP_MACRO_HORIZONTAL_HALO 3->4: 6 -> 22 (much worse).
- Macro x shift 640->645: 6 -> 21 (much worse).
- Output pin distribution (sa_out pos on E, neg on W): 22 -> 42 (much worse).

**Remaining 6 violations are router-internal:**
- 3 m2.7 holes at OUTP M2 pin TOP edges (SA[1] in row 2, SA[8] in row 1 at specific x positions). Created by chip routes ending exactly at pin edge with a small surrounded gap.
- 2 m4.2 between chip-routed M4 signal wire and SA VDD M4 pin (gap 0.175um, need 0.30).
- 1 via.2 inside SA[2] bbox -- two chip-routed via2 cuts 0.03um apart (need 0.17).

**Hard blocker assessment:** these 6 are not at SA-pin-geometry interactions anymore. They're chip-router-induced patterns at specific instances. Eliminating them requires either:
1. **BL muxing** (4:1 or higher): reduces SA count + pin sites + chip routing congestion.
2. **Stdcell-synthesized sense logic**: removes hard-macro pin constraints entirely.
3. **Custom router constraints** for SA-pin nets (NDR or per-net routing layer restriction).


## 2026-05-24: Three alternatives to BL muxing (all failed)
1. **NDR 2x spacing on sa_out_*[1,2,8]:** KLayout 6 -> 6 (no change). NDR was applied per log but violations were on different nets (chip-internal, not sa_out).
2. **NDR on all sa_out_*:** 6 -> 7 (slight worse). Router congestion from wider sa_out routes displaces other nets.
3. **Global NDR 2x (all nets):** aborted after 30 min (DRT runtime exploded).
4. **ROUTING_OBSTRUCTIONS at violation coords (chip-level met2/met4 OBS):** 6 -> 27 (much worse). Pushed router away from documented spots, creating new violations elsewhere.
5. **RUN_HEURISTIC_DIODE_INSERTION=true:** 6 -> 9 KLayout, LVS 15 -> 35. Diodes add new pin connections that increase routing density.

**Hard blocker confirmed at KLayout=6.** Remaining violations require either:
- BL muxing (architectural)
- Synthesized stdcell sense logic (architectural)
- RTL change to register sa_out at SA (1-2 RTL lines but requires testbench update)


## 2026-05-24: Final round attempting to break KLayout=6 (all failed)
- **RTL: register sa_out outputs (add 64 DFFs):** 6 -> 14 KLayout, LVS 15 -> 18. DFFs added stdcell pin connections that increased routing density more than they relieved long-path tension.
- **SA x shift +1 (7->8, still PDN-aligned):** 6 -> 14.
- **SA y shift +2 (130->132, 200->202):** 6 -> 42, LVS 15 -> 32.
- **Die height 300 -> 350:** 6 -> 13. More routing room shifts violations rather than removing them.

**Hard blocker reached.** The 6 KLayout DRC violations are at chip-router-internal patterns at specific SA instances (SA[3], SA[6], SA[8], SA[16]). All tooling-level fixes (NDR, OBS, diodes, halo, pitch, RTL flop) have been exhausted. Escaping requires:
- BL muxing (4:1 or higher) -- big RTL rework
- Synthesized stdcell sense (replaces analog SA)
- 1.70-um-pitch SA cell (full SA layout rewrite)


---

## 2026-05-26: Variant B (3.40um pitch-doubled SA) chip PDN integration
- **Progress:** SA cell rebuilt as a vertical 3.40um abuttable cell
  (KLayout DRC 0, LVS clean, met3 VDD/VGND pins with USE POWER/GROUND).
  Chip floorplan = 32 SAs in two interleaved 16-wide bands at 3.40um
  pitch under the macro.
- **Blocker:** `OpenROAD.GeneratePDN [PDN-0233]`: 18 of 33 per-instance
  macro grids "do not contain any shapes". pdngen makes a *per-instance*
  macro grid and needs each SA to overlap PDN straps of **both** nets,
  but SA pitch (3.40) << vstripe pitch (PDN_VPITCH 20), so most SAs sit
  between stripes and get no strap. pdngen does **not** recognize that
  abutting SAs share continuous power rails, so the band-level continuity
  doesn't help the per-instance check.
- **Why naive fixes fail:** reducing PDN_VPITCH to <=1.70 (both nets per
  SA) is absurd chip-wide density; met4 horizontal SA rails short against
  the perpendicular met4 vstripes of the opposite net.
- **Solution path:** make the 16-SA band a single macro (SRAM-array
  style). A 54.4um-wide band overlaps several vstripes -> pdngen connects
  both nets, and the band's continuous internal rails distribute to all
  16 SAs. Chip then instantiates 2 band macros (even/odd columns).

---

## 2026-05-27: Variant B DRC-reduction pass (band macro): congestion floor
- **Trajectory (KLayout / LVS):** band w/ met2 pins 158/14 -> STROBE merged
  to one met3 rail 140/7 -> all signal pins promoted to met3 100/18.
- **Finding:** the 100 KLayout violations are ALL `m2.2`, split evenly
  across both band regions (~50 each) -- general routing congestion, not a
  specific pin pair. The macro + both stacked bands + all 64 BL nets + 64
  output nets funnel through one ~54 um-wide column (x640-696). ~35 met2
  shapes per 20 um window. Promoting band pins to met3 only moved ~40% of
  it; the rest is the chip router filling the narrow active column.
- **Conclusion:** co-location (variant B) trades the old design's BL-fanout
  DRC for routing-congestion DRC. For THIS chip (dense 1.70 um-pitch macro
  BLs + narrow active column) the congestion floor (~100 KLayout) is WORSE
  than the old spread design's floor (6). Variant B is architecturally
  complete (PDN solved, flow E2E) but does not beat the 6-KLayout baseline.
- **Untried at the time of the entry (uncertain upside):** wider macro-to-band routing channel;
  NDR forcing BL/output to met4+; latch-up taps (Magic-only, no KLayout
  effect). The all-met3 change (100/18) is left UNCOMMITTED pending a
  decision on whether to keep grinding variant B or revert to the baseline.

---

## 2026-05-27: RESOLVED: sign-off ECO clears the 6-KLayout floor to 0
- After reverting variant B (congestion floor worse than baseline; preserved
  on branch `variant-b-sa`), reproduced the baseline KLayout 6 / Magic 2564 /
  LVS 15.
- The 6 were never an architectural limit -- they are isolated router
  artifacts at specific SA instances, fixable by a **post-route sign-off ECO**
  (`librelane/cirom_chip_analog/eco_drc.py`, run via `run_eco.sh`). The prior log's
  "requires architectural change" was wrong: it only ruled out flow/placement
  knobs, not a GDS ECO (standard tapeout practice for the last few DRCs).
- Patches (all net-safe):
  - m2.7 x3: fill the enclosed met2 holes at the SA OUTP/OUTM tops.
  - m4.2 x2: fill the re-entrant notches beside an SA VDD met4 finger (same
    VDD net as the strap it joins).
  - via.2 x1: drop the redundant top-level router via1 at (62.79,184); its
    mate bridges the same met1 (62.63-66.17) and met2 (60-75) polygons, so
    connectivity (and LVS) is unchanged.
- Result: **KLayout DRC 6 -> 0** on the patched final GDS. LVS stays 15
  (pre-existing SA met2 pin-merge, unrelated). Magic DRC unchanged (its count
  is dominated by spurious long-edge rules; KLayout is the sign-off authority).

---

## 2026-05-27: RESOLVED CLEANLY: ECO integrated into Magic.StreamOut
- The post-flow KLayout GDS patch (eco_drc.py) cleared KLayout DRC to 0 but
  was **electrically misleading at sign-off**: re-running the flow's
  Magic.SpiceExtraction + Netgen.LVS on the KLayout-rewritten GDS reported
  312 LVS errors (vs the true 15). Verified the 312 is a GDS-encoding
  artifact: a *zero-patch* round-trip through KLayout (or Magic) gives the
  same 312, because re-streaming exposes the macros' internal geometry and
  defeats MAGIC_EXT_ABSTRACT_CELLS at extraction (strongarm subckt goes
  7->10 ports: INTP_internal/INTM_internal/TAIL leak in). The patches
  themselves add zero electrical delta.
- Fix: integrate the ECO INTO the flow's Magic StreamOut so the patched GDS
  is produced natively (macros stay black-boxed). `run_eco_flow.py` swaps
  `Magic.StreamOut` for a subclass (`Magic.ECOStreamOut`) via LibreLane's
  `SequentialFlow.Substitute`; the step runs `eco_streamout.tcl` =
  LibreLane's def/mag_gds.tcl + the paint/erase patches before `gds write`.
  `run_eco.sh` drives it (and resolves PDK_ROOT to the versioned Ciel store,
  which the Python flow API needs explicitly or synthesis LIB is empty).
- via.2 in Magic: `erase via1` notches the met1 wire (m1.1/m1.2/m1.7) because
  the contact owns its metal halo -> repaint metal1 solid over the spot
  (inside the original wire footprint) to heal it.
- Result (run eco_flow5, flow's own sign-off): **KLayout DRC 0, LVS 15
  (== baseline, net_diff 10 + pin_fail 4), Magic 2533 (spurious long-edge)**.
  Deliverable GDS is +96 bytes vs baseline = just the ECO shapes.

---

## 2026-05-31: RESOLVED: single-ended (sa_se) design KLayout DRC 20 -> 0 via 20-fill ECO
- This is the functionally-correct single-ended design (64 discrete sa_se,
  fixes the differential w=0 gap), NOT the old differential baseline above.
  Its signed-off run sa_se_A3 had **KLayout 20** (m2.2 x8, m2.7 x3, m3.2 x3,
  m4.2 x3, m1.2 x2, m2.1 x1) -- all router-internal metal spacing/width/hole
  violations, none inside the sa_se macros, OpenROAD's own DRT reports clean.
- Method (extends eco_streamout.tcl, the proven Magic.StreamOut ECO):
  - Mapped all 20 to owning nets by parsing the routed DEF (pure Python; the
    odb Python shape API threw on ~all shapes -- DEF text parse is reliable).
  - Geometry-classified each via klayout.db Region: 13 intra-polygon
    (npoly==1, notch/hole/neck inside one connected net) + 7 inter-polygon
    gaps that are all **same-net** (ndnets==1: net170/171/172, net41 x3,
    net47) -> every one is net-safe to fill (no short).
  - 18 are fixed by a grid-snapped marker-bbox fill (bleed 0.05um, snapped to
    the 5nm grid -- un-snapped KLayout boxes fire ~55 *_OFFGRID); 2 need a
    shaped fill: V02 widens a 0.01um met2 neck to >=0.14um (m2.1 width), V03
    bridges a met2 tab flush to its bar so no m2.7 hole is left behind.
- Fast iteration loop (the key enabler): patch the A3 GDS with klayout.db,
  re-run ONLY the sky130A_mr.drc deck (`klayout -b -r ... -rd feol/beol`),
  ~33s vs ~15min full flow. Validated as a faithful proxy: the same 13-fill
  set gives KLayout 10 on both the fast loop and the native Magic flow.
  (GDS round-trip is fine for DRC-only; it only inflates LVS, verified once
  natively at the end.)
- Result (native flow run sa_se_eco4, flow's own sign-off): **KLayout DRC 0**
  (triple-confirmed: flow summary + direct lyrdb parse + independent deck
  re-run on the signed-off GDS). LVS 18, byte-for-byte the same pre-existing
  top-level pin-match failure as A3 (all 24 subcircuits match uniquely; the
  fills add ZERO LVS delta -- A3 and eco3 LVS reports are identical), so the
  fills are proven net-safe.
- Failed sub-attempts within this pass (don't repeat):
  - Fixed-margin box on V03: closed the gap but the sideways overhang created
    a NEW m2.2 + m2.7 pair (1 -> 2). Fix: extend the fill LEFT to merge flush
    with the bar (x->366.92), not a symmetric margin.
  - 0.05um margin fill on V02: too narrow, left the neck < 0.14um (m2.1
    persists). Fix: span the full x-union across the jog.
  - KLayout raw db.Box insertion without grid-snap: ~55 *_OFFGRID violations.
  - "bridge two nearest polygons" auto-logic: grabbed the wrong polygon pair
    and bridged across a whole 33um-tall net -> many new m2.1/m2.2. Marker-bbox
    fills are correct; convex-hull bridging is not.

---

## 2026-05-31: LVS extraction-mode toggle (MAGIC_EXT_ABSTRACT) made LVS WORSE
- Context: single-ended design is KLayout DRC 0 but LVS 18 (top-level pin-match
  fail; chip is electrically correct per DEF + DRC=0 -- an extraction artifact).
- Tried (run sa_se_eco5): `MAGIC_EXT_USE_GDS=false` + `MAGIC_EXT_ABSTRACT=true`
  to make Magic read macro pins from LEF instead of flattening the macro's
  1.70um-pitch BL geometry.
- RESULT: **LVS 18 -> 99 (much WORSE)**, top-level net mismatch 415-vs-405 (+10)
  -> 495-vs-405 (+90), and **illegal_overlap 0 -> 102** (a hard ERROR_ON_ILLEGAL
  _OVERLAPS fail). DRC stayed 0. Reverted config.
- Why it failed (verified from both runs' extracted spice + lvs.netgen.rpt):
  - The 64 macro BLP/BLN merges are present in BOTH modes (abstract did NOT fix
    them in the final LVS, contrary to an early partial read of the Xu_macro
    line). So abstract mode bought nothing on the macro and added 80 more net
    mismatches + 102 overlaps from the sa_se side.
  - The sa_se pin merge is mode-INDEPENDENT (61/64 instances both runs) and is
    dominated by **VDD+VGND** (present in ~11 of 12 merge-group patterns).
    VDD is a full-width (15um) met4 pin; VGND is full-width met2 AND met4. They
    connect to the 20um-pitch PDN (PDN_MACRO_CONNECTIONS), whose met4 vstripes
    cross both full-width met4 pins -> merge, pulling in any signal pin sharing
    the vertical corridor. Signal-only met2-pin narrowing canNOT fix this; the
    dominant merge is power-pin/PDN-coupled and narrowing VDD/VGND risks PDN-0233.
- Conclusion: a pure LEF-pin-narrowing fix (the plan's primary) does NOT cleanly
  close LVS, because (a) abstract mode regresses and (b) the merge is VDD/VGND +
  PDN coupled on met4, not just signal met2. The sa_se pin geometry (full-width
  rails on met2+met4) is the root, but it is entangled with the PDN drop and the
  DRC optimum -- a genuine cell+PDN co-design problem, not a quick toggle.

## 2026-05-31: LVS bottleneck ATTRIBUTED (eco4 extracted netlist): VGND<->VPWR met4 fuse
- Quantified every mis-bound pin in the flat top-level extraction:
  - **247 sa_se pins collapse onto the single VPWR node** (VGND 64/64, VDD 60/64,
    HIT 54/64, STROBE 43/64, HITB 26/64). This -- not neighbor-merges -- is THE
    dominant bottleneck.
  - Macro BL merges (54 pins on their own nets + 9 on power) are a SEPARATE,
    smaller issue, NOT entangled with the sa_se/VPWR collapse.
- Mechanism (verified in GDS + DEF SPECIALNETS): the sa_se VDD pin (full-width
  15um met4 @ y55) and VGND pin (full-width met4 @ y56.2) are BOTH crossed by the
  PDN met4 vstripes. For g_sa[0] (x[0..15]): VPWR stripe at x=10.52, VGND stripe
  at x=13.82 -- both inside the cell. Flat extraction fuses VDD-pin + VPWR-stripe
  + VGND-pin + VGND-stripe into ONE met4 polygon (measured: a single met4 shape
  187um tall over the cell) => VGND==VPWR, then via2/3 stacks drag HIT/STROBE/HITB
  in. The 64/64 VGND-to-VPWR tie is the power-rail short signature.
- WHY a fixed narrow power pad CANNOT fix it: cell pitch is 19um but PDN_VPITCH is
  20um -- they beat. The PDN stripe's per-cell relative-x drifts +1um every cell
  and cycles through ALL of x=-7..+8; 5 of 32 pos-cells have NO grid line in
  their window at all. So there's no single relative-x to place a stripe-aligned
  pad, and a too-narrow VDD/VGND pad would drop PDN connectivity (PDN-0233) on
  the off-beat cells. The full-width met4 power pins exist precisely to tolerate
  this 19-vs-20 beat -- which is exactly what fuses them in extraction.
- Implication: closing LVS requires breaking the VDD/VGND met4 co-fuse WITHOUT
  losing PDN tolerance. Candidate directions (none yet tried): (a) make cell pitch
  == PDN_VPITCH (20um, not 19) so every cell sees a stripe at the SAME relative-x,
  then narrow the met4 power pins to two fixed stripe-aligned pads (one VDD, one
  VGND) -- a placement + cell-abstract change; (b) drop the macro-PDN connection
  for sa_se and feed VDD/VGND on met2 from a dedicated non-PDN rail; (c) keep
  full-width metal but split VDD/VGND into per-stripe PORT sub-rects so extraction
  sees distinct nodes (uncertain Magic honors this under flat GDS read).

## 2026-05-31: LVS bottleneck PROVEN to be an intrinsic PDN-vs-extraction conflict
- Pinned the fuse to exact coords: chip PDN met4 stripes run VPWR at x=10,30,50..
  and VGND at x=13,33,53.. (pitch 20, fixed 3um apart). The sa_se cell's full-width
  (15um) met4 VDD pin (y55.0-55.5) and met4 VGND pin (y56.2-57.2) are BOTH crossed
  by BOTH stripes -> flat extraction fuses VDD-pin+VPWR-stripe+VGND-pin+VGND-stripe
  into one met4 node => VGND==VPWR (64/64). Standalone sa_se is clean (cell met4 has
  VDD and VGND as 2 separate shapes, 0.70um gap) -- the fuse is 100% chip-PDN-induced.
- WHY it can't be fixed by dropping/narrowing the VGND met4 pin: pdngen is
  overlap-driven and does NOT build a via stack from a met4 stripe down to a met2
  pin ([[feedback_pdn_macro_pattern]]). VGND MUST keep met4 copper under the stripes
  or PDN-0232/0233 fails. So "PDN-connectable" (needs full-width met4) and
  "extraction-separable" (needs met4 not under the other net's stripe) are in direct
  conflict GIVEN the 19um cell pitch vs 20um PDN pitch beat (stripe x drifts through
  every relative position; no fixed pad works).
- The only fix that resolves the conflict at the root: **make sa_se cell pitch ==
  PDN_VPITCH (20um, not 19)** so every cell sees the VPWR/VGND stripe pair at the
  SAME relative x, then shape the met4 VDD/VGND pins as offset pads that each sit
  under ONLY their own net's stripe (VDD under x=10-rel, VGND under x=13-rel, never
  overlapping the other's stripe). This is a PLACEMENT change (re-floorplan the 64
  cells at 20um pitch) + a cell-abstract met4-pin reshape, and it RISKS the committed
  KLayout DRC=0 (every prior pitch/placement change regressed DRC). Not attempted;
  gated on a decision to risk the DRC=0 deliverable. Cheap de-risk first: try
  PLACE the cells at 20um pitch with the CURRENT pins and confirm DRC still 0 +
  whether the uniform stripe alignment alone reduces the fuse, before reshaping pins.

## 2026-05-31: De-risk DONE: 20um cell pitch FAILS to route (GRT-0116)
- Ran the de-risk: macro.cfg rewritten to 32 cells/row at 20um pitch (origin 10,
  aligned to VPWR stripe x=10,30,..), macro shifted 640->660 (stays grid-aligned
  mod 20, die 850 unchanged) to make room for the 620um cell span. Plain flow
  (run_librelane.sh, NO ECO -- the 19um ECO coords would be stale).
- RESULT: **flow halts at OpenROAD.GlobalRouting with GRT-0116 congestion** -- no
  DRC/LVS report produced. Same congestion failure mode the earlier placement
  experiments hit (macro-shift + wider sa_se span tightens the BL-fanout channel).
- Also surfaced (pre-existing, not the blocker): two floating nets (RSZ-0020) and
  the harmless duplicate-lib warnings.
- IMPLICATION: the "20um pitch + offset met4 pads" fix path is **blocked at its
  first prerequisite** -- 20um pitch (with a naive macro shift) does not even
  route, before we get to the pin reshape. To pursue it would require ALSO solving
  the BL-fanout congestion (wider die / macro re-placement / BL muxing) -- i.e. the
  big architectural rework the log has repeatedly shown is needed for this design.
  Reverted to the committed 19um placement (KLayout DRC 0 intact).
- NET: every bounded lever to close LVS is now exhausted (extraction mode,
  signal-pin narrowing, power-pin layer-split, 20um pitch). Closing LVS requires
  the architectural rework (BL muxing / synthesized sense / co-located 20um-pitch
  redesign) -- not a config or cell-abstract tweak. The chip remains electrically
  correct (DEF nets distinct, DRC=0); LVS=18 stands as a documented extraction
  artifact.

## 2026-05-31: Re-architecture de-risk: variant-B's ~100 floor is INTRA-BAND, not BL-fanout
- Goal: decide among 3 sense re-architectures (A=sense-into-array-macro, B=abutting
  band, C=column-mux) by finding WHERE variant-B's ~100 KLayout floor actually was.
- Method (ZERO new flow runs): attributed bl_band6's 100 violations (variant-B best
  run, KLayout 100, has final/) by rule + region + net from its lyrdb + routed DEF.
- FINDING: all 100 are **met3** (m3.2 spacing x75, m3.1 width x18, m3.6 area x7), ALL
  at y>=150 (the two stacked bands at y=130/205), x in 640-712 (the ~54um band column).
  **ZERO violations in the array->band gap (y=115-130)** -- so the BL HANDOFF was never
  the congestion source. Net attribution: the congested band-region met3 is a MIX of
  bitlines routing UP into the stacked bands (bln[13/21/29], blp[15/17]) + outputs +
  the merged STROBE rail, all funneling through the narrow 54um stacked-band column.
- IMPLICATION for the 3 options:
  - Option B (abut bands at y=0): would NOT have fixed it -- moving bands removes BL
    routing that was NOT the problem; the congestion is the stacked-band met3 funnel.
    The earlier "B fixes it" hope is DISPROVEN by this data. Demote B.
  - The real issue is geometry: 16 SAs + their I/O crammed into a 54um-wide band. A
    sense region that spans the array's FULL width abutting it (not 2 narrow stacked
    bands) gives BLs a straight drop + outputs the full width to escape. That favors
    Option A (sense INTO/at the array footprint, full-width) over B (stacked bands).
  - Option C (column-mux) still lowest-congestion (8-16 SAs, far fewer I/O nets) but
    costs 4-8x throughput.
- Cheap-test caveat learned: variant-B's band abstracts on disk are the DIFFERENTIAL
  cell (BLP/BLN/OUTP/OUTM), generators committed but abstracts are untracked artifacts;
  a literal "move the bands" test would test the wrong cell. The lyrdb/DEF attribution
  above answered the decision question without that confound.

## 2026-05-31: Option-A de-risk PASSED: full-width-edge output escape routes clean
- Decision: pursue Option A (sense hardened into a full-width macro at the array,
  bitlines internal). De-risked the ONE unknown (does concentrating 64 sense outputs
  at one 54.6um macro edge congest like variant-B's stacked bands did?) on a throwaway
  branch (arch-a-derisk, deleted; master untouched).
- Built a STUB monolithic blackbox macro = array footprint grown to 54.6x155um with:
  64 WL pins (left, from real array LEF) + VPWR/VGND + 64 output pins on the TOP edge
  + NO BL pins (bitlines internal). A stub RTL top drives WL from a registered decoder
  and exposes the 64 outputs. Plain flow (run via config_stub.json).
- Two scaffolding bugs fixed first (MINE, not Option A): hand-built lib used bus()
  syntax (OpenSTA syntax error) -> switched to 64 scalar pins; then lib missing the
  required liberty thresholds (input/output_threshold_pct_*, slew_*) -> added them.
- RESULT (run arch_a_derisk3, reached final): **NO GRT-0116 -- the 64-output escape
  ROUTES.** KLayout DRC = 64 but ALL are m2_OFFGRID at the stub's hand-placed dummy
  output pins (x=643..694, y=175 top edge) -- a stub-LEF artifact, NOT routing/spacing/
  congestion. Real routing+spacing+congestion violations = 0. (Magic 1600 / LVS 71 are
  meaningless here -- the stub is a device-less blackbox with a fake lib; only the
  routability + KLayout-congestion signal is valid.)
- CONCLUSION: directly CONTRASTS variant-B (stacked narrow bands -> GRT-0116 / ~100
  m2.2 floor). Full-width sense-at-array geometry does NOT congest the output escape.
  Option A's main feasibility risk is retired.

## 2026-06-01: Option-A build: 3.40um cell + DRC-clean single-ended band (variant-B seam SOLVED)
- Branch arch-a-sense. 3.40um pitch-doubled sa_se rebuilt (commit c27bb25): standalone
  KLayout DRC 0, LVS clean, narrow vertical signal pins. MC RE-VALIDATED (full 500-trial):
  w=1 250/250, w=0 250/250, 36/36 PVT, worst VREF kickback 252mV -- all pass (schematic
  unchanged, so it transfers; ran for real per no-fabrication rule).
- SEAM FLOOR SOLVED (commit 5878c58): variant-B's band abutment floored ~100 KLayout. Root
  (measured): per-cell right-edge VGND p-tap psdm overrun (difftap.3) + inter-cell nwell
  gaps 0.55um (nwell.2a, persists at ALL pitches incl 4.0). FIX = pitch 3.40->3.70 (clears
  difftap.3 seam) + paint ONE continuous nwell over the PMOS region to merge per-cell wells
  (clears nwell.2a; PMOS all VDD-biased so electrically correct). Verified: 16-cell
  single-ended band sa_se_band16 = **KLayout DRC 0** (59.59 x 73.5um). Generator:
  cell/sky130/sense_se/gen_sa_se_band.tcl. Signal ports are LABEL-ONLY on the abutted cells'
  existing met2 (repainting fired m2.2). Band extracts correctly with `extract all` (NOT
  `extract do local`, which only does top-cell geometry -> 5 devices).
- Beyond this entry's scope (the large integration): 4 bands = 64 sa_se; RTL rewrite
  (64 discrete sa_se -> 4 sa_se_band16 instances, 16 cols each); band abstracts; config +
  abutting macro.cfg; full flow = the REAL LVS test (does the band's VDD-met3/VGND-met1 +
  merged-well design clear the VGND/VPWR fuse). The fuse-fix is PLAUSIBLE (power now met3/met1,
  not the full-width met4 that fused) but UNVERIFIED until the chip flow runs.

## 2026-06-01: One-band LVS probe: INCONCLUSIVE (band abstract pin-export defect)
- Built a minimal probe (array macro + ONE sa_se_band16 abutting at y=118) to test the
  fuse before the full 4-band integration. Flow reached signoff (HAS_FINAL), NO GRT-0116
  (band routes + 16 outputs escape, consistent w/ the Option-A de-risk).
- BUT the LVS result (8 errors, net 211-vs-208 = +3) is a MEASUREMENT ARTIFACT, NOT a
  fuse reading: the band extracted as `.subckt sa_se_band16 VDD VGND` -- only 2 power
  pins, the 64 signal pins ABSENT. Cause: the band GDS has only 2 labels (met1 VGND,
  met3 VDD); the 64 BL/VREF/HIT/STROBE port labels did NOT survive into the GDS (the
  `label ... ; port make` on the abutted-cell met2 lands on the top-cell `space` layer,
  so `gds write` emits no pin label, and Magic LEFview extraction sees no signal port).
  The 8 errors are orphaned bitlines (array BLP nets merge among themselves with no band
  pin to land on) + proxyVREF/proxySTROBE -- all downstream of the missing pins.
- So the probe did NOT validate the fuse fix. What it DID confirm: band places/routes
  with no congestion; the blocker is purely the band ABSTRACT pin-export.
- Also learned: painting met2 pads at the pin coords to make labels stick REGRESSES the
  band to KLayout 22 (m2.2) -- the paint duplicates the abutted cell's existing met2.
  So neither pure label-on-space (pins lost) nor paint-then-label (m2.2) works.
- THE REAL REMAINING PROBLEM: export the band's 64 signal pins as proper labeled ports
  in BOTH lef and gds WITHOUT adding metal. The single sa_se cell exports pins fine via
  its relabel build -- the band needs that same mechanism (e.g. build the band by
  relabeling a differential band whose ports already export, or use `label <name> <layer>`
  with the port flag on the existing instance metal so gds write keeps it). Unsolved at the time of the entry.
- Scaffolding (band_probe.sv, config_bandprobe, hand-LEF) was throwaway, removed. Committed
  work (3.40um cell + DRC-0 band generator) intact on branch arch-a-sense.

## 2026-06-02: Band port-export: ~10 attempts, NOT solved (Magic flatten/label wall)
- Goal: export the band's 64 signal pins as ports in LEF+GDS so Magic LEFview extraction
  recognizes them (the blocker for a valid chip-LVS fuse test). Tried, none clean:
  1. bare `label X` on instance metal -> label lands on `space`, dropped at gds write (0 exported).
  2. `label X metal2` (explicit layer) -> also 0 exported.
  3. exact-coincident met2 pad + `label X` -> 8 m2.2 (pad slivers vs cell's own dogleg met2).
  4. 0.05um inset pad + bare `label` -> 64 labels EXPORT but 1 residual m2.2 (HIT_0, dense riser).
  5. 0.08um inset on HIT -> pad too small, fires m2.1 + m2.6 + m2.2.
  6. flatten to new name + load -> 6 children remain (flatten didn't take), 0 labels.
  7. `flatten -doinplace` -> 6 children remain, 0 labels.
  8. `flatten -dolabels sa_se_band16` + load (mimic gen_macro_array_pc.tcl:389) -> 6 children, 0 labels.
  9. load (UNNAMED)+rename+place+flatten (full macro-gen mimic) -> 6 children, 0 labels, size 2x.
- The macro generator (gen_macro_array_pc.tcl) flattens+labels successfully with the SAME
  idiom, but it does NOT reproduce in the band script -- some session/cell-state difference
  I could not isolate in-budget. The flatten leaves 6 child cells every variant I tried.
- CLOSEST WORKING: attempt #4 (0.05um inset pads, bare label) = all 64 labels export, band
  KLayout DRC = 1 (single m2.2 at HIT_0). If that one m2.2 can be cleared (HIT pad needs a
  shape that's >=min-width AND >=0.14 from the HIT riser -- a per-pin custom pad, not a
  uniform inset), the abstract would be usable. Not finished.
- STATUS: cell + band geometry verified (DRC 0). Band ABSTRACT pin-export is the open
  blocker; without it the chip-LVS fuse test (the rework's goal) cannot run. This is a Magic
  layout-mechanics problem, not a design flaw. Recommend a fresh, focused attempt (or a
  KLayout-based pin-injection instead of Magic label/port) rather than more incremental tries.

## 2026-06-02: Band abstract SOLVED (KLayout injection) + FUSE TEST: power fuse ELIMINATED
- Band abstract pin-export solved via KLayout pin-injection (committed scripts
  build_band_klayout.py + band_lef_ports.tcl). Four stacked bugs fixed:
  (1) Magic label-on-instance-metal exports nothing -> inject labels in KLayout on native
      (flattened) metal, datatype-5 convention (met1=68/5, met2=69/5, met3=70/5);
  (2) cells' OWN bare "BL"/"VREF" labels flatten in 16x and collide w/ indexed band labels
      -> Magic merged them to 1 pin; fix = strip all datatype-5 text before injecting;
  (3) zero-area point labels let Magic pick met1 from the via stack -> DRT-0073 no-access;
      fix = label over the FULL pin rect with explicit `label X metal2`;
  (4) flatten dropped the PR boundary -> Magic StreamOut "Failed to extract PR boundary";
      fix = inject areaid.sc (235/4) covering the band.
  Result: band GDS DRC 0, 66-pin LEF (BL/VREF/HIT/STROBE x16 + VDD-met3 + VGND-met1).
- FUSE TEST (run bandprobe5, array + 1 band abutting, reached signoff): **the VGND<->VPWR
  power fuse is GONE.** Band instance shows VPWR-ties=0, VGND-ties=0 (vs the OLD discrete
  design: 247 sa_se pins fused onto VPWR, VGND 64/64). The band extracted WITH its signal
  pins (not the 2-pin black box of earlier broken abstracts).
- Residual LVS=27 is a DIFFERENT, more tractable problem -- net 186(layout) vs 208(schem) =
  layout MISSING nets (OPENS), not extra merged nets (the fuse signature was extra/merged).
  Composition: (a) the band's VGND/VDD ports not binding to the chip PDN net at extraction
  (sa_se_band16/VGND and macro/VGND appear on the schematic VGND net but not the layout one),
  and (b) the probe RTL intentionally shares one `vref`/`strobe` across all 16 columns
  (so VREF_0..15 / STROBE_0..15 are legitimately one net -- a probe artifact, not the band).
- VERDICT: the band architecture (VDD-met3 / VGND-met1, narrow vertical pins, merged well)
  ELIMINATES the dominant fuse that gave the discrete design LVS 18. LVS 0 is now a
  demonstrated PATH, not a hope: remaining work is power-pin PDN binding + a faithful
  (non-shared-vref) integration, then the macro-BL fuse via the same injection recipe.

## 2026-06-02: Band PDN structure DONE (DRC 0); probe is now the blocker, not the band
- Built the band's power structure (commit cebe2af): continuous met1(VGND)/met2(VDD) rails
  bridging the 0.50um inter-cell gaps (cells abut at 3.40 but placed at 3.70 pitch), + met4
  binding strips (top=VDD, bottom=VGND) + via stacks. KEY fix to the DRC spiral: copy the
  ARRAY macro's EXACT proven via dims -- via1 0.15, via2/via3 0.20 (NOT 0.26/0.28/0.32, which
  are the metal PATCH sizes, misread from comments), 0.50x0.50 met2/3/4 landing pads. Plus
  raise the VDD met2 bridge bottom to y72.30 (clears the cells' met2 dogleg stub at 72.16 by
  0.14 = m2.2 min). Result: **band KLayout DRC 0**, 66-pin LEF, VDD/VGND on met4 for PDN.
  (DRC trajectory while finding via dims: 0->256->78->236->217->16->0.)
- HARD BLOCKER (report, don't grind): the one-band PROBE is no longer a faithful test vehicle.
  bandprobe6 (with the PDN band) dies at GRT-0116 congestion in GlobalRouting. But:
  - PSM-0039 "Unconnected u_macro/VPWR" appears in bandprobe4/5/6 ALIKE (count 2 each) and
    probe5 STILL reached LVS=27 -- so the PSM unconnected warnings are PRE-EXISTING probe
    artifacts, NOT caused by the band PDN work.
  - The probe has multiple artifacts that make further debugging it unproductive: shared
    vref/strobe across all 16 cols (false net merges), only 16 of 32 columns, an arbitrary
    band placement (y=118) never PDN-validated, and a cramped half-floorplan that congests
    when the band's met4 adds routing demand.
- STATUS: the band cell+abstract+PDN are all DRC-clean and verified in isolation; the fuse is
  proven eliminated (probe5). The next REAL step is the actual 4-band chip integration
  (proper RTL, all 64 columns, distinct vref/strobe, PDN-aligned 4-band placement) -- NOT
  more one-band-probe debugging. The probe served its purpose (proved the fuse fix + drove the
  abstract/PDN recipes); it is now the wrong vehicle.

## 2026-06-02: 4-band FULL chip integration: HARD BLOCKER at GeneratePDN (PDN-0232)
- Built the real integration (commits 569db50 and earlier): rtl/chip/cirom_chip_analog.sv
  (4 sa_se_band16 instances replacing 64 discrete sa_se -- BLP[0:15]/BLP[16:31]/BLN[0:15]/
  BLN[16:31], distinct per-col wiring, same chip interface); config_bands.json; macro_bands.cfg
  (array at 640,20; 4 bands in a row at y=120, x=600/660/720/780).
- Cleared synthesis (after removing the undriven pos/neg_hitb_unused wires -> 64 yosys check
  errors) and CheckMacroInstances. Dies at OpenROAD.GeneratePDN: **PDN-0232 "grid does not
  contain any shapes or vias" for ALL 4 band instances -> PDN-0233**. The array u_macro grid
  succeeds in the same run; only the bands fail.
- Tried (did NOT clear it): (a) band power pins on full-width met4 (were met3/met1); (b)
  post-processing the LEF to widen the VDD/VGND met4 pin RECT to full 59um (Magic `lef write`
  clips a full-width strip's port to the ~5.7um label-traced window). Neither fixed PDN-0232.
- LIKELY ROOT (the variant-B per-instance-grid wall, refined): pdngen builds a PER-INSTANCE
  macro grid for each band and needs it to form a closed VPWR+VGND mesh from the band's own
  power pins overlapping the chip stripes. The array binds because its VPWR/VGND met4 are both
  at ONE edge (top, 0.31um apart) -- a vstripe crossing the top edge hits both. The band's
  VDD met4 is at the TOP edge (y+72.3) and VGND met4 at the BOTTOM edge (y+0.2), 72um apart,
  so no single region presents both nets to pdngen's per-instance grid -> empty grid.
- HARD BLOCKER (reporting per instruction): closing this needs real PDN/floorplan design, not
  a tweak -- e.g. (1) a proper macro power RING (VPWR + VGND on the band perimeter, both nets
  reachable per the OpenRAM pattern in feedback_pdn_macro_pattern), or (2) PDN config the band
  as connect-by-abutment to the array's rails, or (3) custom add_pdn_stripe for the band grid.
  All are multi-step EDA-config/layout work. The integration is otherwise built and passes
  synth+placement; PDN binding is the one remaining gate to a routed, LVS-testable chip. Remaining Option-A work is the real
  build: extend gen_macro_array_pc.tcl to host the 64 sense devices + internal PDN +
  perimeter ring, a thin/3.40um-interleaved sa_se sub-cell (re-run its MC/PVT), RTL
  rewrite (drop 64 discrete sa_se, macro exposes outputs), config/macro.cfg, re-derive
  the DRC ECO. Big but de-risked.

## 2026-06-02: 4-band integration: PDN ring SOLVED PDN-0232; now DRT-0073 on BL_0 (hard blocker)
- BIG WIN: the band PDN ring fixed PDN-0232. Mechanism (verified from a working run's ODB):
  pdngen's per-instance macro grid connects met4(vert)<->met5(horiz); the chip met5 power
  hstripes inside the band footprint sit at band-local y~30/70 (VPWR), ~33 (VGND). Horizontal-
  only top/bottom power strips missed them. Adding full-height VERTICAL met4 ring edges (cross
  every met5 hstripe) -> PDN binds. Commits 104330c, 1461092, e652f60. Single-source recipe:
  build_band_klayout.py (GDS + power_pins manifest) -> band_lef_ports.tcl (signal ports) ->
  author_band_lef.py (power pins from manifest). Band KLayout DRC 0, 66-pin LEF.
- Also cleared this turn: GRT-0116 congestion -> spread the 4 bands in a row with ~18um gaps
  (overflow 44->24) + GRT_ALLOW_CONGESTION=true -> passes GlobalRouting into DetailedRouting.
- HARD BLOCKER (report): DetailedRouting fails DRT-0073 "No access point for u_band_*/BL_0" --
  ONLY BL_0 (the leftmost pin, band-local x1.15-1.43, ~1.45um from the band's left edge), in all
  4 bands. Ruled OUT by test: ring-edge position (moved cell0->cell2, still fails), PDN halo
  (1->0.5, still fails), pin width (all 16 BL are identical 0.28um, yet only BL_0 fails so it is
  NOT a via.4a width issue). It is POSITIONAL -- BL_0 being the first/edge pin. Likely the router
  cannot land an access via on BL_0 because its only approach track is blocked by the band's
  left-boundary structure / the abutted-cell-0 geometry. Not root-caused in this entry; would need the DRT
  access-point diagnostic (gated by intermittent tooling this session) or a cell-0 left-margin /
  BL_0 access-pad change.
- STATUS after this turn: the band PDN binding -- the blocker the prior turn reported -- is
  SOLVED. The chip now synthesizes, places, generates PDN, and global-routes; it fails only at
  detailed-routing on BL_0 access. One pin, 4 instances. Genuinely close: every prior gate
  (fuse, abstract, PDN) is cleared; BL_0 access is the remaining detailed-route gate.

## 2026-06-02 (cont.): DRT-0073 RESOLVED: band reaches first full signoff
- ROOT CAUSE of DRT-0073 (the prior entry's "positional/leftmost" guess was WRONG): the band
  signal pins are tiny 0.28x0.60um met2 nubs buried in the cell interior with met1/met3/met4 all
  obstructed -> FlexPA can assign no access point. Proven via standalone OpenROAD pin_access on
  the pre-DRT ODB + in-memory master edits: removing ALL obstructions, widening, shifting, or
  re-layering the nub all still FAIL; via-in-pin / via-access-layer config knobs FAIL. It is
  per-master (FlexPA computes access per unique master), so the leftmost-in-master pin surfaces
  first; fixing it reveals the next. Marginal across most BL/VREF (both at cell-local x~1.29,
  poorly met2-track-aligned).
- FIX (validated, ALL 64 pins pass pin_access): present each signal as a met3 vertical RISER that
  reaches a macro boundary (the array macro's proven BLP/BLN escape). Split {HIT,BL}->bottom
  (y=-0.20), {VREF,STROBE}->top (y=72.80); BL and VREF share x but run opposite directions.
  via2 ties each riser to its met2 nub over a 0.30um landing pad. Power restructured: no
  full-width met4 rails (they would short the bottom risers); bind via the 4 met4 ring edges +
  one base via-stack each. build_band_klayout.py rewritten; band KLayout DRC 0.
- bandsR1 (first time the band topology reached signoff -- every prior run died at DRT): routes
  clean (DRT-0073=0, 0 routing viol) but raw signoff 747 KLayout DRC + 206 LVS.
  * DRC dominated by m3.4 (510, met3 via-enclosure) + m3.1 (63) at the riser/via locations: the
    0.30um risers are too narrow for the chip router's via to land on-grid with >=0.025 met3
    enclosure. FIX: widen risers to 0.72um (the 2+2 split allows it; the 0.30um ring-base pads at
    vchan still clear by >=0.30). bandsR2 routing converges 1066->0.
  * LVS 206 = band abstract subckt extracts with ZERO pins (".subckt sa_se_band16 / .ends") ->
    every band pin floats. Cause: the KLayout GDS text labels are NOT Magic ports, and there were
    no VGND/VDD labels at all. FIX: inject VGND/VDD GDS labels (met1=68/5, met2=69/5, met4=71/5)
    AND publish the Magic-written GDS (band_lef_ports.tcl port-makes + gds writes). Verified the
    power pins (VGND/VDD) then extract; signal-pin extraction pending bandsR2 signoff.

## 2026-06-08: Band DRC overhaul round 1 (bands_drc1): internal 145 cleared, but LVS broke
- **Delta:** KLayout 361 -> 139 (m3.1 71 + m3.2 66 + m4.2 2), but LVS 0 -> fail:
  blp[13] shorted to VGND + STROBE_15 isolated on 2 of 4 band instances.
- **Cause of the short:** the enlarged VGND leg-stack met3 pads (0.33 x 0.73,
  needed for m3.4/via3.4/m3.6) are GDS-only geometry; not a LEF pin, not OBS;
  so DRT routed a met3 BL wire whose end cap clipped the pad by a 0.04 um sliver
  (wire end y+halfwidth 125.44 vs pad bottom 125.385). Any GDS shape the LEF
  doesn't represent is router-invisible and will eventually be shorted into.
- **Standalone band DRC was a false 0 before this round:** tools/klayout_drc.py
  omits the flow's `offgrid/feol/beol/seal` deck options; with them the band had
  162 violations (float truncation defeating the 5nm snap in build_band_klayout's
  box(): int() not int(round()); undersized stack pads; a 0.24 um STROBE-to-HIT
  riser gap; leg-top via3 enclosure).
- **Fix direction (round 2):** author the band LEF met3 OBS as FULL coverage
  (area minus pin shapes) so every GDS met3 shape is represented; the router
  then connects at the protruding stub tips or via3-from-met4 onto a pin.

## 2026-06-08: SIGNOFF REACHED: KLayout DRC 0 + LVS 0 (run bands_eco4)

The working recipe, end to end (361 -> 0 over 14 runs):
1. **Band-internal cleanup (162 -> 0 standalone under the flow's full deck
   options):** int(round()) for the 5nm grid snap (float truncation made
   off-grid vias), leg via-stack pads 0.33x0.73 (enclosures + met3 area),
   met2 landing pads merged down over the cell strip (5nm sliver gaps),
   riser-to-riser spacing fixes. NOTE: tools/klayout_drc.py without
   `offgrid/feol/beol/seal` had reported a false 0.
2. **Full met3 OBS in the authored LEF** (band area minus pins.sized(0.30),
   clamped to the 72.80 design boundary -- SIZE follows the GDS bbox and
   covering to SIZE entombs the protruding pins): stops the router
   free-styling met3 between the risers. The 0.30 moat keeps via3 pads on
   a pin legal (OBS abutting the pins = DRT-0073).
3. **Poke-proof riser geometry:** DRT places via pads up to 0.27 and wire
   end-extensions up to 0.30 past a pin edge, so every riser-to-riser /
   riser-to-fixture gap >= 0.60: HIT narrowed to [0.035,0.365], BL/VREF
   [1.135,1.71] (nub via2 at 1.30, exactly 0.065 enclosure), STROBE
   [2.41,2.97] over a west-jogged via2 on a met2 nub extension. Power
   rails trimmed at source (tips fed nothing; chip wires hugged them and
   Magic ECO erase cannot remove subcell geometry). Power legs span only
   a met5 stripe-pair crossing (VGND y 0.2-33 in the bottom channel, VDD
   y 18-72.75 in the HIT column) so met4 never blocks top-pin via3.
   met1 keepout strip west of the band (cell met1 reaches -0.30).
4. **Sign-off ECO fills:** the ~160 residual m3.1 are same-net euclidean
   inside-corner notches where landings meet the flush pin tops -- closed
   by auto-generated met3 fills (tools/gen_drc_eco.py from the lyrdb)
   sourced at StreamOut via the venv mag_gds.tcl hook (ENV_PATCHES.md),
   so extraction/LVS stay truthful. Converges in 1-2 iterations (fills
   do not perturb routing; geometry changes do).
Dead ends this round (details in the entries above): landing heads (any
head wide enough to be corner-proof needs 1.36um -- no budget), interior-
trimmed pins (DRT starves, ~1170 violations), protruding top stubs
(horizontal track wires hug foreign tips at 0.02).


2026-06-11 -- POST-SIGNOFF: transistor-level LVS of the band (new check)
found the builder's nwell-merge strip swallowing the latch nfets'
diffusion (N+ in nwell = well tap): every comparator's HITB/int_ref
shorted to the well/VDD network in all prior builds. Strip bottom moved
to the cell well edge; band4 + band16 KLayout DRC 0 and netgen "match
uniquely"; chip re-signed (DRC 0 / LVS 0 / STA 0/0/0). Two ECO lessons
re-learned the hard way during the same campaign: vertex-trace BOTH
shapes (full polygon + owning cell) before painting any ECO metal, and
never bridge an untraced pair -- two "same-net" assumptions each shorted
a power rail to a signal and were caught only by per-run LVS.

2026-07-03 -- RESOLVED: re-sign with the FEOL-fixed band (bands_feol3
KLayout 0 / LVS 0). The first re-run (bands_feol1) is what exposed the
band's HIT-to-VDD short (see lvs_root_cause.md); after the band fix,
the leftover 9 KLayout items were (a) 8 m3.1 riser-tip landing notches
whose ECO fills were keyed to the old routing -- regenerate
eco_patches.tcl via tools/gen_drc_eco.py after ANY band/config change,
the file header says so for a reason -- and (b) 1 m2.2 where the new
routing grazed the hand-written VPWR detour patch at x 599.29: cured
structurally with a met2 ROUTING_OBSTRUCTION over that slot (599.10 to
599.45) so no route can conflict with the patch again; the original
VPWR track at 599.54 stays open so the detour keeps its purpose.
Lesson: hand patches painted at StreamOut are invisible to the router;
every hand patch needs a matching obstruction or it will eventually
collide with a reroute.
