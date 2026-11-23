# Ebookread (GTK4 / Libadwaita Edition)

An Ubuntu-native ebook reader built with **GTK4**, **Libadwaita**, and **WebKitGTK 6.0**, replacing the earlier PyQt5/`QTextBrowser` implementation.

## What Changed from the PyQt5 Version

- **WebKitGTK 6.0 rendering engine** (`epubread/ui/reader_view.py`, `epubread/web/`): Full HTML5/CSS3/SVG/embedded-font fidelity via a custom `ebookread://` URI scheme, replacing `QTextBrowser`. Automatically uses [`foliate-js`](https://github.com/johnfactotum/foliate-js) when present (for EPUB, MOBI, AZW3, FB2, CBZ, and PDF) and includes a zero-dependency built-in CSS multi-column EPUB paginator fallback.
- **SQLite-backed Library Home View** (`epubread/core/db.py`, `epubread/ui/library_view.py`): Cover grid is now the primary landing view with instant search, sorting, drag-and-drop import, and cached cover thumbnails—no more blocking modal `QDialog` re-parsing books on open.
- **Live Typography & Theme Popover** (`epubread/ui/settings_popover.py`, `epubread/ui/theme.py`): Non-blocking popover with Light, Sepia, Dark, and OLED Black presets, calibrated warm amber overlay (fixing the malformed 4-argument `rgb(...)` bug), font size, line height, readable line measure, and Paginated vs. Scrolled toggle.
- **Navigation & Reading State**: Two-column spread on wide screens, arrow/spacebar/edge-click pagination, bottom progress scrubber, inline footnote popovers, collapsible TOC/Bookmarks/Search sidebar (`Adw.OverlaySplitView`), and click-center / `F11` distraction-free reading.

## Requirements (Ubuntu 24.04+)

```bash
sudo apt-get install -y \
  python3-gi python3-gi-cairo \
  gir1.2-gtk-4.0 gir1.2-adw-1 \
  gir1.2-webkit-6.0 gir1.2-poppler-0.18
```

## Quick Start

```bash
# Install system dependencies + desktop entry (EPUB works immediately)
chmod +x install.sh
./install.sh

# Optional: also clone foliate-js for native MOBI, AZW3, FB2, CBZ, and PDF rendering
./install.sh --with-foliate-js

# Run directly from source
python3 run.py
# Or open a book directly
python3 run.py ~/Books/example.epub
```

## Running Tests

```bash
python3 -m unittest discover -s tests -v
```
