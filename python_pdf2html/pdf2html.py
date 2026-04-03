#!/usr/bin/env python3
"""
pdf2html.py — Convert a PDF file to a fully self-contained single HTML file.

All pages are rendered to WebP and embedded as base64 data URIs directly
inside the HTML — no external resources folder, no separate image files.
The output is a single .html file you can share, email, or open anywhere.

Usage:
    python3 pdf2html.py <path/to/file.pdf> [options]

Options:
    --dpi INT        Render resolution (default: 150)
    --quality INT    WebP quality 0-100 (default: 85)
    --workers INT    Parallel render workers (default: CPU count)

Output:
    <same folder as PDF>/
        <filename>.html    <- single self-contained file, no dependencies
"""

import argparse
import base64
import concurrent.futures
import json
import sys
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


# ---------------------------------------------------------------------------
# Config defaults (overridable via CLI)
# ---------------------------------------------------------------------------
DEFAULT_DPI     = 150
DEFAULT_QUALITY = 85
DEFAULT_WORKERS = None   # None -> os.cpu_count()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pixmap_to_webp_bytes(pix: fitz.Pixmap, quality: int) -> bytes:
    """Pixmap -> in-memory WebP bytes (no temp file)."""
    if pix.n - pix.alpha > 3:           # CMYK / exotic colour space
        pix = fitz.Pixmap(fitz.csRGB, pix)
    png = pix.tobytes("png")
    img = Image.open(BytesIO(png))
    img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
    buf = BytesIO()
    img.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def webp_bytes_to_data_uri(data: bytes) -> str:
    """Convert raw WebP bytes to a base64 data URI string."""
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/webp;base64,{b64}"


# ---------------------------------------------------------------------------
# Worker function — must be top-level for multiprocessing pickling
# ---------------------------------------------------------------------------

def _render_page_worker(args: tuple) -> tuple:
    """
    Render one page to WebP bytes in memory.
    Returns (page_index, width_px, height_px, webp_bytes).
    """
    pdf_path_str, page_index, dpi, quality = args
    doc  = fitz.open(pdf_path_str)
    page = doc[page_index]
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    pix  = page.get_pixmap(matrix=mat, alpha=False)
    w, h = pix.width, pix.height
    data = pixmap_to_webp_bytes(pix, quality)
    doc.close()
    return page_index, w, h, data


# ---------------------------------------------------------------------------
# Parallel page rendering — returns base64 data URIs, no disk writes
# ---------------------------------------------------------------------------

def render_pages_parallel(
    pdf_path: Path,
    total_pages: int,
    dpi: int,
    quality: int,
    workers,
) -> list:
    """
    Render all pages in parallel.
    Returns list of {src, width, height} dicts where src is a base64 data URI.
    """
    tasks = [
        (str(pdf_path), i, dpi, quality)
        for i in range(total_pages)
    ]

    results = [None] * total_pages

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_render_page_worker, t): idx for idx, t in enumerate(tasks)}
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            page_index, w, h, data = fut.result()
            results[page_index] = {
                "src":    webp_bytes_to_data_uri(data),
                "width":  w,
                "height": h,
            }
            done += 1
            _progress("Rendering pages", done, total_pages)

    print()   # newline after progress bar
    return results


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_texts(doc: fitz.Document) -> list:
    texts = []
    total = len(doc)
    for i, page in enumerate(doc):
        texts.append(page.get_text("text"))
        _progress("Extracting text", i + 1, total)
    print()
    return texts


# ---------------------------------------------------------------------------
# Terminal progress bar
# ---------------------------------------------------------------------------

def _progress(label: str, done: int, total: int) -> None:
    bar_w  = 30
    filled = int(bar_w * done / total)
    bar    = "#" * filled + "." * (bar_w - filled)
    pct    = 100 * done // total
    print(f"\r  {label}: [{bar}] {pct:3d}%  {done}/{total}", end="", flush=True)


# ---------------------------------------------------------------------------
# HTML generation — all images are embedded as base64 data URIs
# ---------------------------------------------------------------------------

def build_html(
    pdf_path: Path,
    page_meta: list,
    page_texts: list,
    output_html: Path,
) -> None:
    title = pdf_path.stem
    total = len(page_meta)

    # Build manifest — src is already a data URI, no relative path needed
    manifest = [
        {
            "src": m["src"],
            "w":   m["width"],
            "h":   m["height"],
            "text": (
                page_texts[i]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            ) if i < len(page_texts) else "",
        }
        for i, m in enumerate(page_meta)
    ]
    manifest_json = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: #525659;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: #e8e8e8;
    }}

    /* Header */
    header {{
      position: sticky;
      top: 0;
      z-index: 200;
      display: flex;
      align-items: center;
      gap: .75rem;
      padding: .5rem 1rem;
      background: #2b2d30;
      box-shadow: 0 2px 8px rgba(0,0,0,.5);
      flex-wrap: wrap;
    }}
    header h1 {{
      font-size: .95rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      flex: 1;
      min-width: 0;
    }}
    .page-counter {{
      font-size: .82rem;
      opacity: .65;
      white-space: nowrap;
    }}
    .jump-form {{
      display: flex;
      align-items: center;
      gap: .4rem;
    }}
    .jump-form label {{ font-size: .8rem; opacity: .65; }}
    .jump-form input {{
      width: 4.5rem;
      padding: .25rem .4rem;
      border: 1px solid #555;
      border-radius: 4px;
      background: #3c3f41;
      color: #e8e8e8;
      font-size: .82rem;
      text-align: center;
    }}
    .jump-form button {{
      padding: .25rem .65rem;
      border: none;
      border-radius: 4px;
      background: #4a90d9;
      color: #fff;
      font-size: .82rem;
      cursor: pointer;
    }}
    .jump-form button:hover {{ background: #357abd; }}
    .kb-hint {{
      font-size: .7rem;
      opacity: .4;
      white-space: nowrap;
    }}

    /* Top load-progress bar */
    #load-bar-wrap {{
      position: fixed;
      top: 0; left: 0; right: 0;
      height: 3px;
      z-index: 300;
      pointer-events: none;
    }}
    #load-bar {{
      height: 100%;
      width: 0%;
      background: #4a90d9;
      transition: width .15s ease;
    }}

    /* Main scroll area */
    main {{
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 1.5rem .75rem;
      gap: 1.5rem;
    }}

    /* Page card */
    .page {{
      position: relative;
      background: #fff;
      box-shadow: 0 4px 18px rgba(0,0,0,.55);
      border-radius: 2px;
      max-width: 960px;
      width: 100%;
      overflow: hidden;
    }}
    .page-inner {{
      position: relative;
      width: 100%;
    }}
    .page-spacer {{
      display: block;
      width: 100%;
    }}
    .page-img {{
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      object-fit: cover;
      display: block;
      opacity: 0;
      transition: opacity .25s ease;
    }}
    .page-img.loaded {{ opacity: 1; }}

    /* Shimmer skeleton while page loads */
    .page-skeleton {{
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, #e0e0e0 25%, #f0f0f0 50%, #e0e0e0 75%);
      background-size: 200% 100%;
      animation: shimmer 1.4s infinite;
    }}
    .page-img.loaded ~ .page-skeleton {{ display: none; }}
    @keyframes shimmer {{
      0%   {{ background-position: 200% 0; }}
      100% {{ background-position: -200% 0; }}
    }}

    /* Page number badge */
    .page-badge {{
      position: absolute;
      bottom: .45rem;
      right: .6rem;
      background: rgba(0,0,0,.52);
      color: #fff;
      font-size: .68rem;
      padding: .12rem .4rem;
      border-radius: 3px;
      pointer-events: none;
      user-select: none;
      z-index: 10;
    }}

    /* Hidden text layer for Ctrl+F / copy-paste */
    .page-text {{
      position: absolute;
      inset: 0;
      overflow: hidden;
      opacity: 0;
      pointer-events: none;
      font-size: 1px;
      white-space: pre-wrap;
      word-break: break-all;
      color: transparent;
    }}

    footer {{
      text-align: center;
      padding: 2rem 1rem 3rem;
      font-size: .78rem;
      opacity: .45;
    }}
  </style>
</head>
<body>

<div id="load-bar-wrap"><div id="load-bar"></div></div>

<header>
  <h1>&#128196; {title}</h1>
  <span class="page-counter" id="page-counter">&#8212; / {total}</span>
  <div class="jump-form">
    <label for="jump-input">Go to</label>
    <input id="jump-input" type="number" min="1" max="{total}" placeholder="page #" />
    <button onclick="jumpToPage()">Go</button>
  </div>
  <span class="kb-hint">Arrow keys: prev/next &nbsp;|&nbsp; G: go to page &nbsp;|&nbsp; Home/End: first/last</span>
</header>

<main id="main"></main>

<footer>
  Converted from <strong>{pdf_path.name}</strong> &nbsp;&middot;&nbsp; {total} pages
  &nbsp;&middot;&nbsp; self-contained (no external files)
</footer>

<script>
(function () {{
  'use strict';

  var PAGES = {manifest_json};
  var TOTAL = PAGES.length;
  var loadedCount = 0;
  var currentPage = 1;

  var main = document.getElementById('main');
  var frag = document.createDocumentFragment();

  for (var i = 0; i < TOTAL; i++) {{
    var p = PAGES[i];
    var pageNum = i + 1;

    var section = document.createElement('section');
    section.className = 'page';
    section.id = 'page-' + pageNum;
    section.dataset.index = i;

    var inner = document.createElement('div');
    inner.className = 'page-inner';

    // Transparent spacer holds aspect ratio before the image fades in
    var spacer = document.createElement('img');
    spacer.className = 'page-spacer';
    spacer.alt = '';
    spacer.width = p.w;
    spacer.height = p.h;
    spacer.style.aspectRatio = p.w + ' / ' + p.h;
    spacer.src = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==';

    var img = document.createElement('img');
    img.className = 'page-img';
    img.alt = 'Page ' + pageNum;
    img.decoding = 'async';
    // src is set by the IntersectionObserver below (lazy load from data URI)

    img.addEventListener('load', (function(im) {{
      return function() {{
        im.classList.add('loaded');
        loadedCount++;
        updateLoadBar();
      }};
    }})(img));

    var skeleton = document.createElement('div');
    skeleton.className = 'page-skeleton';

    var badge = document.createElement('div');
    badge.className = 'page-badge';
    badge.textContent = pageNum + ' / ' + TOTAL;

    var textLayer = document.createElement('div');
    textLayer.className = 'page-text';
    textLayer.textContent = p.text;
    textLayer.setAttribute('aria-hidden', 'true');

    inner.appendChild(spacer);
    inner.appendChild(img);
    inner.appendChild(skeleton);
    inner.appendChild(badge);
    inner.appendChild(textLayer);
    section.appendChild(inner);
    frag.appendChild(section);
  }}

  main.appendChild(frag);

  // Lazy-load: assign the data URI only when the page scrolls into view
  var io = new IntersectionObserver(function(entries) {{
    entries.forEach(function(entry) {{
      if (!entry.isIntersecting) return;
      var section = entry.target;
      var img = section.querySelector('.page-img');
      if (img && !img.src) {{
        var idx = parseInt(section.dataset.index, 10);
        img.src = PAGES[idx].src;   // data URI — no network request
      }}
      io.unobserve(section);
    }});
  }}, {{ root: null, rootMargin: '200% 0px', threshold: 0 }});

  document.querySelectorAll('.page').forEach(function(el) {{ io.observe(el); }});

  // Load-progress bar
  var loadBar = document.getElementById('load-bar');
  function updateLoadBar() {{
    var pct = (loadedCount / TOTAL) * 100;
    loadBar.style.width = pct + '%';
    if (loadedCount >= TOTAL) {{
      setTimeout(function() {{ loadBar.parentElement.style.opacity = '0'; }}, 600);
    }}
  }}

  // Current-page tracker
  var pageCounter = document.getElementById('page-counter');
  var pageIO = new IntersectionObserver(function(entries) {{
    entries.forEach(function(entry) {{
      if (!entry.isIntersecting) return;
      var n = parseInt(entry.target.id.replace('page-', ''), 10);
      currentPage = n;
      pageCounter.textContent = n + ' / ' + TOTAL;
    }});
  }}, {{ root: null, rootMargin: '-45% 0px -45% 0px', threshold: 0 }});

  document.querySelectorAll('.page').forEach(function(el) {{ pageIO.observe(el); }});

  // Jump to page
  window.jumpToPage = function() {{
    var input = document.getElementById('jump-input');
    var n = Math.max(1, Math.min(TOTAL, parseInt(input.value, 10) || 1));
    var el = document.getElementById('page-' + n);
    if (el) {{
      el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      var img = el.querySelector('.page-img');
      if (img && !img.src) img.src = PAGES[n - 1].src;
    }}
    input.value = '';
  }};

  document.getElementById('jump-input').addEventListener('keydown', function(e) {{
    if (e.key === 'Enter') jumpToPage();
  }});

  // Keyboard shortcuts
  document.addEventListener('keydown', function(e) {{
    if (document.activeElement === document.getElementById('jump-input')) return;
    switch (e.key) {{
      case 'ArrowDown':
      case 'PageDown':
        e.preventDefault();
        document.getElementById('page-' + Math.min(currentPage + 1, TOTAL))
          ?.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        break;
      case 'ArrowUp':
      case 'PageUp':
        e.preventDefault();
        document.getElementById('page-' + Math.max(currentPage - 1, 1))
          ?.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        break;
      case 'g':
      case 'G':
        document.getElementById('jump-input')?.focus();
        break;
      case 'Home':
        document.getElementById('page-1')?.scrollIntoView({{ behavior: 'smooth' }});
        break;
      case 'End':
        document.getElementById('page-' + TOTAL)?.scrollIntoView({{ behavior: 'smooth' }});
        break;
    }}
  }});

}})();
</script>
</body>
</html>
"""
    output_html.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def convert(pdf_path_str, dpi, quality, workers):
    pdf_path = Path(pdf_path_str).expanduser().resolve()

    if not pdf_path.exists():
        sys.exit(f"ERROR: File not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        sys.exit(f"ERROR: Not a PDF file: {pdf_path}")

    output_html = pdf_path.parent / (pdf_path.stem + ".html")

    print(f"\n  PDF     : {pdf_path.name}")
    print(f"  Output  : {output_html}")
    print(f"  Mode    : self-contained (base64 embedded images)")
    print(f"  DPI={dpi}  quality={quality}  workers={'auto' if workers is None else workers}\n")

    print("Opening PDF ...")
    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    print(f"  {total_pages:,} page(s) detected\n")

    print("Extracting text ...")
    page_texts = extract_texts(doc)
    doc.close()   # close before parallel render (workers open their own handles)

    print("Rendering pages -> WebP (in memory) ...")
    page_meta = render_pages_parallel(pdf_path, total_pages, dpi, quality, workers)

    print("Building self-contained HTML ...")
    build_html(pdf_path, page_meta, page_texts, output_html)

    size_mb = output_html.stat().st_size / 1_048_576
    print(f"\nDone! -> {output_html}  ({size_mb:.1f} MB)")
    print(f"Open with:  open \"{output_html}\"\n")


def main():
    parser = argparse.ArgumentParser(
        description="Convert a PDF to a fully self-contained HTML file (base64 embedded images).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("pdf",         help="Path to the input PDF file")
    parser.add_argument("--dpi",       type=int, default=DEFAULT_DPI,     help="Render resolution")
    parser.add_argument("--quality",   type=int, default=DEFAULT_QUALITY, help="WebP quality 0-100")
    parser.add_argument("--workers",   type=int, default=None,            help="Parallel workers (default: CPU count)")
    args = parser.parse_args()

    convert(args.pdf, args.dpi, args.quality, args.workers)


if __name__ == "__main__":
    main()
