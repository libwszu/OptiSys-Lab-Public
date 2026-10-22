"""Matplotlib defaults used by both the UI and the report figures.

The UI draws Chinese labels; Matplotlib's default DejaVu Sans has no CJK glyphs,
so axes titles rendered as boxes.  Rather than sprinkling ``rcParams`` calls
through the pages, one helper sets an ordered fallback list and is called before
the first figure of every module that plots.

``axes.unicode_minus = False`` is required in the same breath: with a CJK font,
U+2212 renders as a missing glyph, which would silently mangle negative tick
labels - exactly the kind of quiet corruption this project must not ship.
"""

from __future__ import annotations

#: Ordered CJK-capable candidates, then a Latin-only fallback.
FONT_CANDIDATES = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans SC",
    "DengXian",
    "DejaVu Sans",
)

_applied = False


def apply(force: bool = False) -> None:
    """Idempotent: safe to call at the top of every render."""

    global _applied
    if _applied and not force:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = list(FONT_CANDIDATES)
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.autolayout"] = False
    _applied = True


def available_cjk_font() -> str | None:
    """Which candidate actually exists on this machine (for diagnostics)."""

    import matplotlib.font_manager as fm

    installed = {f.name for f in fm.fontManager.ttflist}
    for name in FONT_CANDIDATES:
        if name in installed:
            return name
    return None