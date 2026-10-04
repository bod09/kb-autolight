# kb-autolight

Automatic keyboard backlight control based on ambient light for Linux laptops.

Keeps the keyboard backlight **off** by default and turns it on to a low brightness when the room gets dark, using the laptop's built-in ambient light sensor. Turns on instantly in the dark and uses debounce when turning off to prevent flickering.

Works on any Linux laptop with an IIO ambient light sensor and a keyboard backlight — not limited to Framework laptops.

> **Tested on:** Framework Laptop 13 (AMD), Fedora 43, KDE Plasma. Other laptops and distros with systemd should work but are untested.

## How it works

The daemon polls the ambient light sensor and controls the keyboard backlight via logind D-Bus (no extra dependencies):

```
                    raw <= 0 (instant)
  [BRIGHT / OFF] ──────────────────────────────────────► [DARK / ON at 1%]
                 ◄──────────────────────────────────────
                    raw > 1 (3 consecutive readings)
```

Turning **on** is instant — when it goes dark you need to see the keys now. Turning **off** is debounced (default: 3 consecutive readings) to prevent flickering from brief sensor fluctuations.

In a dark room the keyboard's own light can reach the sensor and look like the room got brighter. The daemon notices this (it goes dark again the moment the backlight switches off), measures how much the backlight adds to the reading, and ignores that amount while the backlight is on. You may see one off/on blink the first time this happens after the service starts.

## Prerequisites

- A Linux laptop with:
  - An ambient light sensor exposed at `/sys/bus/iio/devices/iio:device*/in_illuminance_raw`
  - A keyboard backlight in `/sys/class/leds/*kbd_backlight`
- **systemd** (for the user service and `busctl`)
- **Python 3**

No additional packages to install — uses `busctl` (part of systemd) to control the backlight without root.

## Installation

```bash
curl -L https://github.com/bod09/kb-autolight/archive/refs/heads/main.tar.gz | tar xz
cd kb-autolight-main
./install.sh
```

Or if you have git installed:

```bash
git clone https://github.com/bod09/kb-autolight.git
cd kb-autolight
./install.sh
```

The install script will:
1. Check for Python 3, keyboard backlight, and the ambient light sensor
2. Install the daemon to `~/.local/bin/`
3. Install the default config to `~/.config/kb-autolight/`
4. Install and start a systemd user service (no root needed)

## Configuration

Edit `~/.config/kb-autolight/kb-autolight.conf`:

```ini
[thresholds]
dark = 0        # Sensor value at or below which backlight turns ON
light = 1       # Sensor value above which backlight turns OFF

[backlight]
brightness = 1  # Backlight brightness (0-100) when dark
device =        # Leave blank for auto-detect, or set device name

[polling]
interval = 1    # Seconds between sensor reads
debounce = 3    # Consecutive readings before turning OFF (on is instant)

[sensor]
device =        # Leave blank for auto-detect, or set full sysfs path
```

After editing, restart the service:

```bash
systemctl --user restart kb-autolight
```

### Finding your sensor values

Read the raw sensor value to calibrate your thresholds:

```bash
# Find your sensor
ls /sys/bus/iio/devices/iio:device*/in_illuminance_raw

# Read the current value
cat /sys/bus/iio/devices/iio:device0/in_illuminance_raw
```

Try reading the value in different lighting conditions:
- Cover the sensor with your hand — note the low value
- Normal room lighting — note the value
- Bright daylight — note the high value

Set `dark` to the value where you can no longer comfortably see the keys, and `light` to the value where you can.

> **Note:** The default thresholds (dark=0, light=1) were tuned for the Framework Laptop 13 which has a narrow sensor range (0–16). Other laptops may have much wider ranges and will need different values.

### Finding your keyboard backlight device

```bash
ls /sys/class/leds/*kbd_backlight
```

Common device names:
- `chromeos::kbd_backlight` — Framework laptops
- `framework_laptop::kbd_backlight` — Framework with framework-laptop-kmod
- `tpacpi::kbd_backlight` — ThinkPads
- `asus::kbd_backlight` — ASUS laptops
- `dell::kbd_backlight` — Dell laptops

The daemon auto-detects this, but you can pin it in the config under `[backlight] device`.

## Usage

```bash
# Check service status
systemctl --user status kb-autolight

# View live logs
journalctl --user -u kb-autolight -f

# Restart after config changes
systemctl --user restart kb-autolight

# Stop temporarily
systemctl --user stop kb-autolight

# Start again
systemctl --user start kb-autolight
```

## Uninstallation

If you still have the source folder:

```bash
cd kb-autolight-main
./uninstall.sh
```

Or re-download and uninstall:

```bash
curl -L https://github.com/bod09/kb-autolight/archive/refs/heads/main.tar.gz | tar xz
./kb-autolight-main/uninstall.sh
```

This stops the service, removes the daemon and service file, and optionally removes the config directory.

## Troubleshooting

### Sensor not found

If the install script or daemon reports no sensor:

```bash
# Check if the kernel module is loaded
lsmod | grep hid_sensor_als

# Load it manually
sudo modprobe hid_sensor_als

# Make it persistent
echo "hid_sensor_als" | sudo tee /etc/modules-load.d/hid_sensor_als.conf
```

### Service keeps restarting

Check the logs for errors:

```bash
journalctl --user -u kb-autolight --no-pager -n 50
```

Common causes:
- Sensor path changed after a kernel update (restart the service to re-detect)
- Invalid config values (dark must be less than light)

### Backlight keeps switching on and off

Check the logs while it is happening:

```bash
journalctl --user -u kb-autolight -f
```

- Alternating `Light detected` / `Dark detected` lines mean the sensor is reacting to the backlight itself. The daemon compensates for this automatically after the first blink. If it still flickers, raise `light` in the config or lower `brightness`.
- Repeated `Backlight was reset` lines mean something else is changing the backlight (the brightness key, your desktop's power settings, or the laptop firmware). After 3 resets in 2 minutes the daemon stops restoring it until the next time it gets dark.

## License

MIT — see [LICENSE](LICENSE).
