"""PDF/image preparation for the vision model.

Rasterises PDF pages to images at a configurable DPI (default 220), normalises
loose image files (.png/.jpg/.jpeg) the same way, and applies a light deskew
(~1 degree) so faint scanned invoices read cleanly. Deskew and auto-rotate use
numpy only (no opencv dependency); if a page is already straight they are no-ops.

Output is a list of PIL RGB images plus a base64-PNG helper for the API payload.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

log = logging.getLogger(__name__)

_PDF_EXTS = {".pdf"}
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def rasterise_pdf(path: Path, dpi: int = 220) -> list[Image.Image]:
    """Render every page of a PDF to an RGB PIL image at ``dpi``."""
    scale = dpi / 72.0  # PDF user space is 72 dpi
    pdf = pdfium.PdfDocument(str(path))
    try:
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=scale)
            pages.append(bitmap.to_pil().convert("RGB"))
        return pages
    finally:
        pdf.close()


def load_image(path: Path) -> list[Image.Image]:
    """Load a single loose image file as one RGB page."""
    return [Image.open(path).convert("RGB")]


def _estimate_skew(img: Image.Image, max_angle: float = 5.0) -> float:
    """Estimate skew via a horizontal-projection variance search.

    Text rows produce sharp peaks in the row-sum profile when the page is level;
    the angle that maximises that sharpness is the skew. Returns degrees in
    [-max_angle, max_angle]. Cheap and opencv-free.
    """
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    # Binarise to ink=1 on a downscaled copy for speed.
    small = Image.fromarray(gray).resize(
        (max(1, gray.shape[1] // 4), max(1, gray.shape[0] // 4))
    )
    arr = np.asarray(small, dtype=np.float32)
    ink = (arr < arr.mean()).astype(np.float32)

    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + 0.25, 0.25):
        rotated = np.asarray(
            Image.fromarray((ink * 255).astype(np.uint8)).rotate(
                angle, resample=Image.BILINEAR, fillcolor=0
            ),
            dtype=np.float32,
        )
        profile = rotated.sum(axis=1)
        score = float(np.var(profile))  # sharper row peaks -> higher variance
        if score > best_score:
            best_score, best_angle = score, float(angle)
    return best_angle


def deskew(img: Image.Image, max_angle: float = 5.0) -> Image.Image:
    """Rotate an image to level its text lines (skip if already ~straight)."""
    angle = _estimate_skew(img, max_angle=max_angle)
    if abs(angle) < 0.25:
        return img
    log.info("deskewing %.2f deg", angle)
    return img.rotate(angle, resample=Image.BICUBIC, fillcolor=(255, 255, 255),
                      expand=True)


def cap_size(img: Image.Image, max_edge: int = 1600) -> Image.Image:
    """Downscale so the longest edge is <= max_edge. Keeps the vision payload
    under the API's per-image limit (~5MB / 1568px) without hurting legibility;
    upscaling is never done."""
    w, h = img.size
    longest = max(w, h)
    if longest <= max_edge:
        return img
    scale = max_edge / longest
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                      resample=Image.LANCZOS)


def prepare(path: str | Path, dpi: int = 220, do_deskew: bool = True,
            max_edge: int = 1600) -> list[Image.Image]:
    """Turn any supported invoice file into a list of clean RGB page images,
    downscaled to stay within the vision API's per-image limit."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in _PDF_EXTS:
        pages = rasterise_pdf(p, dpi=dpi)
    elif ext in _IMG_EXTS:
        pages = load_image(p)
    else:
        raise ValueError(f"unsupported invoice file type: {ext} ({p.name})")

    if do_deskew:
        pages = [deskew(pg) for pg in pages]
    if max_edge:
        pages = [cap_size(pg, max_edge=max_edge) for pg in pages]
    return pages


def to_base64_png(img: Image.Image) -> str:
    """Encode an image as base64 PNG for the Anthropic image content block."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")
