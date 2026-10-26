#!/usr/bin/env bash
# WallpaperHotplug.sh
# Lauscht auf Hyprlands Event-Socket und füllt Wallpaper für Monitore,
# die erst nach dem Boot auftauchen (zweiter Monitor, Live-ISO, Hotplug).
# Nutzt --fill-missing, damit bereits versorgte Monitore NICHT neu
# gewürfelt werden (kein Flackern).

SOCKET="${XDG_RUNTIME_DIR}/hypr/${HYPRLAND_INSTANCE_SIGNATURE}/.socket2.sock"
WALLPAPER_SCRIPT="$HOME/.config/hypr/Wallpapers.sh"

# ─────────────────────────────────────────────────────────────────
# DEBUG-LOGGING (temporär, gleiche Logdatei wie Wallpapers.sh, damit
# beide Skripte im selben Zeitstrahl auftauchen).
# ─────────────────────────────────────────────────────────────────
WB_LOG="$HOME/.cache/wallpapers-debug.log"
hp_log() {
    printf '%s PID=%s [HOTPLUG] %s\n' "$(date +%T.%N)" "$$" "$1" >> "$WB_LOG"
}

hp_log "START, warte auf Socket $SOCKET"

# Warten, bis der Socket existiert (falls der Watcher sehr früh startet)
while [ ! -S "$SOCKET" ]; do
    sleep 0.2
done
hp_log "Socket da"

# Sicherheitsnetz: falls ein Monitor zwischen dem ersten Wallpapers.sh-
# Lauf und unserem Verbindungsaufbau dazukam, jetzt einmal nachfüllen.
hp_log "Sicherheitsnetz --fill-missing: Aufruf"
"$WALLPAPER_SCRIPT" --fill-missing >/dev/null 2>&1
hp_log "Sicherheitsnetz --fill-missing: fertig, rc=$?"

# Auf Events lauschen
hp_log "starte socat-Listener"
socat -u UNIX-CONNECT:"$SOCKET" - | while IFS= read -r line; do
    case "$line" in
        "monitoradded>>"*|"monitoraddedv2>>"*)
            hp_log "Event: $line"
            # Kurz warten, damit der Monitor vollständig initialisiert ist
            sleep 1
            hp_log "fill-missing nach Event: Aufruf"
            "$WALLPAPER_SCRIPT" --fill-missing >/dev/null 2>&1
            hp_log "fill-missing nach Event: fertig, rc=$?"
            ;;
    esac
done
hp_log "LISTENER-SCHLEIFE BEENDET (sollte nie passieren - socat/Pipe gestorben)"
