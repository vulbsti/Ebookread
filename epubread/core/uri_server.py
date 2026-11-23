"""Custom URI scheme resolver (`ebookread://`) for WebKitGTK 6.0.

Everything is served from one origin, ``ebookread://app``, so the reader page can
fetch the book without any cross-origin rules:

  ebookread://app/<path>     -> bundled web assets (reader.html, reader.js, foliate-js/...)
  ebookread://app/book/raw   -> raw bytes of the open book (read by foliate-js)
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
APP_ORIGIN = "ebookread://app"

# Book scripts must never run: they would share the page's origin and could reach the
# Python bridge. Section iframes are blob: documents, which inherit this policy.
CONTENT_SECURITY_POLICY = (
    "default-src 'self' blob: data:; "
    "script-src 'self'; "
    "worker-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline' blob: data:; "
    "img-src 'self' blob: data:; "
    "font-src 'self' blob: data:; "
    "media-src 'self' blob: data:; "
    "connect-src 'self' blob: data:; "
    "frame-src 'self' blob: data:; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)

_MIME_OVERRIDES = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".bcmap": "application/octet-stream",
    ".pfb": "application/octet-stream",
    ".ttf": "font/ttf",
}


class ResourceNotFound(LookupError):
    pass


class BookResourceResolver:
    """Resolves `ebookread://` URIs to `(bytes, mime_type)` pairs."""

    def __init__(self, web_dir: Path | None = None) -> None:
        self.web_dir = (web_dir or WEB_DIR).resolve()
        self._active_path: Path | None = None

    @property
    def active_path(self) -> Path | None:
        return self._active_path

    def open_book(self, file_path: str | Path) -> None:
        self._active_path = Path(file_path).resolve()

    def close_book(self) -> None:
        self._active_path = None

    def resolve(self, uri: str) -> tuple[bytes, str]:
        parsed = urlparse(uri)
        if parsed.scheme != "ebookread" or parsed.netloc != "app":
            raise ResourceNotFound(f"Unknown origin: {uri}")
        path = unquote(parsed.path).lstrip("/")

        if path == "book/raw":
            if self._active_path is None:
                raise ResourceNotFound("No book is open")
            mtype, _ = mimetypes.guess_type(self._active_path.name)
            return self._active_path.read_bytes(), (mtype or "application/octet-stream")

        target = (self.web_dir / path).resolve()
        if not target.is_relative_to(self.web_dir) or not target.is_file():
            raise ResourceNotFound(f"App asset not found: {path}")
        mtype = _MIME_OVERRIDES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0]
        return target.read_bytes(), (mtype or "application/octet-stream")
