"""SQLite library: book metadata, reading progress, bookmarks. Main-thread only."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import get_data_dir

CHUNK = 65536


@dataclass
class BookRecord:
    id: int
    file_path: str
    file_hash: str
    file_format: str
    title: str
    author: str
    language: str
    cover_path: str | None
    chapter_index: int
    chapter_fraction: float
    book_fraction: float
    cfi: str | None
    added_at: float
    last_opened: float

    @property
    def missing(self) -> bool:
        return not Path(self.file_path).is_file()


@dataclass
class BookmarkRecord:
    id: int
    book_id: int
    label: str
    chapter_index: int
    book_fraction: float  # position in the whole book, 0..1 (ordering and fallback target)
    cfi: str | None
    excerpt: str
    created_at: float


@dataclass
class DeletedBook:
    """Everything needed to undo a delete exactly (same id, so bookmarks reattach)."""

    book: dict
    bookmarks: list[dict] = field(default_factory=list)


BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    file_hash TEXT NOT NULL,
    file_format TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT 'Unknown Author',
    language TEXT NOT NULL DEFAULT 'en',
    cover_path TEXT,
    chapter_index INTEGER NOT NULL DEFAULT 0,
    chapter_fraction REAL NOT NULL DEFAULT 0.0,
    book_fraction REAL NOT NULL DEFAULT 0.0,
    cfi TEXT,
    added_at REAL NOT NULL,
    last_opened REAL NOT NULL DEFAULT 0.0
);
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    chapter_index INTEGER NOT NULL DEFAULT 0,
    chapter_fraction REAL NOT NULL DEFAULT 0.0,
    cfi TEXT,
    excerpt TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_books_last_opened ON books(last_opened DESC);
CREATE INDEX IF NOT EXISTS idx_bookmarks_book_id ON bookmarks(book_id);
"""


def compute_file_hash(file_path: Path) -> str:
    """Fingerprint from size + first and last 64 KB: fast, and stable when a file is moved."""
    size = file_path.stat().st_size
    h = hashlib.sha256(str(size).encode("utf-8"))
    with file_path.open("rb") as fh:
        h.update(fh.read(CHUNK))
        if size > 2 * CHUNK:
            fh.seek(-CHUNK, 2)
            h.update(fh.read(CHUNK))
    return h.hexdigest()[:24]


def _migrate_v2(conn: sqlite3.Connection) -> None:
    # Bookmarks kept the whole-book fraction in a column called chapter_fraction.
    conn.execute("ALTER TABLE bookmarks ADD COLUMN book_fraction REAL NOT NULL DEFAULT 0.0")
    conn.execute("UPDATE bookmarks SET book_fraction = chapter_fraction")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_books_hash ON books(file_hash)")


def _migrate_v3(conn: sqlite3.Connection) -> None:
    # The fingerprint now also covers the end of the file; recompute for files still present.
    for row in conn.execute("SELECT id, file_path FROM books").fetchall():
        path = Path(row[1])
        if path.is_file():
            conn.execute("UPDATE books SET file_hash = ? WHERE id = ?", (compute_file_hash(path), row[0]))


MIGRATIONS = [_migrate_v2, _migrate_v3]  # index + 2 = resulting schema version
SCHEMA_VERSION = 1 + len(MIGRATIONS)


class LibraryDB:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (get_data_dir() / "library.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._conn.executescript(BASE_SCHEMA)
            version = 1
        while version < SCHEMA_VERSION:
            with self._conn:  # each step is one transaction
                MIGRATIONS[version - 1](self._conn)
                version += 1
                self._conn.execute(f"PRAGMA user_version = {version}")
        self._conn.commit()

    @property
    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------ books

    @staticmethod
    def _book(row: sqlite3.Row) -> BookRecord:
        return BookRecord(**{k: row[k] for k in BookRecord.__dataclass_fields__})

    def upsert_book(
        self,
        file_path: str | Path,
        file_hash: str,
        file_format: str,
        title: str,
        author: str = "Unknown Author",
        language: str = "en",
        cover_path: str | None = None,
    ) -> BookRecord:
        resolved = str(Path(file_path).resolve())
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO books (file_path, file_hash, file_format, title, author, language,
                               cover_path, added_at, last_opened)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0)
            ON CONFLICT(file_path) DO UPDATE SET
                file_hash = excluded.file_hash,
                file_format = excluded.file_format,
                title = excluded.title,
                author = excluded.author,
                language = excluded.language,
                cover_path = COALESCE(excluded.cover_path, books.cover_path)
            """,
            (resolved, file_hash, file_format, title, author, language, cover_path, now),
        )
        self._conn.commit()
        return self.get_book_by_path(resolved)  # type: ignore[return-value]

    def list_books(self, query: str = "", sort_by: str = "recent") -> list[BookRecord]:
        order = {
            "recent": "last_opened DESC, added_at DESC",
            "title": "LOWER(title) ASC",
            "author": "LOWER(author) ASC, LOWER(title) ASC",
            "added": "added_at DESC",
        }.get(sort_by, "last_opened DESC, added_at DESC")
        q = query.strip().lower()
        if q:
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = self._conn.execute(
                f"SELECT * FROM books WHERE LOWER(title) LIKE ? ESCAPE '\\' "
                f"OR LOWER(author) LIKE ? ESCAPE '\\' ORDER BY {order}",
                (like, like),
            ).fetchall()
        else:
            rows = self._conn.execute(f"SELECT * FROM books ORDER BY {order}").fetchall()
        return [self._book(r) for r in rows]

    def continue_reading(self, limit: int = 3) -> list[BookRecord]:
        """Books opened before and not finished, most recent first."""
        rows = self._conn.execute(
            "SELECT * FROM books WHERE last_opened > 0 AND book_fraction < 0.995 "
            "ORDER BY last_opened DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._book(r) for r in rows]

    def get_book(self, book_id: int) -> BookRecord | None:
        row = self._conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return self._book(row) if row else None

    def get_book_by_path(self, file_path: str | Path) -> BookRecord | None:
        row = self._conn.execute(
            "SELECT * FROM books WHERE file_path = ?", (str(Path(file_path).resolve()),)
        ).fetchone()
        return self._book(row) if row else None

    def find_by_hash(self, file_hash: str) -> list[BookRecord]:
        rows = self._conn.execute("SELECT * FROM books WHERE file_hash = ?", (file_hash,)).fetchall()
        return [self._book(r) for r in rows]

    def update_path(self, book_id: int, file_path: str | Path) -> None:
        self._conn.execute(
            "UPDATE books SET file_path = ? WHERE id = ?", (str(Path(file_path).resolve()), book_id)
        )
        self._conn.commit()

    def update_cover(self, book_id: int, cover_path: str) -> None:
        self._conn.execute("UPDATE books SET cover_path = ? WHERE id = ?", (cover_path, book_id))
        self._conn.commit()

    def update_metadata(self, book_id: int, title: str, author: str) -> None:
        self._conn.execute("UPDATE books SET title = ?, author = ? WHERE id = ?", (title, author, book_id))
        self._conn.commit()

    def update_progress(
        self,
        book_id: int,
        chapter_index: int,
        chapter_fraction: float,
        book_fraction: float,
        cfi: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE books
            SET chapter_index = ?, chapter_fraction = ?, book_fraction = ?,
                cfi = COALESCE(?, cfi), last_opened = ?
            WHERE id = ?
            """,
            (
                max(0, int(chapter_index)),
                max(0.0, min(1.0, float(chapter_fraction))),
                max(0.0, min(1.0, float(book_fraction))),
                cfi,
                time.time(),
                book_id,
            ),
        )
        self._conn.commit()

    def touch_opened(self, book_id: int) -> None:
        self._conn.execute("UPDATE books SET last_opened = ? WHERE id = ?", (time.time(), book_id))
        self._conn.commit()

    def delete_book(self, book_id: int) -> DeletedBook | None:
        """Delete a book and its bookmarks; returns what `restore_book` needs to undo it."""
        row = self._conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if row is None:
            return None
        marks = self._conn.execute("SELECT * FROM bookmarks WHERE book_id = ?", (book_id,)).fetchall()
        snapshot = DeletedBook(book=dict(row), bookmarks=[dict(m) for m in marks])
        self._conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        self._conn.commit()
        return snapshot

    def restore_book(self, snapshot: DeletedBook) -> BookRecord | None:
        with self._conn:
            cols = list(snapshot.book)
            self._conn.execute(
                f"INSERT INTO books ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [snapshot.book[c] for c in cols],
            )
            for bm in snapshot.bookmarks:
                bcols = list(bm)
                self._conn.execute(
                    f"INSERT INTO bookmarks ({', '.join(bcols)}) VALUES ({', '.join('?' * len(bcols))})",
                    [bm[c] for c in bcols],
                )
        return self.get_book(snapshot.book["id"])

    def cover_in_use(self, cover_path: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM books WHERE cover_path = ? LIMIT 1", (cover_path,)
        ).fetchone() is not None

    # ------------------------------------------------------------ bookmarks

    @staticmethod
    def _bookmark(row: sqlite3.Row) -> BookmarkRecord:
        return BookmarkRecord(**{k: row[k] for k in BookmarkRecord.__dataclass_fields__})

    def add_bookmark(
        self,
        book_id: int,
        label: str,
        chapter_index: int,
        book_fraction: float,
        cfi: str | None = None,
        excerpt: str = "",
    ) -> BookmarkRecord:
        cur = self._conn.execute(
            """
            INSERT INTO bookmarks (book_id, label, chapter_index, book_fraction, cfi, excerpt, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (book_id, label, chapter_index, book_fraction, cfi, excerpt[:240], time.time()),
        )
        self._conn.commit()
        row = self._conn.execute("SELECT * FROM bookmarks WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._bookmark(row)

    def list_bookmarks(self, book_id: int) -> list[BookmarkRecord]:
        rows = self._conn.execute(
            "SELECT * FROM bookmarks WHERE book_id = ? ORDER BY book_fraction ASC, created_at ASC",
            (book_id,),
        ).fetchall()
        return [self._bookmark(r) for r in rows]

    def rename_bookmark(self, bookmark_id: int, label: str) -> None:
        self._conn.execute("UPDATE bookmarks SET label = ? WHERE id = ?", (label, bookmark_id))
        self._conn.commit()

    def delete_bookmark(self, bookmark_id: int) -> None:
        self._conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        self._conn.commit()
