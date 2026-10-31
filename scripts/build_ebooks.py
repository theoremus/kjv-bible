#!/usr/bin/env python3
"""Insert verse illustrations into the HTML build and create per-book EPUBs."""

from __future__ import annotations

import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "_site"
SITE_URL = "https://theoremus.github.io/kjv-bible/"
IMAGE_MANIFEST = ROOT / "reader-images" / "illustrations.json"
CONFIG = ROOT / "_quarto-html.yml"
BOOKS = (
    "genesis", "exodus", "leviticus", "numbers", "deuteronomy", "joshua", "judges",
    "ruth", "1-samuel", "2-samuel", "1-kings", "2-kings", "1-chronicles",
    "2-chronicles", "ezra", "nehemiah", "esther", "job", "psalms", "proverbs",
    "ecclesiastes", "song-of-solomon", "isaiah", "jeremiah", "lamentations",
    "ezekiel", "daniel", "hosea", "joel", "amos", "obadiah", "jonah", "micah",
    "nahum", "habakkuk", "zephaniah", "haggai", "zechariah", "malachi", "matthew",
    "mark", "luke", "john", "acts", "romans", "1-corinthians", "2-corinthians",
    "galatians", "ephesians", "philippians", "colossians", "1-thessalonians",
    "2-thessalonians", "1-timothy", "2-timothy", "titus", "philemon", "hebrews",
    "james", "1-peter", "2-peter", "1-john", "2-john", "3-john", "jude", "revelation",
)


def book_files() -> list[str]:
    """Use the configured canonical order, rather than a hard-coded file order."""
    names = re.findall(r"(?m)^\s+-\s+([\w-]+)\.qmd\s*$", CONFIG.read_text(encoding="utf-8"))
    return [Path(name).stem for name in names if name != "index"]


def figure(record: dict[str, object]) -> str:
    image = html.escape(str(record["image"]), quote=True)
    caption = html.escape(str(record["caption"]))
    return (
        '<span class="reader-illustration" role="figure">'
        f'<img src="reader-images/{image}" alt="{caption}" loading="lazy">'
        f'<span class="illustration-caption">{caption}</span>'
        "</span>"
    )


def insert_illustrations(records: list[dict[str, object]]) -> int:
    """Add each plate at its verse boundary without rewriting any Bible text."""
    by_book_chapter: dict[tuple[str, int], list[dict[str, object]]] = {}
    for record in records:
        key = (str(record["book"]), int(record["chapter"]))
        by_book_chapter.setdefault(key, []).append(record)

    inserted = 0
    successful_pages: list[tuple[Path, str]] = []
    scripture = re.compile(
        r'<div class="scripture" data-book="(?P<book>[^"]+)" '
        r'data-chapter="(?P<chapter>\d+)">(.*?)</div>',
        re.DOTALL,
    )
    verse = re.compile(r'<span class="verse-number">(\d+)</span>')
    sentence_end = re.compile(r"[.!?](?=(?:</(?:span|em|strong|i|b)>)*\s*(?:[A-Z\"“‘]|<span class=\"verse-number\"|$))")

    def remove_legacy_illustrations(document: str) -> str:
        """Remove the six original chapter-top plates before placing all plates at verses."""
        opening = re.compile(r'<div class="illustration">')
        while match := opening.search(document):
            scripture_start = document.find('<div class="scripture"', match.end())
            if scripture_start < 0:
                raise RuntimeError("Found an old illustration without a following scripture block.")
            section = document[match.start():scripture_start]
            depth = 0
            end = None
            for tag in re.finditer(r"</?div\b[^>]*>", section):
                if tag.group(0).startswith("</"):
                    depth -= 1
                    if depth == 0:
                        end = match.start() + tag.end()
                        break
                else:
                    depth += 1
            if end is None:
                raise RuntimeError("Could not find the end of an old illustration block.")
            document = document[:match.start()] + document[end:]
        return document

    for slug in BOOKS:
        page = SITE / f"{slug}.html"
        if not page.is_file():
            raise RuntimeError(f"Missing rendered HTML page: {page}")
        source = remove_legacy_illustrations(page.read_text(encoding="utf-8"))
        replacements: list[tuple[int, int, str]] = []

        for block in scripture.finditer(source):
            key = (block.group("book"), int(block.group("chapter")))
            chapter_records = by_book_chapter.get(key, [])
            markers = list(verse.finditer(block.group(3)))
            for record in chapter_records:
                target = int(record["verse"])
                marker_index = next(
                    (index for index, marker in enumerate(markers) if int(marker.group(1)) == target),
                    None,
                )
                # The opening verse of each chapter is unnumbered in the
                # source and begins with its decorated drop-cap letter.
                first_verse = target == 1 and markers and int(markers[0].group(1)) == 2
                if marker_index is None and first_verse:
                    marker_index = -1
                if marker_index is None:
                    raise RuntimeError(f"Could not locate verse {key[0]} {key[1]}:{target} in {page.name}.")

                if first_verse and marker_index == -1:
                    # The decorated drop cap splits the first word into two
                    # text nodes; keep both halves together as the verse text.
                    insertion = re.search(r"\.[^.!?]*</p>\s*$", block.group(3))
                    offset = insertion.end() if insertion else block.group(3).rfind("</p>")
                    if offset < 0:
                        offset = len(block.group(3))
                    replacements.append((block.start(3) + offset, 0, figure(record)))
                    inserted += 1
                    continue

                start = markers[marker_index].end()
                next_marker = markers[0] if first_verse and marker_index == -1 else (
                    markers[marker_index + 1] if marker_index + 1 < len(markers) else None
                )
                end = next_marker.start() if next_marker else len(block.group(3))
                excerpt = block.group(3)[start:end]
                sentence_breaks = list(sentence_end.finditer(excerpt))
                if sentence_breaks:
                    punctuation = sentence_breaks[-1]
                    offset = start + punctuation.end()
                elif next_marker:
                    # No sentence-ending punctuation at this verse boundary;
                    # keep the verse text as a single paragraph and insert here.
                    offset = next_marker.start()
                else:
                    paragraph_end = block.group(3).rfind("</p>")
                    offset = paragraph_end if paragraph_end >= 0 else len(block.group(3))

                replacements.append((block.start(3) + offset, 0, figure(record)))
                inserted += 1

        for offset, length, markup in sorted(replacements, reverse=True):
            source = source[:offset] + markup + source[offset + length:]
        book_match = re.search(r'<h1 class="title">(.*?)</h1>', source, re.DOTALL)
        book_title = html.unescape(re.sub(r"<[^>]+>", "", book_match.group(1))).strip() if book_match else slug.replace("-", " ").title()
        source = add_seo_metadata(
            source,
            f"{slug}.html",
            f"{book_title} — King James Version",
            f"Read {book_title} in the King James Version, with chapter navigation, historical illustrations, and free EPUB downloads.",
        )
        successful_pages.append((page, source))

    if inserted != len(records):
        raise RuntimeError(f"Inserted {inserted} illustrations from a {len(records)}-item manifest.")
    # Commit modified HTML only once every verse reference has been validated.
    for page, source in successful_pages:
        page.write_text(source, encoding="utf-8", newline="")
    return inserted


def build_image_index(records: list[dict[str, object]]) -> None:
    """Create a visual catalogue linking every illustration and cited Bible passage."""
    by_book: dict[str, list[dict[str, object]]] = {slug: [] for slug in BOOKS}
    slug_by_name = {
        re.sub(r"[^a-z0-9]+", "", slug.replace("-", " ").lower()): slug
        for slug in BOOKS
    }
    for record in records:
        name_key = re.sub(r"[^a-z0-9]+", "", str(record["book"]).lower())
        slug = slug_by_name.get(name_key)
        if not slug:
            raise RuntimeError(f"No book page found for illustration reference {record['book']}.")
        by_book[slug].append(record)

    sections = []
    for slug, entries in by_book.items():
        if not entries:
            continue
        book_title = slug.replace("-", " ").title()
        cards = []
        for record in sorted(entries, key=lambda item: (int(item["chapter"]), int(item["verse"]))):
            image = html.escape(str(record["image"]), quote=True)
            caption = html.escape(str(record["caption"]))
            reference = f"{record['book']} {record['chapter']}:{record['verse']}"
            cards.append(
                '<li class="image-index-card">'
                f'<a class="image-index-image-link" href="reader-images/{image}" target="_blank" rel="noopener">'
                f'<img src="reader-images/{image}" alt="{caption}" loading="lazy" decoding="async">'
                f'<span>{caption}</span></a>'
                f'<a class="image-index-reference" href="{slug}.html#{slug}-{record["chapter"]}">'
                f'Read {html.escape(reference)} →</a>'
                '</li>'
            )
        sections.append(
            f'<section class="image-index-book" id="images-{slug}">'
            f'<h2>{html.escape(book_title)}</h2><ul class="image-index-grid">'
            + "".join(cards)
            + "</ul></section>"
        )

    title = "Bible illustration index"
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title} · The Holy Bible</title><link rel="stylesheet" href="styles.css">'
        '</head><body><main class="image-index-page">'
        '<nav class="image-index-nav" aria-label="Page navigation"><a href="index.html">← The Holy Bible</a></nav>'
        f'<h1>{title}</h1>'
        f'<p class="image-index-intro">Browse all {len(records)} illustrations. Select an image to open its full-size version, or follow its reference to the passage it illustrates.</p>'
        + "".join(sections)
        + '</main></body></html>'
    )
    page = add_seo_metadata(
        page,
        "images.html",
        "Bible Illustration Index — The Holy Bible",
        f"Browse and open all {len(records)} historical Bible illustrations, organized by book and linked to their King James Version passages.",
    )
    (SITE / "images.html").write_text(page, encoding="utf-8", newline="")


def add_seo_metadata(document: str, page_name: str, title: str, description: str) -> str:
    """Make each public HTML page discoverable and self-canonical."""
    canonical = SITE_URL if page_name == "index.html" else SITE_URL + page_name
    title = html.escape(title, quote=True)
    description = html.escape(description, quote=True)
    tags = []
    if not re.search(r'<link[^>]+rel=["\']canonical["\']', document, re.IGNORECASE):
        tags.append(f'<link rel="canonical" href="{canonical}">')
    if not re.search(r'<meta[^>]+name=["\']description["\']', document, re.IGNORECASE):
        tags.append(f'<meta name="description" content="{description}">')
    if not re.search(r'<meta[^>]+name=["\']robots["\']', document, re.IGNORECASE):
        tags.append('<meta name="robots" content="index,follow,max-image-preview:large">')
    tags.extend([
        f'<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:description" content="{description}">',
        f'<meta property="og:url" content="{canonical}">',
        f'<meta property="og:image" content="{SITE_URL}cover-vector.svg">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{title}">',
        f'<meta name="twitter:description" content="{description}">',
        f'<meta name="twitter:image" content="{SITE_URL}cover-vector.svg">',
    ])
    block = "<!-- Bible SEO metadata -->\n" + "\n".join(tags) + "\n<!-- /Bible SEO metadata -->"
    marker = re.compile(r"<!-- Bible SEO metadata -->.*?<!-- /Bible SEO metadata -->", re.DOTALL)
    if marker.search(document):
        return marker.sub(block, document, count=1)
    return re.sub(r"</head>", block + "\n</head>", document, count=1, flags=re.IGNORECASE)


def write_crawler_files() -> None:
    """Publish an allow-all robots policy and sitemap for all indexable HTML pages."""
    pages = ["index.html", *(f"{slug}.html" for slug in BOOKS), "images.html"]
    sitemap_ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
    root = ET.Element(f"{{{sitemap_ns}}}urlset")
    lastmod = datetime.now(timezone.utc).date().isoformat()
    for page in pages:
        entry = ET.SubElement(root, f"{{{sitemap_ns}}}url")
        location = SITE_URL if page == "index.html" else SITE_URL + page
        ET.SubElement(entry, f"{{{sitemap_ns}}}loc").text = location
        ET.SubElement(entry, f"{{{sitemap_ns}}}lastmod").text = lastmod
    (SITE / "sitemap.xml").write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    (SITE / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}sitemap.xml\n",
        encoding="utf-8",
        newline="",
    )


def pandoc_command() -> list[str]:
    quarto = shutil.which("quarto")
    if not quarto:
        raise RuntimeError("Quarto must be installed to build per-book EPUB files.")
    probe = subprocess.run([quarto, "pandoc", "--version"], cwd=ROOT, capture_output=True, text=True, check=True)
    version = re.search(r"pandoc\s+(\d+(?:\.\d+){1,2})", probe.stdout)
    if not version:
        raise RuntimeError("Could not identify the Pandoc executable bundled with Quarto.")

    quarto_home = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Quarto"
    bundled = quarto_home / "share" / "pandoc" / version.group(1) / "pandoc.exe"
    if bundled.is_file():
        return [str(bundled)]
    return [quarto, "pandoc"]


def build_epubs() -> None:
    output = SITE / "ebooks"
    output.mkdir(parents=True, exist_ok=True)
    for index, slug in enumerate(BOOKS, start=1):
        page = SITE / f"{slug}.html"
        target = output / f"{slug}.epub"
        title = slug.replace("-", " ").title()
        command = pandoc_command() + [
            "--from=html",
            "--to=epub3",
            "--resource-path=" + str(SITE),
            "--epub-cover-image=" + str(ROOT / "cover.png"),
            "--css=" + str(ROOT / "styles.css"),
            "--metadata",
            "title=" + title,
            "--toc",
            "--toc-depth=5",
            "--output=" + str(target),
        ]
        print(f"[{index}/{len(BOOKS)}] Creating {title} EPUB", flush=True)
        document = page.read_text(encoding="utf-8")
        main = re.search(r'<main class="content" id="quarto-document-content">(.*?)</main>', document, re.DOTALL)
        if not main:
            raise RuntimeError(f"Could not extract Bible book content from {page.name}.")
        body = re.sub(r'<a class="reader-ebook-link"[^>]*>.*?</a>\s*', "", main.group(1), flags=re.DOTALL)
        body = body.replace('src="reader-images/', 'src="../reader-images/')
        source_page = output / f"{slug}.source.html"
        source_page.write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{html.escape(title)}</title></head><body>{body}</body></html>",
            encoding="utf-8",
            newline="",
        )
        command.append(str(source_page))
        try:
            subprocess.run(command, cwd=ROOT, check=True)
        finally:
            source_page.unlink(missing_ok=True)
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"Pandoc did not produce the expected EPUB: {target}")


def build_complete_epub() -> None:
    """Merge the book EPUB packages into one accessible whole-Bible EPUB."""
    epub_dir = SITE / "ebooks"
    target = epub_dir / "The-Holy-Bible.epub"
    opf_ns = "http://www.idpf.org/2007/opf"
    dc_ns = "http://purl.org/dc/elements/1.1/"
    xhtml_ns = "http://www.w3.org/1999/xhtml"
    epub_ns = "http://www.idpf.org/2007/ops"
    container_ns = "urn:oasis:names:tc:opendocument:xmlns:container"
    ET.register_namespace("", opf_ns)
    ET.register_namespace("dc", dc_ns)
    ET.register_namespace("epub", epub_ns)
    ET.register_namespace("", xhtml_ns)

    files: dict[str, tuple[bytes, str]] = {}
    manifest_items: list[ET.Element] = []
    spine_ids: list[str] = []
    toc_entries: list[tuple[str, str, list[tuple[str, str]]]] = []
    ids: set[str] = set()

    def add_manifest_item(item_id: str, href: str, media_type: str, properties: str | None = None) -> None:
        if item_id in ids:
            raise RuntimeError(f"Duplicate full-EPUB manifest id: {item_id}")
        ids.add(item_id)
        attributes = {"id": item_id, "href": href, "media-type": media_type}
        if properties:
            attributes["properties"] = properties
        manifest_items.append(ET.Element(f"{{{opf_ns}}}item", attributes))

    # Keep one custom cover for the combined edition.
    files["EPUB/cover.png"] = ((ROOT / "cover.png").read_bytes(), "image/png")
    add_manifest_item("bible-cover-image", "cover.png", "image/png", "cover-image")
    cover_xhtml = (
        '<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">'
        '<head><title>The Holy Bible</title><meta charset="utf-8"/></head>'
        '<body epub:type="cover"><div><img src="cover.png" alt="The Holy Bible, King James Version" '
        'style="display:block;max-width:100%;max-height:95vh;margin:auto"/></div></body></html>'
    ).encode("utf-8")
    files["EPUB/cover.xhtml"] = (cover_xhtml, "application/xhtml+xml")
    add_manifest_item("bible-cover-page", "cover.xhtml", "application/xhtml+xml")
    spine_ids.append("bible-cover-page")

    # Preserve book/chapter navigation from each already-built book EPUB while
    # namespacing its content and assets under that book's directory.
    for slug in BOOKS:
        source_epub = epub_dir / f"{slug}.epub"
        with zipfile.ZipFile(source_epub) as archive:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(f".//{{{container_ns}}}rootfile")
            if rootfile is None or not rootfile.get("full-path"):
                raise RuntimeError(f"Missing package manifest in {source_epub.name}.")
            package_path = rootfile.get("full-path")
            package_dir = posixpath.dirname(package_path)
            package = ET.fromstring(archive.read(package_path))
            manifest = package.find(f"{{{opf_ns}}}manifest")
            source_spine = package.find(f"{{{opf_ns}}}spine")
            if manifest is None or source_spine is None:
                raise RuntimeError(f"Incomplete package manifest in {source_epub.name}.)")

            by_id = {item.get("id"): item for item in manifest.findall(f"{{{opf_ns}}}item")}
            book_prefix = f"books/{slug}/"
            source_nav = next((item for item in by_id.values() if "nav" in item.get("properties", "").split()), None)
            if source_nav is None:
                raise RuntimeError(f"Missing table of contents in {source_epub.name}.")
            nav_path = posixpath.normpath(posixpath.join(package_dir, source_nav.get("href", "")))
            nav_doc = ET.fromstring(archive.read(nav_path))
            toc = next((node for node in nav_doc.iter(f"{{{xhtml_ns}}}ol") if node.get("class") == "toc"), None)
            toc_items = list(toc) if toc is not None else []
            if not toc_items:
                raise RuntimeError(f"Empty table of contents in {source_epub.name}.")

            book_link = toc_items[0].find(f"{{{xhtml_ns}}}a")
            if book_link is None:
                raise RuntimeError(f"Missing book title link in {source_epub.name}.")
            book_title = " ".join("".join(book_link.itertext()).split())
            book_href = book_prefix + book_link.get("href", "")
            chapters: list[tuple[str, str]] = []
            for toc_item in toc_items[1:]:
                link = toc_item.find(f"{{{xhtml_ns}}}a")
                if link is not None:
                    chapters.append((" ".join("".join(link.itertext()).split()), book_prefix + link.get("href", "")))
            toc_entries.append((book_title, book_href, chapters))

            # Copy chapter XHTML in spine reading order and preserve its relative
            # stylesheet/image paths by retaining each book's package layout.
            chapter_item_ids: set[str] = set()
            for reference in source_spine.findall(f"{{{opf_ns}}}itemref"):
                source_item = by_id.get(reference.get("idref"))
                if source_item is None or source_item.get("media-type") != "application/xhtml+xml":
                    continue
                href = source_item.get("href", "")
                if not re.search(r"(?:^|/)text/ch\d+\.xhtml$", href):
                    continue
                source_item_id = source_item.get("id", "chapter")
                new_id = f"book-{slug}-{source_item_id}"
                new_href = book_prefix + href
                source_path = posixpath.normpath(posixpath.join(package_dir, href))
                files["EPUB/" + new_href] = (archive.read(source_path), "application/xhtml+xml")
                properties = source_item.get("properties")
                add_manifest_item(new_id, new_href, "application/xhtml+xml", properties)
                spine_ids.append(new_id)
                chapter_item_ids.add(source_item_id)

            if not chapter_item_ids:
                raise RuntimeError(f"No book chapter content found in {source_epub.name}.")

            # Copy all book-specific non-document resources. Original cover images
            # are omitted because the combined EPUB has a single shared cover.
            for source_item in by_id.values():
                media_type = source_item.get("media-type", "")
                href = source_item.get("href", "")
                properties = source_item.get("properties", "").split()
                if media_type in {"application/xhtml+xml", "application/x-dtbncx+xml"}:
                    continue
                if "cover-image" in properties:
                    continue
                source_path = posixpath.normpath(posixpath.join(package_dir, href))
                if source_path not in archive.namelist():
                    continue
                new_href = book_prefix + href
                files["EPUB/" + new_href] = (archive.read(source_path), media_type)
                add_manifest_item(f"{slug}-{source_item.get('id', 'asset')}", new_href, media_type)

    # EPUB 3 navigation document containing all books and their chapter entries.
    nav_root = ET.Element(f"{{{xhtml_ns}}}html", {"lang": "en", "{http://www.w3.org/XML/1998/namespace}lang": "en"})
    nav_head = ET.SubElement(nav_root, f"{{{xhtml_ns}}}head")
    ET.SubElement(nav_head, f"{{{xhtml_ns}}}title").text = "Contents — The Holy Bible"
    nav_body = ET.SubElement(nav_root, f"{{{xhtml_ns}}}body")
    nav = ET.SubElement(nav_body, f"{{{xhtml_ns}}}nav", {f"{{{epub_ns}}}type": "toc", "id": "toc"})
    ET.SubElement(nav, f"{{{xhtml_ns}}}h1").text = "The Holy Bible"
    book_list = ET.SubElement(nav, f"{{{xhtml_ns}}}ol")
    for title, href, chapters in toc_entries:
        book_item = ET.SubElement(book_list, f"{{{xhtml_ns}}}li")
        ET.SubElement(book_item, f"{{{xhtml_ns}}}a", {"href": href}).text = title
        if chapters:
            chapter_list = ET.SubElement(book_item, f"{{{xhtml_ns}}}ol")
            for chapter_title, chapter_href in chapters:
                chapter_item = ET.SubElement(chapter_list, f"{{{xhtml_ns}}}li")
                ET.SubElement(chapter_item, f"{{{xhtml_ns}}}a", {"href": chapter_href}).text = chapter_title
    nav_bytes = ET.tostring(nav_root, encoding="utf-8", xml_declaration=True)
    files["EPUB/nav.xhtml"] = (nav_bytes, "application/xhtml+xml")
    add_manifest_item("bible-navigation", "nav.xhtml", "application/xhtml+xml", "nav")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    package_root = ET.Element(
        f"{{{opf_ns}}}package",
        {"version": "3.0", "unique-identifier": "bible-identifier", "{http://www.w3.org/XML/1998/namespace}lang": "en"},
    )
    metadata = ET.SubElement(package_root, f"{{{opf_ns}}}metadata")
    ET.SubElement(metadata, f"{{{dc_ns}}}identifier", {"id": "bible-identifier"}).text = f"urn:uuid:{uuid.uuid4()}"
    ET.SubElement(metadata, f"{{{dc_ns}}}title").text = "The Holy Bible — King James Version"
    ET.SubElement(metadata, f"{{{dc_ns}}}language").text = "en"
    ET.SubElement(metadata, f"{{{opf_ns}}}meta", {"property": "dcterms:modified"}).text = now
    package_manifest = ET.SubElement(package_root, f"{{{opf_ns}}}manifest")
    for item in manifest_items:
        package_manifest.append(item)
    spine = ET.SubElement(package_root, f"{{{opf_ns}}}spine")
    for item_id in spine_ids:
        ET.SubElement(spine, f"{{{opf_ns}}}itemref", {"idref": item_id})
    package_bytes = ET.tostring(package_root, encoding="utf-8", xml_declaration=True)

    container_root = ET.Element(f"{{{container_ns}}}container", {"version": "1.0"})
    rootfiles = ET.SubElement(container_root, f"{{{container_ns}}}rootfiles")
    ET.SubElement(rootfiles, f"{{{container_ns}}}rootfile", {
        "full-path": "EPUB/package.opf",
        "media-type": "application/oebps-package+xml",
    })
    container_bytes = ET.tostring(container_root, encoding="utf-8", xml_declaration=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container_bytes)
        archive.writestr("EPUB/package.opf", package_bytes)
        for path, (content, _) in files.items():
            archive.writestr(path, content, compress_type=zipfile.ZIP_DEFLATED)
    print(f"Created complete Bible EPUB: {target} ({target.stat().st_size:,} bytes)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--html-only",
        action="store_true",
        help="Insert illustrations and build the image index/SEO files without rebuilding EPUBs.",
    )
    args = parser.parse_args()
    if set(book_files()) != set(BOOKS) or len(book_files()) != len(BOOKS):
        raise RuntimeError("The ebook book list is out of sync with _quarto-html.yml.")
    if not IMAGE_MANIFEST.is_file():
        raise RuntimeError("Run scripts/prepare_illustrations.py before building ebooks.")
    records = json.loads(IMAGE_MANIFEST.read_text(encoding="utf-8"))
    print(f"Adding {len(records)} illustrations to their referenced verses.", flush=True)
    insert_illustrations(records)
    build_image_index(records)
    index_page = SITE / "index.html"
    index_html = index_page.read_text(encoding="utf-8")
    index_html = add_seo_metadata(
        index_html,
        "index.html",
        "The Holy Bible — King James Version",
        "Read the complete King James Version of the Holy Bible, browse all 66 books, and download the complete EPUB or individual books free.",
    )
    index_page.write_text(index_html, encoding="utf-8", newline="")
    if not args.html_only:
        build_epubs()
        build_complete_epub()
    write_crawler_files()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"Ebook build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
