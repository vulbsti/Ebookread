"""Unit tests for the non-GUI core: resolver, metadata, library DB, settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from epubread.core.book_parser import EpubArchive, extract_book_metadata, fallback_title
from epubread.core.config import ConfigStore
from epubread.core.db import LibraryDB
from epubread.core.uri_server import BookResourceResolver, ResourceNotFound
from epubread.ui.theme import build_reader_css_vars
from tests.fixtures import build_all


@pytest.fixture(scope="module")
def books(tmp_path_factory) -> dict[str, Path]:
    return build_all(tmp_path_factory.mktemp("books"))


# ---------------------------------------------------------------- resolver

def test_resolver_serves_app_assets_and_the_open_book_from_one_origin(books):
    r = BookResourceResolver()
    html, mtype = r.resolve("ebookread://app/reader.html")
    assert b"reader.js" in html and mtype == "text/html"
    _, js_type = r.resolve("ebookread://app/foliate-js/view.js")
    assert js_type == "application/javascript"

    with pytest.raises(ResourceNotFound):
        r.resolve("ebookread://app/book/raw")  # nothing open yet
    r.open_book(books["epub3.epub"])
    data, _ = r.resolve("ebookread://app/book/raw")
    assert data == books["epub3.epub"].read_bytes()
    r.close_book()
    with pytest.raises(ResourceNotFound):
        r.resolve("ebookread://app/book/raw")


@pytest.mark.parametrize("uri", [
    "ebookread://app/../core/db.py",
    "ebookread://app/%2e%2e/core/db.py",
    "ebookread://book/raw",          # old second origin is gone
    "ebookread://app/missing.js",
])
def test_resolver_refuses_paths_outside_the_web_dir(uri):
    with pytest.raises(ResourceNotFound):
        BookResourceResolver().resolve(uri)


# ---------------------------------------------------------------- metadata

def test_epub_metadata_toc_and_cover(books, tmp_path):
    meta = extract_book_metadata(books["epub3.epub"], cover_dir=tmp_path)
    assert (meta.title, meta.author, meta.file_format) == ("Fixture Three", "Ada Tester", "epub")
    assert meta.cover_path and Path(meta.cover_path).is_file()
    with EpubArchive(books["epub3.epub"]) as epub:
        assert [t.title for t in epub.toc] == ["Part One", "Part Two", "Notes"]
        assert epub.toc[1].children[0].fragment == "late"


def test_epub_without_metadata_falls_back_to_file_name(books, tmp_path):
    meta = extract_book_metadata(books["empty_meta.epub"], cover_dir=tmp_path)
    assert meta.title == fallback_title(books["empty_meta.epub"]) == "empty meta"
    assert meta.author == "Unknown Author"


# ---------------------------------------------------------------- library DB

def test_progress_bookmarks_and_cascading_delete(books, tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    try:
        meta = extract_book_metadata(books["epub3.epub"], cover_dir=tmp_path)
        rec = db.upsert_book(meta.file_path, meta.file_hash, meta.file_format, meta.title, meta.author)
        assert [b.id for b in db.list_books(query="ada")] == [rec.id]

        db.update_progress(rec.id, 2, 0.0, 0.42, cfi="epubcfi(/6/4!/4/2)")
        db.update_progress(rec.id, 2, 0.0, 0.43, cfi=None)  # a missing CFI keeps the last good one
        book = db.get_book(rec.id)
        assert book.book_fraction == pytest.approx(0.43)
        assert book.cfi == "epubcfi(/6/4!/4/2)"

        db.add_bookmark(rec.id, "Two: Middles · 43%", 2, 0.43, cfi=book.cfi)
        assert len(db.list_bookmarks(rec.id)) == 1
        db.delete_book(rec.id)
        assert db.list_bookmarks(rec.id) == []  # foreign keys are on
    finally:
        db.close()


def test_update_metadata_renames_a_book(books, tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    try:
        rec = db.upsert_book(books["fixture.fb2"], "h", "fb2", "fixture", "Unknown Author")
        db.update_metadata(rec.id, "Fixture FB2", "Fiona Tester")
        assert (db.get_book(rec.id).title, db.get_book(rec.id).author) == ("Fixture FB2", "Fiona Tester")
    finally:
        db.close()


# ---------------------------------------------------------------- settings

def test_settings_are_clamped_persisted_and_produce_valid_css(tmp_path):
    cfg = ConfigStore(tmp_path / "settings.json")
    cfg.update(theme="oled", font_size=99, warmth=75)
    assert cfg.settings.font_size == 36
    reloaded = ConfigStore(tmp_path / "settings.json")
    assert reloaded.settings.theme == "oled"
    css = build_reader_css_vars(reloaded.settings)
    assert css["--er-bg"] == "#000000"
    assert css["--er-warm-overlay"].startswith("rgba(255, 168, 64, 0.")


def test_follow_system_theme_resolves_to_light_or_dark():
    from epubread.ui.theme import color_filter, resolve_theme
    from epubread.core.config import ReaderSettings
    assert resolve_theme("system", system_dark=True) == "dark"
    assert resolve_theme("system", system_dark=False) == "light"
    assert resolve_theme("nonsense", system_dark=True) == "sepia"
    assert color_filter(ReaderSettings()) == "none"


def test_old_settings_files_still_load(tmp_path):
    (tmp_path / "settings.json").write_text('{"theme": "dark", "margin_x": 48, "columns": "double", "font_size": "x"}')
    s = ConfigStore(tmp_path / "settings.json").settings
    assert s.theme == "dark" and s.columns == "auto" and s.font_size == 12 and s.margin_pct == 6


# ---------------------------------------------------------------- Phase 4: formats, importer, DB

import shutil
import sqlite3
import struct

from epubread.core.db import SCHEMA_VERSION, compute_file_hash
from epubread.core.formats import _pdf_string, read_cbz, read_fb2, read_mobi, read_pdf
from epubread.core.importer import import_now


def test_every_format_gets_title_author_and_cover_at_import(books, tmp_path):
    expect = {
        "fixture.fb2": ("Fixture FB2", "Fiona Tester", True),
        "comicinfo.cbz": ("Fixture Saga #3: Red Page", "Cara Tester", True),
        "fixture.mobi": ("Fixture Mobi", "Moby Tester", True),
        "outline.pdf": ("Fixture PDF", "Pat Tester", False),  # PDF covers come from first open
    }
    for name, (title, author, has_cover) in expect.items():
        meta = extract_book_metadata(books[name], cover_dir=tmp_path)
        assert (meta.title, meta.author) == (title, author), name
        assert bool(meta.cover_path) is has_cover, name


def test_comic_cover_is_the_first_page_in_natural_order(books, tmp_path):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    meta = extract_book_metadata(books["comicinfo.cbz"], cover_dir=tmp_path)
    r, g, b = GdkPixbuf.Pixbuf.new_from_file(meta.cover_path).get_pixels()[:3]
    assert r > 200 and g < 40 and b < 40  # p1 is red; plain sorting would pick p10 (blue)


def test_pdf_info_strings_decode_escapes_octal_and_utf16():
    assert _pdf_string(rb"(A \(tricky\) title\041)") == "A (tricky) title!"
    assert _pdf_string(b"<FEFF00480069>") == "Hi"
    assert _pdf_string(b"(\xfe\xff\x00O\x00k)") == "Ok"


def test_pdf_info_found_through_an_indirect_reference(tmp_path):
    pdf = tmp_path / "ref.pdf"
    pdf.write_bytes(b"%PDF-1.4\n7 0 obj\n<< /Title (Referenced Title) /Author <FEFF00410042> >>\nendobj\n"
                    b"trailer\n<< /Root 1 0 R /Info 7 0 R >>\n%%EOF\n")
    info = read_pdf(pdf)
    assert (info.title, info.author) == ("Referenced Title", "AB")


def test_unreadable_files_import_by_file_name_or_report_failure(tmp_path):
    (tmp_path / "Broken_Novel.fb2").write_text("<FictionBook><not-closed>")
    (tmp_path / "corrupt.epub").write_bytes(b"not a zip")
    db = LibraryDB(tmp_path / "db.sqlite")
    try:
        report = import_now(db, [tmp_path])
        assert [b.title for b in report.added] == ["Broken Novel"]  # metadata unreadable, still a book
        assert [p.name for p, _ in report.failed] == ["corrupt.epub"]
    finally:
        db.close()


def test_folder_import_skips_duplicates_and_relinks_moved_files(books, tmp_path):
    lib = tmp_path / "lib"
    shutil.copytree(books["epub3.epub"].parent, lib / "shelf")
    shutil.copy(books["epub3.epub"], lib / "copy.epub")
    (lib / "readme.txt").write_text("not a book")
    db = LibraryDB(tmp_path / "db.sqlite")
    try:
        first = import_now(db, [lib])
        assert len(first.added) == len(books) and len(first.duplicates) == 1
        again = import_now(db, [lib])
        assert not again.added and len(again.refreshed) == len(books)

        book = db.get_book_by_path(lib / "shelf" / "epub2.epub")
        db.update_progress(book.id, 1, 0.0, 0.4, cfi="epubcfi(/6/4!/4/2)")
        db.add_bookmark(book.id, "kept", 1, 0.4)
        (tmp_path / "elsewhere").mkdir()
        shutil.move(lib / "shelf" / "epub2.epub", tmp_path / "elsewhere" / "renamed.epub")
        moved = import_now(db, [tmp_path / "elsewhere"])
        assert [b.id for b in moved.relinked] == [book.id]
        found = db.get_book(book.id)
        assert found.file_path.endswith("renamed.epub") and found.book_fraction == pytest.approx(0.4)
        assert [b.label for b in db.list_bookmarks(book.id)] == ["kept"]
    finally:
        db.close()


def test_old_library_database_is_migrated_in_place(books, tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT NOT NULL UNIQUE,
          file_hash TEXT NOT NULL, file_format TEXT NOT NULL, title TEXT NOT NULL,
          author TEXT NOT NULL DEFAULT 'Unknown Author', language TEXT NOT NULL DEFAULT 'en', cover_path TEXT,
          chapter_index INTEGER NOT NULL DEFAULT 0, chapter_fraction REAL NOT NULL DEFAULT 0.0,
          book_fraction REAL NOT NULL DEFAULT 0.0, cfi TEXT, added_at REAL NOT NULL,
          last_opened REAL NOT NULL DEFAULT 0.0);
        CREATE TABLE bookmarks (id INTEGER PRIMARY KEY AUTOINCREMENT,
          book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE, label TEXT NOT NULL,
          chapter_index INTEGER NOT NULL DEFAULT 0, chapter_fraction REAL NOT NULL DEFAULT 0.0, cfi TEXT,
          excerpt TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);""")
    conn.execute("INSERT INTO books (file_path, file_hash, file_format, title, added_at) VALUES (?, 'old', 'epub', 'T', 0)",
                 (str(books["epub3.epub"]),))
    conn.execute("INSERT INTO bookmarks (book_id, label, chapter_fraction, created_at) VALUES (1, 'b', 0.4, 0)")
    conn.commit()
    conn.close()

    db = LibraryDB(path)
    try:
        assert db.schema_version == SCHEMA_VERSION
        assert db.list_bookmarks(1)[0].book_fraction == pytest.approx(0.4)
        assert db.get_book(1).file_hash == compute_file_hash(books["epub3.epub"])
    finally:
        db.close()
    LibraryDB(path).close()  # reopening an up-to-date database is a no-op


def test_removing_a_book_can_be_undone_exactly(books, tmp_path):
    db = LibraryDB(tmp_path / "db.sqlite")
    try:
        rec = db.upsert_book(books["epub3.epub"], "h", "epub", "T")
        db.update_progress(rec.id, 2, 0.0, 0.5, cfi="epubcfi(/6/6!/4/2)")
        db.add_bookmark(rec.id, "mark", 2, 0.5, cfi="epubcfi(/6/6!/4/2)")
        snap = db.delete_book(rec.id)
        assert db.get_book(rec.id) is None and db.list_bookmarks(rec.id) == []
        back = db.restore_book(snap)
        assert back.id == rec.id and back.cfi == "epubcfi(/6/6!/4/2)"
        assert [b.label for b in db.list_bookmarks(rec.id)] == ["mark"]
    finally:
        db.close()


def test_continue_reading_and_search_are_precise(books, tmp_path):
    db = LibraryDB(tmp_path / "db.sqlite")
    try:
        a = db.upsert_book(books["epub3.epub"], "a", "epub", "100% Pure")
        b = db.upsert_book(books["epub2.epub"], "b", "epub", "Other")
        c = db.upsert_book(books["fixture.fb2"], "c", "fb2", "Done")
        db.update_progress(a.id, 0, 0, 0.3)
        db.update_progress(c.id, 0, 0, 1.0)
        assert [x.id for x in db.continue_reading()] == [a.id]  # opened, unfinished; never-opened b excluded
        assert [x.title for x in db.list_books(query="%")] == ["100% Pure"]  # % is literal, not a wildcard
        assert b.id
    finally:
        db.close()
