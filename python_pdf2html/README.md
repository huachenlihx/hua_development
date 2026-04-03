# pdf2html

A command-line tool that converts any PDF — including **1 000+ page documents** — into a
**fully self-contained HTML file** with all page images embedded as base64 data URIs.
No external files, no `resources/` folder — just one `.html` file you can share, email, or open anywhere.

---

## Features

- **Single file output** — all page renders are embedded as base64 WebP data URIs directly
  inside the HTML. No separate image files, no `resources/` folder.
- **Lazy loading** — only the pages you scroll near are ever decoded by the browser.
  A 1 000-page PDF opens instantly.
- **Parallel rendering** — all CPU cores render pages simultaneously, drastically
  reducing conversion time for large files.
- **WebP images** — smaller than PNG/JPEG at the same visual quality.
- **Correct placeholders** — every page reserves its exact height before loading,
  so the scroll bar is always accurate and the layout never jumps.
- **Shimmer skeletons** — pages show an animated placeholder until the image arrives.
- **Page jump** — type a page number in the header and press Go (or Enter).
- **Keyboard navigation** — Arrow keys / PageUp / PageDown / Home / End / G.
- **Hidden text layer** — browser Ctrl+F / ⌘F search and copy-paste still work.
- **Progress bar** — terminal shows real-time rendering progress.

---

## Output structure

Given `~/Documents/report.pdf`, the tool produces a single file:

```
~/Documents/
    report.pdf      <- original (untouched)
    report.html     <- single self-contained file, open this in your browser
```

All page images are embedded inside `report.html` as base64 data URIs —
no companion files needed.

---

## Requirements

| Requirement | Version |
|-------------|---------|
| Python | 3.9+ |
| PyMuPDF (`fitz`) | >= 1.24.0 |
| Pillow | >= 10.0.0 |

---

## Setup

### 1 — Enter the project folder

```bash
cd pdf2html
```

### 2 — Create a virtual environment

```bash
python3 -m venv venv
```

### 3 — Activate it

```bash
source venv/bin/activate
```

You should see `(venv)` at the start of your prompt.

### 4 — Install dependencies

```bash
pip install -r requirements.txt
```

---

## Usage

```bash
python3 pdf2html.py <path/to/file.pdf> [options]
```

### Basic examples

```bash
# Convert a PDF in the current directory
python3 pdf2html.py report.pdf

# Convert a PDF from another location
python3 pdf2html.py ~/Downloads/invoice.pdf

# Open the result immediately (macOS)
open ~/Downloads/invoice.html
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dpi INT` | `150` | Render resolution. Higher = sharper but larger file and slower conversion. |
| `--quality INT` | `85` | WebP quality (0–100). 85 is visually lossless for most content. |
| `--workers INT` | CPU count | Number of parallel render processes. |

### Advanced examples

```bash
# Faster conversion with lower quality (good for drafts)
python3 pdf2html.py big_report.pdf --dpi 100 --quality 70

# High-quality output, limit to 4 workers
python3 pdf2html.py slides.pdf --dpi 200 --quality 90 --workers 4
```

---

## Browser keyboard shortcuts

| Key | Action |
|-----|--------|
| `Arrow Down` / `Page Down` | Next page |
| `Arrow Up` / `Page Up` | Previous page |
| `Home` | First page |
| `End` | Last page |
| `G` | Focus the "Go to page" input |
| `Enter` (in Go input) | Jump to typed page number |

---

## Performance guide

| PDF size | Recommended settings | Expected time* |
|----------|---------------------|----------------|
| < 50 pages | defaults | < 10 s |
| 50–200 pages | defaults | 10–60 s |
| 200–500 pages | `--dpi 120 --quality 75` | 1–3 min |
| 500–1 000+ pages | `--dpi 100 --quality 70` | 3–10 min |

\* On an Apple Silicon MacBook Pro with auto worker count.

> **Note on file size:** Because all images are embedded in the HTML, the output file
> will be larger than the old multi-file approach. For very large PDFs, lower `--dpi`
> and `--quality` to keep the file size manageable.

---

## Configuration

You can also edit these constants directly at the top of `pdf2html.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `DEFAULT_DPI` | `150` | Render DPI |
| `DEFAULT_QUALITY` | `85` | WebP quality |
| `DEFAULT_WORKERS` | `None` | `None` = auto (os.cpu_count()) |

---

## Deactivating the virtual environment

```bash
deactivate
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: fitz` | Run `pip install -r requirements.txt` inside the activated venv |
| `python3: command not found` | Install via `brew install python` or [python.org](https://www.python.org/downloads/) |
| HTML looks blank | Make sure you are opening the `.html` file directly in a browser, not a text editor |
| Very large HTML file | Lower `--dpi` to `100` and `--quality` to `70` |
| Conversion is slow | Reduce `--dpi` and/or `--workers` |
| Pages appear in wrong order | This is a PyMuPDF bug with some encrypted PDFs — try decrypting with `qpdf` first |

---

## License

MIT — do whatever you like with it.
