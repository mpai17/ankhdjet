# Single-ended sense — validation results (2026-05-30)

Reproduce: `bash sim/run_validation.sh` (serial / ANKHDJET_JOBS<=4) then
`uv run sim/parse_results.py`. The weight=0 MC below was re-run on its own
(`sim/run_w0_mc.sh`) and confirmed three ways: parse_results.py, an
independent grep/awk tally, and the max-value check (max v_hit_final across
all 250 trials = 4.6e-7 V, far below the 0.9 V HIT threshold).
HIT decode at VDD/2. strobe @3ns. SS unless noted; mismatch via mc_mm_switch=1.

## [1] Dynamic per-corner (real cell discharge + timed strobe, ideal VREF)
tt/ss/ff x {w=1 discharged, w=0 quiet}: 6/6 decode correctly.
w=1 -> HIT=1 (BL@strobe 0.003-0.126 V); w=0 -> HIT=0 (BL stays 1.80 V).

## [2] Resistor-divider VREF (real divider, not ideal source) + kickback
6/6 corners decode correctly. VREF settles to exact VDD/2 (ratiometric).
Worst-case strobe kickback on VREF = 252 mV (deliberately high-Z 500k/leg
divider). Decision still resolves due to the wide signal margin; a PRODUCTION
divider should use lower-Z legs and/or more decap to cut kickback below ~100 mV.

## [3] Dynamic Monte Carlo (SS + mismatch, 250 trials/weight) -- KEY TEST
weight=1 (discharged -> HIT=1): 250/250 = 100%, 0 infra-fail
weight=0 (quiet      -> HIT=0): 250/250 = 100%, 0 infra-fail
0 wrong-direction decisions across all 500 trials.
(weight=0 max v_hit_final = 4.6e-7 V, i.e. all firmly HIT=0.)
vs the original differential StrongARM's ~50/50 coin flip at weight=0.

## [4] V/T/process sweep (divider VREF)
ss,ff x {1.62,1.80,1.98 V} x {-40,25,125 C} x {w=1,0} = 36 corners:
36/36 correct, 0 sense-fails, 0 infra-fails.

## Verdict
The single-ended sense primitive resolves all three ternary states
{+1, 0, -1} correctly across PVT + mismatch, dynamically, with a real
resistor-divider reference. The weight=0 representation gap that made the
differential StrongARM unusable is closed.

## Not yet done (next, before tapeout use)
- Strobe-timing FSM at chip level (fixed ~3 ns delay covers SS t_50pct=1.74 ns).
- Lower-impedance / decoupled production VREF divider (cut kickback < 100 mV).
- Layout + DRC + LVS of sense_col (task #112).
- RTL rewrite to independent pos/neg bits + abstracts + chip re-integration.
