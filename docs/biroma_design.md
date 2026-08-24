# BiROMA port: investigation and result

Decision record from the BitROM mechanism extraction (arXiv:2509.08542
Sec III-B + Figure 4 decoded at 400 dpi).

**RESULT (2026-06-13): BiROMA's 2-weights-per-cell density does not
port economically to SKY130. The epic concludes NO-GO; keep the proven
one-weight v4 cell.** Two forks were investigated and both close:

- *Discharge-domain* (keep the verified StrongARM sense): needs one
  line per readable nonzero value = four sense lines for two ternary
  weights = break-even pitch. The shared-minus shortcut is
  topologically disproven (a symmetric transistor cannot tell E=-1,O=0
  from E=0,O=-1; sim-confirmed to 5e-11 V).
- *Voltage-domain* (BitROM's actual scheme): the feasibility physics
  works (a SKY130 NMOS resolves all three levels at ~0.184 V margin,
  and StrongARM offset at 3sigma ~30-45 mV fits easily), but the 2x is
  not worth it at this node. BitROM is a DIGITAL CiROM whose 1/8 & 3/8
  VDD comparators are 3-level threshold slicers, not analog sense amps;
  its 2x needs two charge-sourcing mid-rail (1/4 & 1/2 VDD) driven
  rails whose droop spends the entire 1/8-VDD (225 mV) budget, plus
  doubled comparators, growing the analog periphery against the array
  shrink. At BitROM's 65nm the periphery is 4.8% of area; at SKY130
  1.8V it is a large fraction, refunding the density win. The field is
  exiting analog MLC CiROM (the same group's analog Yin JSSC 2024 was
  superseded by the digital DCiROM 2025); all such precedent is at
  28-65nm. The 2x is a SMALLER-NODE technique (it would pay off at
  ASAP7-class, not SKY130/GF180 180nm-class) -- which fits Ankhdjet's
  node-agnostic thesis: the contract is constant, the worthwhile
  cell-level density tricks differ by node.

The generator machinery built here (parameterized pitch, dual-side
per-cell via programming, DRC 0 + LVS-clean 8x4 spike) is sound and
reusable if a smaller-node port ever revisits this. See the analysis
sections below.**

## The BitROM mechanism, compressed

Per column, TWO 3-line digit stacks (E and O sides) at {1/2, 1/4,
0}*VDD on M1/M2/M3; each cell terminal via-connects to exactly one
line of its side (the via choice IS the trit; ZERO IS A CONNECTION to
the 1/2VDD line, never floating). Per phase one side is driven (PRE +
SUP on: static levels) and the other is merged by DEQ equalizers,
precharged to 1/2VDD through PRE, and sensed. THE DRIVEN SIDE'S WEIGHT
IS READ (voltage-domain). Comparators at 1/8 and 3/8 VDD; CS scans 8
columns per TriMLA sequentially; ~16 switch transistors per column;
periphery total 4.8% of macro area.

## Our port: keep discharge sensing, swap roles, strap the zero

Two transferable laws: (1) floating-terminal zero is incompatible with
bidirectional read (an open kills both sides); zero must be a
connection that is electrically invisible in-phase. (2) Voltage-domain
reads the driven side; discharge-domain (ours) reads the SENSED side.

Adopted structure: per column keep BL+/BL- (met4/met3) as the O
side and add E+/E- as a second track pair (two tracks per layer fit
the 1.70 um pitch; met2 stays reserved). The zero connection on BOTH
sides is a licon to the existing per-column li strap: the
substrate-tied source/ground network survives unchanged as the shared
zero line and inter-column shield. Read side S: drive the opposite
side's +/- lines to VSS (two phase-gated NMOS pulldowns per column),
precharge S+/S- with the existing clocked PMOS, fire WL, strobe the
StrongARM pair vs VREF=VDD/2 exactly as verified today. +1 discharges
S+, -1 discharges S-, 0 discharges neither.

Costs: 4 pulldown NMOS + 2 precharge PMOS extra per column; 2:1 SA mux
between sides (or doubled comparators); discharge path gains the
far-side line RC + pulldown (size it); the source terminal needs a via
stack the floorplan reserves only for drains today, so expect pitch
growth toward ~2.0-2.2 um: NET DENSITY GAIN ~1.5-1.7x, not 2x. Role
swap only with WL low + re-precharge (one FSM state; side-major bursts
amortize).

Rejected: the BitROM-faithful voltage-domain port ( needs generated 1/4 and
1/2 VDD rails, abandons verified sensing, mid-rail kickback exposure); the paired-column virtual-ground scheme ( sneak paths, halved
bandwidth; fallback if the adopted structure's pitch growth is unacceptable; precedent
US5590068/US5734602).

Production precedent for terminal-role-swap reads: NROM/MirrorBit
(Eitan, IEEE EDL 2000; US6487114). BiROMA density predecessor: Yin et
al., JSSC 2024.

## First-order electrical results

First-order results (ss/100C/1.62V, decks in
cell/sky130/bitcell_v4/sim_biroma/): development through the far-side
line + pulldown costs 80-150ps against the 8ns evaluate state; the
phase-swap re-precharge step disturbs a held line under 1mV through 64
off-cells; with the far environment driven low all extracted-macro
read verdicts hold and the floating victim gains 92mV of pre-strobe
margin. The dual-rail cell geometry itself was never built; the
investigation closed at the analysis below.

## Cell geometry (dual-rail spec the investigation defined, unbuilt)

Target ~2.1um column pitch: keep the v4 device and gate-top contact;
tracks per column become E- (met3), E+ (met4), li zero-strap (center,
unchanged), O+ (met4), O- (met3); both diffusion terminals get jog
lanes to their side's +/- tracks or a licon to the strap (zero). The
source-side terminal needs the same jog/via candidates the drain has
today, which is the pitch driver. Per-column periphery: two pulldown
NMOS per side at the array edge (phase-gated), second precharge pair,
2:1 side mux ahead of the StrongARM pair. Mask format: two characters
per cell (E,O). Row pitch unchanged.

## Track-plan constraint set (the open layout puzzle)

Scaffold state: column pitch is parameterized (ANKHDJET_CELL_W) and the
five-track mode exists in BL routing (ANKHDJET_BIROMA); an 8x4 array at
2.20 um builds DRC 0 through array + WL + tracks. The unresolved
geometry is met4 ACCESS, not the tracks themselves: a met4 jog needs a
via3 inside a ~0.54 um met3 pad with >= 0.30 clearance to unrelated
met3, and with TWO full-height met3 tracks per column (E-, O-) no
ordering at 2.20 um leaves a wide-enough met3-free lane for two such
pads (one per side). Candidate escapes, in evaluation order:
(a) grow pitch until one pad lane fits per side (~2.6+ um; eats the
density win toward ~1.4x); (b) drop the met3 tracks entirely and run
BOTH polarities of each side on met4 (four met4 tracks per column at
1.10 pitch = 3.30 um pitch minimum; worse); (c) single met3 track per
column shared E-/O- via the phase discipline (the driven side's '-'
and the sensed side's '-' alternate roles on ONE line; halves the
track count and the information still separates because only one side
is sensed per phase -- analyzed below); (d) met2 tracks (rejected
already: chip-level met2.3b history and the SA met2 coupling story).

## The shared-minus-line is disproven (the load-bearing finding)

The discharge-domain port hinged on sharing one met3 minus-line per
column between the E and O sides, to reach a sub-2.5 um pitch. Building
and verifying the spike forced the read scheme to be made precise, and
it does not work. The proof is topological, not marginal:

1. The storage transistor is a symmetric nfet: drain and source are
   interchangeable. A cell therefore stores the UNORDERED pair
   {drain-target, source-target}, not an ordered (E, O).

2. With a shared minus line SM and a grounded zero-strap G, the targets
   are tE in {EP, SM, G} and tO in {OP, SM, G}. Enumerating the nine
   ternary pairs as unordered {tE, tO}: (E=-1, O=0) gives {SM, G} and
   (E=0, O=-1) gives {G, SM} -- the SAME set. The two configurations
   are the identical circuit, so NO read scheme can distinguish them.
   (Confirmed in sim_biroma/gate4_shared_sm_ambiguity.sp: the two cells
   discharge a precharged SM identically to within 5e-11 V.)

3. It is worse than that one collision. SM is a single node shared down
   the column and across both sides. Any terminal sitting on SM pulls
   it low whenever the cell's OTHER terminal is low -- and the other
   terminal is always low (driven low as the far side, or grounded as a
   zero). So a cell with E=-1 (drain on SM) discharges SM in BOTH the
   E-minus and the O-minus sensing windows, falsely reporting O=-1; and
   symmetrically for O=-1. A shared SM cannot attribute a discharge to
   the side being sensed. The only cells that never corrupt a read are
   those with NO -1 on either side -- i.e. the shared-minus column can
   store weights drawn only from {0, +1}. It cannot represent negative
   weights at all, which is fatal for ternary.

The earlier "8 of 9" then "6 of 9" counts in this file's history were
both wrong: the usable count under shared-SM is zero negative weights.

## Why discharge sensing cannot reach BiROMA's 2x at all

The deeper consequence: discharge sensing encodes a value in WHICH line
discharges, so it needs one distinct line per (side, nonzero value) it
must read -- E in {+,-} and O in {+,-} = FOUR distinct sense lines
minimum. Four met3 tracks plus the strap tile to a ~3.3 um pitch
(~2.96 um with KLayout explicit-cut 0.34 strips), giving 2 weights per
(3.3 x 1.30) = 1.03x net density (1.15x best case). That is break-even:
the periphery cost (two per-column pulldowns per side, a 2:1 sense mux,
the FSM swap state, the compiler rework) buys essentially no density.

BiROMA's real 2x lives in BitROM's VOLTAGE-domain read: the sensed
side's three lines are merged (DEQ) into one node and the driven side
delivers a LEVEL (0, 1/4, 1/2 VDD); the sensed side's own weight is
irrelevant because its lines are merged, which is exactly what lets two
weights share one transistor. Merging is compatible with level sensing
and incompatible with discharge sensing. So the 2x requires adopting
the voltage-domain 3-level read -- generated 1/4 and 1/2 VDD rails and
a dual-reference (1/8, 3/8 VDD) comparator -- abandoning the verified
single-ended VDD/2 StrongARM discharge sense. That is a real analog
rework, not a layout tweak, and it is the fork to put to the user.

## Voltage-domain feasibility spike (positive; gates the rework)

Core physics of the voltage-domain rework, checked in
sim_biroma/g5_vdom_*.sp at VDD=1.8 (thresholds 1/8 VDD=0.225,
3/8 VDD=0.675), 6ns strobe, far-side line RC + 63 off-cells:

| weight | driven level | settled SS/100C | margin to nearest threshold |
|--------|--------------|-----------------|------------------------------|
| -1 | 0 V | 0.0008 V | 0.224 V |
| +1 | 1/4 = 0.45 V | 0.457 V | 0.218 V |
| 0 | 1/2 = 0.90 V | 0.859 V | 0.184 V |

Findings: (a) a single SKY130 NMOS delivers 1/4 and 1/2 VDD with no
pass-transistor ceiling (1/2 VDD=0.9 < VDD-Vth ~1.1). (b) the new
no-signal '0' case holds: the selected cell ties the sensed node to the
1/2 VDD rail, so 63 worst-case off-cells (and FF/125C) only droop it to
0.859/0.896 V, still 0.18 V above the 3/8 threshold. (c) worst-case
sense margin ~0.184 V, which must absorb comparator offset + reference
error.

The research pass resolved the budget, and the verdict is NO-GO at
SKY130 despite the positive physics:
- OFFSET IS NOT THE BLOCKER. A 0.18um/1.8V StrongARM has input-offset
  sigma ~3-6 mV (MC, multiple sources); even derated to our sa_se
  ~10-15 mV, 3sigma ~30-45 mV sits well inside the 225 mV (1/8 VDD)
  band. No auto-zero needed.
- THE BLOCKER IS THE DRIVEN RAILS. The scheme needs two low-impedance
  1/4 and 1/2 VDD rails that SOURCE the per-read settling charge (not
  high-Z references) -- new analog blocks (buffer/clamp opamps + decap)
  the discharge scheme has zero of. Their droop comes straight out of
  the 225 mV band; our own VDD/2 reference showed 212-252 mV kickback
  at high-Z = the whole band. The spike's stiff 1k rail hid this.
- WORST SYMBOL IS THE COMMON ONE. Weight 0 = 1/2 VDD has the lowest
  pass overdrive + worst body effect, i.e. the slowest-settling level
  is the most frequent (BitNet sparsity) -- the same 0-misread bug
  class the sa_se rework was done to kill, reintroduced.
- DOUBLED COMPARATORS + 2 BUFFERED RAILS + DECAP grow the analog
  periphery against the 2x array shrink; at 180nm-class that fraction
  is large (vs BitROM's 4.8% at 65nm), refunding the win. The 2x is a
  smaller-node technique.

## What the spike DID prove (reusable regardless of the fork)

The ANKHDJET_CELL_W / ANKHDJET_BIROMA generator machinery is sound and
reusable: parameterized column pitch, multi-track per-column routing
with port labels, and dual-side per-cell via programming from a
2-character-per-cell weight file, all closing at DRC 0 and netgen
"Circuits match uniquely" against a weight-derived reference (8x4
spike). A voltage-domain or 4-line design needs the same dual-side
mask-programming substrate; only the track count, the read periphery,
and the (-1,-1)/cross-corruption handling change. The verified
gate1-3 first-order electrical results stand for any discharge variant
but are moot if the fork goes voltage-domain.

## Jog plan at 2.46 um (mechanical implementation spec)

Cell origin co = c*CELL_W + 0.375. Tracks: E+ [c+0.24, c+0.66],
shared-minus [c+1.06, c+1.48], O+ [c+1.88, c+2.30]. Drain (E-terminal)
plate [c-0.02, c+0.35]; source (O-terminal) m1 plate ~[c+0.455,
c+0.685]; strap li [c+0.96, c+1.13]. Device y: cy = row + 0.34, plates
[cy-0.22, cy+0.22].

Both terminals jog east, so the two m2 runs need separate y lanes:
E lane [cy-0.44, cy-0.07], O lane [cy+0.07, cy+0.44] (0.37 tall each
for the 0.28 via2 + 0.045 enclosure; 0.14 m2.2 between lanes; total
0.88 inside the 1.30 row). Each jog's m2 is an L: a plate-cover box
over its via1 plus the lane box reaching the target track x.

E jogs (from the drain): +1 -> via2 [c+0.31, c+0.59] in E+ (straight
up, the drain overlaps the track); -1 -> lane east to via2 [c+1.13,
c+1.41] in shared-minus; 0 -> lane east to x [c+0.93, c+1.16], via1
down to an m1 landing, viali into the strap li.

O jogs (from the source): +1 -> lane east to via2 [c+1.95, c+2.23] in
O+; -1 -> via2 [c+1.13, c+1.41] in shared-minus (NOTE: if E=-1 too,
this is the forbidden (-1,-1) pair -- assert); 0 -> the per-cell
source stub into the strap (today's blanket stub in the macro
generator moves into mask programming and becomes this case).

Mask format: 2 characters per cell per line (E then O), file rows =
array rows, line length = 2*N_COLS. Assert no (-1,-1).

## Verification gates a smaller-node revisit runs (in order)

1. BL development sims with far-side RC + pulldown in the path, both
   weights, four corner combos.
2. Phase-swap transient: off-cell Cds coupling into the held side when
   a side transitions VSS -> precharge (WL-off sequencing removes the
   DC path; measure the capacitive part).
3. StrongARM kickback re-measurement with the far side driven low
   (expected improvement; verify sign).
4. DRC/LVS of the widened dual-side-programmable cell BEFORE density
   claims; log DRC attempts in drc_failed_attempts.md.
5. The full per-level LVS ladder + regression logs, as always.

The node window above bounds the ANALOG variant: the two-weight gain
requires resolving three levels on one line, so on the fully digital
readout it is unavailable at any node without a multi-level digital
discriminator (a different instance of the architectural family).
