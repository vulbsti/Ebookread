"""Adds books to the library: expands folders, detects duplicates and moved files.

Metadata extraction (the slow part) runs in a worker thread; every database decision is
made on the main thread, which owns the SQLite connection.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .book_parser import SUPPORTED_EXTENSIONS, ParsedMetadata, extract_book_metadata
from .db import BookRecord, LibraryDB

MAX_FILES = 20000


@dataclass
class ImportReport:
    added: list[BookRecord] = field(default_factory=list)
    refreshed: list[BookRecord] = field(default_factory=list)   # same path, already in library
    relinked: list[BookRecord] = field(default_factory=list)    # moved file found again
    duplicates: list[Path] = field(default_factory=list)        # same book at another path
    failed: list[tuple[Path, str]] = field(default_factory=list)
    cancelled: bool = False

    @property
    def books(self) -> list[BookRecord]:
        """Books the user now has, in the order they were given."""
        return self.added + self.refreshed + self.relinked

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"Added {len(self.added)} book{'s' if len(self.added) != 1 else ''}")
        if self.relinked:
            parts.append(f"found {len(self.relinked)} moved")
        if self.refreshed and not self.added:
            parts.append(f"{len(self.refreshed)} already in library")
        if self.duplicates:
            parts.append(f"skipped {len(self.duplicates)} duplicate{'s' if len(self.duplicates) != 1 else ''}")
        if self.failed:
            parts.append(f"{len(self.failed)} could not be read")
        text = ", ".join(parts) or "No books found"
        return text[0].upper() + text[1:]


def collect_paths(paths: list[Path]) -> list[Path]:
    """Files to import: supported files as given, plus supported files inside folders."""
    found: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        r = p.resolve()
        if r not in seen and r.suffix.lower() in SUPPORTED_EXTENSIONS:
            seen.add(r)
            found.append(r)

    for p in paths:
        if p.is_dir():
            for root, dirs, files in os.walk(p, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for name in sorted(files):
                    if not name.startswith("."):
                        add(Path(root) / name)
                if len(found) >= MAX_FILES:
                    return found
        elif p.is_file():
            add(p)
    return found


def store(db: LibraryDB, meta: ParsedMetadata, report: ImportReport) -> None:
    """Main-thread decision for one extracted file."""
    path = Path(meta.file_path)
    existing = db.get_book_by_path(path)
    if existing is None:
        twins = [b for b in db.find_by_hash(meta.file_hash) if Path(b.file_path) != path]
        moved = next((b for b in twins if b.missing), None)
        if moved is not None:
            db.update_path(moved.id, path)
            if meta.cover_path and not moved.cover_path:
                db.update_cover(moved.id, meta.cover_path)
            report.relinked.append(db.get_book(moved.id))
            return
        if twins:
            report.duplicates.append(path)
            return
    rec = db.upsert_book(
        file_path=path, file_hash=meta.file_hash, file_format=meta.file_format,
        title=meta.title, author=meta.author, language=meta.language, cover_path=meta.cover_path,
    )
    (report.refreshed if existing else report.added).append(rec)


def import_now(db: LibraryDB, paths: list[Path]) -> ImportReport:
    """Synchronous import (tests, tiny imports)."""
    report = ImportReport()
    for p in collect_paths(paths):
        try:
            store(db, extract_book_metadata(p), report)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the rest
            report.failed.append((p, str(exc)))
    return report


class BackgroundImport:
    """Imports in a worker thread, reporting progress on the GLib main loop."""

    def __init__(
        self,
        db: LibraryDB,
        paths: list[Path],
        on_progress: Callable[[int, int], None],
        on_done: Callable[[ImportReport], None],
    ) -> None:
        self._db = db
        self._paths = paths
        self._on_progress = on_progress
        self._on_done = on_done
        self._cancel = threading.Event()
        self.report = ImportReport()

    def start(self) -> None:
        threading.Thread(target=self._run, name="ebookread-import", daemon=True).start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self) -> None:
        from gi.repository import GLib

        files = collect_paths(self._paths)
        total = len(files)
        GLib.idle_add(self._progress, 0, total)
        for i, p in enumerate(files, start=1):
            if self._cancel.is_set():
                self.report.cancelled = True
                break
            try:
                meta = extract_book_metadata(p)
                GLib.idle_add(self._store, meta)
            except Exception as exc:  # noqa: BLE001
                self.report.failed.append((p, str(exc)))
            GLib.idle_add(self._progress, i, total)
        GLib.idle_add(self._finish)

    def _store(self, meta: ParsedMetadata) -> bool:
        try:
            store(self._db, meta, self.report)
        except Exception as exc:  # noqa: BLE001
            self.report.failed.append((Path(meta.file_path), str(exc)))
        return False

    def _progress(self, done: int, total: int) -> bool:
        self._on_progress(done, total)
        return False

    def _finish(self) -> bool:
        self._on_done(self.report)
        return False
