#!/usr/bin/env python3
"""Optimize the public-domain Bible plates and read their printed KJV citations."""

from __future__ import annotations

import re
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps
from rapidocr_onnxruntime import RapidOCR

ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "reader-images"
CAPTIONS_FILE = IMAGE_DIR / "recognized-captions.json"
IMAGE_WIDTH = 1000

# OCR is imperfect on a small number of scanned captions. These locations were
# read directly from the printed plate, rather than guessed from nearby text.
REFERENCE_OVERRIDES = {
    "NT-189": ("John", 8, 6),
    "OT-001": ("Genesis", 1, 2),
    "OT-027": ("Genesis", 41, 25),
    "OT-084": ("2 Samuel", 12, 27),
    "OT-085": ("2 Samuel", 18, 9),
    "OT-086": ("2 Samuel", 18, 33),
    "OT-089": ("2 Samuel", 21, 17),
    "OT-092": ("2 Chronicles", 9, 1),
    "OT-093": ("2 Chronicles", 1, 10),
    "OT-098": ("1 Kings", 20, 29),
    "OT-099": ("2 Chronicles", 20, 24),
    "OT-106": ("2 Kings", 9, 35),
    "OT-107": ("2 Chronicles", 23, 15),
    "OT-108": ("2 Kings", 17, 26),
    "OT-110": ("Isaiah", 6, 8),
    "OT-121": ("Esther", 7, 4),
    "OT-133": ("Nehemiah", 8, 5),
}

BOOKS = [
    "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles",
    "Song of Solomon", "1 Corinthians", "2 Corinthians", "1 Thessalonians",
    "2 Thessalonians", "1 Timothy", "2 Timothy", "1 Peter", "2 Peter",
    "1 John", "2 John", "3 John", "Samuel", "Kings", "Chronicles", "Corinthians",
    "Thessalonians", "Timothy", "Peter", "John", "Genesis", "Exodus", "Leviticus", "Numbers",
    "Deuteronomy", "Joshua", "Judges", "Ruth", "Ezra", "Nehemiah", "Esther",
    "Job", "Psalms", "Proverbs", "Ecclesiastes", "Isaiah", "Jeremiah",
    "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah",
    "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah",
    "Malachi", "Matthew", "Mark", "Luke", "John", "Acts", "Romans",
    "Galatians", "Ephesians", "Philippians", "Colossians", "Titus", "Philemon",
    "Hebrews", "James", "Jude", "Revelation",
]
BOOK_PATTERN = "|".join(re.escape(book) for book in sorted(BOOKS, key=len, reverse=True))
REFERENCE = re.compile(
    rf"(?<![A-Za-z])(?P<prefix>III|II|I|3|2|1)?\s*"
    rf"(?P<book>{BOOK_PATTERN})\s*(?P<chapter>\d{{1,3}})\s*[:：]\s*"
    rf"(?P<verse>\d{{1,3}})",
    re.IGNORECASE,
)
ROMAN = {"I": "1", "II": "2", "III": "3"}


def canonical_book(prefix: str, book: str) -> str:
    book = next(name for name in BOOKS if name.lower() == book.lower())
    if book in {"Samuel", "Kings", "Chronicles", "Corinthians", "Thessalonians", "Timothy", "Peter", "John"}:
        number = ROMAN.get(prefix.upper(), prefix)
        if number in {"1", "2", "3"}:
            return f"{number} {book}"
    return book


def find_reference(text: str) -> tuple[str, int, int] | None:
    normalized = text.translate(str.maketrans({"：": ":", "—": "-", "–": "-"}))
    for match in REFERENCE.finditer(normalized):
        book = canonical_book(match.group("prefix") or "", match.group("book"))
        if book in BOOKS:
            return book, int(match.group("chapter")), int(match.group("verse"))
    return None


def main() -> int:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    engine = RapidOCR()
    caption_cache = json.loads(CAPTIONS_FILE.read_text(encoding="utf-8")) if CAPTIONS_FILE.is_file() else {}
    records: list[tuple[str, str, int, int]] = []
    missing: list[str] = []

    # Plates 140–160 illustrate the Apocrypha, which is not part of this 66-book KJV.
    plates = sorted(
        [*ROOT.glob("OT-[0-9][0-9][0-9].jpg"), *ROOT.glob("NT-[0-9][0-9][0-9].jpg")],
        key=lambda path: path.name,
    )
    for index, path in enumerate(plates, start=1):
        if path.name.startswith("OT-") and 140 <= int(path.stem[3:]) <= 160:
            continue
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            width, height = image.size
            reference = REFERENCE_OVERRIDES.get(path.stem)
            if reference is None:
                text = caption_cache.get(path.stem)
                if text is None:
                    # The book/chapter citation is printed below the engraving.
                    crop = image.crop((0, int(height * 0.82), width, height))
                    if crop.width > 1700:
                        crop.thumbnail((1700, 1000))
                    recognized, _ = engine(crop)
                    text = " ".join(str(item[1]) for item in (recognized or []))
                    caption_cache[path.stem] = text
                    CAPTIONS_FILE.write_text(json.dumps(caption_cache, ensure_ascii=False), encoding="utf-8")
                reference = find_reference(text)
            if reference is None:
                missing.append(path.name)
                continue

            book, chapter, verse = reference
            image.thumbnail((IMAGE_WIDTH, IMAGE_WIDTH * 2), Image.Resampling.LANCZOS)
            image.convert("L").save(
                IMAGE_DIR / f"{path.stem}.jpg",
                "JPEG",
                quality=65,
                optimize=True,
                progressive=True,
            )
            records.append((path.stem, book, chapter, verse))

        if index % 20 == 0:
            print(f"Read {index}/{len(plates)} illustration captions", flush=True)

    if missing:
        print("Could not read the printed Bible reference on: " + ", ".join(missing), file=sys.stderr)
        print("No illustration manifest was written; inspect these captions and add reference overrides.", file=sys.stderr)
        return 1

    manifest = [
        {
            "image": f"{image}.jpg",
            "book": book,
            "chapter": chapter,
            "verse": verse,
            "caption": f"Illustration for {book} {chapter}:{verse}",
        }
        for image, book, chapter, verse in records
    ]
    (IMAGE_DIR / "illustrations.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared {len(records)} illustrated KJV references in {IMAGE_DIR}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
