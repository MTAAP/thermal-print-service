"""Dither algorithms — re-exported from printer_core.

The single source of truth lives in ``printer_core.dither``.
"""
from printer_core.dither import (  # noqa: F401
    DITHERS,
    atkinson_dither,
    floyd_steinberg,
    no_dither,
    ordered_dither,
)
