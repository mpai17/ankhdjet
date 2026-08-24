"""Grid RTL emission: a tiled layer as a routable multi-macro top.

Where ankhdjet.backend.macro_grid emits the mask programs (the .wmat
chunks that become the hardened macros), this module emits the RTL that
reads a GRID_R x GRID_C grid of those macros and accumulates their
contributions into the full layer's matrix-vector product. Together they
close the model-to-multi-macro-silicon path: macro_grid says what each
chunk stores, grid_rtl says how the chunks are wired and swept.

The emitted top instantiates the grid front end (one array per chunk) and
the library grid controller (rtl/grid/cirom_grid_ctrl.sv). For simulation
the chunks are behavioral (rtl/grid/cirom_array_beh.sv) loading per-chunk
memh; for hardening they are the named hardened macro blackboxes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ankhdjet.backend.idents import path_token, sv_ident


def _write_chunk_memh(chunk: np.ndarray, base: Path) -> None:
    """Write pos/neg memh for one MR x MC ternary chunk (one MC-bit hex
    word per row; bit c set => that column's weight is +1 / -1)."""
    mr, mc = chunk.shape
    pos, neg = [], []
    for r in range(mr):
        p = n = 0
        for c in range(mc):
            if chunk[r, c] == 1:
                p |= 1 << c
            elif chunk[r, c] == -1:
                n |= 1 << c
        width = (mc + 3) // 4
        pos.append(f"{p:0{width}x}")
        neg.append(f"{n:0{width}x}")
    base.with_suffix(".wpos.memh").write_text("\n".join(pos) + "\n")
    base.with_suffix(".wneg.memh").write_text("\n".join(neg) + "\n")


def emit_grid(
    W: np.ndarray,
    out_dir: Path | str,
    layer_name: str = "layer",
    top_name: str = "ankhdjet_grid",
    macro_rows: int = 8,
    macro_cols: int = 4,
    act_w: int = 4,
    acc_w: int = 16,
    rtl_dir: Path | str | None = None,
    memh_dir: Path | str | None = None,
    memh_prefix: str | None = None,
    afe_name: str = "cirom_grid_afe",
    hardened_dir: Path | str | None = None,
    chunk_base: str | None = None,
) -> dict:
    """Emit the grid top + front-end binding for one ternary layer.

    Tiles W (N x M) into macro_rows x macro_cols chunks, writes each
    chunk's pos/neg memh, and emits an RTL top wiring GRID_R x GRID_C
    behavioral chunk arrays to the grid controller. Returns the paths and
    grid geometry. layer_name must be a safe path token (it is quoted
    verbatim inside the emitted memh string literals; anything else is
    refused); top_name and afe_name are legalized into Verilog
    identifiers. By default everything lands under out_dir with memh
    literals relative to it; rtl_dir/memh_dir split the SV and memh
    outputs, and memh_prefix overrides the path baked into the memh
    string literals (each component validated as a path token) for
    bundles whose simulation working directory is not out_dir.
    When hardened_dir is given, an additional hardened implementation
    of the same AFE module is written there: per-chunk hard-macro
    instances (module <chunk_base>_r{i}_c{j} on the contract's scalar
    ports) instead of behavioral memh arrays. A netlist compiles one
    AFE implementation or the other, never both.
    """
    W = np.asarray(W, dtype=np.int8)
    if W.ndim != 2:
        raise ValueError(f"weight matrix must be 2-D, got {W.shape}")
    layer_name = path_token(layer_name)
    top_name = sv_ident(top_name)
    afe_name = sv_ident(afe_name)
    if memh_prefix is None:
        memh_prefix = layer_name
    else:
        for part in memh_prefix.split("/"):
            path_token(part)
    n, m = W.shape
    gr = -(-n // macro_rows)
    gc = -(-m // macro_cols)
    out = Path(out_dir)
    memh_root = Path(memh_dir) if memh_dir is not None else out
    rtl_root = Path(rtl_dir) if rtl_dir is not None else out
    rtl_root.mkdir(parents=True, exist_ok=True)
    (memh_root / layer_name).mkdir(parents=True, exist_ok=True)

    # per-chunk memh (zero-padded ragged edges = floating drains = weight 0)
    for ir in range(gr):
        for jc in range(gc):
            chunk = np.zeros((macro_rows, macro_cols), dtype=np.int8)
            r0, r1 = ir * macro_rows, min((ir + 1) * macro_rows, n)
            c0, c1 = jc * macro_cols, min((jc + 1) * macro_cols, m)
            chunk[: r1 - r0, : c1 - c0] = W[r0:r1, c0:c1]
            _write_chunk_memh(chunk, memh_root / layer_name / f"r{ir}_c{jc}")

    N, M = gr * macro_rows, gc * macro_cols
    afe = _emit_grid_afe(layer_name, memh_prefix, gr, gc, macro_rows,
                         macro_cols, rtl_root, afe_name)
    top = rtl_root / f"{top_name}.sv"
    top.write_text(_emit_grid_top(top_name, gr, gc, macro_rows, macro_cols,
                                  act_w, acc_w, afe_name))

    hard_afe = None
    chunk_modules: list[str] = []
    if hardened_dir is not None:
        hdir = Path(hardened_dir)
        if hdir.resolve() == rtl_root.resolve():
            raise ValueError(
                "hardened_dir must differ from rtl_dir (both AFE "
                "implementations share the module name)")
        hdir.mkdir(parents=True, exist_ok=True)
        base = sv_ident(chunk_base or
                        f"macro_array_pc_{macro_rows}x{macro_cols}_"
                        f"{layer_name}")
        hard_afe, chunk_modules = _emit_grid_afe_hard(
            layer_name, gr, gc, macro_rows, macro_cols, hdir, afe_name,
            base)

    return {"top": top, "afe": afe, "grid_r": gr, "grid_c": gc,
            "N": N, "M": M, "macro_rows": macro_rows, "macro_cols": macro_cols,
            "memh_dir": memh_root / layer_name,
            "hard_afe": hard_afe, "chunk_modules": chunk_modules}


def _emit_grid_afe(layer: str, memdir: str, gr: int, gc: int, mr: int,
                   mc: int, out: Path, name: str) -> Path:
    """Front-end binding: GRID_R*GRID_C behavioral chunk arrays wired to
    the flattened grid interface (wl per row-chunk, bitlines row-banded)."""
    M = gc * mc
    lines = [
        "// GENERATED by ankhdjet.backend.grid_rtl -- do not edit.",
        f"// Grid front end for layer {layer}: {gr}x{gc} chunks of {mr}x{mc}.",
        "`default_nettype none",
        "",
        f"module {name} #(",
        f"    parameter int GRID_R = {gr}, parameter int GRID_C = {gc},",
        f"    parameter int MR = {mr}, parameter int MC = {mc}",
        ")(",
        "    input  logic [GRID_R*MR-1:0]          wl,",
        "    input  logic                          pre_n,",
        "    output logic [GRID_R*(GRID_C*MC)-1:0] blp,",
        "    output logic [GRID_R*(GRID_C*MC)-1:0] bln",
        ");",
    ]
    for ir in range(gr):
        for jc in range(gc):
            band = (ir * gc + jc) * mc          # == ir*M + jc*mc
            assert band == ir * M + jc * mc
            lines += [
                f"    cirom_array_beh #(.MR(MR), .MC(MC),",
                f"        .WPOS(\"{memdir}/r{ir}_c{jc}.wpos.memh\"),",
                f"        .WNEG(\"{memdir}/r{ir}_c{jc}.wneg.memh\")) u_{ir}_{jc} (",
                f"        .wl(wl[{ir}*MR +: MR]), .pre_n(pre_n),",
                f"        .blp(blp[{band} +: MC]), .bln(bln[{band} +: MC]));",
            ]
    lines += ["endmodule", "", "`default_nettype wire", ""]
    p = out / f"{name}.sv"
    p.write_text("\n".join(lines))
    return p


def _emit_grid_afe_hard(layer: str, gr: int, gc: int, mr: int, mc: int,
                        out: Path, name: str,
                        chunk_base: str) -> tuple[Path, list[str]]:
    """Hardened front-end binding: the AFE interface implemented by
    per-chunk hard-macro instances on the contract's scalar ports.
    Power ports pass through under USE_POWER_PINS, matching the chip
    tops' macro-binding convention."""
    M = gc * mc

    def _wrap(items: list[str]) -> list[str]:
        return [("        " + ", ".join(items[i:i + 8]) +
                 ("," if i + 8 < len(items) else ""))
                for i in range(0, len(items), 8)]

    lines = [
        "// GENERATED by ankhdjet.backend.grid_rtl -- do not edit.",
        f"// Hardened grid front end for layer {layer}: {gr}x{gc} chunks "
        f"of {mr}x{mc}.",
        "// Compile INSTEAD of the behavioral front end; the chunk",
        "// macros come from the hardening flow per the hardening",
        "// manifest.",
        "`default_nettype none",
        "",
        f"module {name} #(",
        f"    parameter int GRID_R = {gr}, parameter int GRID_C = {gc},",
        f"    parameter int MR = {mr}, parameter int MC = {mc}",
        ")(",
        "`ifdef USE_POWER_PINS",
        "    inout  wire                          VPWR,",
        "    inout  wire                          VGND,",
        "`endif",
        "    input  wire [GRID_R*MR-1:0]          wl,",
        "    input  wire                          pre_n,",
        "    output wire [GRID_R*(GRID_C*MC)-1:0] blp,",
        "    output wire [GRID_R*(GRID_C*MC)-1:0] bln",
        ");",
    ]
    modules: list[str] = []
    for ir in range(gr):
        for jc in range(gc):
            band = ir * M + jc * mc
            mod = f"{chunk_base}_r{ir}_c{jc}"
            modules.append(mod)
            wl_conns = [f".WL_{k}(wl[{ir * mr + k}])" for k in range(mr)]
            bl_conns = []
            for c in range(mc):
                bl_conns += [f".BLP_{c}(blp[{band + c}])",
                             f".BLN_{c}(bln[{band + c}])"]
            lines += [
                f"    {mod} u_{ir}_{jc} (",
                "`ifdef USE_POWER_PINS",
                "        .VPWR(VPWR), .VGND(VGND),",
                "`endif",
                "        .PRE_N(pre_n),",
                *_wrap(wl_conns + bl_conns),
                "    );",
            ]
    lines += ["endmodule", "", "`default_nettype wire", ""]
    p = out / f"{name}.sv"
    p.write_text("\n".join(lines))
    return p, modules


def _emit_grid_top(top: str, gr: int, gc: int, mr: int, mc: int,
                   act_w: int, acc_w: int,
                   afe_name: str = "cirom_grid_afe") -> str:
    return f"""// GENERATED by ankhdjet.backend.grid_rtl -- do not edit.
// Grid top: {gr}x{gc} macro grid ({gr*mr} rows x {gc*mc} cols) read and
// accumulated into the layer's matrix-vector product.
`default_nettype none

module {top} (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [7:0] ui,
    input  logic       act_wr,
    input  logic       start,
    output logic [7:0] result,
    output logic       result_valid,
    output logic       busy,
    output logic       done
);
    localparam int GRID_R = {gr}, GRID_C = {gc}, MR = {mr}, MC = {mc};
    wire [GRID_R*MR-1:0]          wl;
    wire                          pre_n;
    wire [GRID_R*(GRID_C*MC)-1:0] blp, bln;

    cirom_grid_ctrl #(
        .GRID_R(GRID_R), .GRID_C(GRID_C), .MR(MR), .MC(MC),
        .ACT_W({act_w}), .ACC_W({acc_w})
    ) u_ctrl (
        .clk(clk), .rst_n(rst_n), .ui(ui), .act_wr(act_wr), .start(start),
        .wl(wl), .pre_n(pre_n), .blp(blp), .bln(bln),
        .result(result), .result_valid(result_valid),
        .busy(busy), .done(done)
    );

    {afe_name} #(
        .GRID_R(GRID_R), .GRID_C(GRID_C), .MR(MR), .MC(MC)
    ) u_afe (
        .wl(wl), .pre_n(pre_n), .blp(blp), .bln(bln)
    );
endmodule

`default_nettype wire
"""
