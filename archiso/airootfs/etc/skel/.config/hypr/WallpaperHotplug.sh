#!/usr/bin/env bash
# WallpaperHotplug.sh
# Lauscht auf Hyprlands Event-Socket und füllt Wallpaper für Monitore,
# die erst nach dem Boot auftauchen (zweiter Monitor, Live-ISO, Hotplug).
# Nutzt --fill-missing, damit bereits versorgte Monitore NICHT neu
# gewürfelt werden (kein Flackern).

SOCKET="${XDG_RUNTIME_DIR}/hypr/${HYPRLAND_INSTANCE_SIGNATURE}/.socket2.sock"
WALLPAPER_SCRIPT="$HOME/.config/hypr/Wallpapers.sh"

# Warten, bis der Socket existiert (falls der Watcher sehr früh startet)
while [ ! -S "$SOCKET" ]; do
    sleep 0.2
done

# Sicherheitsnetz: falls ein Monitor zwischen dem ersten Wallpapers.sh-
# Lauf und unserem Verbindungsaufbau dazukam, jetzt einmal nachfüllen.
"$WALLPAPER_SCRIPT" --fill-missing >/dev/null 2>&1

# Auf Events lauschen
socat -u UNIX-CONNECT:"$SOCKET" - | while IFS= read -r line; do
    case "$line" in
        monitoradded>>*|monitoraddedv2>>*)
            # Kurz warten, damit der Monitor vollständig initialisiert ist
            sleep 1
            "$WALLPAPER_SCRIPT" --fill-missing >/dev/null 2>&1
            ;;
    esac
done