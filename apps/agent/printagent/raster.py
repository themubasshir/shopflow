"""PDF → monochrome raster → ESC/POS (Phase 2D-2).

This is the only place the saved-invoice PDF is turned into printer bytes, and
it is shared by the real network transport and the in-test simulator. The
pipeline preserves Bengali shaping because it rasterizes the *embedded* PDF
font with MuPDF rather than asking the printer's firmware to interpret Unicode.

Steps:

1. Render every PDF page to a grayscale pixmap at the printer's DPI.
2. Calibrate: scale each page to the printer's printable dot width so the
   receipt fills the paper without overflow or a shrunken gutter.
3. Stitch pages vertically into one continuous strip (a single tall page is
   the normal case; multi-page input still produces one strip).
4. Threshold to 1-bit monochrome and pack 8 pixels per byte, MSB-first — the
   bit order ESC/POS ``GS v 0`` raster commands expect.
5. Emit the byte stream: init, raster chunks (``GS v 0``), feed, and a partial
   cut when the device supports it.

No Unicode is ever sent to the printer; it only ever receives bitmap bands.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

# ESC/POS control bytes.
ESC = 0x1B
GS = 0x1D

# Default monochrome threshold (0=black … 255=white). Pixels darker than this
# burn. 160 is a mid-point tuned for antialiased receipt text.
DEFAULT_THRESHOLD = 160

# Chunk height for each GS v 0 block. Printers bound a single raster command to
# a modest band; 400-dot strips stream reliably and keep memory bounded on long
# receipts.
RASTER_CHUNK = 400


@dataclass(frozen=True)
class RasterPage:
    """A calibrated monochrome page ready to stream."""

    width: int  # dots (== printable dot width after calibration)
    height: int  # dots
    data: bytes  # 1-bit packed, MSB-first, rowbytes = ceil(width/8)


def _pixmap_to_gray_rows(pix: "pymupdf.Pixmap") -> tuple[int, int, int, bytes]:
    """Return (width, height, stride, samples) for a grayscale pixmap."""
    return pix.width, pix.height, pix.stride, pix.samples


def _scale_to_width(
    doc: "pymupdf.Document", page_index: int, target_width: int
) -> "pymupdf.Pixmap":
    """Render one page at a DPI chosen so the grayscale pixmap is exactly
    ``target_width`` dots wide. MuPDF rescales during render, so the embedded
    font is shaped at full fidelity before any quantization."""
    page = doc[page_index]
    # Width in PDF points → inches → dots at 72dpi baseline, then solve for dpi.
    pt_width = page.rect.width
    if pt_width <= 0:
        dpi = 203.0
    else:
        inches = pt_width / 72.0
        dpi = target_width / inches
    dpi = max(24.0, min(dpi, 1200.0))  # guard against degenerate pages
    # pymupdf's set_dpi requires ints; round to the nearest whole DPI, which at
    # thermal resolutions keeps us within a dot of the target width.
    return page.get_pixmap(dpi=max(24, round(dpi)), colorspace=pymupdf.csGRAY)


def _threshold_pack(
    pix: "pymupdf.Pixmap", threshold: int, width: int
) -> tuple[int, int, bytes]:
    """Convert a grayscale pixmap to 1-bit packed rows at exactly ``width`` dots.

    DPI rounding can land the rendered pixmap a dot wider or narrower than the
    target. We pack exactly ``width`` columns and crop/pad any residue with
    white, so every band shares one row stride — required for the receipt to
    hit the printable width without a seam.
    """
    _w, height, stride, samples = _pixmap_to_gray_rows(pix)
    usable = min(width, _w)
    rowbytes = (width + 7) // 8
    out = bytearray(rowbytes * height)
    for y in range(height):
        row_base = y * stride
        out_base = y * rowbytes
        for x in range(usable):
            if samples[row_base + x] < threshold:
                out[out_base + (x >> 3)] |= 0x80 >> (x & 7)
    return width, height, bytes(out)


def pdf_to_raster(
    pdf_bytes: bytes,
    dots_width: int,
    *,
    threshold: int = DEFAULT_THRESHOLD,
) -> RasterPage:
    """Render a saved-invoice PDF to a single calibrated monochrome strip.

    ``dots_width`` is the printer's printable dot width (e.g. 576 for an 80 mm
    roll at 203 dpi). Pages are scaled to that width and concatenated; the
    result is the full receipt as one continuous bitmap.
    """
    if dots_width <= 0:
        raise ValueError("dots_width must be positive")
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        strips: list[tuple[int, int, bytes]] = []
        total_h = 0
        for i in range(doc.page_count):
            pix = _scale_to_width(doc, i, dots_width)
            w, h, data = _threshold_pack(pix, threshold, dots_width)
            strips.append((w, h, data))
            total_h += h
        # All strips share the same calibrated width; concatenate vertically.
        rowbytes = (dots_width + 7) // 8
        merged = bytearray(rowbytes * total_h)
        offset = 0
        for _w, h, data in strips:
            merged[offset : offset + len(data)] = data
            offset += len(data)
        return RasterPage(width=dots_width, height=total_h, data=bytes(merged))
    finally:
        doc.close()


def escpos_raster_stream(
    page: RasterPage,
    *,
    has_cutter: bool,
    chunk: int = RASTER_CHUNK,
    feed_dots: int = 90,
) -> bytes:
    """Encode a monochrome strip as ESC/POS ``GS v 0`` raster blocks.

    Output order: initialize → raster chunks → feed → cut (if supported). The
    caller streams the returned bytes verbatim to the printer.
    """
    width = page.width
    rowbytes = (width + 7) // 8
    out = bytearray()
    out += bytes([ESC, 0x40])  # ESC @  — initialize
    for top in range(0, page.height, chunk):
        band = min(chunk, page.height - top)
        block = page.data[top * rowbytes : (top + band) * rowbytes]
        # GS v 0  m=0 (normal) xL xH yL yH  <data>
        out += bytes(
            [
                GS,
                0x76,
                0x30,
                0x00,
                rowbytes & 0xFF,
                (rowbytes >> 8) & 0xFF,
                band & 0xFF,
                (band >> 8) & 0xFF,
            ]
        )
        out += block
    # Feed and cut. ESC d feeds n * 1/8 line; GS V 66 0 = partial cut.
    out += bytes([ESC, 0x64, feed_dots & 0xFF])
    if has_cutter:
        out += bytes([GS, 0x56, 0x42, 0x00])
    return bytes(out)


def pdf_to_escpos(
    pdf_bytes: bytes,
    dots_width: int,
    *,
    has_cutter: bool,
    threshold: int = DEFAULT_THRESHOLD,
) -> bytes:
    """Convenience: PDF → calibrated raster → ESC/POS byte stream."""
    page = pdf_to_raster(pdf_bytes, dots_width, threshold=threshold)
    return escpos_raster_stream(page, has_cutter=has_cutter)

