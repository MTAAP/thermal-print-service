from PIL import Image

from printer.transport.escpos_file import FilePrinter


def test_file_printer_writes_to_path(tmp_path):
    fake = tmp_path / "fake-printer"
    fake.touch()

    img = Image.new("1", (576, 32), 1)
    p = FilePrinter(str(fake))
    p.print_image(img, auto_cut=True, feed_lines_after=2)
    p.close()

    written = fake.read_bytes()
    # python-escpos always emits ESC @ on init
    assert written[:2] == b"\x1b@"
    # Auto-cut adds GS V
    assert b"\x1dV" in written
