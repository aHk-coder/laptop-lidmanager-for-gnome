#!/usr/bin/env bash
# Remove Lid Behaviour for the current user. Does not change your settings.
set -euo pipefail

APP_ID="no.finter.LidBehaviour"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="$HOME/.local/bin"

rm -f  "$BIN/lidbehaviour"
rm -rf "$PREFIX/lidbehaviour"
rm -f  "$PREFIX/applications/$APP_ID.desktop"
rm -f  "$PREFIX/icons/hicolor/scalable/apps/$APP_ID.svg"

update-desktop-database "$PREFIX/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "$PREFIX/icons/hicolor" 2>/dev/null || true

echo "✓ Removed. Your lid settings are unchanged."
echo "  To reset them to GNOME defaults, run:"
echo "    gsettings reset org.gnome.settings-daemon.plugins.power lid-close-ac-action"
echo "    gsettings reset org.gnome.settings-daemon.plugins.power lid-close-battery-action"
