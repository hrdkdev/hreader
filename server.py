import os
import pickle
import json
from functools import lru_cache
from typing import Optional, Dict, List, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from reader3 import Book, BookMetadata, ChapterContent, TOCEntry


# Highlight data models
class Highlight(BaseModel):
    id: str
    chapter_index: int
    text: str
    start_offset: int
    end_offset: int
    created_at: str


class HighlightRequest(BaseModel):
    book_id: str
    highlight: Highlight


class RemoveHighlightRequest(BaseModel):
    book_id: str
    chapter_index: int
    highlight_id: str


app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Where are the book folders located?
BOOKS_DIR = "."


@lru_cache(maxsize=10)
def load_book_cached(folder_name: str) -> Optional[Book]:
    """
    Loads the book from the pickle file.
    Cached so we don't re-read the disk on every click.
    """
    file_path = os.path.join(BOOKS_DIR, folder_name, "book.pkl")
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "rb") as f:
            book = pickle.load(f)
        return book
    except Exception as e:
        print(f"Error loading book {folder_name}: {e}")
        return None


def load_highlights(book_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Load highlights for a book from JSON file."""
    highlights_file = os.path.join(BOOKS_DIR, book_id, "highlights.json")
    if not os.path.exists(highlights_file):
        return {}

    try:
        with open(highlights_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading highlights for {book_id}: {e}")
        return {}


def save_highlights(book_id: str, highlights: Dict[str, List[Dict[str, Any]]]) -> bool:
    """Save highlights for a book to JSON file."""
    highlights_file = os.path.join(BOOKS_DIR, book_id, "highlights.json")
    try:
        with open(highlights_file, "w", encoding="utf-8") as f:
            json.dump(highlights, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving highlights for {book_id}: {e}")
        return False


@app.get("/", response_class=HTMLResponse)
async def library_view(request: Request):
    """Lists all available processed books."""
    books = []

    # Scan directory for folders ending in '_data' that have a book.pkl
    if os.path.exists(BOOKS_DIR):
        for item in os.listdir(BOOKS_DIR):
            if item.endswith("_data") and os.path.isdir(item):
                # Try to load it to get the title
                book = load_book_cached(item)
                if book:
                    books.append(
                        {
                            "id": item,
                            "title": book.metadata.title,
                            "author": ", ".join(book.metadata.authors),
                            "chapters": len(book.spine),
                        }
                    )

    return templates.TemplateResponse(
        "library.html", {"request": request, "books": books}
    )


@app.get("/read/{book_id}", response_class=HTMLResponse)
async def redirect_to_first_chapter(request: Request, book_id: str):
    """Helper to just go to chapter 0."""
    return await read_chapter(request=request, book_id=book_id, chapter_index=0)


@app.get("/read/{book_id}/{chapter_index}", response_class=HTMLResponse)
async def read_chapter(request: Request, book_id: str, chapter_index: int):
    """The main reader interface."""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if chapter_index < 0 or chapter_index >= len(book.spine):
        raise HTTPException(status_code=404, detail="Chapter not found")

    current_chapter = book.spine[chapter_index]

    # Calculate Prev/Next links
    prev_idx = chapter_index - 1 if chapter_index > 0 else None
    next_idx = chapter_index + 1 if chapter_index < len(book.spine) - 1 else None

    return templates.TemplateResponse(
        "reader.html",
        {
            "request": request,
            "book": book,
            "current_chapter": current_chapter,
            "chapter_index": chapter_index,
            "book_id": book_id,
            "prev_idx": prev_idx,
            "next_idx": next_idx,
        },
    )


@app.get("/cover/{book_id}")
async def serve_cover(book_id: str):
    """Serves the cover image for a book."""
    safe_book_id = os.path.basename(book_id)

    # First, try to load the book and check if it has a cover_image path
    book = load_book_cached(safe_book_id)
    if book and hasattr(book, "cover_image") and book.cover_image:
        cover_path = os.path.join(BOOKS_DIR, safe_book_id, book.cover_image)
        if os.path.exists(cover_path):
            return FileResponse(cover_path)

    # Fallback: Try common cover image names
    images_dir = os.path.join(BOOKS_DIR, safe_book_id, "images")
    if os.path.exists(images_dir):
        # Try common cover patterns
        for filename in os.listdir(images_dir):
            if "cover" in filename.lower() and filename.lower().endswith(
                (".jpg", ".jpeg", ".png", ".gif")
            ):
                cover_path = os.path.join(images_dir, filename)
                return FileResponse(cover_path)

    # If no cover found, return 404
    raise HTTPException(status_code=404, detail="Cover image not found")


@app.get("/read/{book_id}/images/{image_name}")
async def serve_image(book_id: str, image_name: str):
    """
    Serves images specifically for a book.
    The HTML contains <img src="images/pic.jpg">.
    The browser resolves this to /read/{book_id}/images/pic.jpg.
    """
    # Security check: ensure book_id is clean
    safe_book_id = os.path.basename(book_id)
    safe_image_name = os.path.basename(image_name)

    img_path = os.path.join(BOOKS_DIR, safe_book_id, "images", safe_image_name)

    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(img_path)


# Highlight API endpoints
@app.post("/api/highlights")
async def create_highlight(request_data: HighlightRequest):
    """Create a new highlight."""
    try:
        highlights = load_highlights(request_data.book_id)
        chapter_key = str(request_data.highlight.chapter_index)

        if chapter_key not in highlights:
            highlights[chapter_key] = []

        # Add highlight to the chapter
        highlights[chapter_key].append(request_data.highlight.dict())

        # Save to file
        success = save_highlights(request_data.book_id, highlights)

        if success:
            return {"status": "success", "message": "Highlight saved"}
        else:
            raise HTTPException(status_code=500, detail="Failed to save highlight")

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error creating highlight: {str(e)}"
        )


@app.get("/api/highlights/{book_id}/{chapter_index}")
async def get_highlights(book_id: str, chapter_index: int):
    """Get all highlights for a specific chapter."""
    try:
        highlights = load_highlights(book_id)
        chapter_key = str(chapter_index)
        chapter_highlights = highlights.get(chapter_key, [])

        return {"highlights": chapter_highlights}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error loading highlights: {str(e)}"
        )


@app.delete("/api/highlights")
async def remove_highlight(request_data: RemoveHighlightRequest):
    """Remove a specific highlight."""
    try:
        highlights = load_highlights(request_data.book_id)
        chapter_key = str(request_data.chapter_index)

        if chapter_key not in highlights:
            raise HTTPException(status_code=404, detail="Chapter highlights not found")

        # Find and remove the highlight with matching ID
        original_count = len(highlights[chapter_key])
        highlights[chapter_key] = [
            h
            for h in highlights[chapter_key]
            if h.get("id") != request_data.highlight_id
        ]

        if len(highlights[chapter_key]) == original_count:
            raise HTTPException(status_code=404, detail="Highlight not found")

        # Save to file
        success = save_highlights(request_data.book_id, highlights)

        if success:
            return {"status": "success", "message": "Highlight removed"}
        else:
            raise HTTPException(status_code=500, detail="Failed to remove highlight")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error removing highlight: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    print("Starting server at http://127.0.0.1:8123")
    uvicorn.run(app, host="127.0.0.1", port=8123)
