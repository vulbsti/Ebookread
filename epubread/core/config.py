"""XDG-compliant configuration management for Ebookread."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def get_config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "ebookread"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "ebookread"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = base / "ebookread"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class ReaderSettings:
    # Colours
    theme: str = "sepia"            # system | light | sepia | dark | oled
    warmth: int = 0                 # 0..100  amber tint
    contrast: int = 100             # 50..150 %
    saturation: int = 100           # 0..100 %  (0 = grayscale)
    brightness: int = 100           # 40..100 % (lower = darker)
    invert_pdf_in_dark: bool = True  # dark themes invert PDF pages (not comics)
    # Text ("my formatting"); with publisher_formatting only size and colours apply
    publisher_formatting: bool = False
    font_family: str = "serif"      # CSS font-family value
    font_size: int = 18             # px (12..36)
    line_height: float = 1.6        # 1.2..2.2
    paragraph_spacing: str = "book"  # book | none | small | large
    justify: bool = True
    hyphenate: bool = True
    # Layout
    layout_mode: str = "paginated"  # paginated | scrolled
    columns: str = "auto"           # auto | single
    max_width: int = 720            # px (480..1400) longest line
    margin_pct: int = 6             # side margins, % of the page (2..14)
    fxl_zoom: str = "fit-page"      # PDFs/comics: fit-page | fit-width | 100 | 150 | 200
    # Window
    auto_hide_controls: bool = True
    window_width: int = 1120
    window_height: int = 780

    THEMES = ("system", "light", "sepia", "dark", "oled")
    PARAGRAPH_SPACINGS = ("book", "none", "small", "large")
    ZOOMS = ("fit-page", "fit-width", "100", "150", "200")

    def clamp(self) -> "ReaderSettings":
        def num(value, lo, hi, kind=int):
            try:
                return max(lo, min(hi, kind(value)))
            except (TypeError, ValueError):
                return lo

        if self.theme not in self.THEMES:
            self.theme = "sepia"
        self.warmth = num(self.warmth, 0, 100)
        self.contrast = num(self.contrast, 50, 150)
        self.saturation = num(self.saturation, 0, 100)
        self.brightness = num(self.brightness, 40, 100)
        self.font_family = str(self.font_family or "serif").strip()[:200] or "serif"
        self.font_size = num(self.font_size, 12, 36)
        self.line_height = round(num(self.line_height, 1.2, 2.2, float), 2)
        if self.paragraph_spacing not in self.PARAGRAPH_SPACINGS:
            self.paragraph_spacing = "book"
        if self.layout_mode not in ("paginated", "scrolled"):
            self.layout_mode = "paginated"
        if self.columns not in ("auto", "single"):
            self.columns = "auto"
        self.max_width = num(self.max_width, 480, 1400)
        self.margin_pct = num(self.margin_pct, 2, 14)
        if str(self.fxl_zoom) not in self.ZOOMS:
            self.fxl_zoom = "fit-page"
        for flag in ("invert_pdf_in_dark", "publisher_formatting", "justify", "hyphenate", "auto_hide_controls"):
            setattr(self, flag, bool(getattr(self, flag)))
        self.window_width = num(self.window_width, 640, 10000)
        self.window_height = num(self.window_height, 480, 10000)
        return self


class ConfigStore:
    """Loads and persists ReaderSettings to XDG config JSON."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.path = config_path or (get_config_dir() / "settings.json")
        self.settings = self._load()

    def _load(self) -> ReaderSettings:
        if not self.path.exists():
            return ReaderSettings().clamp()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            valid = {
                k: v for k, v in raw.items() if k in ReaderSettings.__dataclass_fields__
            }
            return ReaderSettings(**valid).clamp()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return ReaderSettings().clamp()

    def update(self, **kwargs: Any) -> ReaderSettings:
        for key, value in kwargs.items():
            if hasattr(self.settings, key):
                setattr(self.settings, key, value)
        self.settings.clamp()
        self.save()
        return self.settings

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(asdict(self.settings), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.path)
