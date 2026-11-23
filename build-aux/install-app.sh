#!/bin/sh
# Installs Ebookread into PREFIX (e.g. /app inside Flatpak, /usr for the .deb, ~/.local).
#   [DESTDIR=stage] [NO_COMPILE=1] build-aux/install-app.sh PREFIX
# The package goes to PREFIX/share/ebookread so it doesn't depend on the Python
# version's site-packages path; PREFIX/bin/ebookread finds it relative to itself.
# DESTDIR stages the files for packaging; NO_COMPILE skips .pyc files (the .deb
# compiles them on the target machine, for its Python version).
set -eu
PREFIX="${1:?usage: install-app.sh PREFIX}"
PREFIX="${DESTDIR:-}$PREFIX"
APP_ID=io.github.vulbsti.Ebookread
SRC="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"

mkdir -p "$PREFIX/share/ebookread" "$PREFIX/bin"
tar -C "$SRC" --exclude=__pycache__ --exclude='*.pyc' --exclude='.git*' -cf - epubread | tar -C "$PREFIX/share/ebookread" -xf -
[ -n "${NO_COMPILE:-}" ] || "$PY" -m compileall -q "$PREFIX/share/ebookread/epubread"

cat > "$PREFIX/bin/ebookread" <<'LAUNCHER'
#!/usr/bin/python3
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "share", "ebookread"))
from epubread.main import main
raise SystemExit(main(sys.argv))
LAUNCHER
chmod 755 "$PREFIX/bin/ebookread"

install -Dm644 "$SRC/data/$APP_ID.desktop" "$PREFIX/share/applications/$APP_ID.desktop"
install -Dm644 "$SRC/data/$APP_ID.metainfo.xml" "$PREFIX/share/metainfo/$APP_ID.metainfo.xml"
install -Dm644 "$SRC/data/icons/hicolor/scalable/apps/$APP_ID.svg" \
  "$PREFIX/share/icons/hicolor/scalable/apps/$APP_ID.svg"
install -Dm644 "$SRC/data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg" \
  "$PREFIX/share/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
install -Dm644 "$SRC/LICENSE" "$PREFIX/share/licenses/$APP_ID/LICENSE"
install -Dm644 "$SRC/epubread/web/foliate-js/LICENSE" "$PREFIX/share/licenses/$APP_ID/foliate-js.LICENSE"
