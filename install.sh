#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAEMON_NAME="kb-autolight"

BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/$DAEMON_NAME"
SERVICE_DIR="$HOME/.config/systemd/user"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# --- Preflight checks ---

info "Running preflight checks..."

# Python 3
if ! command -v python3 &>/dev/null; then
    error "Python 3 is required but not found. Install it with: sudo dnf install python3"
    exit 1
fi
info "Python 3 found: $(python3 --version)"

# Keyboard backlight
KBD_MATCHES=$(ls -d /sys/class/leds/*kbd_backlight 2>/dev/null || true)
if [ -z "$KBD_MATCHES" ]; then
    warn "No keyboard backlight device found in /sys/class/leds/"
    echo "  Your laptop may not have a keyboard backlight, or the driver may not be loaded."
    echo ""
    echo "  Continuing installation anyway — the service will fail until the device is available."
else
    KBD_DEVICE=$(basename "$(echo "$KBD_MATCHES" | head -1)")
    info "Keyboard backlight found: $KBD_DEVICE"
fi

# Ambient light sensor
SENSOR_MATCHES=$(ls /sys/bus/iio/devices/iio:device*/in_illuminance_raw 2>/dev/null || true)
if [ -z "$SENSOR_MATCHES" ]; then
    warn "No ambient light sensor found."
    echo "  Expected at: /sys/bus/iio/devices/iio:device*/in_illuminance_raw"
    echo "  Try loading the kernel module: sudo modprobe hid_sensor_als"
    echo ""
    echo "  Continuing installation anyway — the service will fail until the sensor is available."
else
    info "Ambient light sensor found: $(echo "$SENSOR_MATCHES" | head -1)"
fi

# --- Remove the pre-rename install (fw13-kb-autolight) ---
# Leaving it running alongside the new service makes the two fight over the
# backlight every 5 seconds, and the old config silently wins.

OLD_NAME="fw13-kb-autolight"
if [ -f "$SERVICE_DIR/$OLD_NAME.service" ] || [ -f "$BIN_DIR/$OLD_NAME.py" ]; then
    info "Found old $OLD_NAME install, removing it"
    systemctl --user disable --now "$OLD_NAME.service" &>/dev/null || true
    rm -f "$SERVICE_DIR/$OLD_NAME.service" "$BIN_DIR/$OLD_NAME.py"
    if [ -f "$HOME/.config/$OLD_NAME/$OLD_NAME.conf" ] && [ ! -f "$CONFIG_DIR/$DAEMON_NAME.conf" ]; then
        info "Moving old config to $CONFIG_DIR/$DAEMON_NAME.conf"
        mkdir -p "$CONFIG_DIR"
        mv "$HOME/.config/$OLD_NAME/$OLD_NAME.conf" "$CONFIG_DIR/$DAEMON_NAME.conf"
    fi
    rm -rf "$HOME/.config/$OLD_NAME"
fi

# --- Install ---

info "Installing daemon script to $BIN_DIR/"
mkdir -p "$BIN_DIR"
cp "$SCRIPT_DIR/$DAEMON_NAME.py" "$BIN_DIR/$DAEMON_NAME.py"
chmod +x "$BIN_DIR/$DAEMON_NAME.py"

if [ -f "$CONFIG_DIR/$DAEMON_NAME.conf" ]; then
    info "Config file already exists at $CONFIG_DIR/$DAEMON_NAME.conf — keeping existing config"
else
    info "Installing default config to $CONFIG_DIR/"
    mkdir -p "$CONFIG_DIR"
    cp "$SCRIPT_DIR/$DAEMON_NAME.conf" "$CONFIG_DIR/$DAEMON_NAME.conf"
fi

info "Installing systemd user service to $SERVICE_DIR/"
mkdir -p "$SERVICE_DIR"
cp "$SCRIPT_DIR/$DAEMON_NAME.service" "$SERVICE_DIR/$DAEMON_NAME.service"

info "Reloading systemd user daemon..."
systemctl --user daemon-reload

# restart rather than "enable --now", which leaves an already running
# service on the old script when updating
info "Enabling and starting $DAEMON_NAME service..."
systemctl --user enable "$DAEMON_NAME.service"
systemctl --user restart "$DAEMON_NAME.service"

echo ""
info "Installation complete!"
echo ""
systemctl --user status "$DAEMON_NAME.service" --no-pager || true
echo ""
echo "  View logs:     journalctl --user -u $DAEMON_NAME -f"
echo "  Edit config:   $CONFIG_DIR/$DAEMON_NAME.conf"
echo "  Restart:       systemctl --user restart $DAEMON_NAME"
echo ""
