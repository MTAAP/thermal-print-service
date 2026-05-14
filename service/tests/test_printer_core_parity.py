"""Regression guard: service.printer.render.dither must produce
byte-identical output to printer_core.dither.atkinson_dither for the
shared fixture. Catches accidental drift if anyone forks the algorithm.
"""
import hashlib
from pathlib import Path

from PIL import Image
from printer_core.dither import atkinson_dither as core_atkinson

from printer.render.dither import atkinson_dither as service_atkinson

FIXTURE = (
    Path(__file__).parent.parent.parent
    / "printer-core" / "tests" / "fixtures" / "grayscale_ramp.png"
)


def test_service_dither_matches_printer_core():
    img = Image.open(FIXTURE)
    a = hashlib.sha256(service_atkinson(img.copy()).tobytes()).hexdigest()
    b = hashlib.sha256(core_atkinson(img.copy()).tobytes()).hexdigest()
    assert a == b
