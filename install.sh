#!/usr/bin/env bash
# Install Ebookread for the current user on Ubuntu 24.04+ / Debian (no Flatpak).
# For other distributions, build the Flatpak instead (see README).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"

echo "==> Installing system packages (GTK4, Libadwaita, WebKitGTK 6.0)…"
sudo apt-get update
sudo apt-get install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0

echo "==> Installing Ebookread into $PREFIX…"
"$SCRIPT_DIR/build-aux/install-app.sh" "$PREFIX"
update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true

echo "==> Done. Launch “Ebookread” from your apps, or run: $PREFIX/bin/ebookread"
