"""Reading themes: palettes, page CSS variables, colour filters, and matching window chrome."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import ReaderSettings


@dataclass(frozen=True)
class ThemePalette:
    name: str
    bg: str
    fg: str
    muted: str
    accent: str
    surface: str  # toolbars and popovers around the page
    border: str
    is_dark: bool


PALETTES: dict[str, ThemePalette] = {
    "light": ThemePalette("Light", "#ffffff", "#1c1c1e", "#636366", "#2a6df4", "#f2f2f4", "#e2e2e7", False),
    "sepia": ThemePalette("Sepia", "#f7f1e3", "#342a1e", "#7a6a53", "#9c5a1b", "#ece3cf", "#dfd3bc", False),
    "dark": ThemePalette("Dark", "#1e1e22", "#dedee4", "#9a9aa6", "#6ea8fe", "#28282e", "#383842", True),
    "oled": ThemePalette("Black", "#000000", "#d4d4d8", "#8e8e98", "#7ab3ff", "#0e0e10", "#24242b", True),
}

THEME_CHOICES = [("system", "Follow system"), ("light", "Light"), ("sepia", "Sepia"),
                 ("dark", "Dark"), ("oled", "Black")]


def resolve_theme(theme: str, system_dark: bool) -> str:
    """'system' becomes light or dark; anything unknown becomes sepia."""
    if theme == "system":
        return "dark" if system_dark else "light"
    return theme if theme in PALETTES else "sepia"


def get_palette(theme_name: str, system_dark: bool = False) -> ThemePalette:
    return PALETTES[resolve_theme(theme_name, system_dark)]


def color_filter(settings: ReaderSettings, invert: bool = False) -> str:
    """CSS filter for the page: contrast, colour (grayscale) and brightness; 'none' at defaults."""
    parts = []
    if invert:
        parts.append("invert(1) hue-rotate(180deg)")
    if settings.contrast != 100:
        parts.append(f"contrast({settings.contrast}%)")
    if settings.saturation != 100:
        parts.append(f"saturate({settings.saturation}%)")
    if settings.brightness != 100:
        parts.append(f"brightness({settings.brightness}%)")
    return " ".join(parts) or "none"


def build_reader_css_vars(settings: ReaderSettings, system_dark: bool = False) -> dict[str, str]:
    """CSS custom properties for the reader page."""
    p = get_palette(settings.theme, system_dark)
    warm_alpha = round((max(0, min(100, settings.warmth)) / 100.0) * 0.28, 3)
    return {
        "--er-bg": p.bg,
        "--er-fg": p.fg,
        "--er-muted": p.muted,
        "--er-accent": p.accent,
        "--er-surface": p.surface,
        "--er-border": p.border,
        "--er-font-family": settings.font_family,
        "--er-font-size": f"{settings.font_size}px",
        "--er-line-height": str(settings.line_height),
        "--er-text-align": "justify" if settings.justify else "start",
        "--er-hyphens": "auto" if settings.hyphenate else "manual",
        "--er-warm-overlay": f"rgba(255, 168, 64, {warm_alpha})",
    }


def chrome_css(palette: ThemePalette) -> str:
    """GTK CSS so the reader's header bar and footer wear the page's colours."""
    return f"""
    .reader-chrome, headerbar.reader-chrome {{
      background-color: {palette.surface};
      color: {palette.fg};
      box-shadow: none;
    }}
    .reader-chrome.top {{ border-bottom: 1px solid {palette.border}; }}
    .reader-chrome.bottom {{ border-top: 1px solid {palette.border}; }}
    .reader-chrome scale trough highlight {{ background-color: {palette.accent}; }}
    .reader-chrome scale marks {{ color: {palette.muted}; }}
    """


SWATCH_CSS = "".join(
    f".theme-swatch.{key} {{ background: {p.bg}; color: {p.fg}; }}\n" for key, p in PALETTES.items()
) + """
.theme-swatch {
  min-width: 36px; min-height: 36px; padding: 0; border-radius: 999px;
  box-shadow: inset 0 0 0 1px alpha(currentColor, 0.25);
  font-weight: bold;
}
.theme-swatch.system { background: linear-gradient(135deg, #ffffff 50%, #1e1e22 50%); color: #888; }
.theme-swatch:checked { box-shadow: inset 0 0 0 3px @accent_bg_color; }
"""
