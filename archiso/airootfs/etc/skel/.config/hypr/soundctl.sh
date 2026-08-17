#!/usr/bin/env bash
#
# soundctl.sh — zentraler Dispatcher für alle Systemsounds.
#
# Aufruf:
#   soundctl.sh <event>                  spielt <event> ab (wenn Master UND
#                                         das Event selbst aktiviert sind)
#   soundctl.sh --enable  [event]        Master EIN, oder nur <event> EIN
#   soundctl.sh --disable [event]        Master AUS, oder nur <event> AUS
#   soundctl.sh --toggle  [event]        Master umschalten, oder nur <event>
#                                         umschalten; gibt "on"/"off" aus
#   soundctl.sh --status  [event]        Master-Status, oder Status von
#                                         <event>; gibt "on"/"off" aus
#
# Ohne [event]-Argument wirken --enable/--disable/--toggle/--status auf den
# MASTER-Schalter (schneller Gesamt-Mute, z.B. für den Settings-Toggle in
# widgets_daemon.py - unverändert wie bisher). MIT [event]-Argument wirken
# sie nur auf DIESES eine Event, z.B. "soundctl.sh --disable click" schaltet
# nur den Klick-Sound aus, "nav"/"open"/etc. bleiben unberührt. Ein Sound
# spielt nur, wenn BEIDE Schalter (Master UND das jeweilige Event) an sind.
#
# Events (siehe SOUND_DIR unten für die zugehörigen Dateien):
#   click   - Standard-Klick (Buttons, Waybar-Module, Menüpunkte)
#   toggle  - Ein/Aus-Schalter (Dark Mode, WLAN, Bluetooth, ...)
#   open    - Fenster/Bubble/Menü öffnet sich
#   close   - Fenster/Bubble/Menü schließt sich
#   nav     - Bewegen im Menü (Pfeiltasten, Durchblättern, Fokuswechsel)
#   enter   - Auswahl bestätigt (Return/Enter in einem Menü)
#   error   - Aktion fehlgeschlagen / ungültige Eingabe
#   notify  - Benachrichtigung
#
# Architektur (zurückgebaut, KEIN Daemon mehr): der Daemon-Ansatz
# (soundd/clickd) hat sich nicht gelohnt - er hat keine echte
# Geschwindigkeit gebracht (pw-play wurde bei jedem Aufruf sowieso neu
# gespawnt, nur eben über einen zusätzlichen socat/Socket-Hop drumherum -
# das ist tendenziell LANGSAMER, nicht schneller), und brachte neue
# Abhängigkeiten mit (systemd-Units, "input"-Gruppen-Mitgliedschaft für
# jeden User - für eine Distro mit vielen Usern ein echtes
# Rollout-Problem). Zurück zu direktem Spawnen wie am Anfang - aber mit
# dem eigentlich nötigen Fix für das "Player stirbt mit dem
# Elternprozess"-Problem: "setsid" statt nur "&". "&" allein reicht nicht
# immer - wenn soundctl.sh selbst aus einem schon kurzlebigen Prozess
# heraus aufgerufen wird (pip.sh via exec_cmd, bubble-menu.py als
# Rofi-Subprozess), kann der spawnte Player getötet werden, sobald die
# Prozessgruppe des Aufrufers aufräumt. "setsid <player>" hebt den Player
# in eine komplett NEUE, unabhängige Session - er hängt danach an gar
# nichts mehr, das mit dem Aufrufer zusammenhängt.

set -uo pipefail

STATE_DIR="$HOME/.cache/hypr"
MASTER_FILE="$STATE_DIR/sounds_enabled"
EVENT_STATE_DIR="$STATE_DIR/sound_events"
SOUND_DIR="$HOME/.config/hypr/sounds"

mkdir -p "$EVENT_STATE_DIR"

# Master-Schalter: Default an, falls noch nie umgeschaltet.
master_enabled() {
    [ ! -f "$MASTER_FILE" ] || [ "$(cat "$MASTER_FILE" 2>/dev/null)" = "1" ]
}
set_master() {
    echo "$1" > "$MASTER_FILE"
}

# Pro-Event-Schalter: eine Datei pro Event, Default ebenfalls an (fehlt die
# Datei -> Event ist aktiv). So muss man beim Hinzufügen eines neuen Events
# nirgends eine Liste pflegen - fehlt einfach die Datei, ist es an.
event_enabled() {
    local f="$EVENT_STATE_DIR/$1"
    [ ! -f "$f" ] || [ "$(cat "$f" 2>/dev/null)" = "1" ]
}
set_event() {
    echo "$2" > "$EVENT_STATE_DIR/$1"
}

# Event -> Dateiname. Ein einziger Ort, an dem sich das Sound-Set austauschen lässt.
sound_file_for() {
    case "$1" in
        click)  echo "$SOUND_DIR/click.ogg" ;;
        toggle) echo "$SOUND_DIR/toggle.ogg" ;;
        open)   echo "$SOUND_DIR/open.ogg" ;;
        close)  echo "$SOUND_DIR/close.ogg" ;;
        nav)    echo "$SOUND_DIR/nav.ogg" ;;
        enter)  echo "$SOUND_DIR/enter.ogg" ;;
        error)  echo "$SOUND_DIR/error.ogg" ;;
        notify) echo "$SOUND_DIR/notify.ogg" ;;
        *)      echo "" ;;
    esac
}

# setsid: siehe Architektur-Kommentar oben - das ist der eigentliche Fix,
# nicht der (verworfene) Daemon. "< /dev/null" zusätzlich, damit der
# losgelöste Prozess nicht an stdin des Aufrufers hängen bleibt.
play_file() {
    local f="$1"
    [ -f "$f" ] || return 0
    if command -v pw-play >/dev/null 2>&1; then
        setsid pw-play "$f" >/dev/null 2>&1 </dev/null &
    elif command -v paplay >/dev/null 2>&1; then
        setsid paplay "$f" >/dev/null 2>&1 </dev/null &
    elif command -v canberra-gtk-play >/dev/null 2>&1; then
        setsid canberra-gtk-play -f "$f" >/dev/null 2>&1 </dev/null &
    fi
    disown 2>/dev/null || true
}

case "${1:-}" in
    --enable)
        if [ -n "${2:-}" ]; then set_event "$2" 1; else set_master 1; fi
        echo "on"
        ;;
    --disable)
        if [ -n "${2:-}" ]; then set_event "$2" 0; else set_master 0; fi
        echo "off"
        ;;
    --toggle)
        if [ -n "${2:-}" ]; then
            if event_enabled "$2"; then set_event "$2" 0; echo "off"; else set_event "$2" 1; echo "on"; fi
        else
            if master_enabled; then set_master 0; echo "off"; else set_master 1; echo "on"; fi
        fi
        ;;
    --status)
        if [ -n "${2:-}" ]; then
            if event_enabled "$2"; then echo "on"; else echo "off"; fi
        else
            if master_enabled; then echo "on"; else echo "off"; fi
        fi
        ;;
    "" )
        # kein Argument -> nichts tun, kein Fehler (macht Aufrufe robuster)
        exit 0
        ;;
    *)
        master_enabled || exit 0
        event_enabled "$1" || exit 0
        f=$(sound_file_for "$1")
        [ -n "$f" ] && play_file "$f"
        ;;
esac
