#!/usr/bin/env bash
# Install Lid Behaviour for the current user (no root required).
set -euo pipefail

APP_ID="no.finter.LidBehaviour"
SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="$HOME/.local/bin"

# App code
install -Dm755 "$SRC/lidbehaviour.py" "$PREFIX/lidbehaviour/lidbehaviour.py"
install -Dm755 "$SRC/dockd.py"        "$PREFIX/lidbehaviour/dockd.py"

# Background service that restores the display layout on dock (user, opt-in:
# enabled from the app's "Automatically restore on dock" switch)
install -Dm644 "$SRC/data/lidbehaviour-dock.service" \
    "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/lidbehaviour-dock.service"
systemctl --user daemon-reload 2>/dev/null || true

# Launcher on PATH
install -d "$BIN"
cat > "$BIN/lidbehaviour" <<EOF
#!/usr/bin/env bash
exec python3 "$PREFIX/lidbehaviour/lidbehaviour.py" "\$@"
EOF
chmod 755 "$BIN/lidbehaviour"

# Desktop entry (use an absolute Exec so the app menu works regardless of PATH)
install -Dm644 "$SRC/data/$APP_ID.desktop" "$PREFIX/applications/$APP_ID.desktop"
sed -i "s|^Exec=lidbehaviour\$|Exec=$BIN/lidbehaviour|" "$PREFIX/applications/$APP_ID.desktop"

# Icon
install -Dm644 "$SRC/data/$APP_ID.svg" \
    "$PREFIX/icons/hicolor/scalable/apps/$APP_ID.svg"

# Refresh caches (ignore failures — purely cosmetic)
update-desktop-database "$PREFIX/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "$PREFIX/icons/hicolor" 2>/dev/null || true

echo "✓ Installed."
echo "  Launch from your app menu (search “Lid Behaviour”), or run: lidbehaviour"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "  Note: $BIN is not on your PATH; the app-menu entry still works." ;;
esac
