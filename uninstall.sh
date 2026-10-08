#!/usr/bin/env bash
set -euo pipefail

DAEMON_NAME="kb-autolight"

BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/$DAEMON_NAME"
SERVICE_DIR="$HOME/.config/systemd/user"

GREEN='\033[0;32m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $*"; }

# --- Stop and disable service ---

if systemctl --user is-active "$DAEMON_NAME.service" &>/dev/null; then
    info "Stopping $DAEMON_NAME service..."
    systemctl --user stop "$DAEMON_NAME.service"
fi

if systemctl --user is-enabled "$DAEMON_NAME.service" &>/dev/null; then
    info "Disabling $DAEMON_NAME service..."
    systemctl --user disable "$DAEMON_NAME.service"
fi

# --- Also remove the pre-rename install (fw13-kb-autolight), if any ---

OLD_NAME="fw13-kb-autolight"
if [ -f "$SERVICE_DIR/$OLD_NAME.service" ] || [ -f "$BIN_DIR/$OLD_NAME.py" ]; then
    info "Removing old $OLD_NAME service..."
    systemctl --user disable --now "$OLD_NAME.service" &>/dev/null || true
    rm -f "$SERVICE_DIR/$OLD_NAME.service" "$BIN_DIR/$OLD_NAME.py"
    rm -rf "$HOME/.config/$OLD_NAME"
fi

# --- Remove files ---

if [ -f "$SERVICE_DIR/$DAEMON_NAME.service" ]; then
    info "Removing service file..."
    rm "$SERVICE_DIR/$DAEMON_NAME.service"
    systemctl --user daemon-reload
fi

if [ -f "$BIN_DIR/$DAEMON_NAME.py" ]; then
    info "Removing daemon script..."
    rm "$BIN_DIR/$DAEMON_NAME.py"
fi

# --- Config removal (ask first) ---

if [ -d "$CONFIG_DIR" ]; then
    echo ""
    read -rp "Remove config directory ($CONFIG_DIR)? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        info "Removing config directory..."
        rm -rf "$CONFIG_DIR"
    else
        info "Keeping config directory at $CONFIG_DIR"
    fi
fi

# --- Turn off backlight ---

KBD_DEVICE=$(basename "$(ls -d /sys/class/leds/*kbd_backlight 2>/dev/null | head -1)" 2>/dev/null || true)
if [ -n "$KBD_DEVICE" ]; then
    info "Turning off keyboard backlight..."
    busctl call org.freedesktop.login1 /org/freedesktop/login1/session/auto \
        org.freedesktop.login1.Session SetBrightness ssu leds "$KBD_DEVICE" 0 &>/dev/null || true
fi

echo ""
info "Uninstall complete."
