"""WebKitGTK 6.0 reader page: foliate-js view, sidebar (contents/search/bookmarks), footer."""

from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
gi.require_version("Soup", "3.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango, Soup, WebKit

from ..core.book_parser import covers_dir, fallback_title
from ..core.formats import save_cover
from ..core.config import ConfigStore, ReaderSettings
from ..core.db import BookRecord, LibraryDB
from ..core.uri_server import APP_ORIGIN, CONTENT_SECURITY_POLICY, BookResourceResolver
from .settings_popover import SettingsPopover
from .sidebar import BookmarksPanel, SearchPanel, TocPanel
from .theme import build_reader_css_vars, chrome_css, color_filter, get_palette

READER_URL = f"{APP_ORIGIN}/reader.html"
EXTERNAL_SCHEMES = {"http", "https", "mailto"}
PAGE_MESSAGES = {
    "page_ready", "ready", "relocate", "history", "footnote", "link_external", "error",
    "escape", "toggle_chrome", "search_progress", "search_results", "search_done",
    "user_turn", "edge", "cover",
}
MAX_COVER_B64 = 4 * 1024 * 1024
SCRUB_SETTLE_MS = 150
MAX_SCRUBBER_MARKS = 60


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _section_index(msg: dict) -> int:
    section = msg.get("section")
    return max(0, _int(section.get("current"))) if isinstance(section, dict) else 0


def format_minutes(minutes) -> str | None:
    try:
        m = float(minutes)
    except (TypeError, ValueError):
        return None
    if m != m or m < 0:  # NaN / negative
        return None
    m = round(m)
    if m < 1:
        return "less than a minute"
    if m < 60:
        return f"{m} min"
    h, rest = divmod(m, 60)
    return f"{h} h {rest} min" if rest else f"{h} h"


class ReaderView(Adw.NavigationPage):
    """Distraction-free reading page."""

    _scheme_registered = False

    def __init__(
        self,
        db: LibraryDB,
        config: ConfigStore,
        resolver: BookResourceResolver,
        toast_overlay: Adw.ToastOverlay,
    ) -> None:
        super().__init__(title="Reader", tag="reader")
        self.db = db
        self.config = config
        self.resolver = resolver
        self.toast_overlay = toast_overlay
        self.current_book: BookRecord | None = None
        self._token: str | None = None
        self._pending_open: dict | None = None
        self._last_relocate: dict = {}
        self._chrome_visible = True
        self._scrub_timeout = 0
        self.can_go_back = False
        self.can_go_forward = False

        self._ensure_uri_scheme()

        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_show_sidebar(False)
        self.split_view.set_sidebar_width_fraction(0.28)
        self.split_view.set_min_sidebar_width(270)
        self.split_view.set_max_sidebar_width(400)
        self.split_view.connect("notify::show-sidebar", self._on_sidebar_toggled)
        self.set_child(self.split_view)
        self.split_view.set_sidebar(self._build_sidebar())

        self.toolbar_view = Adw.ToolbarView()
        # The page runs underneath the toolbars, which float over its top and bottom
        # margins. Showing or hiding them therefore never resizes the page (a resize
        # reflows the text and would lose the reader's place).
        self.toolbar_view.set_extend_content_to_top_edge(True)
        self.toolbar_view.set_extend_content_to_bottom_edge(True)
        self.split_view.set_content(self.toolbar_view)

        self._style_manager = Adw.StyleManager.get_default()
        self._style_manager.connect("notify::dark", self._on_system_dark_changed)
        self._chrome_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._chrome_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # The NavigationView adds its own back button to this header bar.
        self.header = Adw.HeaderBar()
        self.header.add_css_class("reader-chrome")
        self.header.add_css_class("top")
        self.toolbar_view.add_top_bar(self.header)

        self.sidebar_btn = Gtk.ToggleButton()
        self.sidebar_btn.set_icon_name("sidebar-show-symbolic")
        self.sidebar_btn.set_tooltip_text("Contents, Search and Bookmarks (Ctrl+T)")
        self.sidebar_btn.bind_property(
            "active", self.split_view, "show-sidebar",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        self.header.pack_start(self.sidebar_btn)

        self.title_widget = Adw.WindowTitle(title="", subtitle="")
        self.header.set_title_widget(self.title_widget)

        bm_btn = Gtk.Button.new_from_icon_name("bookmark-new-symbolic")
        bm_btn.set_tooltip_text("Bookmark this page (Ctrl+D)")
        bm_btn.connect("clicked", lambda _b: self.add_current_bookmark())
        self.header.pack_end(bm_btn)

        self.settings_popover = SettingsPopover(config, self.apply_settings)
        settings_btn = Gtk.MenuButton()
        settings_btn.set_icon_name("font-x-generic-symbolic")
        settings_btn.set_tooltip_text("Typography and Theme")
        settings_btn.set_popover(self.settings_popover)
        self.header.pack_end(settings_btn)

        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler("ebookread", None)
        ucm.connect("script-message-received::ebookread", self._on_js_message)

        self.webview = WebKit.WebView(user_content_manager=ucm)
        wk = self.webview.get_settings()
        wk.set_enable_javascript(True)
        wk.set_enable_smooth_scrolling(True)
        wk.set_javascript_can_open_windows_automatically(False)
        if os.environ.get("EBOOKREAD_DEBUG"):
            wk.set_enable_developer_extras(True)
            wk.set_enable_write_console_messages_to_stdout(True)
        self.webview.connect("decide-policy", self._on_decide_policy)
        self.toolbar_view.set_content(self.webview)

        self.footer = self._build_footer()
        self.toolbar_view.add_bottom_bar(self.footer)
        self._apply_chrome_theme(config.settings)

    # ------------------------------------------------------------ URI scheme

    def _ensure_uri_scheme(self) -> None:
        if ReaderView._scheme_registered:
            return
        ctx = WebKit.WebContext.get_default()
        ctx.register_uri_scheme("ebookread", self._handle_uri_scheme)
        ctx.get_security_manager().register_uri_scheme_as_secure("ebookread")
        ReaderView._scheme_registered = True

    def _handle_uri_scheme(self, request: WebKit.URISchemeRequest) -> None:
        try:
            data, mtype = self.resolver.resolve(request.get_uri())
        except Exception as exc:  # noqa: BLE001 - any failure is a 404 to the page
            request.finish_error(
                GLib.Error.new_literal(Gio.io_error_quark(), str(exc), int(Gio.IOErrorEnum.NOT_FOUND))
            )
            return
        stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
        response = WebKit.URISchemeResponse.new(stream, len(data))
        response.set_content_type(mtype)
        headers = Soup.MessageHeaders.new(Soup.MessageHeadersType.RESPONSE)
        headers.append("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        headers.append("Cache-Control", "no-store")
        response.set_http_headers(headers)
        request.finish_with_response(response)

    def _on_decide_policy(self, _wv, decision, decision_type) -> bool:
        if decision_type == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            return True
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri() or ""
            if urlparse(uri).scheme not in ("ebookread", "blob", "data", "about"):
                decision.ignore()
                return True
        return False

    # ------------------------------------------------------------ layout

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.sidebar_stack = Gtk.Stack()
        self.sidebar_stack.set_vexpand(True)
        self.sidebar_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        switcher = Gtk.StackSwitcher(stack=self.sidebar_stack)
        switcher.set_hexpand(True)
        for side in ("top", "bottom", "start", "end"):
            getattr(switcher, f"set_margin_{side}")(8)
        box.append(switcher)

        self.toc_panel = TocPanel(navigate=lambda t: self.go_to(t, close_sidebar=True))
        self.search_panel = SearchPanel(
            start=lambda q: self._call("search", q),
            clear=lambda: self._call("clearSearch"),
            navigate=lambda cfi: self.go_to(cfi, close_sidebar=False),
        )
        self.bookmarks_panel = BookmarksPanel(
            self.db, navigate=lambda t: self.go_to(t, close_sidebar=True), toast_overlay=self.toast_overlay
        )
        self.sidebar_stack.add_titled(self.toc_panel, "toc", "Contents")
        self.sidebar_stack.add_titled(self.search_panel, "search", "Search")
        self.sidebar_stack.add_titled(self.bookmarks_panel, "bookmarks", "Bookmarks")

        box.append(self.sidebar_stack)
        return box

    def _build_footer(self) -> Gtk.Widget:
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        footer.add_css_class("reader-chrome")
        footer.add_css_class("bottom")

        info = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        info.set_margin_top(4)
        info.set_margin_start(56)
        info.set_margin_end(56)
        self.chapter_label = Gtk.Label(xalign=0.0)
        self.chapter_label.set_hexpand(True)
        self.chapter_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.chapter_label.add_css_class("caption-heading")
        info.append(self.chapter_label)
        self.chapter_detail = Gtk.Label(xalign=1.0)
        self.chapter_detail.add_css_class("caption")
        self.chapter_detail.add_css_class("dim-label")
        self.chapter_detail.add_css_class("numeric")
        info.append(self.chapter_detail)
        footer.append(info)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls.set_margin_start(12)
        controls.set_margin_end(12)
        controls.set_margin_bottom(6)

        self.history_back_btn = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        self.history_back_btn.add_css_class("flat")
        self.history_back_btn.set_tooltip_text("Back to where you were (Alt+Left)")
        self.history_back_btn.set_visible(False)
        self.history_back_btn.connect("clicked", lambda _b: self.history_back())
        controls.append(self.history_back_btn)

        prev_btn = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        prev_btn.add_css_class("flat")
        prev_btn.set_tooltip_text("Previous page")
        prev_btn.connect("clicked", lambda _b: self._call("prev"))
        controls.append(prev_btn)

        self.scrubber = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 0.1)
        self.scrubber.set_hexpand(True)
        self.scrubber.set_draw_value(False)
        self.scrubber.set_has_tooltip(True)
        self.scrubber.connect("change-value", self._on_scrubber_change_value)
        self.scrubber.connect("query-tooltip", self._on_scrubber_tooltip)
        self._reset_scrubber_marks()
        controls.append(self.scrubber)

        self.progress_label = Gtk.Label(label="")
        self.progress_label.add_css_class("caption")
        self.progress_label.add_css_class("numeric")
        self.progress_label.set_width_chars(5)
        controls.append(self.progress_label)

        next_btn = Gtk.Button.new_from_icon_name("go-next-symbolic")
        next_btn.add_css_class("flat")
        next_btn.set_tooltip_text("Next page")
        next_btn.connect("clicked", lambda _b: self._call("next"))
        controls.append(next_btn)

        self.history_forward_btn = Gtk.Button.new_from_icon_name("edit-redo-symbolic")
        self.history_forward_btn.add_css_class("flat")
        self.history_forward_btn.set_tooltip_text("Forward again (Alt+Right)")
        self.history_forward_btn.set_visible(False)
        self.history_forward_btn.connect("clicked", lambda _b: self.history_forward())
        controls.append(self.history_forward_btn)

        footer.append(controls)
        return footer

    # ------------------------------------------------------------ book lifecycle

    def open_book(self, book: BookRecord) -> None:
        self.current_book = book
        self._token = uuid.uuid4().hex
        self._last_relocate = {}
        self.db.touch_opened(book.id)
        self.resolver.open_book(book.file_path)
        self.title_widget.set_title(book.title)
        self.title_widget.set_subtitle(book.author)
        self.chapter_label.set_text("")
        self.chapter_detail.set_text("")
        self.progress_label.set_text("")
        self._reset_scrubber_marks()
        self.scrubber.set_value(book.book_fraction * 100.0)
        self._set_history(False, False)
        self.toc_panel.set_toc([])
        self.search_panel.reset_for_new_book()
        self.bookmarks_panel.load(book.id)
        self._pending_open = {
            "token": self._token,
            "filename": Path(book.file_path).name,
            "lastLocation": book.cfi if book.cfi and book.cfi.startswith("epubcfi(") else None,
            "settings": self._settings_payload(self.config.settings),
            "wantCover": not (book.cover_path and Path(book.cover_path).is_file()),
        }
        self.webview.load_uri(READER_URL)
        self.webview.grab_focus()

    def close_book(self) -> None:
        """Stop listening to the page and release the book. Safe to call twice."""
        self._token = None
        self._pending_open = None
        self.current_book = None
        if self._scrub_timeout:
            GLib.source_remove(self._scrub_timeout)
            self._scrub_timeout = 0
        self.resolver.close_book()
        self.webview.load_uri("about:blank")

    # ------------------------------------------------------------ navigation API (shortcuts use these)

    def go_to(self, target, close_sidebar: bool = True) -> None:
        self._call("goTo", target)
        if close_sidebar:
            self.split_view.set_show_sidebar(False)
            self.focus_reader()

    def focus_reader(self) -> None:
        self.webview.grab_focus()
        self._call("focus")

    def history_back(self) -> bool:
        if not self.can_go_back:
            return False
        self._call("back")
        return True

    def history_forward(self) -> bool:
        if not self.can_go_forward:
            return False
        self._call("forward")
        return True

    def show_panel(self, name: str) -> None:
        """Open the sidebar on a panel; pressing the shortcut again closes it."""
        if self.split_view.get_show_sidebar() and self.sidebar_stack.get_visible_child_name() == name:
            self.split_view.set_show_sidebar(False)
            return
        self.sidebar_stack.set_visible_child_name(name)
        self.toggle_distraction_free(force_show=True)
        self.split_view.set_show_sidebar(True)
        if name == "search":
            self.search_panel.focus()
        elif name == "toc":
            GLib.idle_add(lambda: self.toc_panel.scroll_to_current() and False)

    def _on_sidebar_toggled(self, *_args) -> None:
        if self.split_view.get_show_sidebar():
            if self.sidebar_stack.get_visible_child_name() == "toc":
                GLib.idle_add(lambda: self.toc_panel.scroll_to_current() and False)
        else:
            self.focus_reader()

    # ------------------------------------------------------------ settings

    def _system_dark(self) -> bool:
        # Only meaningful for "Follow system"; other themes force the scheme themselves.
        return self.config.settings.theme == "system" and self._style_manager.get_dark()

    def _chrome_margin(self) -> int:
        """Space above/below the text that the floating toolbars may cover."""
        tallest = max(
            self.header.measure(Gtk.Orientation.VERTICAL, -1)[1],
            self.footer.measure(Gtk.Orientation.VERTICAL, -1)[1],
        )
        return tallest + 12 if tallest > 0 else 84

    def _settings_payload(self, s: ReaderSettings) -> dict:
        dark = self._system_dark()
        palette = get_palette(s.theme, dark)
        return {
            "publisher": s.publisher_formatting,
            "paragraph_spacing": s.paragraph_spacing,
            "layout_mode": s.layout_mode,
            "columns": s.columns,
            "max_width": s.max_width,
            "margin_pct": s.margin_pct,
            "chrome_margin": self._chrome_margin(),
            "fxl_zoom": s.fxl_zoom,
            "is_dark": palette.is_dark,
            "filter": color_filter(s),
            "filter_inverted": color_filter(s, invert=True),
            "invert_pdf": palette.is_dark and s.invert_pdf_in_dark,
            "css_vars": build_reader_css_vars(s, dark),
        }

    def _apply_chrome_theme(self, s: ReaderSettings) -> None:
        if s.theme == "system":
            self._style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)
        else:
            dark = get_palette(s.theme).is_dark
            self._style_manager.set_color_scheme(
                Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT)
        self._chrome_provider.load_from_string(chrome_css(get_palette(s.theme, self._system_dark())))

    def _on_system_dark_changed(self, *_args) -> None:
        if self.config.settings.theme == "system":
            self.apply_settings(self.config.settings)

    def apply_settings(self, settings: ReaderSettings) -> None:
        self._apply_chrome_theme(settings)
        if self._token is not None:
            self._call("applySettings", self._settings_payload(settings))

    # ------------------------------------------------------------ JS bridge

    def _call(self, fn: str, *args) -> None:
        if self._token is None:
            return
        arg_js = ", ".join(json.dumps(a) for a in args)
        self.webview.evaluate_javascript(
            f"window.Ebookread && window.Ebookread.{fn}({arg_js})", -1, None, None, None, None, None
        )

    def _on_js_message(self, _ucm: WebKit.UserContentManager, js_val) -> None:
        try:
            msg = json.loads(js_val.to_string())
        except (TypeError, ValueError):
            return
        if not isinstance(msg, dict) or msg.get("type") not in PAGE_MESSAGES:
            return
        mtype = msg["type"]

        if mtype == "page_ready":
            if self._pending_open is not None:
                payload, self._pending_open = self._pending_open, None
                self._call("open", payload)
            return

        # Everything else must belong to the book that is open right now.
        if self._token is None or msg.get("token") != self._token:
            return

        if mtype == "ready":
            self._on_ready(msg)
        elif mtype == "relocate":
            self._on_relocate(msg)
        elif mtype == "history":
            self._set_history(bool(msg.get("can_back")), bool(msg.get("can_forward")))
        elif mtype == "search_progress":
            self.search_panel.on_progress(msg)
        elif mtype == "search_results":
            self.search_panel.on_results(msg)
        elif mtype == "search_done":
            self.search_panel.on_done(msg)
        elif mtype == "link_external":
            self._confirm_external_link(str(msg.get("url", "")))
        elif mtype == "error":
            self.toast_overlay.add_toast(Adw.Toast.new(str(msg.get("message", "Could not open book"))[:200]))
        elif mtype == "toggle_chrome":
            self.toggle_distraction_free()
        elif mtype == "user_turn":
            if self.config.settings.auto_hide_controls and not self._chrome_busy():
                self.toggle_distraction_free(force_show=False)
        elif mtype == "edge":
            self.toggle_distraction_free(force_show=True)
        elif mtype == "cover":
            self._save_cover(msg.get("data"))
        elif mtype == "escape" and not self._chrome_visible:
            self.toggle_distraction_free(force_show=True)

    def _on_ready(self, msg: dict) -> None:
        toc = msg.get("toc") if isinstance(msg.get("toc"), list) else []
        fractions = msg.get("section_fractions") if isinstance(msg.get("section_fractions"), list) else []
        self.toc_panel.set_toc(toc, fractions)
        self._reset_scrubber_marks()
        for fraction, _label in self.toc_panel.chapter_marks()[:MAX_SCRUBBER_MARKS]:
            if 0.0 < fraction < 1.0:
                self.scrubber.add_mark(fraction * 100.0, Gtk.PositionType.BOTTOM, None)

        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        book = self.current_book
        if book is not None and meta:
            title = str(meta.get("title") or "").strip()
            author = str(meta.get("author") or "").strip()
            # Formats without an import-time extractor arrive titled by file name.
            # Some (CBZ) only know the file name too, which is no improvement.
            path = Path(book.file_path)
            if title and title not in (path.name, path.stem) and book.title == fallback_title(path):
                self.db.update_metadata(book.id, title=title, author=author or book.author)
                self.title_widget.set_title(title)
                if author:
                    self.title_widget.set_subtitle(author)

    def _on_relocate(self, msg: dict) -> None:
        self._last_relocate = msg
        try:
            frac = min(1.0, max(0.0, float(msg.get("fraction", 0.0))))
        except (TypeError, ValueError):
            frac = 0.0
        if not self._scrub_timeout:  # don't yank the knob while the user is dragging it
            self.scrubber.set_value(frac * 100.0)
        self.progress_label.set_text(f"{int(frac * 100)}%")

        toc_item = msg.get("toc_item") if isinstance(msg.get("toc_item"), dict) else {}
        self.chapter_label.set_text(str(toc_item.get("label") or ""))
        if toc_item.get("href") is not None:
            self.toc_panel.show_current(toc_item["href"])

        details = []
        page = msg.get("section_page")
        if isinstance(page, dict) and _int(page.get("total")) > 1:
            details.append(f"Page {_int(page.get('current'))} of {_int(page.get('total'))} in chapter")
        page_item = msg.get("page_item")
        if isinstance(page_item, dict) and page_item.get("label"):
            details.append(f"p. {page_item['label']}")
        time = msg.get("time") if isinstance(msg.get("time"), dict) else {}
        left = format_minutes(time.get("section"))
        if left:
            details.append(f"{left} left in chapter")
        self.chapter_detail.set_text(" · ".join(details))
        book_left = format_minutes(time.get("total"))
        self.progress_label.set_tooltip_text(f"{book_left} left in book" if book_left else None)

        cfi = msg.get("cfi")
        if self.current_book is not None:
            self.db.update_progress(
                book_id=self.current_book.id,
                chapter_index=_section_index(msg),
                chapter_fraction=0.0,
                book_fraction=frac,
                cfi=cfi if isinstance(cfi, str) and cfi.startswith("epubcfi(") else None,
            )

    def _save_cover(self, data) -> None:
        book = self.current_book
        if book is None or not isinstance(data, str) or len(data) > MAX_COVER_B64:
            return
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            return
        path = save_cover(raw, covers_dir(), book.file_hash)
        if path:
            self.db.update_cover(book.id, path)

    def _set_history(self, can_back: bool, can_forward: bool) -> None:
        self.can_go_back = can_back
        self.can_go_forward = can_forward
        self.history_back_btn.set_visible(can_back)
        self.history_forward_btn.set_visible(can_forward)

    def _confirm_external_link(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in EXTERNAL_SCHEMES:
            return
        shown = parsed.netloc or parsed.path
        toast = Adw.Toast.new(f"Open link to {shown[:60]}?")
        toast.set_button_label("Open")
        toast.set_timeout(6)

        def launch(_t):
            Gtk.UriLauncher.new(url).launch(self.get_root(), None, None, None)

        toast.connect("button-clicked", launch)
        self.toast_overlay.add_toast(toast)

    # ------------------------------------------------------------ chrome

    def _chrome_busy(self) -> bool:
        """True while the reader is using the toolbars (sidebar or settings open)."""
        return self.split_view.get_show_sidebar() or self.settings_popover.get_visible()

    def toggle_distraction_free(self, force_show: bool | None = None) -> None:
        self._chrome_visible = (not self._chrome_visible) if force_show is None else force_show
        self.toolbar_view.set_reveal_top_bars(self._chrome_visible)
        self.toolbar_view.set_reveal_bottom_bars(self._chrome_visible)

    # ------------------------------------------------------------ bookmarks

    def add_current_bookmark(self) -> None:
        if self.current_book is None or not self._last_relocate:
            return
        msg = self._last_relocate
        cfi = msg.get("cfi") if isinstance(msg.get("cfi"), str) else None
        frac = float(msg.get("fraction") or 0.0)
        toc_item = msg.get("toc_item") if isinstance(msg.get("toc_item"), dict) else {}
        chapter = str(toc_item.get("label") or "") or f"Section {_section_index(msg) + 1}"
        label = f"{chapter} · {int(frac * 100)}%"
        self.db.add_bookmark(self.current_book.id, label, _section_index(msg), frac, cfi=cfi,
                             excerpt=str(msg.get("excerpt") or ""))
        self.bookmarks_panel.refresh()
        self.toast_overlay.add_toast(Adw.Toast.new(f"Bookmarked {label}"))

    # ------------------------------------------------------------ scrubber

    def _reset_scrubber_marks(self) -> None:
        # Marks make the scale taller. Keeping start/end ticks at all times means adding
        # chapter ticks later never resizes the footer, which would reflow the page.
        self.scrubber.clear_marks()
        self.scrubber.add_mark(0.0, Gtk.PositionType.BOTTOM, None)
        self.scrubber.add_mark(100.0, Gtk.PositionType.BOTTOM, None)

    def _on_scrubber_change_value(self, scale: Gtk.Scale, _scroll, value: float) -> bool:
        """User moved the scrubber (drag, click, keys). Seek once it settles."""
        value = min(100.0, max(0.0, value))
        chapter = self.toc_panel.chapter_at(value / 100.0)
        self.progress_label.set_text(f"{int(value)}%")
        if chapter:
            self.chapter_label.set_text(chapter)
        if self._scrub_timeout:
            GLib.source_remove(self._scrub_timeout)

        def seek() -> bool:
            self._scrub_timeout = 0
            self._call("goToFraction", scale.get_value() / 100.0)
            return False

        self._scrub_timeout = GLib.timeout_add(SCRUB_SETTLE_MS, seek)
        return False  # let the scale move the knob

    def _on_scrubber_tooltip(self, scale: Gtk.Scale, x: int, _y: int, _kb: bool, tooltip: Gtk.Tooltip) -> bool:
        width = scale.get_width()
        if width <= 0 or not self.toc_panel.entries:
            return False
        frac = min(1.0, max(0.0, x / width))
        chapter = self.toc_panel.chapter_at(frac)
        tooltip.set_text(f"{chapter} · {int(frac * 100)}%" if chapter else f"{int(frac * 100)}%")
        return True
