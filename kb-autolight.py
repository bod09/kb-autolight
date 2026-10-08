#!/usr/bin/env python3
"""
kb-autolight — Automatic keyboard backlight control for Linux laptops.

Reads the ambient light sensor and toggles the keyboard backlight via logind D-Bus.
Uses debounce to avoid flickering when turning off.
"""

import configparser
import fcntl
import glob
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Built-in defaults (used if config file is missing or incomplete)
DEFAULTS = {
    "dark": 0,
    "light": 1,
    "brightness": 1,
    "interval": 1,
    "debounce": 3,
    "sensor": "",
    "keyboard": "",
}

CONFIG_PATH = os.path.expanduser("~/.config/kb-autolight/kb-autolight.conf")
SENSOR_GLOB = "/sys/bus/iio/devices/iio:device*/in_illuminance_raw"
KBD_BACKLIGHT_GLOB = "/sys/class/leds/*kbd_backlight"

# Going dark again within this many polls of switching the backlight off
# means the "light" we saw was the backlight itself.
FLAP_POLLS = 3

# Stop restoring the backlight if something else changes it this many times
# within RESTORE_WINDOW seconds, rather than fighting over it forever.
RESTORE_LIMIT = 3
RESTORE_WINDOW = 120

running = True


def handle_signal(signum, frame):
    global running
    running = False


def load_config():
    config = configparser.ConfigParser()

    if os.path.isfile(CONFIG_PATH):
        config.read(CONFIG_PATH)
        logging.info("Loaded config from %s", CONFIG_PATH)
    else:
        logging.info("No config file found at %s, using defaults", CONFIG_PATH)

    dark = config.getint("thresholds", "dark", fallback=DEFAULTS["dark"])
    light = config.getint("thresholds", "light", fallback=DEFAULTS["light"])
    brightness = config.getint("backlight", "brightness", fallback=DEFAULTS["brightness"])
    interval = config.getint("polling", "interval", fallback=DEFAULTS["interval"])
    debounce = config.getint("polling", "debounce", fallback=DEFAULTS["debounce"])
    sensor = config.get("sensor", "device", fallback=DEFAULTS["sensor"]).strip()
    keyboard = config.get("backlight", "device", fallback=DEFAULTS["keyboard"]).strip()

    if dark >= light:
        logging.error(
            "Invalid config: dark threshold (%d) must be less than light threshold (%d)",
            dark, light,
        )
        sys.exit(1)

    if not 0 <= brightness <= 100:
        logging.error("Invalid config: brightness (%d) must be between 0 and 100", brightness)
        sys.exit(1)

    if interval < 1:
        logging.error("Invalid config: poll interval (%d) must be at least 1 second", interval)
        sys.exit(1)

    if debounce < 1:
        logging.error("Invalid config: debounce (%d) must be at least 1", debounce)
        sys.exit(1)

    return dark, light, brightness, interval, debounce, sensor, keyboard


def find_sensor(device_override):
    if device_override:
        if os.path.isfile(device_override):
            logging.info("Using configured sensor: %s", device_override)
            return device_override
        else:
            logging.error("Configured sensor path does not exist: %s", device_override)
            sys.exit(1)

    matches = sorted(glob.glob(SENSOR_GLOB))
    if not matches:
        logging.error(
            "No ambient light sensor found at %s. "
            "Check that the sensor kernel module is loaded (try: modprobe hid_sensor_als).",
            SENSOR_GLOB,
        )
        sys.exit(1)

    sensor = matches[0]
    logging.info("Auto-detected sensor: %s", sensor)
    if len(matches) > 1:
        logging.info(
            "Multiple sensors found (%d total). Using the first one. "
            "Set 'device' in [sensor] config to override.",
            len(matches),
        )
    return sensor


def find_keyboard(device_override):
    if device_override:
        return device_override

    matches = sorted(glob.glob(KBD_BACKLIGHT_GLOB))
    if not matches:
        logging.error(
            "No keyboard backlight found at %s. "
            "Check that your laptop has a keyboard backlight and the driver is loaded.",
            KBD_BACKLIGHT_GLOB,
        )
        sys.exit(1)

    # Extract device name from path (e.g., "chromeos::kbd_backlight")
    device = os.path.basename(matches[0])
    logging.info("Auto-detected keyboard backlight: %s", device)
    if len(matches) > 1:
        logging.info(
            "Multiple keyboard backlights found (%d total). Using the first one. "
            "Set 'device' in [backlight] config to override.",
            len(matches),
        )
    return device


def get_backlight(device):
    try:
        return int(Path(f"/sys/class/leds/{device}/brightness").read_text().strip())
    except (OSError, ValueError):
        return None


def set_backlight(device, value):
    try:
        subprocess.run(
            [
                "busctl", "call",
                "org.freedesktop.login1",
                "/org/freedesktop/login1/session/auto",
                "org.freedesktop.login1.Session",
                "SetBrightness", "ssu",
                "leds", device, str(value),
            ],
            check=True, capture_output=True, timeout=5,
        )
    except subprocess.CalledProcessError as e:
        logging.error("Failed to set backlight: %s", e.stderr.decode().strip())
    except subprocess.TimeoutExpired:
        logging.error("Failed to set backlight: timed out")


def acquire_lock():
    """Refuse to run a second copy. Two instances (say the service plus one
    started by hand with a different config) each keep "restoring" their own
    brightness, so the backlight flips between the two values forever."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    lock_path = os.path.join(runtime_dir, "kb-autolight.lock")
    lock = open(lock_path, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.seek(0)
        pid = lock.read().strip()
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
        except OSError:
            cmd = "unknown command"
        logging.error(
            "Another copy is already running: pid %s (%s). Stop it first, "
            "e.g. with: systemctl --user stop kb-autolight", pid or "?", cmd,
        )
        sys.exit(1)
    lock.truncate(0)
    lock.write(str(os.getpid()))
    lock.flush()
    return lock


def read_sensor(sensor_path):
    try:
        return int(Path(sensor_path).read_text().strip())
    except (OSError, ValueError) as e:
        logging.warning("Failed to read sensor: %s", e)
        return None


def main():
    global running

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    lock = acquire_lock()  # noqa: F841 (held open for the life of the process)

    dark, light, brightness, interval, debounce, sensor_override, kbd_override = load_config()
    sensor_path = find_sensor(sensor_override)
    kbd_device = find_keyboard(kbd_override)

    logging.info(
        "Starting: dark=%d, light=%d, brightness=%d%%, poll=%ds, debounce=%d, keyboard=%s",
        dark, light, brightness, interval, debounce, kbd_device,
    )

    # Start with backlight off
    state = "bright"
    set_backlight(kbd_device, 0)
    counter = 0
    last_set = 0

    # Sensor reading caused by the backlight's own light. In a dark room the
    # glow from the keys can be enough to cross the light threshold, which
    # would switch the backlight off, go dark, and switch it back on forever.
    # It is learned the first time that happens and added to the threshold.
    glow = 0
    peak = 0
    off_time = None
    off_peak = 0

    restore = True
    restores = []

    while running:
        raw = read_sensor(sensor_path)
        if raw is None:
            time.sleep(interval)
            continue

        now = time.monotonic()

        if state == "bright" and raw <= dark:
            if off_time is not None and now - off_time <= FLAP_POLLS * interval:
                glow = max(glow, off_peak - raw)
                logging.info(
                    "Dark again right after switching off, so the sensor was seeing "
                    "the backlight itself. Now ignoring %d of its reading while on",
                    glow,
                )
            # Turn on immediately — you need to see the keys now
            set_backlight(kbd_device, brightness)
            state = "dark"
            counter = 0
            peak = 0
            off_time = None
            last_set = now
            restore = True
            restores = []
            logging.info("Dark detected (raw=%d <= %d), backlight ON at %d%%", raw, dark, brightness)
        elif state == "dark" and raw > light + glow:
            # Debounce before turning off — avoid flicker
            counter += 1
            peak = max(peak, raw)
            if counter >= debounce:
                set_backlight(kbd_device, 0)
                state = "bright"
                counter = 0
                off_time = now
                off_peak = peak
                last_set = now
                logging.info("Light detected (raw=%d > %d), backlight OFF", raw, light + glow)
        else:
            counter = 0
            peak = 0
            # Recover from suspend/resume — the EC can silently zero the
            # backlight. Check the actual value and only write if wrong.
            if state == "dark" and restore and now - last_set >= 5:
                actual = get_backlight(kbd_device)
                if actual is not None and actual != brightness:
                    restores = [t for t in restores if now - t < RESTORE_WINDOW]
                    restores.append(now)
                    if len(restores) >= RESTORE_LIMIT:
                        restore = False
                        logging.warning(
                            "Backlight was changed %d times in %ds by something else "
                            "(brightness key, desktop power settings or firmware). "
                            "Leaving it alone until the next time it gets dark",
                            RESTORE_LIMIT, RESTORE_WINDOW,
                        )
                    else:
                        set_backlight(kbd_device, brightness)
                        logging.info("Backlight was reset (was %d), restoring to %d%%", actual, brightness)
                last_set = now

        time.sleep(interval)

    # Clean shutdown
    set_backlight(kbd_device, 0)
    logging.info("Shutting down, backlight off")


if __name__ == "__main__":
    main()
