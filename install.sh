#!/usr/bin/env bash
set -euo pipefail

APP_TITLE="OLED Control Center"
APP_ID="oled-control-center"
ARCH="$(uname -m)"

fail() {
    printf '\nFEHLER: %s\n' "$1" >&2
    exit 1
}

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    fail "Bitte als normaler Benutzer starten, nicht mit sudo. Das Skript fragt sudo bei Bedarf selbst ab."
fi

case "$ARCH" in
    aarch64|armv7l)
        ;;
    *)
        fail "Dieses Installationspaket ist für Raspberry Pi 4/5 (ARM32/ARM64) gedacht. Erkannte Architektur: $ARCH. x86 wird absichtlich nicht unterstützt."
        ;;
esac

MODEL=""
if [[ -r /proc/device-tree/model ]]; then
    MODEL="$(tr -d '\000' </proc/device-tree/model 2>/dev/null || true)"
fi
if [[ -n "$MODEL" ]] && ! grep -Eq 'Raspberry Pi (4|5)' <<<"$MODEL"; then
    fail "Erkanntes Gerät: $MODEL. Unterstützt werden Raspberry Pi 4 und Raspberry Pi 5."
fi

if ! command -v apt-get >/dev/null 2>&1; then
    fail "apt-get wurde nicht gefunden. Bitte Raspberry Pi OS verwenden."
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
for required in oled_gui.py launch.sh oled-control-center.png; do
    [[ -f "$SCRIPT_DIR/$required" ]] || fail "Datei fehlt im Installationspaket: $required"
done

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_HOME/$APP_ID"
MENU_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
VENV="$APP_DIR/venv"

printf 'OLED Control Center für %s installieren ...\n' "${MODEL:-Raspberry Pi 4/5}"
printf 'Zielordner: %s\n\n' "$APP_DIR"

SUDO=()
if [[ "$(id -u)" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || fail "sudo wurde nicht gefunden."
    SUDO=(sudo)
fi

printf '[1/5] Raspberry-Pi-Systempakete installieren ...\n'
"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y python3-venv python3-tk python3-pil i2c-tools

printf '\n[2/5] Programmdateien einrichten ...\n'
mkdir -p "$APP_DIR" "$MENU_DIR"
install -m 644 "$SCRIPT_DIR/oled_gui.py" "$APP_DIR/oled_gui.py"
install -m 755 "$SCRIPT_DIR/launch.sh" "$APP_DIR/launch.sh"
install -m 644 "$SCRIPT_DIR/oled-control-center.png" "$APP_DIR/oled-control-center.png"

printf '\n[3/5] ARM-kompatible Python-Umgebung einrichten ...\n'
# System-Pillow und Tkinter werden aus den Raspberry-Pi-OS-Paketen verwendet.
# luma.oled und psutil werden isoliert in dieser App-Umgebung installiert.
if [[ -d "$VENV" ]]; then
    rm -rf "$VENV"
fi
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check luma.oled psutil
"$VENV/bin/python" - <<'PY'
import tkinter
from PIL import Image, ImageTk
from luma.oled.device import ssd1306
import psutil
print("Python-Abhängigkeiten: OK")
PY

printf '\n[4/5] Eintrag im Anwendungsmenü erstellen ...\n'
python3 - "$APP_DIR" "$MENU_DIR/$APP_ID.desktop" <<'PY'
from pathlib import Path
import sys

app_dir = Path(sys.argv[1])
entry = Path(sys.argv[2])
launcher = app_dir / "launch.sh"
icon = app_dir / "oled-control-center.png"

def quote_exec(value: str) -> str:
    # Freedesktop-Exec-Argumente mit Leerzeichen korrekt quoten.
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$') + '"'

content = "\n".join([
    "[Desktop Entry]",
    "Version=1.0",
    "Type=Application",
    "Name=OLED Control Center",
    "Name[de]=OLED Control Center",
    "Comment=SSD1306 OLED am Raspberry Pi steuern",
    "Comment[de]=SSD1306-OLED am Raspberry Pi steuern",
    f"Exec={quote_exec(str(launcher))}",
    f"Path={app_dir}",
    f"Icon={icon}",
    "Terminal=false",
    "Categories=Utility;System;",
    "Keywords=OLED;SSD1306;I2C;Raspberry Pi;",
    "StartupNotify=true",
    "",
])
entry.parent.mkdir(parents=True, exist_ok=True)
entry.write_text(content, encoding="utf-8")
entry.chmod(0o755)
PY

printf '\n[5/5] Desktop-Symbol anlegen ...\n'
DESKTOP_DIR=""
if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
fi
if [[ -z "$DESKTOP_DIR" || "$DESKTOP_DIR" == "$HOME" ]]; then
    if [[ -d "$HOME/Schreibtisch" ]]; then
        DESKTOP_DIR="$HOME/Schreibtisch"
    elif [[ -d "$HOME/Desktop" ]]; then
        DESKTOP_DIR="$HOME/Desktop"
    else
        DESKTOP_DIR="$HOME/Desktop"
        mkdir -p "$DESKTOP_DIR"
    fi
fi
mkdir -p "$DESKTOP_DIR"

DESKTOP_LINK="$DESKTOP_DIR/OLED Control Center.desktop"
install -m 755 "$MENU_DIR/$APP_ID.desktop" "$DESKTOP_LINK"
if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_LINK" metadata::trusted true 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$MENU_DIR" >/dev/null 2>&1 || true
fi

printf '\nInstallation abgeschlossen!\n'
printf 'Anwendungsmenü: OLED Control Center\n'
printf 'Desktop-Symbol: %s\n' "$DESKTOP_LINK"
printf 'Programmordner: %s\n' "$APP_DIR"
printf '\nDu kannst OLED Control Center jetzt über das Desktop-Symbol oder das Anwendungsmenü starten.\n'
