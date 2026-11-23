"""Keyboard shortcut table (single source for the handler and the help window)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

# (section, [(accelerator, description)])
SHORTCUTS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Reading", [
        ("Right Page_Down space", "Next page"),
        ("Left Page_Up <Shift>space", "Previous page"),
        ("End", "Next chapter"),
        ("Home", "Previous chapter"),
        ("<Alt>Left", "Back to where you were (or to the library)"),
        ("<Alt>Right", "Forward again"),
    ]),
    ("Find Your Way", [
        ("<Ctrl>t", "Contents"),
        ("<Ctrl>f", "Search in book"),
        ("<Ctrl>g", "Next search result"),
        ("<Ctrl><Shift>g", "Previous search result"),
        ("<Ctrl>b", "Bookmarks"),
        ("<Ctrl>d", "Bookmark this page"),
    ]),
    ("Window", [
        ("F11", "Fullscreen"),
        ("Escape", "Close footnote / show controls"),
        ("<Ctrl>o", "Import books"),
        ("<Ctrl>question F1", "Keyboard shortcuts"),
    ]),
]


def build_shortcuts_window(parent: Gtk.Window) -> Gtk.ShortcutsWindow:
    groups = []
    for title, rows in SHORTCUTS:
        items = "".join(
            f'<child><object class="GtkShortcutsShortcut">'
            f'<property name="accelerator">{GLib.markup_escape_text(accel)}</property>'
            f'<property name="title">{GLib.markup_escape_text(desc)}</property>'
            f"</object></child>"
            for accel, desc in rows
        )
        groups.append(
            f'<child><object class="GtkShortcutsGroup">'
            f'<property name="title">{GLib.markup_escape_text(title)}</property>{items}</object></child>'
        )
    ui = (
        '<interface><object class="GtkShortcutsWindow" id="win"><property name="modal">1</property>'
        '<child><object class="GtkShortcutsSection"><property name="section-name">main</property>'
        + "".join(groups)
        + "</object></child></object></interface>"
    )
    builder = Gtk.Builder.new_from_string(ui, -1)
    win: Gtk.ShortcutsWindow = builder.get_object("win")
    win.set_transient_for(parent)
    return win
