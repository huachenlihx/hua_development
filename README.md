# Hua Development

A collection of my development projects, covering back end (Django), front end
(Next.js) and Python tooling.

## Repository structure

```
hua_development/
├── python_pdf2html/   # PDF to HTML conversion
├── python_test/       # PDF to Markdown conversion (pdf2md.py)
├── Jenkinsfile        # CI pipeline for python_test
└── README.md
```

| Folder / file     | Description                                                          |
| ----------------- | -------------------------------------------------------------------- |
| `python_pdf2html` | Python project for converting PDF files to HTML                      |
| `python_test`     | Python project for converting PDF files to Markdown with `pdf2md.py` |
| `Jenkinsfile`     | Jenkins pipeline that lints and runs the PDF-to-Markdown conversion  |

## Getting started

```bash
git clone https://github.com/huachenlihx/hua_development.git
cd hua_development
```

### Run the PDF to Markdown converter

Requires Python 3.11.

```bash
cd python_test
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python pdf2md.py converts/c3_algorithm.pdf --verbose
```

The Markdown output, and any images extracted from the PDF, are written to the
`converts/` folder.

## Continuous integration

The `Jenkinsfile` defines a pipeline with these stages:

1. **Checkout**: clone the repository
2. **Set Up Python Environment**: create a virtual environment and install `python_test/requirements.txt`
3. **Lint**: run `flake8` on `pdf2md.py`
4. **Convert PDF → Markdown**: run `pdf2md.py` on the sample PDF
5. **Archive Output**: save the generated `.md` file and extracted images as build artifacts

The workspace is cleaned after every build.

## Other projects

Related npm packages I maintain:

- [form_recaptcha](https://github.com/huachenlihx/form_recaptcha): simple CAPTCHA component for Next.js forms
- [pdfjs-embed-viewer](https://github.com/huachenlihx/pdfjs-embed-viewer): embed PDFs in Next.js pages

## License

MIT © Hua Chen
