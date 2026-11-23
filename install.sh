#!/usr/bin/env bash
set -euo pipefail

# Ubuntu 24.04+ installer for Ebookread (GTK4 + Libadwaita + WebKitGTK 6.0)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WITH_FOLIATE=0

for arg in "$@"; do
  case "$arg" in
    --with-foliate-js) WITH_FOLIATE=1 ;;
  esac
done

echo "==> Installing Ubuntu GTK4 / Libadwaita / WebKitGTK 6.0 system packages..."
sudo apt-get update
sudo apt-get install -y \
  python3-gi \
  python3-gi-cairo \
  gir1.2-gtk-4.0 \
  gir1.2-adw-1 \
  gir1.2-webkit-6.0 \
  gir1.2-poppler-0.18

if [[ "$WITH_FOLIATE" -eq 1 ]]; then
  echo "==> Cloning foliate-js into epubread/web/foliate-js..."
  mkdir -p "$SCRIPT_DIR/epubread/web"
  if [[ -d "$SCRIPT_DIR/epubread/web/foliate-js/.git" ]]; then
    git -C "$SCRIPT_DIR/epubread/web/foliate-js" pull --ff-only
  else
    git clone --depth 1 https://github.com/johnfactotum/foliate-js.git "$SCRIPT_DIR/epubread/web/foliate-js"
  fi
fi

echo "==> Installing ebookread into user Python environment..."
python3 -m pip install --user --break-system-packages -e "$SCRIPT_DIR"

echo "==> Installing desktop entry..."
mkdir -p "$HOME/.local/share/applications"
cp "$SCRIPT_DIR/ebookread.desktop" "$HOME/.local/share/applications/ebookread.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "==> Done! Launch with: ebookread  (or ./run.py)"
