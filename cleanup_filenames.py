#!/usr/bin/env python3
"""
Clean up EPUB and book_data folder filenames by keeping only the book title.
Removes author names, publisher info, ISBN, hashes, and other metadata.
"""

import os
import re
from pathlib import Path


def clean_filename(filename: str) -> str:
    """
    Keep only the book title (everything before the first ' -- ').

    For example:
    - "Behave _ The Biology of Humans at Our Best and Worst -- Author -- ..."
      becomes "Behave _ The Biology of Humans at Our Best and Worst"
    - Files without ' -- ' are left unchanged
    """
    # Check if this is a _data folder, .epub file, or .sdr folder
    is_data_folder = filename.endswith("_data")
    is_epub = filename.endswith(".epub")
    is_sdr = filename.endswith(".sdr")

    # Remove extension/suffix temporarily
    if is_data_folder:
        base_filename = filename[:-5]  # Remove '_data'
    elif is_epub:
        base_filename = filename[:-5]  # Remove '.epub'
    elif is_sdr:
        base_filename = filename[:-4]  # Remove '.sdr'
    else:
        base_filename = filename

    # Find the first occurrence of ' -- ' (space-dash-dash-space)
    separator = " -- "
    if separator in base_filename:
        # Keep only the part before the first ' -- '
        title = base_filename.split(separator)[0]
    else:
        # No separator found, keep as-is
        title = base_filename

    # Clean up any trailing spaces
    title = title.strip()

    # Add back extension and _data suffix if needed
    if is_epub:
        result = title + ".epub"
    elif is_data_folder:
        result = title + "_data"
    elif is_sdr:
        result = title + ".sdr"
    else:
        result = title

    return result


def rename_files(directory: str = ".", dry_run: bool = True) -> None:
    """
    Rename EPUB files, _data folders, and .sdr folders by removing random suffixes.

    Args:
        directory: Directory to search in (default: current directory)
        dry_run: If True, only print what would be renamed without actually renaming
    """
    dir_path = Path(directory)

    # Find all .epub files, *_data folders, and .sdr folders
    items_to_rename = []

    # Get EPUB files
    epub_files = list(dir_path.glob("*.epub"))
    items_to_rename.extend(epub_files)

    # Get _data directories
    data_dirs = [
        d for d in dir_path.iterdir() if d.is_dir() and d.name.endswith("_data")
    ]
    items_to_rename.extend(data_dirs)

    # Get .sdr directories
    sdr_dirs = [d for d in dir_path.iterdir() if d.is_dir() and d.name.endswith(".sdr")]
    items_to_rename.extend(sdr_dirs)

    # Sort for consistent output
    items_to_rename.sort(key=lambda x: x.name)

    renamed_count = 0
    skipped_count = 0

    for item in items_to_rename:
        old_name = item.name
        new_name = clean_filename(old_name)

        if old_name == new_name:
            print(f"[SKIP] {old_name}")
            skipped_count += 1
            continue

        old_path = item
        new_path = dir_path / new_name

        # Check if target already exists
        if new_path.exists():
            print(f"[ERROR] Target already exists: {new_name}")
            print(f"        Cannot rename: {old_name}")
            skipped_count += 1
            continue

        if dry_run:
            print(f"[DRY-RUN] {old_name}")
            print(f"       -> {new_name}")
        else:
            try:
                old_path.rename(new_path)
                print(f"[RENAMED] {old_name}")
                print(f"       -> {new_name}")
                renamed_count += 1
            except Exception as e:
                print(f"[ERROR] Failed to rename {old_name}: {e}")
                skipped_count += 1

        print()

    print(f"\nSummary:")
    print(f"  Renamed: {renamed_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Total:   {len(items_to_rename)}")

    if dry_run:
        print(f"\nThis was a dry run. Use --execute to actually rename files.")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Clean up EPUB and book_data folder filenames"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually rename files (default is dry-run mode)",
    )
    parser.add_argument(
        "--directory",
        default=".",
        help="Directory to process (default: current directory)",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("Filename Cleanup Tool")
    print("=" * 80)
    print(f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"Directory: {os.path.abspath(args.directory)}")
    print("=" * 80)
    print()

    rename_files(args.directory, dry_run=not args.execute)


if __name__ == "__main__":
    main()
