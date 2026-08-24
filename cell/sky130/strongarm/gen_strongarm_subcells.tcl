# Generate the per-transistor subcells used by gen_strongarm_top.tcl.
# Each subcell is a single PCell-instantiated transistor at a specific
# (W, L), so the top-level cell can `getcell` instances with scoped
# nets (preventing the source/drain merge we saw with co-located
# PCell-draw calls in the same flat cell).
#
# Run via:
#   cd build && magic -dnull -noconsole -T sky130A < ../gen_strongarm_subcells.tcl

drc off

# Helper: emit one nmos subcell at (W, L)
proc make_nmos {name w l} {
    load $name -quiet
    select top cell
    cellname rename "(UNNAMED)" $name
    box position 0 0
    box size 0 0
    ::sky130::sky130_fd_pr__nfet_01v8_draw [dict merge \
        [::sky130::sky130_fd_pr__nfet_01v8_defaults] \
        [list w $w l $l nf 1 m 1 \
              glc 0 grc 0 gtc 0 gbc 0 \
              topc 1 botc 0 \
              diffcov 50 polycov 50 tbcov 50 rlcov 50 \
              viasrc 50 viadrn 50 viagate 50 \
              guard 0 doverlap 0 poverlap 0]]
    save $name
    puts "wrote $name"
}

proc make_pmos {name w l} {
    load $name -quiet
    select top cell
    cellname rename "(UNNAMED)" $name
    box position 0 0
    box size 0 0
    ::sky130::sky130_fd_pr__pfet_01v8_draw [dict merge \
        [::sky130::sky130_fd_pr__pfet_01v8_defaults] \
        [list w $w l $l nf 1 m 1 \
              glc 0 grc 0 gtc 0 gbc 0 \
              topc 1 botc 0 \
              diffcov 50 polycov 50 tbcov 50 rlcov 50 \
              viasrc 50 viadrn 50 viagate 50 \
              guard 0 doverlap 0 poverlap 0]]
    save $name
    puts "wrote $name"
}

# Strongarm transistors at the SS-mismatch-margin-validated sizing
# (matches test_harness_big.sp). Rationale: production sizing
# (W=2/L=0.3 input pair, 0.6 um^2 area) gives sigma_offset ~170 mV at
# SS in 200-trial Monte Carlo, which leaves 68% correct at 100 mV BL
# differential -- 32% wrong-direction or unresolved. To hit the 99.9%
# correct gate at 100 mV under SKY130 mismatch, sigma_offset must drop
# to <= 30 mV. By Pelgrom (sigma ~ 1/sqrt(W*L)), W*L of the input
# pair must grow ~32x: from 0.6 um^2 to 20 um^2. The chosen sizing
# gives 0.75 mV/dev intrinsic VTH sigma on the input pair which
# matches the empirical SS-corner SA offset target.
#
# Per-SA area ~50 um^2 = ~3% of the 256x256 cirom_array (42600 um^2);
# tiny fraction of the wrapped macro and negligible at die scale.
make_nmos sa_tail   14.0 1.0
make_nmos sa_inp     8.0 2.0
make_nmos sa_xc_n    4.0 1.0
make_pmos sa_xc_p    8.0 1.0
make_pmos sa_rst     0.84 1.0

quit -noprompt
