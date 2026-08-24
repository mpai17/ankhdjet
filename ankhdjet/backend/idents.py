"""Name legalization at the emission boundary.

Layer and model names arrive from arbitrary sources (a HuggingFace repo
id keeps its dots: bitnet_b1.58_2B_4T), while a Verilog simple
identifier allows only [A-Za-z0-9_] with no leading digit, and a memh
path is quoted verbatim inside an SV string literal. Everything the
emitters splice into module names goes through `sv_ident` (deterministic
legalization) guarded by `check_unique` (legalization is not injective;
a collision would silently merge two modules), and everything spliced
into paths-inside-literals goes through `path_token` (refusal rather
than rewriting, so the on-disk spelling and the SV literal can never
diverge).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_SV_ILLEGAL = re.compile(r"[^A-Za-z0-9_]")
_PATH_TOKEN = re.compile(r"[A-Za-z0-9._-]+")


def sv_ident(name: str) -> str:
    """Legalize a name into a Verilog simple identifier: every character
    outside [A-Za-z0-9_] becomes '_', a leading digit gains a '_'
    prefix. Legal names pass through unchanged."""
    if not name:
        raise ValueError("empty name cannot become a Verilog identifier")
    ident = _SV_ILLEGAL.sub("_", name)
    if ident[0].isdigit():
        ident = "_" + ident
    return ident


def check_unique(names: Iterable[str]) -> None:
    """Refuse a name set whose legalized identifiers collide: the
    emitters mint one module per name, so a collision (or a plain
    duplicate) would emit two modules with the same name."""
    seen: dict[str, str] = {}
    for n in names:
        ident = sv_ident(n)
        if ident in seen:
            prev = seen[ident]
            reason = ("is duplicated" if prev == n
                      else f"collides with {prev!r} after legalization")
            raise ValueError(
                f"layer name {n!r} {reason}: both map to Verilog "
                f"identifier {ident!r}")
        seen[ident] = n


def path_token(name: str) -> str:
    """Refuse any name not usable verbatim as both a single path
    component and the body of an SV string literal (the emitted RTL
    references the emitted memh files by this exact spelling). Allowed
    characters are A-Za-z0-9._- and dot-only names are reserved."""
    if not _PATH_TOKEN.fullmatch(name) or set(name) == {"."}:
        raise ValueError(
            f"name {name!r} is not a safe path token (allowed: a single "
            "path component of A-Za-z0-9._-)")
    return name
