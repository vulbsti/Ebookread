"""Drives the real Ebookread app (GTK4 + WebKitGTK) through a scenario and writes JSON results.

Usage: python -m tests.integration.driver <scenario> <out.json> <book> [more books]

Run with XDG_CONFIG_HOME / XDG_DATA_HOME / XDG_CACHE_HOME pointing at a throwaway
directory. Scenarios are generators that yield:
  float                  -> wait that many seconds
  ("until", pred, secs)  -> poll pred() until true (raises TimeoutError otherwise)
  ("js", body)           -> run async JS (function body, may `await`); the generator receives its result
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gio, GLib, WebKit  # noqa: E402

from epubread.main import EbookreadApp  # noqa: E402
from epubread.ui import reader_view as rv  # noqa: E402

RAW: list[str] = []
MSGS: list[dict] = []

_orig_on_js = rv.ReaderView._on_js_message


def _spy(self, ucm, js_val):
    raw = js_val.to_string()
    RAW.append(raw)
    try:
        MSGS.append(json.loads(raw))
    except ValueError:
        pass
    return _orig_on_js(self, ucm, js_val)


rv.ReaderView._on_js_message = _spy


class Driver:
    def __init__(self, app: EbookreadApp) -> None:
        self.app = app

    @property
    def win(self):
        return self.app.props.active_window

    @property
    def reader(self):
        return self.win.reader_view

    def msgs(self, mtype: str, current: bool = True) -> list[dict]:
        tok = self.reader._token
        return [m for m in MSGS if m.get("type") == mtype and (not current or m.get("token") == tok)]

    def wait_ready(self, secs: float = 25):
        yield ("until", lambda: bool(self.msgs("ready") or self.msgs("error")), secs)
        yield ("until", lambda: bool(self.msgs("relocate") or self.msgs("error")), secs)
        yield 0.4

    def content_probe(self):
        return (yield ("js", """
            const v = document.querySelector('foliate-view');
            const docs = (v?.renderer?.getContents?.() || []).map(c => c.doc).filter(Boolean);
            const doc = docs[0];
            const cs = el => el ? getComputedStyle(el) : null;
            return {
              text_len: docs.reduce((n, d) => n + (d.body?.innerText?.trim().length || 0), 0),
              bg: cs(doc?.body)?.backgroundColor ?? null,
              html_font_size: cs(doc?.documentElement)?.fontSize ?? null,
              body_font_family: cs(doc?.body)?.fontFamily ?? null,
              error_shown: !document.getElementById('error').hidden,
              page_uri: location.href,
            };"""))


def _flat(toc):
    for t in toc or []:
        yield t
        yield from _flat(t.get("subitems"))


# ---------------------------------------------------------------- scenarios

def scenario_open(d: Driver, books: list[Path], out: dict):
    yield from d.wait_ready()
    ready = (d.msgs("ready") or [{}])[-1]
    book = d.reader.current_book
    out["errors"] = [m.get("message") for m in d.msgs("error")]
    out["toc_labels"] = [t["label"] for t in _flat(ready.get("toc"))]
    out["metadata"] = ready.get("metadata")
    out["window_title"] = d.reader.title_widget.get_title()
    out["db_title"] = d.win.db.get_book(book.id).title if book else None
    out["content"] = yield from d.content_probe()


def scenario_toc(d: Driver, books: list[Path], out: dict):
    yield from d.wait_ready()
    out["result"] = yield ("js", """
        const v = document.querySelector('foliate-view');
        const flat = [];
        (function w(a) { for (const i of a || []) { flat.push(i); w(i.subitems); } })(v.book.toc);
        const bad = [];
        for (const t of flat) {
          if (!t.href) continue;
          const target = v.resolveNavigation(t.href);
          await v.goTo(t.href);
          await new Promise(r => setTimeout(r, 80));
          const onScreen = v.renderer.getContents().map(c => c.index);
          if (!target || !onScreen.includes(target.index)) bad.push([t.label, target?.index, onScreen]);
        }
        return { entries: flat.length, not_on_screen: bad };""")


def scenario_reopen(d: Driver, books: list[Path], out: dict):
    yield from d.wait_ready()
    yield ("js", "await document.querySelector('foliate-view').goToFraction(0.55); return true;")
    yield 0.8
    saved = d.msgs("relocate")[-1]
    out["saved"] = {"cfi": saved.get("cfi"), "fraction": saved.get("fraction")}

    d.win.nav_view.pop()  # same path as the header back button, Esc, or a swipe
    yield 0.6
    out["after_pop"] = {
        "resolver_open": d.win.resolver.active_path is not None,
        "token": d.reader._token,
        "card_fraction": d.win.library_view.flowbox.get_child_at_index(0).get_child().book.book_fraction,
    }

    lv = d.win.library_view
    lv._on_card_activated(lv.flowbox, lv.flowbox.get_child_at_index(0))
    yield from d.wait_ready()
    first = d.msgs("relocate")[0]
    out["restored"] = {"cfi": first.get("cfi"), "fraction": first.get("fraction")}

    if len(books) > 1:  # "Open with" while the app is already running
        d.app.open([Gio.File.new_for_path(str(books[1]))], "")
        yield ("until", lambda: d.reader.current_book is not None
               and Path(d.reader.current_book.file_path).name == books[1].name, 10)
        yield from d.wait_ready()
        out["second_open_title"] = d.reader.title_widget.get_title()
        out["second_open_text"] = (yield from d.content_probe())["text_len"]


def scenario_security(d: Driver, books: list[Path], out: dict):
    yield from d.wait_ready()
    yield 1.5
    out["clicked"] = yield ("js", """
        const v = document.querySelector('foliate-view');
        const doc = v.renderer.getContents()[0].doc;
        const a = doc.getElementById('ext');
        if (!a) return false;
        a.click();
        return true;""")
    yield 0.8
    out["script_beacons"] = [m for m in MSGS if m.get("type") == "BOOK_SCRIPT_RAN"]
    out["excerpt_has_script_source"] = any("BOOK_SCRIPT_RAN" in str(m.get("excerpt", "")) for m in d.msgs("relocate"))
    out["external_links"] = [m.get("url") for m in d.msgs("link_external")]
    out["page_uri"] = d.reader.webview.get_uri()


def _toc_target(d: Driver, label: str):
    return next(n.target for n in d.reader.toc_panel.entries if n.label == label)


def _where(d: Driver):
    return (yield ("js", """
        const v = document.querySelector('foliate-view');
        return { cfi: v.lastLocation?.cfi ?? null, index: v.lastLocation?.section?.current ?? null,
                 fraction: v.lastLocation?.fraction ?? null,
                 // the visible spread as a range of the whole book
                 span: v.lastLocation?.location
                   ? [v.lastLocation.location.current / v.lastLocation.location.total,
                      (v.lastLocation.location.next + 1) / v.lastLocation.location.total] : null,
                 footnote_open: !document.getElementById('footnote').hidden,
                 footnote_text: document.getElementById('footnote-body').querySelector('foliate-view')
                   ?.renderer?.getContents?.()[0]?.doc?.body?.innerText?.trim() ?? '' };"""))


def scenario_nav(d: Driver, books: list[Path], out: dict):
    yield from d.wait_ready()
    r = d.reader

    # Footnote: shown in place, reading position untouched.
    yield ("js", """
        const v = document.querySelector('foliate-view');
        const { doc, index } = v.renderer.getContents()[0];
        const a = doc.getElementById('r1');
        const range = doc.createRange(); range.selectNode(a);
        await v.goTo(v.getCFI(index, range));
        return true;""")
    yield 0.8
    before = yield from _where(d)
    yield ("js", """
        const v = document.querySelector('foliate-view');
        v.renderer.getContents()[0].doc.getElementById('r1').click();
        return true;""")
    yield ("until", lambda: bool(d.msgs("footnote")), 8)
    yield 1.0
    during = yield from _where(d)
    out["footnote"] = {
        "message": bool(d.msgs("footnote")),
        "popover_open": during["footnote_open"],
        "text": during["footnote_text"],
        "position_unchanged": during["cfi"] == before["cfi"],
    }

    # "Go to note", then Back returns to the exact reading spot.
    yield ("js", "document.getElementById('footnote-goto').click(); return true;")
    yield 1.0
    at_note = yield from _where(d)
    out["goto_note"] = {"index": at_note["index"], "popover_open": at_note["footnote_open"],
                        "can_go_back": r.can_go_back, "back_button_visible": r.history_back_btn.get_visible()}
    r.history_back()
    yield 1.0
    after = yield from _where(d)
    out["history_back"] = {"returned": after["cfi"] == before["cfi"], "index": after["index"],
                           "can_go_forward": r.can_go_forward}

    # TOC: the entry for where you are is highlighted, the footer names the chapter.
    r.go_to(_toc_target(d, "Three: Late Section"))
    yield 1.2
    item = r.toc_panel._selection.get_selected_item()
    out["toc_current"] = {"selected": item.get_item().label if item else None,
                          "footer_chapter": r.chapter_label.get_text(),
                          "footer_detail": r.chapter_detail.get_text()}

    # Search: results stream in; stepping jumps into the right chapter.
    sp = r.search_panel
    sp.entry.set_text("Delta paragraph 7")
    sp._on_activate(1)
    yield ("until", lambda: sp.status.get_text().endswith(("match", "matches")), 15)
    out["search"] = {"count": sp.result_count, "status": sp.status.get_text()}
    r.go_to(_toc_target(d, "One: Beginnings"))
    yield 1.0
    sp.step(1)
    yield 1.2
    out["search"]["index_after_step"] = (yield from _where(d))["index"]

    # Scrubber: a quick drag seeks once, to where the knob ended.
    for v in (20.0, 45.0, 70.0, 90.0, 30.0):
        r.scrubber.emit("change-value", 0, v)
        yield 0.03
    yield 1.5
    here = yield from _where(d)
    out["scrub"] = {"fraction": here["fraction"], "span": here["span"]}

    # Bookmark carries the chapter title and the visible text.
    r.add_current_bookmark()
    bms = d.win.db.list_bookmarks(r.current_book.id)
    out["bookmark"] = {"label": bms[-1].label if bms else None, "excerpt": bms[-1].excerpt if bms else ""}


def scenario_turns(d: Driver, books: list[Path], out: dict):
    yield from d.wait_ready()
    out["turns"] = yield ("js", """
        const v = document.querySelector('foliate-view');
        await v.goTo(0);
        const crossing = [];
        await new Promise(r => setTimeout(r, 400));
        const times = [], fractions = [], sections = [];
        for (let i = 0; i < 25; i++) {
          const t0 = performance.now();
          await v.next();
          times.push(performance.now() - t0);
          fractions.push(v.lastLocation.fraction);
          sections.push(v.lastLocation.section.current);
          if (i > 0 && sections[i] !== sections[i - 1]) crossing.push(Math.round(times[i]));
          await new Promise(r => setTimeout(r, 120));  // a reader pauses between pages
        }
        const s = [...times].sort((a, b) => a - b);
        return { animated: v.renderer.hasAttribute('animated'), crossing_ms: crossing,
                 median_ms: Math.round(s[12]), p95_ms: Math.round(s[23]), max_ms: Math.round(s[24]),
                 fractions, sections };""")


STYLE_PROBE = """
    const v = document.querySelector('foliate-view');
    const r = v.renderer;
    const doc = r.getContents?.()[0]?.doc;
    const cs = el => el ? getComputedStyle(el) : null;
    const p = doc?.querySelector('p:not(#inked)');
    return {
      renderer: r.localName,
      zoom: r.getAttribute('zoom'),
      margin: r.getAttribute('margin'),
      gap: r.getAttribute('gap'),
      host_filter: document.getElementById('foliate-host').style.filter,
      body_font_family: cs(doc?.body)?.fontFamily ?? null,
      html_font_size: cs(doc?.documentElement)?.fontSize ?? null,
      p_margin_bottom: cs(p)?.marginBottom ?? null,
      p_line_height: cs(p)?.lineHeight ?? null,
      inked_color: cs(doc?.getElementById('inked'))?.color ?? null,
      bg: cs(doc?.body)?.backgroundColor ?? null,
    };"""


def scenario_style(d: Driver, books: list[Path], out: dict):
    yield from d.wait_ready()
    yield 0.5
    out["style"] = yield ("js", STYLE_PROBE)


def scenario_chrome(d: Driver, books: list[Path], out: dict):
    yield from d.wait_ready()
    r = d.reader
    tv = r.toolbar_view
    before = yield from _where(d)
    height_before = r.webview.get_height()

    # Hiding the toolbars must not resize the page (which would reflow the text).
    r.toggle_distraction_free(force_show=False)
    yield 0.8
    hidden = yield from _where(d)
    out["hide"] = {"revealed": tv.get_reveal_top_bars(), "same_cfi": hidden["cfi"] == before["cfi"],
                   "same_height": r.webview.get_height() == height_before}
    r.toggle_distraction_free(force_show=True)
    yield 0.5

    # A page turn from the keyboard hides them; the pointer at an edge brings them back.
    yield ("js", "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight'})); return 1")
    yield 0.8
    out["after_turn"] = {"revealed": tv.get_reveal_top_bars()}
    yield ("js", "document.dispatchEvent(new MouseEvent('mousemove', {clientX: 300, clientY: 400})); "
                 "document.dispatchEvent(new MouseEvent('mousemove', {clientX: 300, clientY: 4})); return 1")
    yield 0.5
    out["after_edge"] = {"revealed": tv.get_reveal_top_bars()}

    # With auto-hide off, turning pages leaves them alone.
    r.config.update(auto_hide_controls=False)
    yield ("js", "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight'})); return 1")
    yield 0.8
    out["auto_hide_off"] = {"revealed": tv.get_reveal_top_bars()}


def scenario_library(d: Driver, books: list[Path], out: dict):
    """books[0] is a folder of books; the app starts on an empty library."""
    lv = d.win.library_view
    folder = books[0]
    lv.import_paths([folder])
    out["progress_shown"] = lv.import_revealer.get_reveal_child()
    yield ("until", lambda: getattr(lv, "last_report", None) is not None, 60)
    rep = lv.last_report
    out["import"] = {"added": len(rep.added), "duplicates": len(rep.duplicates), "failed": len(rep.failed),
                     "progress_hidden": not lv.import_revealer.get_reveal_child()}

    def cards():
        out_ = []
        c = lv.flowbox.get_first_child()
        while c:
            out_.append(c.get_child().book)
            c = c.get_next_sibling()
        return out_

    out["cards"] = len(cards())
    out["continue_before"] = lv.continue_box.get_visible()

    # First open of a PDF fetches its cover from the renderer.
    pdf = next(b for b in cards() if b.file_format == "pdf")
    out["pdf_cover_before"] = pdf.cover_path
    lv.open_book(pdf)
    yield from d.wait_ready()
    yield ("until", lambda: bool(d.win.db.get_book(pdf.id).cover_path), 10)
    out["pdf_cover_after"] = Path(d.win.db.get_book(pdf.id).cover_path).is_file()
    yield ("js", "await document.querySelector('foliate-view').goToFraction(0.5); return 1")
    yield 0.8
    d.win.nav_view.pop()
    yield 0.6
    first_continue = lv.continue_box.get_child_at_index(0)
    out["continue_after"] = first_continue.get_child().book.id == pdf.id if first_continue else False

    # A file moved behind the app's back shows as missing, and can be relinked in place.
    epub = next(b for b in cards() if b.file_path.endswith("epub2.epub"))
    moved = Path(epub.file_path).with_name("moved-away.epub")
    Path(epub.file_path).rename(moved)
    lv.refresh()
    out["missing_flag"] = next(b for b in cards() if b.id == epub.id).missing
    lv.open_book(epub)
    yield 0.5
    dialog = d.win.get_visible_dialog()
    out["missing_dialog"] = dialog.get_heading() if dialog else None
    if dialog:
        dialog.close()
    yield 0.3
    lv.relink(d.win.db.get_book(epub.id), moved)
    yield from d.wait_ready()
    out["relinked_open"] = {"id": d.reader.current_book.id == epub.id,
                            "title": d.reader.title_widget.get_title()}


SCENARIOS = {
    "open": scenario_open,
    "toc": scenario_toc,
    "reopen": scenario_reopen,
    "security": scenario_security,
    "nav": scenario_nav,
    "turns": scenario_turns,
    "style": scenario_style,
    "chrome": scenario_chrome,
    "library": scenario_library,
}
NO_FILE_ON_START = {"library"}


# ---------------------------------------------------------------- runner

def main() -> int:
    name, out_path, *book_args = sys.argv[1:]
    books = [Path(b).resolve() for b in book_args]
    out: dict = {"scenario": name}
    app = EbookreadApp()
    # Never hand off to (or receive files from) another running Ebookread, e.g. the user's.
    app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    driver = Driver(app)
    state = {"gen": None}

    def finish(error: str | None = None) -> None:
        if error:
            out["driver_error"] = error
        Path(out_path).write_text(json.dumps(out, indent=2, default=str))
        app.quit()

    def advance(value=None) -> bool:
        gen = state["gen"]
        try:
            item = gen.send(value)
        except StopIteration:
            finish()
            return False
        except Exception:  # noqa: BLE001
            finish(traceback.format_exc())
            return False

        if isinstance(item, (int, float)):
            GLib.timeout_add(int(item * 1000), lambda: advance() and False)
        elif item[0] == "until":
            _, pred, secs = item
            deadline = GLib.get_monotonic_time() + int(secs * 1e6)

            def poll() -> bool:
                try:
                    ok = pred()
                except Exception:  # noqa: BLE001
                    ok = False
                if ok:
                    advance()
                    return False
                if GLib.get_monotonic_time() > deadline:
                    try:
                        gen.throw(TimeoutError(f"timed out after {secs}s"))
                    except Exception:  # noqa: BLE001
                        finish(traceback.format_exc())
                    return False
                return True

            GLib.timeout_add(50, poll)
        elif item[0] == "js":
            body = "return JSON.stringify(await (async () => {" + item[1] + "})());"

            def done(wv, res) -> None:
                try:
                    v = wv.call_async_javascript_function_finish(res)
                    advance(json.loads(v.to_string()))
                except Exception as exc:  # noqa: BLE001
                    advance({"js_error": str(exc)})

            driver.reader.webview.call_async_javascript_function(body, -1, None, None, None, None, done)
        return False

    def on_startup(_app) -> None:
        GLib.timeout_add(120_000, lambda: finish("global timeout") or False)

    def on_activate_late(_app) -> None:
        if state["gen"] is None:
            state["gen"] = SCENARIOS[name](driver, books, out)
            GLib.idle_add(lambda: advance() and False)

    app.connect("startup", on_startup)
    app.connect_after("activate", on_activate_late)
    app.connect_after("open", lambda a, *_: on_activate_late(a))
    argv = [sys.argv[0]] if name in NO_FILE_ON_START else [sys.argv[0], str(books[0])]
    return app.run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
