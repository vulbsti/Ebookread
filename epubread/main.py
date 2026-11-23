"""Application entry point for Ebookread (GTK4 + Libadwaita)."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio

from . import APP_ID
from .ui.window import MainWindow


class EbookreadApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self._initial_file: Path | None = None

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = MainWindow(self, initial_file=self._initial_file)
        win.present()

    def do_open(self, files: list[Gio.File], _n_files: int, _hint: str) -> None:
        path = Path(files[0].get_path()) if files and files[0].get_path() else None
        win = self.props.active_window
        if win is None:
            self._initial_file = path
            self.do_activate()
            return
        if path is not None:
            win.open_path(path)
        win.present()


def main(argv: list[str] | None = None) -> int:
    app = EbookreadApp()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
