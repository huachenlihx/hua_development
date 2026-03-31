#!/usr/bin/env python3
"""
pdf2md.py — Convert a PDF file to a Markdown file
==================================================

Features
--------
- Preserves headings (H1/H2/H3) via font-size ratio heuristics
- Preserves bold and italic text via font-name heuristics
- Preserves ordered and unordered lists (indent + bullet/number detection)
- Converts tables to GFM (GitHub Flavoured Markdown) tables
- Extracts hyperlinks (URI annotations) → [text](url) Markdown syntax
- Extracts embedded images at NATIVE resolution:
    • JPEG  (DCTDecode)   → saved as .jpg  (raw byte copy, zero re-encoding loss)
    • JPEG2000 (JPXDecode) → saved as .jp2 (raw byte copy)
    • Everything else     → reconstructed via Pillow and saved as .png (lossless)
- Streams pages one-by-one and writes the .md file incrementally —
  safe for very large PDFs (never loads the whole document into RAM)
- Releases memory every CHUNK_SIZE pages via gc.collect()

Usage
-----
    python pdf2md.py /path/to/file.pdf
    python pdf2md.py /path/to/file.pdf --no-images
    python pdf2md.py /path/to/file.pdf --chunk-size 10
    python pdf2md.py /path/to/file.pdf --verbose
"""

from __future__ import annotations

import argparse
import gc
import io
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_CHUNK_SIZE = 20     # pages per gc cycle; tune down for very-low-RAM machines
MIN_IMG_PX         = 8      # skip images smaller than this in either dimension

# Bullet characters commonly embedded in PDFs
BULLET_CHARS = set("•·‣▸▹►▻◦‐–—*-")

# Ordered-list prefix patterns: "1.", "1)", "(1)", "a.", "a)"
ORDERED_RE = re.compile(r'^(\(?[0-9]+[.)]\)?|[a-zA-Z][.)]) ')

# Plain-URL pattern for bare URLs appearing as text
URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────────────
# Small utilities
# ──────────────────────────────────────────────────────────────────────────────

def safe_filename(name: str) -> str:
    """Strip characters that are illegal in file names (cross-platform)."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def heading_prefix(font_size: float, body_size: float) -> Optional[str]:
    """Return '# ', '## ', '### ' or None based on the font-size ratio."""
    if body_size <= 0:
        return None
    r = font_size / body_size
    if r >= 1.8:
        return "# "
    if r >= 1.4:
        return "## "
    if r >= 1.15:
        return "### "
    return None


def gfm_table(rows: list[list]) -> str:
    """Convert a list-of-lists table to a GitHub-Flavoured Markdown table."""
    if not rows:
        return ""

    def cell(v) -> str:
        if v is None:
            return ""
        return str(v).replace("\n", " ").replace("|", "\\|").strip()

    norm  = [[cell(c) for c in row] for row in rows]
    width = max(len(r) for r in norm)
    norm  = [r + [""] * (width - len(r)) for r in norm]   # pad short rows

    lines = [
        "| " + " | ".join(norm[0])         + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in norm[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Link extraction from the pypdf annotation layer
# ──────────────────────────────────────────────────────────────────────────────

def extract_page_links(pypdf_page) -> list[dict]:
    """
    Return [{'url': str, 'rect': (x0, y0, x1, y1)}, …] for every URI annotation.
    Coordinates are in PDF user space (origin = bottom-left).
    """
    result: list[dict] = []
    try:
        annots = pypdf_page.get("/Annots")
        if annots is None:
            return result
        for ref in annots:
            try:
                obj = ref.get_object()
            except Exception:
                continue
            if obj.get("/Subtype") != "/Link":
                continue
            action = obj.get("/A")
            if action is None:
                continue
            if action.get("/S") != "/URI":
                continue
            uri = str(action.get("/URI", "")).strip()
            if not uri:
                continue
            rect_raw = obj.get("/Rect")
            if rect_raw is None:
                continue
            result.append({"url": uri, "rect": tuple(float(v) for v in rect_raw)})
    except Exception as exc:
        log.debug(f"  Annotation parse error: {exc}")
    return result


def pdf_to_plumber_rect(pdf_rect: tuple, page_height: float) -> tuple:
    """
    Convert a PDF annotation rect (origin bottom-left) to
    pdfplumber coordinate space (origin top-left).
    Input:  (x0, y0, x1, y1)
    Output: (x0, top, x1, bottom)
    """
    x0, y0, x1, y1 = pdf_rect
    return (x0, page_height - y1, x1, page_height - y0)


def find_url_for_word(word: dict, link_rects: list[tuple]) -> Optional[str]:
    """Return the URL if the word's bounding box overlaps a link annotation rect."""
    wx0, wt, wx1, wb = word["x0"], word["top"], word["x1"], word["bottom"]
    for (lx0, lt, lx1, lb), url in link_rects:
        if wx0 < lx1 + 4 and wx1 > lx0 - 4 and wt < lb + 4 and wb > lt - 4:
            return url
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Image extraction
# ──────────────────────────────────────────────────────────────────────────────

def extract_images_from_page(
    pypdf_page,
    page_num: int,
    out_dir: Path,
    stem: str,
) -> list[str]:
    """
    Extract all embedded images from one page at their native resolution.
    Returns a list of saved filenames relative to out_dir.

    Strategy
    --------
    - DCT (JPEG) → raw byte copy → .jpg   (zero quality loss)
    - JPX (JPEG 2000) → raw byte copy → .jp2
    - All others → reconstruct pixels via Pillow → .png (lossless, fast compress)
    """
    from PIL import Image

    saved: list[str] = []

    try:
        resources = pypdf_page.get("/Resources")
        if not resources:
            return saved
        xobjects = resources.get("/XObject")
        if not xobjects:
            return saved
    except Exception:
        return saved

    idx = 0
    for name in xobjects:
        try:
            xobj = xobjects[name].get_object()
            if xobj.get("/Subtype") != "/Image":
                idx += 1
                continue

            w = int(xobj.get("/Width",  0))
            h = int(xobj.get("/Height", 0))
            if w < MIN_IMG_PX or h < MIN_IMG_PX:
                idx += 1
                continue

            raw = xobj.get_data()

            # Normalise /Filter to a plain string
            filt     = xobj.get("/Filter")
            filt_str = ""
            if filt is not None:
                if hasattr(filt, "__iter__") and not isinstance(filt, str):
                    filt_str = " ".join(str(f) for f in filt)
                else:
                    filt_str = str(filt)

            if "DCTDecode" in filt_str:
                fname = f"{stem}_p{page_num:04d}_{idx:03d}.jpg"
                (out_dir / fname).write_bytes(raw)

            elif "JPXDecode" in filt_str:
                fname = f"{stem}_p{page_num:04d}_{idx:03d}.jp2"
                (out_dir / fname).write_bytes(raw)

            else:
                # Determine PIL colour mode
                cs   = str(xobj.get("/ColorSpace", ""))
                mode = ("L"    if ("Gray" in cs or cs == "/DeviceGray") else
                        "CMYK" if ("CMYK" in cs or cs == "/DeviceCMYK") else
                        "RGB")
                try:
                    img = Image.frombytes(mode, (w, h), raw)
                except Exception:
                    # Last resort: let Pillow sniff the format from raw bytes
                    img = Image.open(io.BytesIO(raw))

                if img.mode == "CMYK":
                    img = img.convert("RGB")

                fname = f"{stem}_p{page_num:04d}_{idx:03d}.png"
                # compress_level=1 → fast write, still fully lossless
                img.save(out_dir / fname, format="PNG", compress_level=1)

            saved.append(fname)
            log.debug(f"  Saved: {fname}  ({w}×{h}px)")

        except Exception as exc:
            log.debug(f"  Skipped image {name} on page {page_num}: {exc}")

        idx += 1

    return saved


# ──────────────────────────────────────────────────────────────────────────────
# Body-font-size estimation
# ──────────────────────────────────────────────────────────────────────────────

def estimate_body_size(plumber_pdf, sample: int = 5) -> float:
    """
    Sample up to `sample` pages and return the most common rounded font size.
    This is the baseline used by heading_prefix() for H1/H2/H3 detection.
    """
    counter: Counter = Counter()
    n = min(sample, len(plumber_pdf.pages))
    for i in range(n):
        try:
            for w in plumber_pdf.pages[i].extract_words(extra_attrs=["size"]):
                s = w.get("size")
                if s and s > 0:
                    counter[round(float(s))] += 1
        except Exception:
            pass
    return float(counter.most_common(1)[0][0]) if counter else 12.0


# ──────────────────────────────────────────────────────────────────────────────
# List-item detection
# ──────────────────────────────────────────────────────────────────────────────

def detect_list_item(text: str, x0: float, page_width: float) -> tuple[Optional[str], str]:
    """
    Detect whether a line is a list item.
    Returns (marker_md, body_text) or (None, original_text).
    """
    stripped = text.strip()
    if not stripped:
        return None, text

    # Two-space indent for lines starting well inside the left margin
    indent = "  " if (page_width > 0 and x0 / page_width > 0.12) else ""

    if stripped[0] in BULLET_CHARS:
        return f"{indent}- ", stripped[1:].strip()

    m = ORDERED_RE.match(stripped)
    if m:
        return f"{indent}1. ", stripped[len(m.group(0)):].strip()

    return None, text


# ──────────────────────────────────────────────────────────────────────────────
# Per-page conversion
# ──────────────────────────────────────────────────────────────────────────────

def convert_page(
    pl_page,
    pypdf_page,
    page_num: int,
    out_dir: Path,
    stem: str,
    body_size: float,
    do_images: bool,
) -> str:
    """Convert one page to a Markdown string."""
    parts: list[str] = []

    page_h = float(pl_page.height)
    page_w = float(pl_page.width)

    # ── 1. Link annotations (convert once to pdfplumber coord space) ──────────
    raw_links  = extract_page_links(pypdf_page)
    link_rects = [
        (pdf_to_plumber_rect(lk["rect"], page_h), lk["url"])
        for lk in raw_links
    ]
    seen_urls: set[str] = set()

    # ── 2. Table bounding boxes (we skip these words in the text flow) ─────────
    table_bboxes: list[tuple] = []
    try:
        for t in pl_page.find_tables():
            table_bboxes.append(t.bbox)    # (x0, top, x1, bottom)
    except Exception:
        pass

    def in_table(w: dict) -> bool:
        wx0, wt, wx1, wb = w["x0"], w["top"], w["x1"], w["bottom"]
        for tx0, tt, tx1, tb in table_bboxes:
            if wx0 >= tx0 - 2 and wx1 <= tx1 + 2 and wt >= tt - 2 and wb <= tb + 2:
                return True
        return False

    # ── 3. Words with font metadata ────────────────────────────────────────────
    try:
        words = pl_page.extract_words(
            x_tolerance=3,
            y_tolerance=3,
            keep_blank_chars=False,
            use_text_flow=True,
            extra_attrs=["size", "fontname"],
        )
    except Exception:
        words = []

    # Group non-table words into visual lines (4-pt vertical bucket)
    buckets: dict[int, list] = {}
    for w in words:
        if in_table(w):
            continue
        key = round(w["top"] / 4) * 4
        buckets.setdefault(key, []).append(w)

    # ── 4. Build text Markdown ─────────────────────────────────────────────────
    text_lines: list[str] = []

    for key in sorted(buckets):
        group = sorted(buckets[key], key=lambda w: w["x0"])
        if not group:
            continue

        sizes     = [w.get("size") or body_size for w in group]
        line_size = sum(sizes) / len(sizes)
        x0_line   = group[0]["x0"]

        # Assemble tokens, grouping link-annotated words into [text](url) spans
        tokens: list[str]         = []
        link_buf: list[str]       = []
        active_url: Optional[str] = None

        def flush_link_buf() -> None:
            nonlocal active_url
            if active_url and link_buf:
                joined = " ".join(link_buf).strip()
                tokens.append(f"[{joined}]({active_url})")
                seen_urls.add(active_url)
                link_buf.clear()
            active_url = None

        for w in group:
            wtext = w["text"]
            url   = find_url_for_word(w, link_rects)

            # Catch bare URLs typed as plain text (e.g. "https://example.com")
            if not url and URL_RE.fullmatch(wtext):
                url = wtext

            if url:
                if url != active_url:
                    flush_link_buf()
                    active_url = url
                link_buf.append(wtext)
            else:
                flush_link_buf()
                tokens.append(wtext)

        flush_link_buf()

        line_text = " ".join(tokens).strip()
        if not line_text:
            continue

        # Heading?
        h_pfx = heading_prefix(line_size, body_size)
        if h_pfx:
            text_lines.append(f"\n{h_pfx}{line_text}\n")
            continue

        # List item?
        marker, body_text = detect_list_item(line_text, x0_line, page_w)
        if marker:
            text_lines.append(f"{marker}{body_text}")
            continue

        # Bold / italic from font name
        fontnames  = [w.get("fontname", "") for w in group]
        is_bold    = any("Bold"   in fn for fn in fontnames)
        is_italic  = any("Italic" in fn or "Oblique" in fn for fn in fontnames)

        if is_bold and is_italic:
            text_lines.append(f"***{line_text}***")
        elif is_bold:
            text_lines.append(f"**{line_text}**")
        elif is_italic:
            text_lines.append(f"*{line_text}*")
        else:
            text_lines.append(line_text)

    if text_lines:
        parts.append("\n".join(text_lines))

    # ── 5. Tables ──────────────────────────────────────────────────────────────
    try:
        for tbl in pl_page.extract_tables() or []:
            if tbl:
                parts.append("\n" + gfm_table(tbl) + "\n")
    except Exception as exc:
        log.debug(f"  Table error page {page_num}: {exc}")

    # ── 6. Images ──────────────────────────────────────────────────────────────
    if do_images:
        try:
            for fname in extract_images_from_page(pypdf_page, page_num, out_dir, stem):
                parts.append(f"\n![image]({fname})\n")
        except Exception as exc:
            log.warning(f"  Image extraction failed on page {page_num}: {exc}")

    # ── 7. Orphan links (annotations whose text was not captured in word flow) ─
    for _, url in link_rects:
        if url not in seen_urls:
            parts.append(f"\n<{url}>\n")
            seen_urls.add(url)

    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# Main driver
# ──────────────────────────────────────────────────────────────────────────────

def convert(
    pdf_path: str,
    do_images: bool = True,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    """
    Convert a PDF file to Markdown.

    Pages are processed one at a time and written to the output file
    incrementally, so even very large PDFs are handled without loading
    the whole document into RAM.
    """
    try:
        import pdfplumber
        from pypdf import PdfReader
    except ImportError as exc:
        log.error(f"Missing dependency: {exc}\nRun:  pip install -r requirements.txt")
        sys.exit(1)

    src = Path(pdf_path).resolve()
    if not src.exists():
        log.error(f"File not found: {src}")
        sys.exit(1)

    out_dir = src.parent
    stem    = safe_filename(src.stem)
    md_path = out_dir / f"{stem}.md"

    log.info(f"Input      : {src}")
    log.info(f"Output     : {md_path}")
    log.info(f"Images     : {'enabled' if do_images else 'disabled'}")
    log.info(f"Chunk size : {chunk_size} pages per GC cycle")

    with pdfplumber.open(str(src)) as pl_pdf:
        reader    = PdfReader(str(src))
        total     = len(pl_pdf.pages)
        body_size = estimate_body_size(pl_pdf)

        log.info(f"Total pages: {total}")
        log.info(f"Body font  : {body_size:.1f}pt (estimated)")

        with open(md_path, "w", encoding="utf-8") as out:
            # Write document title (prefer PDF metadata, fall back to filename)
            title = src.stem
            try:
                meta = reader.metadata
                if meta and getattr(meta, "title", None):
                    title = meta.title.strip()
            except Exception:
                pass
            out.write(f"# {title}\n\n")

            for chunk_start in range(0, total, chunk_size):
                chunk_end = min(chunk_start + chunk_size, total)
                log.info(f"  Pages {chunk_start + 1}–{chunk_end} / {total} …")

                for i in range(chunk_start, chunk_end):
                    try:
                        md_chunk = convert_page(
                            pl_page    = pl_pdf.pages[i],
                            pypdf_page = reader.pages[i],
                            page_num   = i + 1,
                            out_dir    = out_dir,
                            stem       = stem,
                            body_size  = body_size,
                            do_images  = do_images,
                        )
                    except Exception as exc:
                        log.warning(f"  Page {i + 1} failed: {exc}")
                        md_chunk = f"\n<!-- page {i + 1} could not be parsed -->\n"

                    out.write(md_chunk)
                    out.write("\n\n")
                    out.flush()          # partial output always on disk

                gc.collect()             # release page objects after each chunk

    log.info(f"Done → {md_path}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a PDF file to Markdown, preserving structure and extracting images.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pdf",
        help="Path to the input PDF file",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip image extraction (faster for text-only PDFs)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        metavar="N",
        help=(
            f"Pages processed per memory-release cycle (default: {DEFAULT_CHUNK_SIZE}). "
            "Lower this (e.g. --chunk-size 5) for very large PDFs on low-RAM machines."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging (shows per-image details, etc.)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    convert(
        pdf_path   = args.pdf,
        do_images  = not args.no_images,
        chunk_size = args.chunk_size,
    )


if __name__ == "__main__":
    main()
