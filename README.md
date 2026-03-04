# Books Folder

This folder is used for automatic book processing.

## How to Add Books

Simply drop your EPUB files into this `books/` folder. When you start the server with `uv run server.py`, any new EPUB files will be automatically processed.

## What Happens

1. When the server starts, it scans this folder for `.epub` files
2. Any EPUB that hasn't been processed yet will be converted automatically
3. A `<bookname>_data/` folder will be created in the parent directory containing:
   - `book.pkl` (processed book data)
   - `images/` (extracted images)
   - `highlights.json` (for your highlights)
   - `reading_progress.json` (for your reading position)
4. The book will then appear in your library at http://localhost:8123

## Already Processed Books

Books that have already been processed (have a corresponding `_data` folder) will be skipped automatically.

## Manual Processing

If you prefer to process books manually, you can still use:
```bash
uv run reader3.py path/to/book.epub
```
