"""Main Adw.ApplicationWindow coordinating LibraryView and ReaderView."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk

from .. import APP_NAME
from ..core.config import ConfigStore
from ..core.db import BookRecord, LibraryDB
from ..core.uri_server import BookResourceResolver
from .library_view import LibraryView
from .reader_view import ReaderView
from .shortcuts import build_shortcuts_window


class MainWindow(Adw.ApplicationWindow):
    """Primary window using Adw.NavigationView (Library -> Reader)."""

    def __init__(self, app: Adw.Application, initial_file: Path | None = None) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.config = ConfigStore()
        self.db = LibraryDB()
        self.resolver = BookResourceResolver()

        self.set_default_size(
            self.config.settings.window_width,
            self.config.settings.window_height,
        )

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        self.nav_view = Adw.NavigationView()
        self.toast_overlay.set_child(self.nav_view)

        self.library_view = LibraryView(
            db=self.db,
            on_open_book=self._open_book,
            toast_overlay=self.toast_overlay,
        )
        self.reader_view = ReaderView(
            db=self.db,
            config=self.config,
            resolver=self.resolver,
            toast_overlay=self.toast_overlay,
        )
        self.nav_view.add(self.library_view)
        # Every way of leaving the reader (back button, Esc, swipe, Alt+Left) ends here.
        self.nav_view.connect("popped", self._on_page_popped)

        # Capture phase: shortcuts work even while the book view has keyboard focus.
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        self.connect("close-request", self._on_close_request)

        if initial_file is not None:
            self.open_path(initial_file)

    def open_path(self, path: Path) -> None:
        """Import (if needed) and open a file, e.g. from the command line or "Open with"."""
        if path.is_file():
            self.library_view.import_paths([path], open_first=True)

    def _open_book(self, book: BookRecord) -> None:
        fresh = self.db.get_book(book.id) or book
        self.reader_view.open_book(fresh)
        if self.nav_view.get_visible_page() is not self.reader_view:
            self.nav_view.push(self.reader_view)

    def _on_page_popped(self, _nav, page: Adw.NavigationPage) -> None:
        if page is self.reader_view:
            self.reader_view.close_book()
            self.library_view.refresh()

    def _on_key_pressed(self, _ctrl, keyval: int, _keycode: int, state: Gdk.ModifierType) -> bool:
        mods = state & Gtk.accelerator_get_default_mod_mask()
        ctrl = mods == Gdk.ModifierType.CONTROL_MASK
        ctrl_shift = mods == (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        alt = mods == Gdk.ModifierType.ALT_MASK
        key = Gdk.keyval_to_lower(keyval)
        reader = self.reader_view
        in_reader = self.nav_view.get_visible_page() is reader

        if keyval == Gdk.KEY_F11 and not mods:
            self.unfullscreen() if self.is_fullscreen() else self.fullscreen()
            return True
        if keyval == Gdk.KEY_F1 or (keyval == Gdk.KEY_question and mods & Gdk.ModifierType.CONTROL_MASK):
            build_shortcuts_window(self).present()
            return True
        if ctrl and key == Gdk.KEY_o:
            self.library_view.prompt_import_books()
            return True

        if not in_reader:
            if ctrl and key == Gdk.KEY_f:
                self.library_view.search_entry.grab_focus()
                return True
            return False

        if ctrl and key == Gdk.KEY_d:
            reader.add_current_bookmark()
            return True
        if ctrl and key == Gdk.KEY_t:
            reader.show_panel("toc")
            return True
        if ctrl and key == Gdk.KEY_f:
            reader.sidebar_stack.set_visible_child_name("search")
            reader.split_view.set_show_sidebar(True)
            reader.search_panel.focus()
            return True
        if ctrl and key == Gdk.KEY_b:
            reader.show_panel("bookmarks")
            return True
        if (ctrl or ctrl_shift) and key == Gdk.KEY_g:
            reader.search_panel.step(-1 if ctrl_shift else 1)
            return True
        # Alt+Left: back through link/TOC jumps first; with no history it leaves the reader.
        if alt and keyval == Gdk.KEY_Left:
            return reader.history_back()
        if alt and keyval == Gdk.KEY_Right:
            return reader.history_forward()
        return False

    def _on_close_request(self, _win) -> bool:
        w, h = self.get_default_size()
        if w > 0 and h > 0 and not self.is_maximized() and not self.is_fullscreen():
            self.config.update(window_width=w, window_height=h)
        # Stop the page first so no late progress message reaches a closed database.
        self.reader_view.close_book()
        self.db.close()
        return False
