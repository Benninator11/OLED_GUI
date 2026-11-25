#!/usr/bin/env bash
set -u

APP_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON="$APP_DIR/venv/bin/python"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/oled-control-center"
LOG_FILE="$LOG_DIR/app.log"
mkdir -p "$LOG_DIR"

show_error() {
    local message="$1"
    if command -v zenity >/dev/null 2>&1; then
        zenity --error --title="OLED Control Center" --text="$message" 2>/dev/null || true
    elif command -v xmessage >/dev/null 2>&1; then
        xmessage -center "$message" 2>/dev/null || true
    fi
}

if [[ ! -x "$PYTHON" ]]; then
    show_error "Die Programmumgebung wurde nicht gefunden. Bitte installiere OLED Control Center erneut mit install.sh."
    exit 1
fi

cd "$APP_DIR"
"$PYTHON" "$APP_DIR/oled_gui.py" >>"$LOG_FILE" 2>&1
STATUS=$?
if [[ $STATUS -ne 0 ]]; then
    DETAILS="$(tail -n 25 "$LOG_FILE" 2>/dev/null || true)"
    show_error "OLED Control Center konnte nicht gestartet werden.\n\nLetzte Fehlermeldungen:\n$DETAILS\n\nProtokoll: $LOG_FILE"
fi
exit "$STATUS"
