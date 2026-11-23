"""Reader sidebar panels: table of contents tree, in-book search, bookmarks."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango

from ..core.db import BookmarkRecord, LibraryDB

Navigate = Callable[[object], None]  # goTo target: href / CFI string, or section index


# ====================================================================== contents


class TocNode(GObject.Object):
    """One table-of-contents entry. `target` is an href, or a section index for generated TOCs."""

    def __init__(self, label: str, target, fraction: float | None, path: tuple[int, ...]) -> None:
        super().__init__()
        self.label = label
        self.target = target
        self.fraction = fraction
        self.path = path
        self.children = Gio.ListStore.new(TocNode)


class TocPanel(Gtk.Box):
    """Collapsible TOC that highlights and reveals the chapter you are reading."""

    AUTO_EXPAND_LIMIT = 40  # small TOCs open fully; big ones only along the current path

    def __init__(self, navigate: Navigate) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._navigate = navigate
        self._root = Gio.ListStore.new(TocNode)
        self._by_target: dict[object, TocNode] = {}
        self._current_path: tuple[int, ...] | None = None
        self.entries: list[TocNode] = []  # flat, in reading order

        self._tree = Gtk.TreeListModel.new(self._root, False, False, self._children_of)
        self._selection = Gtk.SingleSelection.new(self._tree)
        self._selection.set_autoselect(False)
        self._selection.set_can_unselect(True)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup)
        factory.connect("bind", self._on_bind)
        self.list_view = Gtk.ListView.new(self._selection, factory)
        self.list_view.set_single_click_activate(True)
        self.list_view.add_css_class("navigation-sidebar")
        self.list_view.connect("activate", self._on_activate)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self.list_view)
        self.append(scroll)

    # -------------------------------------------------------------- model

    @staticmethod
    def _children_of(item: TocNode):
        return item.children if item.children.get_n_items() else None

    def set_toc(self, toc: list, section_fractions: list | None = None) -> None:
        self._root.remove_all()
        self._by_target.clear()
        self.entries = []
        self._current_path = None

        if not toc and section_fractions:
            # No TOC in the book: offer its sections so there is always somewhere to jump.
            toc = [
                {"label": f"Section {i + 1}", "href": i, "fraction": f}
                for i, f in enumerate(section_fractions[:-1])
            ]

        def build(items: list, store: Gio.ListStore, prefix: tuple[int, ...]) -> None:
            for i, item in enumerate(i for i in items if isinstance(i, dict)):
                node = TocNode(
                    str(item.get("label") or "Untitled"),
                    item.get("href"),
                    item.get("fraction") if isinstance(item.get("fraction"), (int, float)) else None,
                    prefix + (i,),
                )
                store.append(node)
                self.entries.append(node)
                if node.target is not None:
                    self._by_target.setdefault(node.target, node)
                build(item.get("subitems") or [], node.children, node.path)

        build(toc, self._root, ())
        expand_all = len(self.entries) <= self.AUTO_EXPAND_LIMIT
        self._tree = Gtk.TreeListModel.new(self._root, False, expand_all, self._children_of)
        self._selection.set_model(self._tree)

    def chapter_marks(self) -> list[tuple[float, str]]:
        """(fraction, label) of top-level entries, for scrubber ticks and tooltips."""
        marks = []
        for i in range(self._root.get_n_items()):
            node = self._root.get_item(i)
            if node.fraction is not None:
                marks.append((node.fraction, node.label))
        return marks

    def chapter_at(self, fraction: float) -> str | None:
        best = None
        for node in self.entries:
            if node.fraction is not None and node.fraction <= fraction + 1e-6:
                if best is None or node.fraction >= best.fraction:
                    best = node
        return best.label if best else None

    # -------------------------------------------------------------- current chapter

    def show_current(self, target) -> None:
        """Select the entry for `target` (the TOC href foliate reports), expanding its parents."""
        node = self._by_target.get(target)
        if node is None or node.path == self._current_path:
            return
        self._current_path = node.path
        position = self._reveal(node.path)
        if position is None:
            return
        self._selection.set_selected(position)
        if self.get_mapped():
            self.list_view.scroll_to(position, Gtk.ListScrollFlags.NONE, None)

    def scroll_to_current(self) -> None:
        pos = self._selection.get_selected()
        if pos != Gtk.INVALID_LIST_POSITION:
            self.list_view.scroll_to(pos, Gtk.ListScrollFlags.FOCUS, None)

    def _reveal(self, path: tuple[int, ...]) -> int | None:
        """Expand every ancestor of `path`; return the flat row position of the node."""
        position = 0
        row = None
        for depth, index in enumerate(path):
            if depth == 0:
                row = self._tree.get_child_row(index)
            else:
                row.set_expanded(True)
                row = row.get_child_row(index)
            if row is None:
                return None
        position = row.get_position()
        return position

    # -------------------------------------------------------------- rows

    def _on_setup(self, _f, list_item: Gtk.ListItem) -> None:
        expander = Gtk.TreeExpander()
        label = Gtk.Label(xalign=0.0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_margin_top(3)
        label.set_margin_bottom(3)
        expander.set_child(label)
        list_item.set_child(expander)

    def _on_bind(self, _f, list_item: Gtk.ListItem) -> None:
        row: Gtk.TreeListRow = list_item.get_item()
        node: TocNode = row.get_item()
        expander: Gtk.TreeExpander = list_item.get_child()
        expander.set_list_row(row)
        label: Gtk.Label = expander.get_child()
        label.set_label(node.label)
        if node.path and len(node.path) == 1 and node.children.get_n_items():
            label.add_css_class("heading")
        else:
            label.remove_css_class("heading")
        list_item.set_activatable(node.target is not None)

    def _on_activate(self, _lv, position: int) -> None:
        row = self._tree.get_row(position)
        node = row.get_item() if row else None
        if node is not None and node.target is not None:
            self._current_path = node.path
            self._navigate(node.target)


# ====================================================================== search


class SearchPanel(Gtk.Box):
    """Search the whole book; results stream in grouped by chapter, matches highlighted."""

    def __init__(self, start: Callable[[str], None], clear: Callable[[], None], navigate: Navigate) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._start = start
        self._clear_page = clear
        self._navigate = navigate
        self._generation: int | None = None
        self._query = ""
        self._rows: list[Gtk.ListBoxRow] = []
        self._index = -1
        for side in ("top", "start", "end"):
            getattr(self, f"set_margin_{side}")(8)

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("Search in book…")
        self.entry.connect("activate", lambda _e: self._on_activate(1))
        self.entry.connect("next-match", lambda _e: self.step(1))
        self.entry.connect("previous-match", lambda _e: self.step(-1))
        self.entry.connect("stop-search", lambda _e: self.clear())
        shift_enter = Gtk.ShortcutController()
        shift_enter.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Shift>Return"),
            Gtk.CallbackAction.new(lambda *_: self._on_activate(-1) or True)))
        self.entry.add_controller(shift_enter)
        self.append(self.entry)

        self.progress = Gtk.ProgressBar()
        self.progress.add_css_class("osd")
        self.progress.set_visible(False)
        self.append(self.progress)

        self.status = Gtk.Label(xalign=0.0)
        self.status.add_css_class("dim-label")
        self.status.add_css_class("caption")
        self.append(self.status)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.results = Gtk.ListBox()
        self.results.add_css_class("navigation-sidebar")
        self.results.connect("row-activated", self._on_row_activated)
        scroll.set_child(self.results)
        self.append(scroll)

    @property
    def result_count(self) -> int:
        return len(self._rows)

    def focus(self) -> None:
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def clear(self) -> None:
        self._generation = None
        self._query = ""
        self._rows = []
        self._index = -1
        self.entry.set_text("")
        self.results.remove_all()
        self.progress.set_visible(False)
        self.status.set_text("")
        self._clear_page()

    def reset_for_new_book(self) -> None:
        self._generation = None
        self._query = ""
        self._rows = []
        self._index = -1
        self.entry.set_text("")
        self.results.remove_all()
        self.progress.set_visible(False)
        self.status.set_text("")

    def _on_activate(self, direction: int) -> None:
        query = self.entry.get_text().strip()
        if query and query == self._query and self._rows:
            self.step(direction)
            return
        self._query = query
        self._rows = []
        self._index = -1
        self.results.remove_all()
        if not query:
            self.clear()
            return
        self.status.set_text("Searching…")
        self.progress.set_fraction(0.0)
        self.progress.set_visible(True)
        self._generation = None  # adopt the generation of the next search message
        self._start(query)

    def step(self, direction: int) -> None:
        if not self._rows:
            return
        self._index = (self._index + direction) % len(self._rows)
        row = self._rows[self._index]
        self.results.select_row(row)
        self._navigate(row._cfi)  # type: ignore[attr-defined]
        self.status.set_text(f"{self._index + 1} of {len(self._rows)}")

    # ------------------------------------------------------------ messages from the page

    def _accept(self, msg: dict) -> bool:
        gen = msg.get("generation")
        if self._generation is None and self._query:
            self._generation = gen
        return gen == self._generation

    def on_progress(self, msg: dict) -> None:
        if self._accept(msg):
            self.progress.set_fraction(min(1.0, float(msg.get("progress") or 0.0)))

    def on_results(self, msg: dict) -> None:
        if not self._accept(msg):
            return
        header = Gtk.Label(label=str(msg.get("label") or ""), xalign=0.0)
        header.add_css_class("heading")
        header.set_wrap(True)
        header.set_margin_top(8)
        hrow = Gtk.ListBoxRow(activatable=False, selectable=False)
        hrow.set_child(header)
        self.results.append(hrow)
        for item in msg.get("items") or []:
            if not isinstance(item, dict) or not item.get("cfi"):
                continue
            lbl = Gtk.Label(xalign=0.0)
            lbl.set_wrap(True)
            lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            lbl.set_markup(
                GLib.markup_escape_text(str(item.get("pre", ""))[-60:])
                + "<b>" + GLib.markup_escape_text(str(item.get("match", ""))) + "</b>"
                + GLib.markup_escape_text(str(item.get("post", ""))[:80])
            )
            lbl.set_margin_top(3)
            lbl.set_margin_bottom(3)
            row = Gtk.ListBoxRow()
            row.set_child(lbl)
            row._cfi = item["cfi"]  # type: ignore[attr-defined]
            self.results.append(row)
            self._rows.append(row)
        self.status.set_text(f"{len(self._rows)} found so far…")

    def on_done(self, msg: dict) -> None:
        if not self._accept(msg):
            return
        self.progress.set_visible(False)
        n = len(self._rows)
        self.status.set_text("No matches" if n == 0 else f"{n} match{'es' if n != 1 else ''}")

    def _on_row_activated(self, _lb, row: Gtk.ListBoxRow) -> None:
        cfi = getattr(row, "_cfi", None)
        if cfi:
            self._index = self._rows.index(row)
            self.status.set_text(f"{self._index + 1} of {len(self._rows)}")
            self._navigate(cfi)


# ====================================================================== bookmarks


class BookmarksPanel(Gtk.Box):
    """Bookmarks in reading order, with rename and delete (undoable)."""

    def __init__(self, db: LibraryDB, navigate: Navigate, toast_overlay: Adw.ToastOverlay) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._db = db
        self._navigate = navigate
        self._toasts = toast_overlay
        self._book_id: int | None = None

        self.empty = Adw.StatusPage()
        self.empty.set_icon_name("bookmark-new-symbolic")
        self.empty.set_title("No Bookmarks")
        self.empty.set_description("Press Ctrl+D to bookmark the page you are on.")
        self.empty.add_css_class("compact")

        self.list = Gtk.ListBox()
        self.list.add_css_class("navigation-sidebar")
        self.list.connect("row-activated", self._on_activated)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self.list)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.empty, "empty")
        self.stack.add_named(scroll, "list")
        self.stack.set_vexpand(True)
        self.append(self.stack)

    def load(self, book_id: int | None) -> None:
        self._book_id = book_id
        self.refresh()

    def refresh(self) -> None:
        self.list.remove_all()
        marks = self._db.list_bookmarks(self._book_id) if self._book_id is not None else []
        for bm in marks:
            self.list.append(self._row(bm))
        self.stack.set_visible_child_name("list" if marks else "empty")

    def _row(self, bm: BookmarkRecord) -> Gtk.ListBoxRow:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        title = Gtk.Label(label=bm.label, xalign=0.0)
        title.set_wrap(True)
        text.append(title)
        if bm.excerpt:
            ex = Gtk.Label(label=bm.excerpt[:110], xalign=0.0)
            ex.set_wrap(True)
            ex.set_lines(2)
            ex.set_ellipsize(Pango.EllipsizeMode.END)
            ex.add_css_class("caption")
            ex.add_css_class("dim-label")
            text.append(ex)
        box.append(text)

        rename = Gtk.Button.new_from_icon_name("document-edit-symbolic")
        rename.add_css_class("flat")
        rename.set_valign(Gtk.Align.CENTER)
        rename.set_tooltip_text("Rename bookmark")
        rename.connect("clicked", lambda _b: self._rename(bm))
        box.append(rename)

        delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        delete.add_css_class("flat")
        delete.set_valign(Gtk.Align.CENTER)
        delete.set_tooltip_text("Delete bookmark")
        delete.connect("clicked", lambda _b: self.delete(bm))
        box.append(delete)

        row = Gtk.ListBoxRow()
        row.set_child(box)
        row._bookmark = bm  # type: ignore[attr-defined]
        return row

    def _on_activated(self, _lb, row: Gtk.ListBoxRow) -> None:
        bm = getattr(row, "_bookmark", None)
        if bm is None:
            return
        self._navigate(bm.cfi if bm.cfi and bm.cfi.startswith("epubcfi(") else {"fraction": bm.book_fraction})

    def delete(self, bm: BookmarkRecord) -> None:
        self._db.delete_bookmark(bm.id)
        self.refresh()
        toast = Adw.Toast.new(f"Deleted “{bm.label}”")
        toast.set_button_label("Undo")

        def undo(_t) -> None:
            self._db.add_bookmark(bm.book_id, bm.label, bm.chapter_index, bm.book_fraction,
                                  cfi=bm.cfi, excerpt=bm.excerpt)
            self.refresh()

        toast.connect("button-clicked", undo)
        self._toasts.add_toast(toast)

    def _rename(self, bm: BookmarkRecord) -> None:
        dialog = Adw.AlertDialog(heading="Rename Bookmark")
        entry = Gtk.Entry(text=bm.label, activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("rename", "Rename")
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")

        def done(_d, response: str) -> None:
            name = entry.get_text().strip()
            if response == "rename" and name:
                self._db.rename_bookmark(bm.id, name)
                self.refresh()

        dialog.connect("response", done)
        dialog.present(self.get_root())

