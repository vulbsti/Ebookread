"""User-visible promises of the reader, checked against the real GTK + WebKit app."""

from __future__ import annotations

import pytest

FORMATS = {
    # fixture -> (expected title, expected TOC labels, has text layer)
    "epub3.epub": ("Fixture Three", ["Part One", "One: Beginnings", "Two: Middles", "Part Two",
                                     "Three: Late Section", "Notes"], True),
    "epub2.epub": ("Fixture Two", ["First Chapter", "Second Chapter", "Second, Later Part"], True),
    "empty_meta.epub": ("empty meta", [], True),
    "fixture.fb2": ("Fixture FB2", ["Chapter One", "Chapter Two"], True),
    "outline.pdf": ("Fixture PDF", ["Opening", "Development", "Resolution"], True),
    "comic.cbz": ("comic", None, False),
}


@pytest.mark.parametrize("name", FORMATS)
def test_every_format_opens_with_title_and_contents(run_app, books, name):
    title, toc, has_text = FORMATS[name]
    r = run_app("open", books[name])
    assert r["errors"] == []
    assert not r["content"]["error_shown"]
    assert r["window_title"] == title
    assert r["db_title"] == title
    if toc is not None:
        assert r["toc_labels"] == toc
    if has_text:
        assert r["content"]["text_len"] > 0


@pytest.mark.parametrize("name", ["epub3.epub", "epub2.epub", "fixture.fb2", "outline.pdf"])
def test_every_toc_entry_brings_its_section_on_screen(run_app, books, name):
    r = run_app("toc", books[name])["result"]
    assert r["entries"] > 0
    assert r["not_on_screen"] == []


def test_reopening_returns_to_the_exact_place_and_open_with_switches_books(run_app, books):
    r = run_app("reopen", books["epub3.epub"], books["epub2.epub"])
    # Leaving the reader by any route releases the book and saves progress.
    assert r["after_pop"]["resolver_open"] is False
    assert r["after_pop"]["token"] is None
    assert r["after_pop"]["card_fraction"] == pytest.approx(r["saved"]["fraction"], abs=1e-4)
    # The first position reported after reopening is the saved one (no transient jump).
    assert r["restored"]["cfi"] == r["saved"]["cfi"]
    # "Open with" while running opens the new book.
    assert r["second_open_title"] == "Fixture Two"
    assert r["second_open_text"] > 0


def test_book_scripts_never_run_and_external_links_go_through_python(run_app, books):
    r = run_app("security", books["evil.epub"])
    assert r["script_beacons"] == []
    assert r["excerpt_has_script_source"] is False
    assert r["clicked"] is True
    assert r["external_links"] == ["https://example.org/evil"]
    assert r["page_uri"] == "ebookread://app/reader.html"


def test_saved_theme_and_font_apply_to_the_first_page(run_app, books):
    r = run_app("open", books["epub3.epub"],
                settings={"theme": "dark", "font_size": 26, "font_family": "Georgia, serif"})
    assert r["content"]["bg"] == "rgb(30, 30, 34)"
    assert r["content"]["html_font_size"] == "26px"
    assert r["content"]["body_font_family"].startswith("Georgia")


# ---------------------------------------------------------------- Phase 2: navigation

# One app run covers the whole navigation flow; the tests below each check one promise.
_NAV_CACHE: dict = {}


def _nav(run_app, books) -> dict:
    if "r" not in _NAV_CACHE:
        _NAV_CACHE["r"] = run_app("nav", books["epub3.epub"])
    return _NAV_CACHE["r"]


def test_footnote_opens_in_place_without_moving_the_reader(run_app, books):
    fn = _nav(run_app, books)["footnote"]
    assert fn["popover_open"] is True
    assert fn["text"] == "1. The footnote text lives here."
    assert fn["position_unchanged"] is True


def test_going_to_a_note_and_back_returns_to_the_exact_spot(run_app, books):
    r = _nav(run_app, books)
    assert r["goto_note"]["index"] == 3            # the notes section
    assert r["goto_note"]["popover_open"] is False
    assert r["goto_note"]["back_button_visible"] is True
    assert r["history_back"]["returned"] is True   # same CFI as before the jump
    assert r["history_back"]["can_go_forward"] is True


def test_contents_highlights_the_chapter_being_read(run_app, books):
    t = _nav(run_app, books)["toc_current"]
    assert t["selected"] == "Three: Late Section"
    assert t["footer_chapter"] == "Three: Late Section"
    assert "in chapter" in t["footer_detail"]


def test_search_finds_text_and_jumps_to_its_chapter(run_app, books):
    s = _nav(run_app, books)["search"]
    assert s["count"] == 1 and s["status"] == "1 match"
    assert s["index_after_step"] == 2


def test_dragging_the_scrubber_seeks_once_to_where_it_stopped(run_app, books):
    start, end = _nav(run_app, books)["scrub"]["span"]
    assert start - 0.01 <= 0.30 <= end + 0.01  # the final value (30%) is on screen


def test_bookmark_names_the_chapter_and_keeps_the_visible_text(run_app, books):
    bm = _nav(run_app, books)["bookmark"]
    chapter_words = {"One: Beginnings": "Alpha", "Two: Middles": "Beta",
                     "Part Two": "Gamma", "Three: Late Section": "Delta"}
    chapter = bm["label"].rsplit(" · ", 1)[0]
    assert chapter in chapter_words, bm["label"]
    assert chapter_words[chapter] in bm["excerpt"]  # label and visible text agree


def test_page_turns_animate_and_always_move_forward_across_chapters(run_app, books):
    t = run_app("turns", books["epub2.epub"])["turns"]
    assert t["animated"] is True
    fr = t["fractions"]
    moving = [b for a, b in zip(fr, fr[1:]) if b < 1]
    assert all(b > a for a, b in zip(fr, fr[1:]) if b < 1), fr
    assert moving, "no page turn advanced"
    assert 1 in t["sections"]                      # crossed into the second chapter
    assert t["max_ms"] < 1500                      # no turn stalls


# ---------------------------------------------------------------- Phase 3: readability

DARK_FG = "rgb(222, 222, 228)"


def test_my_formatting_overrides_the_book_font_and_spacing(run_app, books):
    st = run_app("style", books["epub3.epub"], settings={
        "font_family": "'Noto Serif', serif", "font_size": 20, "paragraph_spacing": "large"})["style"]
    assert st["body_font_family"].startswith("\"Noto Serif\"") or st["body_font_family"].startswith("Noto Serif")
    assert st["html_font_size"] == "20px"
    assert st["p_margin_bottom"] == "24px"  # 1.2em at 20px


def test_book_formatting_keeps_the_publisher_font_but_not_the_size(run_app, books):
    st = run_app("style", books["epub3.epub"], settings={
        "publisher_formatting": True, "font_family": "'Noto Serif', serif", "font_size": 22})["style"]
    assert "DejaVu Sans Mono" in st["body_font_family"]
    assert st["html_font_size"] == "22px"


def test_dark_theme_keeps_text_the_book_coloured_black_readable(run_app, books):
    st = run_app("style", books["epub3.epub"], settings={"theme": "oled"})["style"]
    assert st["bg"] == "rgb(0, 0, 0)"
    assert st["inked_color"] == "rgb(212, 212, 216)"


def test_contrast_and_grayscale_sliders_filter_the_page(run_app, books):
    st = run_app("style", books["epub3.epub"], settings={"contrast": 120, "saturation": 0})["style"]
    assert st["host_filter"] == "contrast(120%) saturate(0%)"


def test_pdf_zoom_and_dark_inversion_apply_to_pdfs_but_not_comics(run_app, books):
    pdf = run_app("style", books["outline.pdf"], settings={"fxl_zoom": "fit-width", "theme": "dark"})["style"]
    assert pdf["renderer"] == "foliate-fxl"
    assert pdf["zoom"] == "fit-width"
    assert pdf["host_filter"].startswith("invert(1)")
    comic = run_app("style", books["comic.cbz"], settings={"fxl_zoom": "150", "theme": "dark"})["style"]
    assert comic["zoom"] == "1.5"
    assert "invert" not in comic["host_filter"]


def test_hiding_controls_never_reflows_and_auto_hide_follows_reading(run_app, books):
    r = run_app("chrome", books["epub3.epub"])
    assert r["hide"] == {"revealed": False, "same_cfi": True, "same_height": True}
    assert r["after_turn"]["revealed"] is False      # turning a page hides the toolbars
    assert r["after_edge"]["revealed"] is True       # pointer at the top edge shows them
    assert r["auto_hide_off"]["revealed"] is True    # setting off: they stay


# ---------------------------------------------------------------- Phase 4: library

def test_library_imports_folders_covers_pdfs_continues_and_relinks(run_app, books, tmp_path):
    import shutil
    shelf = tmp_path / "shelf"
    shutil.copytree(books["epub3.epub"].parent, shelf)
    shutil.copy(books["epub3.epub"], shelf / "duplicate.epub")
    r = run_app("library", shelf)
    assert r["progress_shown"] is True
    assert r["import"] == {"added": len(books), "duplicates": 1, "failed": 0, "progress_hidden": True}
    assert r["cards"] == len(books)
    assert r["continue_before"] is False              # nothing opened yet
    assert r["pdf_cover_before"] is None
    assert r["pdf_cover_after"] is True               # captured on first open
    assert r["continue_after"] is True                # the PDF heads "Continue Reading"
    assert r["missing_flag"] is True
    assert r["missing_dialog"] == "Book File Not Found"
    assert r["relinked_open"] == {"id": True, "title": "Fixture Two"}
