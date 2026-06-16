#!/usr/bin/env bash
# Build a .deb package for Lid Behaviour (system-wide install).
#
#   ./packaging/build-deb.sh [version]   # default version: 1.0.0
#
# Output: dist/lidbehaviour_<version>_all.deb
# Install with:  sudo apt install ./dist/lidbehaviour_<version>_all.deb
set -euo pipefail

VERSION="${1:-1.0.0}"
PKG="lidbehaviour"
ARCH="all"
APP_ID="no.finter.LidBehaviour"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
ROOT="$BUILD/$PKG"

# --- File tree (FHS, system-wide) -----------------------------------------
# App code. lidbehaviour.py locates dockd.py relative to itself, so keeping
# both in one dir is all that's needed.
install -Dm644 "$REPO/lidbehaviour.py" "$ROOT/usr/share/lidbehaviour/lidbehaviour.py"
install -Dm644 "$REPO/dockd.py"        "$ROOT/usr/share/lidbehaviour/dockd.py"

# Launcher on PATH (the .desktop file's Exec=lidbehaviour resolves to this).
mkdir -p "$ROOT/usr/bin"
cat > "$ROOT/usr/bin/lidbehaviour" <<'EOF'
#!/usr/bin/env bash
exec python3 /usr/share/lidbehaviour/lidbehaviour.py "$@"
EOF
chmod 755 "$ROOT/usr/bin/lidbehaviour"

# Desktop entry + icon.
install -Dm644 "$REPO/data/$APP_ID.desktop" \
    "$ROOT/usr/share/applications/$APP_ID.desktop"
install -Dm644 "$REPO/data/$APP_ID.svg" \
    "$ROOT/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"

# systemd *user* service — opt-in, enabled per-user from the app's
# "Automatically restore on dock" switch. Shipped as a system-provided user
# unit; ExecStart points at the packaged dockd.py.
mkdir -p "$ROOT/usr/lib/systemd/user"
cat > "$ROOT/usr/lib/systemd/user/lidbehaviour-dock.service" <<'EOF'
[Unit]
Description=Lid Behaviour — restore display layout on dock
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/share/lidbehaviour/dockd.py --watch
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF

# Copyright file (Debian convention) — the MIT license text.
install -Dm644 "$REPO/LICENSE" "$ROOT/usr/share/doc/$PKG/copyright"

# --- Control metadata ------------------------------------------------------
INSTALLED_KB="$(du -ks "$ROOT/usr" | cut -f1)"
mkdir -p "$ROOT/DEBIAN"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-glib-2.0
Installed-Size: $INSTALLED_KB
Maintainer: Alexander H Kristiansen <alhjakri@pm.me>
Homepage: https://github.com/aHk-coder/laptop-lidmanager-for-gnome
Description: Choose what closing your laptop lid does, on GNOME
 A tiny GTK4/libadwaita GUI to set the lid-close action per power state
 (plugged in / on battery), like Windows 11 Power Options — no terminal and
 no root. It also remembers external-monitor layouts by serial so they
 survive docking, even on DisplayLink docks that rename the ports.
EOF

# Refresh desktop/icon caches after (de)install (cosmetic; never fail on it).
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache -qtf /usr/share/icons/hicolor 2>/dev/null || true
fi
EOF
chmod 755 "$ROOT/DEBIAN/postinst"

cat > "$ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache -qtf /usr/share/icons/hicolor 2>/dev/null || true
fi
EOF
chmod 755 "$ROOT/DEBIAN/postrm"

# --- Build -----------------------------------------------------------------
mkdir -p "$REPO/dist"
OUT="$REPO/dist/${PKG}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT"
echo "✓ Built $OUT"
