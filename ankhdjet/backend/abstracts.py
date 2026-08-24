"""Macro abstract views (LEF footprint, Liberty, blackbox Verilog) for
the macro_array_pc hard-macro contract, generated per array shape and
PDK descriptor.

The contract's macro is a regular structure (bitcell array + precharge
row, per-row wordline pins, per-column bitline strips, shared PRE_N and
rails), so its abstract views generate parametrically from a small
per-PDK constant set: cell pitch, pin plan, rails geometry, and the
per-unit pin capacitances characterized at that PDK's anchor macro.
The constants come from the named PDK pack's abstracts.yaml (see
ankhdjet.pdks), and a pack's constants must regenerate its anchor's
extracted pin geometry (`ankhdjet pdk validate` asserts it rectangle
by rectangle; the SKY130 pack's anchor is the signed-off macro). These
are template-grade views: floorplanning and synthesis consume them,
obstruction maps are omitted, and the extracted views of a hardened
macro remain the authoritative signoff collateral.
"""

from __future__ import annotations

from pathlib import Path

from ankhdjet.backend.idents import sv_ident
from ankhdjet.pdks import abstract_pack


def blackbox_lines(name: str, rows: int, cols: int) -> list[str]:
    """`celldefine blackbox declaration for one macro of the contract's
    port shape (scalar per-pin ports, power under no ifdef: synthesis
    reads these through the flow's power-aware liberty binding)."""
    out = ["`celldefine", "(* blackbox *)", f"module {name} ("]
    pins = [f"    input  WL_{r}" for r in range(rows)]
    for c in range(cols):
        pins += [f"    inout  BLP_{c}", f"    inout  BLN_{c}"]
    pins += ["    input  PRE_N", "    inout  VPWR", "    inout  VGND"]
    out.append(",\n".join(pins))
    out += [");", "endmodule", "`endcelldefine"]
    return out


def _provenance(p: dict) -> str:
    return (f"template-grade view from the macro contract constants, "
            f"anchored to {p['anchor_note']}; a hardened macro's "
            f"extracted views are the signoff collateral")


def _geometry(rows: int, cols: int, p: dict) -> dict:
    def wl_y(r: int) -> float:
        return p["wl_y0"] + (r + r // p["tap_every"]) * p["row_pitch"]

    bln_h = wl_y(rows - 1) + p["wl_h"] + p["bln_top_pad"]
    return {
        "wl_y": wl_y,
        "width": cols * p["col_pitch"] + p["edge_w"],
        "bln_h": bln_h,
        "blp_h": bln_h + p["blp_extra"],
        "height": bln_h + p["rails_extra"],
    }


def emit_macro_abstracts(rows: int, cols: int, out_dir: Path | str,
                         name: str | None = None,
                         pdk: str = "sky130") -> dict:
    """Write {name}.lef/.lib/.bb.v for the macro_array_pc contract at
    (rows, cols) under the named PDK pack; one set serves every
    chunk of that shape (the mask program lives in the GDS, not the
    abstracts). Returns the paths, the footprint, and the pack's
    provenance fields."""
    p, pack = abstract_pack(pdk)
    name = sv_ident(name or f"macro_array_pc_{rows}x{cols}")
    g = _geometry(rows, cols, p)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    W, H = g["width"], g["height"]
    prov = _provenance(p)

    lef = [
        "VERSION 5.7 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        "",
        f"# {name} LEF ({prov}).",
        f"# {rows}x{cols} array + precharge row; OBS omitted.",
        "",
        f"MACRO {name}",
        "  CLASS BLOCK ;",
        f"  FOREIGN {name} ;",
        "  ORIGIN 0.000 0.000 ;",
        f"  SIZE {W:.3f} BY {H:.3f} ;",
        "",
        "  PIN VPWR",
        "    USE POWER ; DIRECTION INOUT ;",
        "    PORT",
        f"      LAYER {p['rail_layer_lo']} ;",
        f"        RECT 0.000 {H - p['vpwr_lo_y'][0]:.3f} "
        f"{W - p['rail_inset']:.3f} {H - p['vpwr_lo_y'][1]:.3f} ;",
        "    END",
        "    PORT",
        f"      LAYER {p['rail_layer_hi']} ;",
        f"        RECT 0.000 {H - p['vpwr_hi_y'][0]:.3f} "
        f"{W - p['rail_inset']:.3f} {H - p['vpwr_hi_y'][1]:.3f} ;",
        "    END",
        "  END VPWR",
        "",
        "  PIN VGND",
        "    USE GROUND ; DIRECTION INOUT ;",
        "    PORT",
        f"      LAYER {p['rail_layer_lo']} ;",
        f"        RECT 0.000 {H - p['vgnd_lo_y'][0]:.3f} "
        f"{W - p['rail_inset']:.3f} {H - p['vgnd_lo_y'][1]:.3f} ;",
        "    END",
        "  END VGND",
        "",
    ]
    for r in range(rows):
        y = g["wl_y"](r)
        lef += [
            f"  PIN WL_{r}",
            "    DIRECTION INPUT ; USE SIGNAL ;",
            "    PORT",
            f"      LAYER {p['wl_layer']} ;",
            f"        RECT 0.000 {y:.3f} {p['wl_w']:.3f} "
            f"{y + p['wl_h']:.3f} ;",
            "    END",
            f"  END WL_{r}",
        ]
    for c in range(cols):
        xp = p["blp_x0"] + c * p["col_pitch"]
        xn = p["bln_x0"] + c * p["col_pitch"]
        lef += [
            f"  PIN BLP_{c}",
            "    DIRECTION INOUT ; USE SIGNAL ;",
            "    PORT",
            f"      LAYER {p['blp_layer']} ;",
            f"        RECT {xp:.3f} 0.000 {xp + p['bl_w']:.3f} "
            f"{g['blp_h']:.3f} ;",
            "    END",
            f"  END BLP_{c}",
            f"  PIN BLN_{c}",
            "    DIRECTION INOUT ; USE SIGNAL ;",
            "    PORT",
            f"      LAYER {p['bln_layer']} ;",
            f"        RECT {xn:.3f} 0.000 {xn + p['bl_w']:.3f} "
            f"{g['bln_h']:.3f} ;",
            "    END",
            f"  END BLN_{c}",
        ]
    xpre = p["pre_x_frac"] * W
    lef += [
        "  PIN PRE_N",
        "    DIRECTION INPUT ; USE SIGNAL ;",
        "    PORT",
        f"      LAYER {p['pre_layer']} ;",
        f"        RECT {xpre:.3f} {H - p['pre_h']:.3f} "
        f"{xpre + p['pre_w']:.3f} {H:.3f} ;",
        "    END",
        "  END PRE_N",
        "",
        f"END {name}",
        "",
        "END LIBRARY",
        "",
    ]

    lib = [
        f"/* {name} Liberty ({prov}).",
        f" * {rows}x{cols} array + precharge row; "
        f"bbox {W:.2f} x {H:.2f} um.",
        " * Pin capacitances scale per unit from the descriptor's",
        " * characterized anchor; BLP/BLN carry no timing arcs (raw",
        " * bitlines: full-swing sampled in the digital tier,",
        " * comparator-sensed in the analog variant).",
        " */",
        "",
        f"library ({name}) {{",
        "  technology (cmos);",
        "  delay_model : table_lookup;",
        '  time_unit                    : "1ns";',
        '  voltage_unit                 : "1V";',
        '  current_unit                 : "1mA";',
        '  pulling_resistance_unit      : "1kohm";',
        "  capacitive_load_unit (1, ff);",
        '  leakage_power_unit           : "1nW";',
        "  default_input_pin_cap        : 0.001;",
        "  default_inout_pin_cap        : 0.001;",
        "  default_output_pin_cap       : 0.000;",
        f"  nom_voltage                  : {p['vdd']:.2f};",
        "  nom_temperature              : 25.0;",
        "  nom_process                  : 1.0;",
        "  input_threshold_pct_rise     : 50;",
        "  input_threshold_pct_fall     : 50;",
        "  output_threshold_pct_rise    : 50;",
        "  output_threshold_pct_fall    : 50;",
        "  slew_lower_threshold_pct_rise: 20;",
        "  slew_upper_threshold_pct_rise: 80;",
        "  slew_lower_threshold_pct_fall: 20;",
        "  slew_upper_threshold_pct_fall: 80;",
        "  slew_derate_from_library     : 1.0;",
        f"  voltage_map (VPWR, {p['vdd']:.2f});",
        "  voltage_map (VGND, 0.0);",
        "",
        f"  cell ({name}) {{",
        "    is_macro_cell : true;",
        f"    area : {W * H:.1f};",
        "    pg_pin (VPWR) {",
        "      pg_type : primary_power;",
        "      voltage_name : VPWR;",
        "    }",
        "    pg_pin (VGND) {",
        "      pg_type : primary_ground;",
        "      voltage_name : VGND;",
        "    }",
        "",
    ]
    cap_wl = p["cap_wl_per_col"] * cols
    cap_pre = p["cap_pre_per_col"] * cols
    cap_bl = p["cap_bl_per_row"] * rows
    for r in range(rows):
        lib += [
            f"    pin (WL_{r}) {{",
            "      direction : input;",
            f"      capacitance : {cap_wl:.1f};",
            "      related_power_pin  : VPWR;",
            "      related_ground_pin : VGND;",
            "    }",
        ]
    lib += [
        "    pin (PRE_N) {",
        "      direction : input;",
        f"      capacitance : {cap_pre:.1f};",
        "      related_power_pin  : VPWR;",
        "      related_ground_pin : VGND;",
        "    }",
    ]
    for c in range(cols):
        for sig in ("BLP", "BLN"):
            lib += [
                f"    pin ({sig}_{c}) {{",
                "      direction : inout;",
                f"      capacitance : {cap_bl:.1f};",
                f"      max_capacitance : {p['bl_max_cap']:.1f};",
                "      related_power_pin  : VPWR;",
                "      related_ground_pin : VGND;",
                "    }",
            ]
    lib += ["  }", "}", ""]

    bb = [
        f"// {name} blackbox ({prov}).",
        f"// {rows}x{cols} bitcell array + precharge row.",
        "",
        *blackbox_lines(name, rows, cols),
        "",
    ]

    paths = {"lef": out / f"{name}.lef", "lib": out / f"{name}.lib",
             "bb": out / f"{name}.bb.v"}
    paths["lef"].write_text("\n".join(lef))
    paths["lib"].write_text("\n".join(lib))
    paths["bb"].write_text("\n".join(bb))
    return {"name": name, "pdk": pdk, **paths,
            "width_um": W, "height_um": H,
            "pack_version": pack.version, "restricted": pack.restricted}
