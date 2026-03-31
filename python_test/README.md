# pdf2md — PDF to Markdown Converter

Convert any PDF to a well-structured Markdown file, preserving formatting and extracting all images at their highest native resolution.

## Features

| Feature | Detail |
|---|---|
| **Headings** | H1 / H2 / H3 inferred from font-size ratios |
| **Bold / Italic** | Detected via font-name metadata |
| **Lists** | Ordered (`1.`) and unordered (`-`) lists, with two-level indent |
| **Tables** | Rendered as GFM (GitHub Flavoured Markdown) tables |
| **Hyperlinks** | PDF URI annotations become `[text](url)` links |
| **Images** | Saved at native resolution alongside the Markdown file |
| **Large PDFs** | Streamed page-by-page; never loads the whole file into RAM |

### Image format strategy

| PDF encoding | Saved as | Quality |
|---|---|---|
| JPEG (DCTDecode) | `.jpg` | Byte-exact copy — zero re-encoding loss |
| JPEG 2000 (JPXDecode) | `.jp2` | Byte-exact copy |
| All others (raw, deflate, etc.) | `.png` | Lossless via Pillow |

## Requirements

- Python 3.9 or later
- Dependencies listed in `requirements.txt`

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Basic conversion
python pdf2md.py /path/to/document.pdf

# Skip image extraction (faster for text-only PDFs)
python pdf2md.py /path/to/document.pdf --no-images

# Reduce memory usage on very large PDFs (process 5 pages per cycle)
python pdf2md.py /path/to/document.pdf --chunk-size 5

# Verbose output (shows per-image details)
python pdf2md.py /path/to/document.pdf --verbose
```

## Output

All output files are placed **in the same folder as the input PDF**:

```
/your/folder/
  document.pdf          ← input
  document.md           ← Markdown output (same name as PDF)
  document_p0001_000.jpg  ← images extracted from page 1
  document_p0001_001.png
  document_p0002_000.jpg
  ...
```

Image file names follow the pattern: `{pdf_stem}_p{page:04d}_{index:03d}.{ext}`

## Memory management for large PDFs

The converter processes pages one at a time and writes to the `.md` file
incrementally — it never builds the entire output in memory. After every
`--chunk-size` pages (default: 20), `gc.collect()` is called to release
pdfplumber/pypdf page objects.

For very large PDFs (1000+ pages) on machines with limited RAM, use:

```bash
python pdf2md.py big_document.pdf --chunk-size 5
```

## Limitations

- **Scanned PDFs** (image-only): no text will be extracted; use an OCR tool
  (e.g. `ocrmypdf`) to add a text layer before converting.
- Complex multi-column layouts may not linearise perfectly into Markdown.
- Code blocks in PDFs are not automatically detected as fenced code blocks.
