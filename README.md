# Pawread

**Turn a book list into a full set of chapter-by-chapter reading notes.**

Paste a list of titles. Pawread finds each book online, downloads it, verifies
the file is actually the book you asked for, splits it into chapters, and has
an LLM read every chapter and write detailed notes. One Markdown file per
book, with a table of contents and the original quotations kept verbatim.

<!-- Screenshots go in docs/images/. Drop them in and reference them here:

![The web UI](docs/images/ui-library.png)
![A generated note](docs/images/note-sample.png)

-->

## Quick start

```bash
git clone https://github.com/Topaz1618/Pawread.git
cd Pawread
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

brew install poppler tesseract        # text extraction + OCR

cp config/env.example config/env.local   # add your keys
```

Fill in `DASHSCOPE_API_KEY` for the model and `SMARTPROXY_ACCOUNT` /
`SMARTPROXY_PASSWORD` for the proxy. Set `PAWREAD_HOST` and `PAWREAD_PORT`
for the web server.

Then:

```bash
python3 -m pawread.cli --list-file books.txt    # full pipeline
python3 server.py                               # web UI
```

Notes land in `notes/<Title>.md`.

---

## Usage

```bash
python3 -m pawread.cli --help
```

| Flag | Meaning |
|---|---|
| `--list-file PATH` | Read titles from a file, one per line |
| `--builtin-list` | Use the built-in list in `data/booklist.json` |
| `--only N [N ...]` | Process only these entries |
| `--no-discover` | Skip downloading; read what's already on disk |
| `--no-read` | Stop after download and verification |
| `--max-chapters N` | Read at most N chapters per book |
| `--tier NAME` | `test` / `standard` / `quality` / `max` |

```bash
python3 -m pawread.cli --builtin-list --only 6 --only 12
python3 tools/demo_read.py --book "Thinking in Systems" --chapters 3
```

---

## Sources

| Source | Compliance | Notes |
|---|---|---|
| `archive.org` | open lending | The primary source. Lending-restricted items can't be downloaded. |
| `openlibrary.org` | open lending | Points at Internet Archive scans. |
| `gutenberg.org` | public domain | Public-domain books. |
| `donellameadows.org` | publisher | The author's own scan of *The Limits to Growth*. |
| `scottberkun.com` | publisher | The author's own *Making Things Happen*. |
| `pacounderhill.com` | publisher | The publisher's catalogue. |
| `otexts.com` | publisher | The official *Forecasting: Principles and Practice*. |
| `order.poorcharliesalmanack.com` | publisher | The official order page — not a free download. |
| `books.google.com` | reference | Metadata only, rate-limited. Off by default. |

---

## Requirements

Python 3.9+, `requests`, `tornado` (web UI only), and the poppler tools
`pdftotext` / `pdfinfo` / `pdftoppm` plus `tesseract` for image-scanned PDFs.

---

## License

MIT — see [`LICENSE`](LICENSE).
