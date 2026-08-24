"""Generate Liberty + LEF abstracts for cirom_array_NxM hard macros.

Both files describe the universal macro interface — variant-specific
weight data is encoded in the via-1 mask emitted by the compiler at
synth time, NOT in these abstracts. So one (Liberty, LEF) pair is
reusable across all chip variants of a given (N, M) shape.

Sizing for SKY130 from measured BL discharge / sense-amp timings:
  - BL discharge SS @ N=64: 1.285 ns lumped, ~0.80 ns parasitic-extracted
  - StrongARM oversize SA resolve SS: 2.23 ns (200/200 MC pass)
  - Total clk-to-bl_out worst case at SS: ~3.05 ns

Sizing for GF180MCU is scaled from SKY130 by node-shrink ratios
pending direct SPICE characterization at GF180:
  - Linear cell dim scale: (180/130) = 1.385x
  - Timing scale at SS: ~1.5x slower (longer L, larger cap)

Usage:
  uv run macro/sky130/gen_anchor_abstracts.py 64 32              # SKY130 (default)
  uv run macro/sky130/gen_anchor_abstracts.py 64 32 --pdk gf180  # GF180MCU port
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).parent
# Generated macro artifacts (.lib, .lef, _wrapper.sv, _synth.ys, gates.v)
# go into build/ which is gitignored. The generator script + per-PDK
# constants live in HERE; everything in BUILD is regenerable.
BUILD = HERE / "build"
BUILD.mkdir(exist_ok=True)


# Per-PDK constants. Each entry holds the bitcell footprint, wrapper
# margins, timing, and Liberty operating-condition voltage that the
# generator needs to emit a macro abstraction for that node.
PDK_PARAMS = {
    "sky130": {
        # bitcell_v4 footprint (PCell W=0.42 minimum, no built-in tap).
        # Production target. Pairs with SUBCOL_ROWS=64.
        # Pitch height 0.89 um is set by SKY130 poly.2 spacing against
        # the cell's gate-stub poly (y=±0.34 um); 0.89 - 0.68 = 0.21
        # is the minimum poly-poly spacing.
        "cell_w_um":        0.73,
        "cell_h_um":        0.89,
        "wrap_margin_x_um": 20.0,
        "wrap_margin_y_um": 10.0,
        "clk_to_bl_ns":     3.05,
        "setup_ns":         0.30,
        "hold_ns":          0.10,
        "vdd_v":            1.80,
        "vdd_v_ss":         1.62,
        "layer_m4":         "met4",   # power straps
        "layer_signal":     "met3",   # signal pins
    },
    # GF180 cell dims scaled 1.39x linearly from SKY130 (180/130 ratio).
    # Timing now anchored to direct GF180 SPICE characterization
    # (cell/sky130/sim/run_bl_sweep_gf180.py): SS @ N=128 BL discharge
    # is 1.916 ns vs SKY130's 1.535 ns -> 1.25x scale (was assumed
    # 1.5x; measured is 17% better). SA resolve assumed to scale
    # similarly; clk_to_bl_ns updated accordingly.
    "gf180": {
        "cell_w_um":        1.01,   # 0.73 * 1.39
        "cell_h_um":        1.24,   # 0.89 * 1.39 (bitcell_v4 production target)
        "wrap_margin_x_um": 28.0,   # 20 * 1.39
        "wrap_margin_y_um": 14.0,
        "clk_to_bl_ns":     3.81,   # 3.05 * 1.25 (measured BL-discharge scale)
        "setup_ns":         0.38,   # 0.30 * 1.25
        "hold_ns":          0.13,   # 0.10 * 1.25
        "vdd_v":            5.00,
        "vdd_v_ss":         4.50,
        "layer_m4":         "Metal4",
        "layer_signal":     "Metal3",
    },
    # ASAP7 digital-tier anchor. Cell dims are the bottom-up estimate of
    # pdk/sky130_scaled.yaml (wire-pitch-dominated, 0.07 um^2/weight;
    # naive (7/130)^2 scaling is wrong because ASAP7 keeps 27/54 nm
    # M1/M2 pitches). Timing is a placeholder consistent with a sub-ns
    # 64-row full-swing read at 7 nm; it anchors AREA, and any timing
    # conclusion needs node characterization first.
    "asap7": {
        "cell_w_um":        0.27,
        "cell_h_um":        0.26,
        "wrap_margin_x_um": 2.0,
        "wrap_margin_y_um": 1.0,
        "clk_to_bl_ns":     0.20,
        "setup_ns":         0.05,
        "hold_ns":          0.02,
        "vdd_v":            0.70,
        "vdd_v_ss":         0.63,
        "layer_m4":         "M4",   # horizontal-preferred; matches the FakeRAM macro-PDN convention
        "layer_signal":     "M4",
        # ASAP7 enforces on-track pins (RightWayOnGridOnly): M4 is
        # horizontal-preferred, y tracks at 0.012 + k*0.048.
        "pin_grid_y":       (0.012, 0.048),
        "pin_h_um":         0.048,
    },
}

WRAPPER_OVERHEAD_FRAC = 0.30  # decoder + drivers + SAs + accumulators


def write_liberty(rows: int, cols: int, pdk: str, biroma: bool = False) -> None:
    """Write cirom_array_{rows}x{cols}_{pdk}[_biroma].lib."""
    p = PDK_PARAMS[pdk]
    per_cell_um2 = p["cell_w_um"] * p["cell_h_um"]
    name = f"cirom_array_{rows}x{cols}"
    suffix = f"_{pdk}"
    if biroma:
        suffix += "_biroma"
    file_stem = f"{name}{suffix}"
    n_weights = rows * cols
    n_cells = (n_weights + 1) // 2 if biroma else n_weights
    active_um2 = n_cells * per_cell_um2
    total_um2 = active_um2 * (1 + WRAPPER_OVERHEAD_FRAC)
    addr_bits = (rows - 1).bit_length()
    clk_to_bl = p["clk_to_bl_ns"]
    setup = p["setup_ns"]
    hold = p["hold_ns"]
    vdd = p["vdd_v"]
    vdd_ss = p["vdd_v_ss"]
    cells_note = f" ({n_cells} cells x 2 weights/cell)" if biroma else ""

    lines = [
        f"/* {file_stem} Liberty (auto-generated from gen_anchor_abstracts.py).",
        f" * {n_weights} ternary weights{cells_note}; {active_um2:.0f} um^2 active + 30% wrapper",
        f" * = {total_um2:.0f} um^2 total. SS clk-to-bl_out = {clk_to_bl:.2f} ns.",
        f" * PDK: {pdk} (VDD={vdd}V nominal, {vdd_ss}V SS).",
        " */",
        "",
        f"library ({file_stem}) {{",
        "  technology (cmos);",
        "  delay_model : table_lookup;",
        "  time_unit                    : \"1ns\";",
        "  voltage_unit                 : \"1V\";",
        "  current_unit                 : \"1mA\";",
        "  pulling_resistance_unit      : \"1kohm\";",
        "  capacitive_load_unit (1, ff);",
        "  leakage_power_unit           : \"1nW\";",
        "  default_input_pin_cap        : 0.001;",
        "  default_inout_pin_cap        : 0.001;",
        "  default_output_pin_cap       : 0.000;",
        "  default_fanout_load          : 1.0;",
        f"  nom_voltage                  : {vdd};",
        "  nom_temperature              : 25.0;",
        "  nom_process                  : 1.0;",
        f"  voltage_map (VDD, {vdd});",
        "  voltage_map (VSS, 0.0);",
        "  operating_conditions (\"ss_corner\") {",
        "    process : 1.0;",
        f"    voltage : {vdd_ss};",
        "    temperature : 100.0;",
        "  }",
        "  default_operating_conditions : \"ss_corner\";",
        "",
        "  type (wl_addr_bus) {",
        "    base_type : array;",
        "    data_type : bit;",
        f"    bit_width : {addr_bits};",
        f"    bit_from : {addr_bits-1};",
        "    bit_to : 0;",
        "    downto : true;",
        "  }",
        "  type (bl_bus) {",
        "    base_type : array;",
        "    data_type : bit;",
        f"    bit_width : {cols};",
        f"    bit_from : {cols-1};",
        "    bit_to : 0;",
        "    downto : true;",
        "  }",
        "",
        f"  cell ({name}) {{",
        "    is_macro_cell : true;",
        f"    area : {total_um2:.1f};",
        "    pg_pin (VDD) {",
        "      pg_type : primary_power;",
        "      voltage_name : VDD;",
        "    }",
        "    pg_pin (VSS) {",
        "      pg_type : primary_ground;",
        "      voltage_name : VSS;",
        "    }",
        "",
        "    pin (clk) {",
        "      direction : input;",
        "      clock : true;",
        "      capacitance : 8.0;",
        "      max_transition : 0.5;",
        "    }",
    ]

    for sig in ("rst_n", "act_bit"):
        lines += [
            "",
            f"    pin ({sig}) {{",
            "      direction : input;",
            "      capacitance : 4.0;",
            "      max_transition : 0.5;",
            "      timing () {",
            "        related_pin : \"clk\";",
            "        timing_type : setup_rising;",
            "        rise_constraint (scalar) {",
            f"          values (\"{setup:.2f}\");",
            "        }",
            "        fall_constraint (scalar) {",
            f"          values (\"{setup:.2f}\");",
            "        }",
            "      }",
            "      timing () {",
            "        related_pin : \"clk\";",
            "        timing_type : hold_rising;",
            "        rise_constraint (scalar) {",
            f"          values (\"{hold:.2f}\");",
            "        }",
            "        fall_constraint (scalar) {",
            f"          values (\"{hold:.2f}\");",
            "        }",
            "      }",
            "    }",
        ]

    lines += [
        "",
        "    bus (wl_addr) {",
        "      bus_type : wl_addr_bus;",
        "      direction : input;",
        "      capacitance : 2.0;",
        "      max_transition : 0.5;",
        f"      pin (wl_addr[{addr_bits-1}:0]) {{",
        "        timing () {",
        "          related_pin : \"clk\";",
        "          timing_type : setup_rising;",
        "          rise_constraint (scalar) {",
        f"            values (\"{setup:.2f}\");",
        "          }",
        "          fall_constraint (scalar) {",
        f"            values (\"{setup:.2f}\");",
        "          }",
        "        }",
        "        timing () {",
        "          related_pin : \"clk\";",
        "          timing_type : hold_rising;",
        "          rise_constraint (scalar) {",
        f"            values (\"{hold:.2f}\");",
        "          }",
        "          fall_constraint (scalar) {",
        f"            values (\"{hold:.2f}\");",
        "          }",
        "        }",
        "      }",
        "    }",
    ]

    # NLDM 3x3 lookup tables. Indexed by input slew (input_net_transition,
    # the strobe edge rate at the macro's clk pin) and output load
    # (total_output_net_capacitance, the M2 BL routing + receiver gate
    # cap on bl_pos/bl_neg). Center value matches the prior scalar
    # estimate; corners scale linearly with slew/load.
    #
    # Slew range chosen 50 ps - 500 ps (typical for sky130 nominal
    # buffer-driven clk net); load range chosen 1 fF - 50 fF (single
    # receiver up to small wire stack).
    slew_idx = "0.05, 0.20, 0.50"
    load_idx = "1.0, 10.0, 50.0"
    base = clk_to_bl
    # delay(slew, load) = base + 0.5*(slew - 0.20) + 0.020*(load - 10)
    # Picks a sensible NLDM shape that the SPICE characterization
    # will eventually replace with measured values.
    def cell_table(_):
        rows_t = []
        for s in (0.05, 0.20, 0.50):
            cells = []
            for l in (1.0, 10.0, 50.0):
                d = base + 0.5 * (s - 0.20) + 0.020 * (l - 10)
                cells.append(f"{d:.3f}")
            rows_t.append(", ".join(cells))
        return ", ".join(f'"{r}"' for r in rows_t)
    def trans_table():
        rows_t = []
        for s in (0.05, 0.20, 0.50):
            cells = []
            for l in (1.0, 10.0, 50.0):
                t = 0.05 + 0.005 * l + 0.5 * s
                cells.append(f"{t:.3f}")
            rows_t.append(", ".join(cells))
        return ", ".join(f'"{r}"' for r in rows_t)

    if "lu_table_template (ankhdjet_nldm_3x3)" not in "\n".join(lines):
        # Insert NLDM template once at library scope (before the cell block).
        # We inject just before the `cell (` line.
        for i, ln in enumerate(lines):
            if ln.startswith(f"  cell ({name}) {{"):
                lines[i:i] = [
                    "  lu_table_template (ankhdjet_nldm_3x3) {",
                    "    variable_1 : input_net_transition;",
                    "    variable_2 : total_output_net_capacitance;",
                    f"    index_1 (\"{slew_idx}\");",
                    f"    index_2 (\"{load_idx}\");",
                    "  }",
                    "",
                ]
                break

    for out in ("bl_pos", "bl_neg"):
        lines += [
            "",
            f"    bus ({out}) {{",
            "      bus_type : bl_bus;",
            "      direction : output;",
            "      capacitance : 0.0;",
            "      max_capacitance : 50.0;",
            f"      pin ({out}[{cols-1}:0]) {{",
            "        timing () {",
            "          related_pin : \"clk\";",
            "          timing_type : rising_edge;",
            "          cell_rise (ankhdjet_nldm_3x3) {",
            f"            values ({cell_table('rise')});",
            "          }",
            "          cell_fall (ankhdjet_nldm_3x3) {",
            f"            values ({cell_table('fall')});",
            "          }",
            "          rise_transition (ankhdjet_nldm_3x3) {",
            f"            values ({trans_table()});",
            "          }",
            "          fall_transition (ankhdjet_nldm_3x3) {",
            f"            values ({trans_table()});",
            "          }",
            "        }",
            "      }",
            "    }",
        ]

    lines += [
        "  }",
        "}",
        "",
    ]

    out = BUILD / f"{file_stem}.lib"
    out.write_text("\n".join(lines))
    print(f"wrote {out} ({n_weights} weights / {n_cells} cells, area={total_um2:.0f} um^2)")


def write_lef(rows: int, cols: int, pdk: str, biroma: bool = False) -> None:
    """Write cirom_array_{rows}x{cols}_{pdk}[_biroma].lef."""
    p = PDK_PARAMS[pdk]
    cw, ch = p["cell_w_um"], p["cell_h_um"]
    mx, my = p["wrap_margin_x_um"], p["wrap_margin_y_um"]
    name = f"cirom_array_{rows}x{cols}"
    suffix = f"_{pdk}"
    if biroma:
        suffix += "_biroma"
    file_stem = f"{name}{suffix}"
    addr_bits = (rows - 1).bit_length()

    # BiROMA halves the physical row count (each cell stores 2 weights)
    physical_rows = (rows + 1) // 2 if biroma else rows
    width_um = cols * cw + 2 * mx
    height_um = physical_rows * ch + 2 * my

    lines = [
        "VERSION 5.7 ;",
        "NOWIREEXTENSIONATPIN ON ;",
        "DIVIDERCHAR \"/\" ;",
        "BUSBITCHARS \"[]\" ;",
        "",
        f"# {file_stem} LEF abstract (auto-generated from gen_anchor_abstracts.py).",
        f"# Bitcell footprint {cw} x {ch} um, wrapper margin {mx}/{my} um, PDK {pdk}.",
        f"# Total bbox {width_um:.2f} x {height_um:.2f} um.",
        "",
        f"MACRO {name}",
        "  CLASS BLOCK ;",
        f"  FOREIGN {name} 0 0 ;",
        "  ORIGIN 0.000 0.000 ;",
        f"  SIZE {width_um:.3f} BY {height_um:.3f} ;",
        "  SYMMETRY X Y ;",
        "",
        "  PIN VDD",
        "    USE POWER ; DIRECTION INOUT ; SHAPE ABUTMENT ;",
        "    PORT",
        f"      LAYER {p['layer_m4']} ;",
        f"        RECT 0.000 0.000 {width_um:.3f} 0.480 ;",
        f"        RECT 0.000 {height_um-0.480:.3f} {width_um:.3f} {height_um:.3f} ;",
        "    END",
        "  END VDD",
        "",
        "  PIN VSS",
        "    USE GROUND ; DIRECTION INOUT ; SHAPE ABUTMENT ;",
        "    PORT",
        f"      LAYER {p['layer_m4']} ;",
        f"        RECT 0.000 0.480 {width_um:.3f} 0.960 ;",
        f"        RECT 0.000 {height_um-0.960:.3f} {width_um:.3f} {height_um-0.480:.3f} ;",
        "    END",
        "  END VSS",
        "",
    ]

    # Pin y-placement, snapped to the signal layer's routing tracks when
    # the PDK enforces on-grid pins (ASAP7 RightWayOnGridOnly).
    def pin_rect_y(y_center: float) -> tuple[float, float]:
        if "pin_grid_y" in p:
            off, pitch = p["pin_grid_y"]
            c = off + round((y_center - off) / pitch) * pitch
            half = p.get("pin_h_um", pitch) / 2.0
            return c - half, c + half
        return y_center, y_center + 0.480

    # Left-edge input pins on the signal layer
    y0 = height_um / 2 - 30
    inputs = ["clk", "rst_n", "act_bit"] + [f"wl_addr[{i}]" for i in range(addr_bits-1, -1, -1)]
    for i, sig in enumerate(inputs):
        ylo, yhi = pin_rect_y(y0 + i * 2.0)
        lines += [
            f"  PIN {sig}",
            "    DIRECTION INPUT ; USE SIGNAL ;",
            "    PORT",
            f"      LAYER {p['layer_signal']} ;",
            f"        RECT 0.000 {ylo:.3f} 0.480 {yhi:.3f} ;",
            "    END",
            f"  END {sig}",
        ]

    # Right-edge output pins on met3
    pin_pitch = (height_um - 4.0) / (2 * cols)  # 2 cols pins on each side
    for c in range(cols):
        for half, name_out in enumerate(["bl_pos", "bl_neg"]):
            ylo, yhi = pin_rect_y(2.0 + (c * 2 + half) * pin_pitch)
            lines += [
                f"  PIN {name_out}[{c}]",
                "    DIRECTION OUTPUT ; USE SIGNAL ;",
                "    PORT",
                f"      LAYER {p['layer_signal']} ;",
                f"        RECT {width_um-0.480:.3f} {ylo:.3f} {width_um:.3f} {yhi:.3f} ;",
                "    END",
                f"  END {name_out}[{c}]",
            ]

    lines += [
        "",
        f"END {name}",
        "",
        "END LIBRARY",
        "",
    ]

    out = BUILD / f"{file_stem}.lef"
    out.write_text("\n".join(lines))
    print(f"wrote {out} (size {width_um:.1f} x {height_um:.1f} um)")


def write_wrapper_sv(rows: int, cols: int, pdk: str) -> None:
    """Write {macro}_wrapper.sv: counter + macro instance + result regs."""
    name = f"cirom_array_{rows}x{cols}"
    addr_bits = (rows - 1).bit_length()
    text = f"""// Test harness for {name} hard macro.
//
// Auto-generated by gen_anchor_abstracts.py — do not hand-edit.
//
// Counter drives the WL row address; the macro returns 32 differential
// pos/neg sense outputs each cycle; results latch into output regs.
// Yosys reads {name} as a blackbox (via the macro Liberty), so the
// wrapper synthesizes to standard cells around a single hard macro
// instance.

`default_nettype none

(* blackbox *)
module {name} (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  act_bit,
    input  wire [{addr_bits-1}:0]  wl_addr,
    output wire [{cols-1}:0] bl_pos,
    output wire [{cols-1}:0] bl_neg
);
endmodule

module {name}_test_harness (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  act_bit,
    output reg  [{cols-1}:0] result_p,
    output reg  [{cols-1}:0] result_n
);
    reg [{addr_bits-1}:0] wl_addr;
    always @(posedge clk) begin
        if (!rst_n) wl_addr <= '0;
        else        wl_addr <= wl_addr + 1'b1;
    end

    wire [{cols-1}:0] bl_pos_w;
    wire [{cols-1}:0] bl_neg_w;

    {name} u_macro (
        .clk     (clk),
        .rst_n   (rst_n),
        .act_bit (act_bit),
        .wl_addr (wl_addr),
        .bl_pos  (bl_pos_w),
        .bl_neg  (bl_neg_w)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            result_p <= '0;
            result_n <= '0;
        end else begin
            result_p <= bl_pos_w;
            result_n <= bl_neg_w;
        end
    end
endmodule

`default_nettype wire
"""
    file_stem = f"cirom_array_{rows}x{cols}_{pdk}"
    out = BUILD / f"{file_stem}_wrapper.sv"
    out.write_text(text)
    print(f"wrote {out} (top={name}_test_harness)")


# Standard cell library paths per PDK. SKY130 uses the local volare
# install; GF180 uses the ORFS container path (see run_openroad_*.sh).
SYNTH_LIBS = {
    # Container-side paths, matching the volume mounts in run_openroad.sh.
    # Both PDKs are volare-installed locally and mounted at /host/.volare.
    "sky130": "/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib",
    "gf180":  "/host/.volare/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_5v00.lib",
    # asap7 synthesizes through the ORFS container's native flow
    # (tools/openroad/run_asap7_block.sh); this path only satisfies the
    # standalone yosys-script writer.
    "asap7":  "/OpenROAD-flow-scripts/flow/platforms/asap7/lib/NLDM/asap7sc7p5t_SIMPLE_RVT_TT_nldm_211120.lib.gz",
}

# Macro-dir path from the perspective of the yosys/openroad invocation:
# SKY130 runs locally and uses repo paths; GF180 runs inside the ORFS
# container with the repo bind-mounted at /host/repo.
SYNTH_MACRO_DIR = {
    # Container-side paths (run_openroad.sh always invokes Yosys inside
    # the openroad/orfs Docker image with REPO mounted at /host/repo).
    "sky130": "/host/repo/macro/sky130/build",
    "gf180":  "/host/repo/macro/sky130/build",
    "asap7":  "/host/repo/macro/sky130/build",
}


def write_yosys_script(rows: int, cols: int, pdk: str, biroma: bool = False) -> None:
    """Write {macro}_synth.ys: Yosys synth script.

    The synth script reads whichever macro Liberty is on disk for the
    current (pdk, biroma) selection. Output gates.v + wrapper.sv stay
    on the BiROMA-agnostic stem since the wrapper RTL itself is
    identical between BiROMA and standard encodings (the macro is a
    blackbox to Yosys; only the .lib's area attribute changes)."""
    name = f"cirom_array_{rows}x{cols}"
    lib_suffix = f"_{pdk}"
    if biroma:
        lib_suffix += "_biroma"
    lib_stem = f"{name}{lib_suffix}"
    file_stem = f"{name}_{pdk}"
    sc_lib = SYNTH_LIBS[pdk]
    macro_dir = SYNTH_MACRO_DIR[pdk]
    text = f"""# Synthesize {name}_test_harness with the {name} hard macro
# treated as a blackbox. Auto-generated by gen_anchor_abstracts.py for PDK {pdk}.

read_liberty -lib {sc_lib}
read_liberty -lib {macro_dir}/{lib_stem}.lib

read_verilog -sv {macro_dir}/{file_stem}_wrapper.sv

hierarchy -check -top {name}_test_harness

proc
flatten
opt
fsm
opt
memory
opt

techmap
opt

dfflibmap -liberty {sc_lib}
abc -liberty {sc_lib}
opt
clean

stat -liberty {sc_lib}

write_verilog -noattr {macro_dir}/{file_stem}_test_harness.gates.v
"""
    out = BUILD / f"{file_stem}_synth.ys"
    out.write_text(text)
    print(f"wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", type=int)
    ap.add_argument("cols", type=int)
    ap.add_argument("--pdk", choices=list(PDK_PARAMS.keys()), default="sky130")
    ap.add_argument("--biroma", action="store_true",
                    help="Halve the cell-area accounting for BiROMA "
                         "2-weights-per-1T-cell encoding (uses bitcell_v3_biroma).")
    args = ap.parse_args()
    write_liberty(args.rows, args.cols, args.pdk, biroma=args.biroma)
    write_lef(args.rows, args.cols, args.pdk, biroma=args.biroma)
    write_wrapper_sv(args.rows, args.cols, args.pdk)
    write_yosys_script(args.rows, args.cols, args.pdk, biroma=args.biroma)
    return 0


if __name__ == "__main__":
    sys.exit(main())
