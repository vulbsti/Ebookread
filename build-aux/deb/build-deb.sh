#!/bin/sh
# Builds dist/ebookread_<version>_all.deb for Ubuntu 24.04+ and Debian 13+.
#   build-aux/deb/build-deb.sh
# Pure Python on top of the distro's GTK4, Libadwaita and WebKitGTK, so one
# architecture-independent package serves every machine; the distro keeps WebKit
# patched. Older releases (Libadwaita < 1.5) can't satisfy Depends: use the Flatpak.
set -eu
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$SRC/build-aux/deb"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/epubread/__init__.py")"
STAGE="$SRC/build/deb/ebookread_$VERSION"
OUT="$SRC/dist/ebookread_${VERSION}_all.deb"

if [ -e "$STAGE" ]; then
  mv "$STAGE" "$STAGE.old.$$"   # keep stale trees out of the package without deleting
fi
mkdir -p "$STAGE/DEBIAN" "$SRC/dist"

DESTDIR="$STAGE" NO_COMPILE=1 "$SRC/build-aux/install-app.sh" /usr
# Debian keeps licences in the copyright file, not under share/licenses.
mv "$STAGE/usr/share/licenses" "$SRC/build/deb/licenses.$$"

DOC="$STAGE/usr/share/doc/ebookread"
install -Dm644 "$HERE/copyright" "$DOC/copyright"
sed "s/@VERSION@/$VERSION/; s/@DATE@/$(date -uR -d "@${SOURCE_DATE_EPOCH:-$(git -C "$SRC" log -1 --format=%ct 2>/dev/null || date +%s)}")/" \
  "$HERE/changelog.in" | gzip -9n > "$DOC/changelog.gz"
chmod 644 "$DOC/changelog.gz"

install -m755 "$HERE/postinst" "$HERE/prerm" "$STAGE/DEBIAN/"
SIZE="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"
sed "s/@VERSION@/$VERSION/; s/@SIZE@/$SIZE/" "$HERE/control.in" > "$STAGE/DEBIAN/control"

find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE/usr" -type f -exec chmod 644 {} +
chmod 755 "$STAGE/usr/bin/ebookread"
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$OUT" >/dev/null
echo "$OUT"
