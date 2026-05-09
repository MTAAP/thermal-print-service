import io

import pytest
from PIL import Image

from printer.transport import PrinterUnavailable
from printer.transport.runtime import FilePrinterAdapter


def _png_bytes(width: int = 576, height: int = 32) -> bytes:
    buf = io.BytesIO()
    Image.new("1", (width, height), 1).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_adapter_raises_printer_unavailable_when_device_missing(tmp_path):
    """OSError at FilePrinter.__init__ must be wrapped as PrinterUnavailable
    so the worker's generic-Exception branch retries (rather than the
    IOError branch which writes unknown_partial).

    Use a path under a missing parent dir; ``open(p, "wb")`` would otherwise
    create a regular file rather than fail. On the Pi when the printer is
    unplugged the kernel removes ``/dev/usb/lp0`` itself, so the same
    FileNotFoundError fires there for the same reason.
    """
    missing = tmp_path / "missing-dir" / "lp0"
    adapter = FilePrinterAdapter(str(missing))
    with pytest.raises(PrinterUnavailable):
        await adapter.print_png(_png_bytes(), auto_cut=True, feed_lines_after=2)


@pytest.mark.asyncio
async def test_printer_unavailable_is_not_oserror_subclass():
    """Worker's IOError branch (unknown_partial) must NOT catch
    PrinterUnavailable. PrinterUnavailable is plain Exception on purpose."""
    assert not issubclass(PrinterUnavailable, OSError)
