"""Library home: continue reading, cover grid, search/sort, background import, missing files."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk, Pango

from ..core.book_parser import SUPPORTED_EXTENSIONS
from ..core.db import BookRecord, LibraryDB, compute_file_hash
from ..core.importer import BackgroundImport, ImportReport, collect_paths, import_now

SYNC_IMPORT_LIMIT = 3  # a handful of files imports instantly; more goes to the background


_TEXTURES: dict[tuple[str, float], Gdk.Texture] = {}


def _texture(path: str) -> Gdk.Texture | None:
    p = Path(path)
    try:
        key = (path, p.stat().st_mtime)
    except OSError:
        return None
    if key not in _TEXTURES:
        try:
            _TEXTURES[key] = Gdk.Texture.new_from_filename(path)
        except GLib.Error:
            return None
    return _TEXTURES[key]


class Cover(Gtk.Widget):
    """A cover at a fixed size, cropped to fill it.

    Gtk.Picture reports the image's own size as its natural size, which made the grid
    lay out a few huge cards; this widget always asks for exactly width x height.
    """

    def __init__(self, texture: Gdk.Texture, width: int, height: int) -> None:
        super().__init__()
        self._texture = texture
        self._w, self._h = width, height
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def do_measure(self, orientation, _for_size):
        size = self._w if orientation == Gtk.Orientation.HORIZONTAL else self._h
        return size, size, -1, -1

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        w, h = self.get_width(), self.get_height()
        tw, th = self._texture.get_width(), self._texture.get_height()
        if not (w and h and tw and th):
            return
        scale = max(w / tw, h / th)
        dw, dh = tw * scale, th * scale
        snapshot.push_clip(Graphene.Rect().init(0, 0, w, h))
        snapshot.append_scaled_texture(
            self._texture, Gsk.ScalingFilter.TRILINEAR, Graphene.Rect().init((w - dw) / 2, (h - dh) / 2, dw, dh))
        snapshot.pop()


def _cover_widget(book: BookRecord, width: int, height: int) -> Gtk.Widget:
    texture = _texture(book.cover_path) if book.cover_path else None
    if texture is not None:
        return Cover(texture, width, height)
    # No cover: a plain "cover" with the title on it, so the book is still recognisable.
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    outer.set_size_request(width, height)
    outer.add_css_class("view")
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, vexpand=True,
                    valign=Gtk.Align.CENTER, margin_start=12, margin_end=12)
    icon = Gtk.Image.new_from_icon_name("accessories-dictionary-symbolic")
    icon.set_pixel_size(max(20, width // 5))
    icon.add_css_class("dim-label")
    inner.append(icon)
    if height >= 150:
        title = Gtk.Label(label=book.title, wrap=True, lines=4, justify=Gtk.Justification.CENTER,
                          ellipsize=Pango.EllipsizeMode.END, max_width_chars=14)
        title.add_css_class("heading")
        inner.append(title)
    fmt = Gtk.Label(label=book.file_format.upper())
    fmt.add_css_class("caption")
    fmt.add_css_class("dim-label")
    inner.append(fmt)
    outer.append(inner)
    return outer


def _progress_text(book: BookRecord) -> str | None:
    if book.book_fraction >= 0.995:
        return "Finished"
    if book.book_fraction > 0:
        return f"{int(book.book_fraction * 100)}%"
    return None


class BookCard(Gtk.Box):
    """One book in the grid."""

    def __init__(self, book: BookRecord, on_delete: Callable[[BookRecord], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.book = book
        self.set_size_request(156, -1)
        self.set_halign(Gtk.Align.CENTER)
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(6)

        frame = Gtk.Frame()
        frame.add_css_class("card")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        overlay = Gtk.Overlay()
        overlay.set_child(_cover_widget(book, 148, 210))
        if book.missing:
            overlay.get_child().set_opacity(0.35)
            badge = Gtk.Label(label="File missing", valign=Gtk.Align.END, halign=Gtk.Align.CENTER)
            badge.add_css_class("osd")
            badge.add_css_class("caption-heading")
            badge.set_margin_bottom(10)
            overlay.add_overlay(badge)
            self.set_tooltip_text(f"Not found: {book.file_path}")
        if 0 < book.book_fraction < 0.995:
            bar = Gtk.ProgressBar(fraction=book.book_fraction, valign=Gtk.Align.END)
            bar.add_css_class("osd")
            overlay.add_overlay(bar)
        frame.set_child(overlay)
        self.append(frame)

        title = Gtk.Label(label=book.title, xalign=0.0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(18)
        title.set_lines(2)
        title.set_wrap(True)
        title.add_css_class("heading")
        self.append(title)

        meta = Gtk.Box(spacing=4)
        author = Gtk.Label(label=book.author, xalign=0.0, hexpand=True)
        author.set_ellipsize(Pango.EllipsizeMode.END)
        author.set_max_width_chars(14)
        author.add_css_class("caption")
        author.add_css_class("dim-label")
        meta.append(author)
        progress = _progress_text(book)
        if progress:
            badge = Gtk.Label(label=progress)
            badge.add_css_class("caption")
            badge.add_css_class("accent" if progress != "Finished" else "success")
            meta.append(badge)
        remove = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        remove.add_css_class("flat")
        remove.set_tooltip_text("Remove from library")
        remove.update_property([Gtk.AccessibleProperty.LABEL], [f"Remove {book.title}"])
        remove.connect("clicked", lambda _b: on_delete(book))
        meta.append(remove)
        self.append(meta)


class ContinueCard(Gtk.Button):
    """Large 'pick up where you left off' card."""

    def __init__(self, book: BookRecord, on_open: Callable[[BookRecord], None]) -> None:
        super().__init__()
        self.book = book
        self.set_size_request(340, -1)
        self.set_halign(Gtk.Align.START)
        self.add_css_class("card")
        self.add_css_class("activatable")
        self.set_tooltip_text(f"Continue {book.title}")
        box = Gtk.Box(spacing=14)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(10)
        frame = Gtk.Frame()
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.set_child(_cover_widget(book, 72, 104))
        box.append(frame)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        title = Gtk.Label(label=book.title, xalign=0.0, wrap=True, lines=2, ellipsize=Pango.EllipsizeMode.END)
        title.set_max_width_chars(26)
        title.add_css_class("heading")
        text.append(title)
        author = Gtk.Label(label=book.author, xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        author.add_css_class("dim-label")
        author.add_css_class("caption")
        text.append(author)
        text.append(Gtk.ProgressBar(fraction=book.book_fraction, margin_top=6))
        pct = Gtk.Label(label=f"{int(book.book_fraction * 100)}% read", xalign=0.0)
        pct.add_css_class("caption")
        pct.add_css_class("numeric")
        text.append(pct)
        box.append(text)
        self.set_child(box)
        self.connect("clicked", lambda _b: on_open(book))


class LibraryView(Adw.NavigationPage):
    def __init__(
        self,
        db: LibraryDB,
        on_open_book: Callable[[BookRecord], None],
        toast_overlay: Adw.ToastOverlay,
    ) -> None:
        super().__init__(title="Library", tag="library")
        self.db = db
        self.on_open_book = on_open_book
        self.toast_overlay = toast_overlay
        self._sort_by = "recent"
        self._query = ""
        self._import: BackgroundImport | None = None
        self._open_after_import = False

        actions = Gio.SimpleActionGroup()
        for name, cb in (("import-files", lambda *_: self.prompt_import_books()),
                         ("import-folder", lambda *_: self.prompt_import_folder())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            actions.add_action(act)
        self.insert_action_group("lib", actions)

        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        menu = Gio.Menu()
        menu.append("Import Files…", "lib.import-files")
        menu.append("Import Folder…", "lib.import-folder")
        add_btn = Gtk.MenuButton(icon_name="list-add-symbolic", menu_model=menu)
        add_btn.set_tooltip_text("Import books (Ctrl+O)")
        header.pack_start(add_btn)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search title or author…")
        self.search_entry.set_size_request(280, -1)
        self.search_entry.connect("search-changed", self._on_search_changed)
        header.set_title_widget(self.search_entry)

        sort_dropdown = Gtk.DropDown.new_from_strings(["Recent", "Title", "Author", "Date Added"])
        sort_dropdown.set_tooltip_text("Sort books")
        sort_dropdown.connect("notify::selected", self._on_sort_changed)
        header.pack_end(sort_dropdown)

        # Import progress
        self.import_bar = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER)
        self.import_label = Gtk.Label(xalign=0.0)
        self.import_label.add_css_class("caption")
        cancel = Gtk.Button(label="Cancel")
        cancel.add_css_class("flat")
        cancel.connect("clicked", lambda _b: self._import and self._import.cancel())
        progress_box = Gtk.Box(spacing=12, margin_start=18, margin_end=12, margin_top=6, margin_bottom=6)
        progress_box.append(self.import_label)
        progress_box.append(self.import_bar)
        progress_box.append(cancel)
        self.import_revealer = Gtk.Revealer(child=progress_box)
        toolbar.add_top_bar(self.import_revealer)

        self.stack = Gtk.Stack()
        toolbar.set_content(self.stack)

        empty = Adw.StatusPage(icon_name="book-open-symbolic", title="Your Library is Empty",
                               description="Import EPUB, MOBI, AZW3, FB2, CBZ or PDF books — "
                                           "or drop files and folders onto this window.")
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        for label, cb, suggested in (("Import Books", self.prompt_import_books, True),
                                     ("Import Folder", self.prompt_import_folder, False)):
            b = Gtk.Button(label=label)
            b.add_css_class("pill")
            if suggested:
                b.add_css_class("suggested-action")
            b.connect("clicked", lambda _b, f=cb: f())
            buttons.append(b)
        empty.set_child(buttons)
        self.stack.add_named(empty, "empty")

        no_results = Adw.StatusPage(icon_name="system-search-symbolic", title="No Matching Books")
        self.stack.add_named(no_results, "no-results")

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_margin_top(18)
        page.set_margin_bottom(24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        self.continue_title = Gtk.Label(label="Continue Reading", xalign=0.0)
        self.continue_title.add_css_class("title-4")
        page.append(self.continue_title)
        self.continue_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                                        min_children_per_line=1, column_spacing=12, row_spacing=12)
        page.append(self.continue_box)
        self.library_title = Gtk.Label(label="Library", xalign=0.0, margin_top=12)
        self.library_title.add_css_class("title-4")
        page.append(self.library_title)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_max_children_per_line(10)
        self.flowbox.set_min_children_per_line(2)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_activate_on_single_click(True)
        self.flowbox.set_row_spacing(12)
        self.flowbox.set_column_spacing(12)
        self.flowbox.connect("child-activated", self._on_card_activated)
        page.append(self.flowbox)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(page)
        self.stack.add_named(scroller, "grid")

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        self.refresh()

    # ------------------------------------------------------------ listing

    def refresh(self) -> None:
        self.flowbox.remove_all()
        self.continue_box.remove_all()
        books = self.db.list_books(query=self._query, sort_by=self._sort_by)
        if not books:
            self.stack.set_visible_child_name("no-results" if self._query else "empty")
            return
        self.stack.set_visible_child_name("grid")

        recent = [] if self._query else [b for b in self.db.continue_reading(3) if not b.missing]
        for book in recent:
            self.continue_box.append(ContinueCard(book, self.open_book))
        self.continue_title.set_visible(bool(recent))
        self.continue_box.set_visible(bool(recent))
        self.library_title.set_visible(bool(recent))

        for book in books:
            self.flowbox.append(BookCard(book, on_delete=self._delete_book))

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._query = entry.get_text()
        self.refresh()

    def _on_sort_changed(self, dd: Gtk.DropDown, _param) -> None:
        self._sort_by = ["recent", "title", "author", "added"][dd.get_selected()]
        self.refresh()

    def _on_card_activated(self, _fb: Gtk.FlowBox, child: Gtk.FlowBoxChild) -> None:
        card = child.get_child()
        if isinstance(card, BookCard):
            self.open_book(card.book)

    # ------------------------------------------------------------ opening & missing files

    def open_book(self, book: BookRecord) -> None:
        fresh = self.db.get_book(book.id) or book
        if fresh.missing:
            self._ask_about_missing(fresh)
        else:
            self.on_open_book(fresh)

    def _ask_about_missing(self, book: BookRecord) -> None:
        dialog = Adw.AlertDialog(
            heading="Book File Not Found",
            body=f"“{book.title}” is no longer at\n{book.file_path}\n\n"
                 "It may have been moved, renamed or deleted. Your reading position and bookmarks are kept.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.add_response("locate", "Locate…")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("locate", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("locate")
        dialog.set_close_response("cancel")

        def on_response(_d, response: str) -> None:
            if response == "remove":
                self._delete_book(book)
            elif response == "locate":
                self._locate(book)

        dialog.connect("response", on_response)
        dialog.present(self.get_root())

    def _locate(self, book: BookRecord) -> None:
        dialog = Gtk.FileDialog(title=f"Locate “{book.title}”")
        ff = Gtk.FileFilter()
        ff.set_name(f"{book.file_format.upper()} books")
        ff.add_suffix(book.file_format)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(ff)
        dialog.set_filters(filters)

        def done(d: Gtk.FileDialog, result) -> None:
            try:
                f = d.open_finish(result)
            except GLib.Error:
                return
            if not f or not f.get_path():
                return
            self.relink(book, Path(f.get_path()))

        dialog.open(self.get_root(), None, done)

    def relink(self, book: BookRecord, new_path: Path) -> None:
        """Point a missing book at its new location and open it."""
        if self.db.get_book_by_path(new_path) is not None:
            self.toast_overlay.add_toast(Adw.Toast.new("That file is already in your library"))
            return
        same = compute_file_hash(new_path) == book.file_hash
        self.db.update_path(book.id, new_path)
        if not same:
            self.toast_overlay.add_toast(Adw.Toast.new("This file differs from the original; "
                                                       "your saved position may not match"))
        self.refresh()
        self.open_book(self.db.get_book(book.id))

    # ------------------------------------------------------------ removing (undoable)

    def _delete_book(self, book: BookRecord) -> None:
        snapshot = self.db.delete_book(book.id)
        if snapshot is None:
            return
        self.refresh()
        toast = Adw.Toast.new(f"Removed “{book.title}”")
        toast.set_button_label("Undo")
        state = {"undone": False}

        def undo(_t) -> None:
            state["undone"] = True
            self.db.restore_book(snapshot)
            self.refresh()

        def forget(_t) -> None:
            # Once the chance to undo has passed, drop the cover thumbnail too.
            cover = snapshot.book.get("cover_path")
            if not state["undone"] and cover and not self.db.cover_in_use(cover):
                Path(cover).unlink(missing_ok=True)

        toast.connect("button-clicked", undo)
        toast.connect("dismissed", forget)
        self.toast_overlay.add_toast(toast)

    # ------------------------------------------------------------ importing

    def _on_drop(self, _target, value, _x, _y) -> bool:
        paths = [Path(f.get_path()) for f in value.get_files() if f.get_path()]
        if not paths:
            return False
        self.import_paths(paths)
        return True

    def _dialog_filters(self) -> Gio.ListStore:
        ff = Gtk.FileFilter()
        ff.set_name("Ebooks (EPUB, MOBI, AZW3, FB2, CBZ, PDF)")
        for ext in sorted(SUPPORTED_EXTENSIONS):
            ff.add_suffix(ext.lstrip("."))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(ff)
        return filters

    def prompt_import_books(self) -> None:
        dialog = Gtk.FileDialog(title="Import Books")
        dialog.set_filters(self._dialog_filters())

        def done(d: Gtk.FileDialog, result) -> None:
            try:
                files = d.open_multiple_finish(result)
            except GLib.Error:
                return
            self.import_paths([Path(f.get_path()) for f in files if f.get_path()])

        dialog.open_multiple(self.get_root(), None, done)

    def prompt_import_folder(self) -> None:
        dialog = Gtk.FileDialog(title="Import a Folder of Books")

        def done(d: Gtk.FileDialog, result) -> None:
            try:
                folder = d.select_folder_finish(result)
            except GLib.Error:
                return
            if folder and folder.get_path():
                self.import_paths([Path(folder.get_path())])

        dialog.select_folder(self.get_root(), None, done)

    def import_paths(self, paths: list[Path], open_first: bool = False) -> None:
        small = len(paths) <= SYNC_IMPORT_LIMIT and all(p.is_file() for p in paths)
        if small:
            self._finish_import(import_now(self.db, paths), open_first)
            return
        if self._import is not None:
            self.toast_overlay.add_toast(Adw.Toast.new("Already importing; try again when it finishes"))
            return
        self._open_after_import = open_first
        self._import = BackgroundImport(self.db, paths, self._on_import_progress, self._on_import_done)
        self.import_label.set_text("Looking for books…")
        self.import_bar.set_fraction(0.0)
        self.import_revealer.set_reveal_child(True)
        self._import.start()

    def _on_import_progress(self, done: int, total: int) -> None:
        self.import_label.set_text(f"Importing {done} of {total}" if total else "Looking for books…")
        self.import_bar.set_fraction(done / total if total else 0.0)
        if done and done % 25 == 0:
            self.refresh()  # let big imports fill the grid as they go

    def _on_import_done(self, report: ImportReport) -> None:
        self._import = None
        self.import_revealer.set_reveal_child(False)
        self._finish_import(report, self._open_after_import)

    def _finish_import(self, report: ImportReport, open_first: bool) -> None:
        self.refresh()
        text = report.summary() + (" (cancelled)" if report.cancelled else "")
        toast = Adw.Toast.new(text)
        if report.failed:
            names = ", ".join(p.name for p, _ in report.failed[:3])
            toast.set_title(f"{text}: {names}{'…' if len(report.failed) > 3 else ''}")
        self.toast_overlay.add_toast(toast)
        self.last_report = report
        if open_first and report.books:
            self.open_book(report.books[0])


__all__ = ["LibraryView", "BookCard", "ContinueCard", "collect_paths"]
