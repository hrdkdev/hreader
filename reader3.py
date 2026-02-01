"""
Parses an EPUB file into a structured object that can be used to serve the book via a web interface.
"""

import os
import pickle
import re
import shutil
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
from urllib.parse import unquote

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, Comment

# --- Obsidian Integration Config ---
OBSIDIAN_BOOKS_PATH = "/home/hrdk/gen/Notes/books"
OBSIDIAN_IMAGES_PATH = "/home/hrdk/gen/Notes/Images"

# --- Data structures ---


@dataclass
class ChapterContent:
    """
    Represents a physical file in the EPUB (Spine Item).
    A single file might contain multiple logical chapters (TOC entries).
    """

    id: str  # Internal ID (e.g., 'item_1')
    href: str  # Filename (e.g., 'part01.html')
    title: str  # Best guess title from file
    content: str  # Cleaned HTML with rewritten image paths
    text: str  # Plain text for search/LLM context
    order: int  # Linear reading order


@dataclass
class TOCEntry:
    """Represents a logical entry in the navigation sidebar."""

    title: str
    href: str  # original href (e.g., 'part01.html#chapter1')
    file_href: str  # just the filename (e.g., 'part01.html')
    anchor: str  # just the anchor (e.g., 'chapter1'), empty if none
    children: List["TOCEntry"] = field(default_factory=list)


@dataclass
class BookMetadata:
    """Metadata"""

    title: str
    language: str
    authors: List[str] = field(default_factory=list)
    description: Optional[str] = None
    publisher: Optional[str] = None
    date: Optional[str] = None
    identifiers: List[str] = field(default_factory=list)
    subjects: List[str] = field(default_factory=list)


@dataclass
class Book:
    """The Master Object to be pickled."""

    metadata: BookMetadata
    spine: List[ChapterContent]  # The actual content (linear files)
    toc: List[TOCEntry]  # The navigation tree
    images: Dict[str, str]  # Map: original_path -> local_path
    source_file: str
    processed_at: str
    version: str = "3.0"
    cover_image: Optional[str] = None  # Relative path to cover image


# --- Utilities ---


def clean_html_content(soup: BeautifulSoup) -> BeautifulSoup:
    # Remove dangerous/useless tags
    for tag in soup(["script", "style", "iframe", "video", "nav", "form", "button"]):
        tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove input tags
    for tag in soup.find_all("input"):
        tag.decompose()

    return soup


def extract_plain_text(soup: BeautifulSoup) -> str:
    """Extract clean text for LLM/Search usage."""
    text = soup.get_text(separator=" ")
    # Collapse whitespace
    return " ".join(text.split())


def parse_toc_recursive(toc_list, depth=0) -> List[TOCEntry]:
    """
    Recursively parses the TOC structure from ebooklib.
    """
    result = []

    for item in toc_list:
        # ebooklib TOC items are either `Link` objects or tuples (Section, [Children])
        if isinstance(item, tuple):
            section, children = item
            entry = TOCEntry(
                title=section.title,
                href=section.href,
                file_href=section.href.split("#")[0],
                anchor=section.href.split("#")[1] if "#" in section.href else "",
                children=parse_toc_recursive(children, depth + 1),
            )
            result.append(entry)
        elif isinstance(item, epub.Link):
            entry = TOCEntry(
                title=item.title,
                href=item.href,
                file_href=item.href.split("#")[0],
                anchor=item.href.split("#")[1] if "#" in item.href else "",
            )
            result.append(entry)
        # Note: ebooklib sometimes returns direct Section objects without children
        elif isinstance(item, epub.Section):
            entry = TOCEntry(
                title=item.title,
                href=item.href,
                file_href=item.href.split("#")[0],
                anchor=item.href.split("#")[1] if "#" in item.href else "",
            )
            result.append(entry)

    return result


def get_fallback_toc(book_obj) -> List[TOCEntry]:
    """
    If TOC is missing, build a flat one from the Spine.
    """
    toc = []
    for item in book_obj.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            name = item.get_name()
            # Try to guess a title from the content or ID
            title = (
                item.get_name()
                .replace(".html", "")
                .replace(".xhtml", "")
                .replace("_", " ")
                .title()
            )
            toc.append(TOCEntry(title=title, href=name, file_href=name, anchor=""))
    return toc


def extract_metadata_robust(book_obj) -> BookMetadata:
    """
    Extracts metadata handling both single and list values.
    """

    def get_list(key):
        data = book_obj.get_metadata("DC", key)
        return [x[0] for x in data] if data else []

    def get_one(key):
        data = book_obj.get_metadata("DC", key)
        return data[0][0] if data else None

    return BookMetadata(
        title=get_one("title") or "Untitled",
        language=get_one("language") or "en",
        authors=get_list("creator"),
        description=get_one("description"),
        publisher=get_one("publisher"),
        date=get_one("date"),
        identifiers=get_list("identifier"),
        subjects=get_list("subject"),
    )


def detect_cover_image(book_obj, image_map: Dict[str, str]) -> Optional[str]:
    """
    Tries to detect the cover image from the EPUB.
    Returns the relative path to the cover image or None.
    """
    # Method 1: Check for cover metadata
    cover_meta = book_obj.get_metadata("OPF", "cover")
    if cover_meta:
        cover_id = cover_meta[0][1].get("content") if cover_meta[0][1] else None
        if cover_id:
            cover_item = book_obj.get_item_with_id(cover_id)
            if cover_item:
                cover_name = cover_item.get_name()
                if cover_name in image_map:
                    return image_map[cover_name]

    # Method 2: Look for images with 'cover' in the name
    for original_path, local_path in image_map.items():
        if "cover" in original_path.lower():
            return local_path

    # Method 3: Try to find the first image in the first chapter
    for item in book_obj.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_content().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(content, "html.parser")
            first_img = soup.find("img")
            if first_img:
                src = first_img.get("src", "")
                if src:
                    src_decoded = unquote(str(src))
                    filename = os.path.basename(src_decoded)
                    if src_decoded in image_map:
                        return image_map[src_decoded]
                    elif filename in image_map:
                        return image_map[filename]
            # Only check first document
            break

    return None


# --- Main Conversion Logic ---


def process_epub(epub_path: str, output_dir: str) -> Book:
    # 1. Load Book
    print(f"Loading {epub_path}...")
    book = epub.read_epub(epub_path)

    # 2. Extract Metadata
    metadata = extract_metadata_robust(book)

    # 3. Prepare Output Directories
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # 4. Extract Images & Build Map
    print("Extracting images...")
    image_map = {}  # Key: internal_path, Value: local_relative_path

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            # Normalize filename
            original_fname = os.path.basename(item.get_name())
            # Sanitize filename for OS
            safe_fname = "".join(
                [c for c in original_fname if c.isalpha() or c.isdigit() or c in "._-"]
            ).strip()

            # Save to disk
            local_path = os.path.join(images_dir, safe_fname)
            with open(local_path, "wb") as f:
                f.write(item.get_content())

            # Map keys: We try both the full internal path and just the basename
            # to be robust against messy HTML src attributes
            rel_path = f"images/{safe_fname}"
            image_map[item.get_name()] = rel_path
            image_map[original_fname] = rel_path

    # 5. Process TOC
    print("Parsing Table of Contents...")
    toc_structure = parse_toc_recursive(book.toc)
    if not toc_structure:
        print("Warning: Empty TOC, building fallback from Spine...")
        toc_structure = get_fallback_toc(book)

    # 6. Process Content (Spine-based to preserve HTML validity)
    print("Processing chapters...")
    spine_chapters = []

    # We iterate over the spine (linear reading order)
    for i, spine_item in enumerate(book.spine):
        item_id, linear = spine_item
        item = book.get_item_with_id(item_id)

        if not item:
            continue

        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            # Raw content
            raw_content = item.get_content().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(raw_content, "html.parser")

            # A. Fix Images
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if not src:
                    continue

                # Decode URL (part01/image%201.jpg -> part01/image 1.jpg)
                src_decoded = unquote(str(src))
                filename = os.path.basename(src_decoded)

                # Try to find in map
                if src_decoded in image_map:
                    img["src"] = image_map[src_decoded]
                elif filename in image_map:
                    img["src"] = image_map[filename]

            # B. Clean HTML
            soup = clean_html_content(soup)

            # C. Extract Body Content only
            body = soup.find("body")
            if body:
                # Extract inner HTML of body
                final_html = "".join([str(x) for x in body.contents])
            else:
                final_html = str(soup)

            # D. Create Object
            chapter = ChapterContent(
                id=item_id,
                href=item.get_name(),  # Important: This links TOC to Content
                title=f"Section {i + 1}",  # Fallback, real titles come from TOC
                content=final_html,
                text=extract_plain_text(soup),
                order=i,
            )
            spine_chapters.append(chapter)

    # 7. Detect Cover Image
    print("Detecting cover image...")
    cover_image = detect_cover_image(book, image_map)
    if cover_image:
        print(f"Found cover image: {cover_image}")
    else:
        print("No cover image detected")

    # 8. Final Assembly
    final_book = Book(
        metadata=metadata,
        spine=spine_chapters,
        toc=toc_structure,
        images=image_map,
        source_file=os.path.basename(epub_path),
        processed_at=datetime.now().isoformat(),
        cover_image=cover_image,
    )

    return final_book


def save_to_pickle(book: Book, output_dir: str):
    p_path = os.path.join(output_dir, "book.pkl")
    with open(p_path, "wb") as f:
        pickle.dump(book, f)
    print(f"Saved structured data to {p_path}")


# --- Obsidian Integration ---


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """
    Sanitize a string for use as a filename.
    Removes/replaces invalid characters and truncates to max_length.
    """
    # Remove or replace invalid filename characters
    sanitized = re.sub(r'[<>:"/\\|?*]', "", name)
    # Replace multiple spaces with single space
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    # Truncate if needed
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rsplit(" ", 1)[0].strip()
    return sanitized


def strip_html_tags(html_text: str) -> str:
    """Strip HTML tags and return plain text."""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text(separator=" ")
    # Collapse whitespace and clean up
    text = " ".join(text.split())
    return text


def find_cover_image(book_data_dir: str, book: Book) -> Optional[str]:
    """
    Find the cover image path. Tries book.cover_image first,
    then falls back to looking for cover.* in images folder.
    Returns the full path to the cover image or None.
    """
    images_dir = os.path.join(book_data_dir, "images")

    # Try the cover_image attribute first
    if book.cover_image:
        cover_path = os.path.join(book_data_dir, book.cover_image)
        if os.path.exists(cover_path):
            return cover_path

    # Fallback: look for cover.* in images folder
    if os.path.exists(images_dir):
        for fname in os.listdir(images_dir):
            if fname.lower().startswith("cover."):
                return os.path.join(images_dir, fname)

    return None


def export_to_obsidian(book_data_dir: str) -> bool:
    """
    Export a processed book to Obsidian vault.

    Args:
        book_data_dir: Path to the book's data directory (e.g., 'naval_data')

    Returns:
        True if export was successful, False otherwise.
    """
    # Load the book
    pkl_path = os.path.join(book_data_dir, "book.pkl")
    if not os.path.exists(pkl_path):
        print(f"Error: {pkl_path} not found")
        return False

    with open(pkl_path, "rb") as f:
        book = pickle.load(f)

    # Generate sanitized title for filenames
    title_sanitized = sanitize_filename(book.metadata.title)

    # Check if note already exists
    note_filename = f"{title_sanitized}.md"
    note_path = os.path.join(OBSIDIAN_BOOKS_PATH, note_filename)

    if os.path.exists(note_path):
        print(f"Skipping: Note already exists at {note_path}")
        return False

    # Find and copy cover image
    cover_image_name = None
    cover_source = find_cover_image(book_data_dir, book)

    if cover_source:
        # Determine extension
        _, ext = os.path.splitext(cover_source)
        cover_image_name = f"{title_sanitized}_cover{ext}"
        cover_dest = os.path.join(OBSIDIAN_IMAGES_PATH, cover_image_name)

        # Copy if doesn't exist
        if not os.path.exists(cover_dest):
            shutil.copy2(cover_source, cover_dest)
            print(f"Copied cover image to {cover_dest}")
        else:
            print(f"Cover image already exists at {cover_dest}")
    else:
        print("Warning: No cover image found for this book")

    # Prepare metadata
    title = book.metadata.title
    authors = book.metadata.authors or ["Unknown"]
    description = (
        strip_html_tags(book.metadata.description) if book.metadata.description else ""
    )
    # Truncate description if too long (for frontmatter readability)
    if len(description) > 300:
        description = description[:297] + "..."

    # Extract year from date if available
    published = ""
    if book.metadata.date:
        # Try to extract year from various date formats
        year_match = re.search(r"\b(19|20)\d{2}\b", book.metadata.date)
        if year_match:
            published = year_match.group(0)

    # Build frontmatter
    created_date = datetime.now().strftime("%Y-%m-%d")

    # Format authors as wiki-links
    author_lines = "\n".join([f'  - "[[{author}]]"' for author in authors])

    # Build the markdown content
    lines = [
        "---",
        f'title: "{title}"',
        f"created: {created_date}",
    ]

    if description:
        # Escape quotes in description for YAML
        desc_escaped = description.replace('"', '\\"')
        lines.append(f'description: "{desc_escaped}"')

    lines.extend(
        [
            "tags:",
            "  - books",
        ]
    )

    if cover_image_name:
        lines.append(f'cover: "[[{cover_image_name}]]"')

    lines.extend(
        [
            "author:",
            author_lines,
            "status: want to read",
        ]
    )

    if published:
        lines.append(f"published: {published}")

    lines.append("---")

    # Body
    if cover_image_name:
        lines.append(f"![[{cover_image_name}]]")

    lines.extend(
        [
            "",
            "## notes",
            "",
        ]
    )

    # Write the note
    os.makedirs(OBSIDIAN_BOOKS_PATH, exist_ok=True)
    with open(note_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Created Obsidian note: {note_path}")
    return True


def process_all_epubs(directory: str = ".") -> tuple[int, int]:
    """
    Process all epub files in the directory that don't already have a _data folder.

    Returns:
        Tuple of (processed_count, skipped_count)
    """
    processed = 0
    skipped = 0

    # Find all epub files
    epub_files = [f for f in os.listdir(directory) if f.endswith(".epub")]

    if not epub_files:
        print("No epub files found in current directory")
        return 0, 0

    print(f"Found {len(epub_files)} epub file(s)")

    for epub_file in sorted(epub_files):
        epub_path = os.path.join(directory, epub_file)
        out_dir = os.path.splitext(epub_path)[0] + "_data"
        pkl_path = os.path.join(out_dir, "book.pkl")

        # Skip if already processed
        if os.path.exists(pkl_path):
            print(f"Skipping (already processed): {epub_file}")
            skipped += 1
            continue

        print(f"\n{'=' * 60}")
        print(f"Processing: {epub_file}")
        print("=" * 60)

        try:
            book_obj = process_epub(epub_path, out_dir)
            save_to_pickle(book_obj, out_dir)
            print(f"Done: {book_obj.metadata.title}")
            processed += 1
        except Exception as e:
            print(f"Error processing {epub_file}: {e}")
            skipped += 1

    return processed, skipped


def export_all_to_obsidian(directory: str = ".") -> tuple[int, int]:
    """
    Export all processed books to Obsidian.

    Returns:
        Tuple of (exported_count, skipped_count)
    """
    exported = 0
    skipped = 0

    # Find all _data folders with book.pkl
    data_folders = [
        f
        for f in os.listdir(directory)
        if f.endswith("_data") and os.path.isdir(os.path.join(directory, f))
    ]

    if not data_folders:
        print("No processed books found (no *_data folders)")
        return 0, 0

    print(f"Found {len(data_folders)} processed book(s)")

    for folder in sorted(data_folders):
        folder_path = os.path.join(directory, folder)
        pkl_path = os.path.join(folder_path, "book.pkl")

        if not os.path.exists(pkl_path):
            print(f"Skipping (no book.pkl): {folder}")
            skipped += 1
            continue

        print(f"\nExporting: {folder}")

        try:
            if export_to_obsidian(folder_path):
                exported += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"Error exporting {folder}: {e}")
            skipped += 1

    return exported, skipped


# --- CLI ---

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  Process EPUB:       python reader3.py <file.epub>")
        print("  Process all EPUBs:  python reader3.py --process-all")
        print("  Export to Obsidian: python reader3.py --obsidian <book_data_folder>")
        print("  Export all to Obsidian: python reader3.py --obsidian-all")
        sys.exit(1)

    # Handle --process-all flag
    if sys.argv[1] == "--process-all":
        processed, skipped = process_all_epubs()
        print(f"\n{'=' * 60}")
        print(f"Summary: {processed} processed, {skipped} skipped")
        sys.exit(0)

    # Handle --obsidian-all flag
    if sys.argv[1] == "--obsidian-all":
        exported, skipped = export_all_to_obsidian()
        print(f"\n{'=' * 60}")
        print(f"Summary: {exported} exported, {skipped} skipped")
        sys.exit(0)

    # Handle --obsidian flag
    if sys.argv[1] == "--obsidian":
        if len(sys.argv) < 3:
            print("Error: Please specify the book data folder")
            print("Usage: python reader3.py --obsidian <book_data_folder>")
            sys.exit(1)

        book_folder = sys.argv[2]
        if not os.path.isdir(book_folder):
            print(f"Error: {book_folder} is not a directory")
            sys.exit(1)

        success = export_to_obsidian(book_folder)
        sys.exit(0 if success else 1)

    # Normal EPUB processing
    epub_file = sys.argv[1]
    assert os.path.exists(epub_file), "File not found."
    out_dir = os.path.splitext(epub_file)[0] + "_data"

    book_obj = process_epub(epub_file, out_dir)
    save_to_pickle(book_obj, out_dir)
    print("\n--- Summary ---")
    print(f"Title: {book_obj.metadata.title}")
    print(f"Authors: {', '.join(book_obj.metadata.authors)}")
    print(f"Physical Files (Spine): {len(book_obj.spine)}")
    print(f"TOC Root Items: {len(book_obj.toc)}")
    print(f"Images extracted: {len(book_obj.images)}")
