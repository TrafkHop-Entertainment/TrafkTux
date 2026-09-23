#!/bin/bash
#
# trafktux-grub-theme-sync
#
# Erkennt die native Aufloesung/Aspect-Ratio des aktuell angeschlossenen
# Displays (ueber sysfs, funktioniert ohne X/Wayland) und waehlt das
# dazu passende TrafkTux-GRUB-Theme-Bucket (43 / 32 / 1610 / 169 / 219 / 329).
#
# WICHTIG: Das Ergebnis gilt fuer den NAECHSTEN Boot. GRUB kann waehrend
# des eigenen Bootvorgangs nicht selbst erkennen/nachladen - das ist eine
# harte Grenze des Formats, kein Bug in diesem Skript. Deswegen laeuft
# das hier bei JEDEM Systemstart (per systemd, nicht nur bei der
# Installation), damit ein Monitorwechsel spaetestens einen Neustart
# spaeter korrekt ankommt.
#
# Aufruf: root (braucht Schreibzugriff auf /boot und /etc/default/grub)

set -euo pipefail

THEME_DIR="/boot/grub/themes/trafktux"
DEFAULT_GRUB="/etc/default/grub"

log() { echo "[trafktux-grub-theme-sync] $*" >&2; }

# Sucht unter /sys/class/drm den verbundenen Ausgang mit der groessten
# Flaeche (Heuristik fuer "das ist der Hauptmonitor") und gibt dessen
# native/bevorzugte Aufloesung als "WxH" zurueck. Die erste Zeile der
# modes-Datei ist per Konvention der EDID-preferred-Mode.
detect_resolution() {
    local best_area=0 best_res=""
    local status_file
    for status_file in /sys/class/drm/card*-*/status; do
        [ -e "$status_file" ] || continue
        [ "$(cat "$status_file" 2>/dev/null)" = "connected" ] || continue

        local modes_file="${status_file%status}modes"
        [ -r "$modes_file" ] || continue

        local first_mode
        first_mode="$(head -n1 "$modes_file" 2>/dev/null || true)"
        [ -n "$first_mode" ] || continue

        local w="${first_mode%x*}"
        local h="${first_mode#*x}"
        [[ "$w" =~ ^[0-9]+$ && "$h" =~ ^[0-9]+$ ]] || continue

        local area=$((w * h))
        if [ "$area" -gt "$best_area" ]; then
            best_area=$area
            best_res="${w}x${h}"
        fi
    done
    echo "$best_res"
}

# Waehlt den Bucket, dessen Referenz-Seitenverhaeltnis der tatsaechlich
# erkannten Aufloesung am naechsten liegt.
pick_bucket() {
    local width="$1" height="$2"
    awk -v w="$width" -v h="$height" '
        BEGIN {
            ratio = w / h
            n = split("43 32 1610 169 219 329", buckets, " ")
            target["43"]   = 1.3333     # 4:3
            target["32"]   = 1.5        # 3:2
            target["1610"] = 1.6        # 16:10
            target["169"]  = 1.7778     # 16:9
            target["219"]  = 2.3704     # 21:9
            target["329"]  = 3.5556     # 32:9
            best = ""
            bestdiff = 999
            for (i = 1; i <= n; i++) {
                b = buckets[i]
                diff = ratio - target[b]
                if (diff < 0) diff = -diff
                if (diff < bestdiff) { bestdiff = diff; best = b }
            }
            print best
        }
    '
}

main() {
    local res
    res="$(detect_resolution)"
    if [ -z "$res" ]; then
        log "Kein verbundenes Display unter /sys/class/drm gefunden, breche ab (Theme bleibt wie es ist)."
        exit 0
    fi

    local width="${res%x*}"
    local height="${res#*x}"

    local bucket
    bucket="$(pick_bucket "$width" "$height")"
    log "Erkannt: ${width}x${height} -> Bucket $bucket"

    # theme_<bucket>.txt liegt im Theme-Root (neben theme.txt) und referenziert
    # seine Bucket-Assets bereits vollstaendig als "assets/<bucket>/...", die
    # gemeinsamen Layer1/Layer5 als "assets/...". Es muss also nur noch diese
    # eine Datei nach theme.txt kopiert werden - keine PNGs mehr anfassen.
    local bucket_theme="$THEME_DIR/assets/${bucket}/theme_${bucket}.txt"
    if [ ! -f "$bucket_theme" ]; then
        log "FEHLER: $bucket_theme existiert nicht - breche ab, ohne etwas zu veraendern."
        exit 1
    fi

    # Direkt gegen die tatsaechlich aktive theme.txt UND GRUB_GFXMODE
    # vergleichen statt gegen eine separate State-Datei (kann veralten).
    # WICHTIG: beide muessen stimmen - vorher wurde nur theme.txt geprueft,
    # wodurch GRUB_GFXMODE/grub.cfg stumm veraltet blieb, wenn theme.txt aus
    # einem anderen Grund (z.B. manuelles Kopieren) schon richtig war.
    local gfxmode_line="GRUB_GFXMODE=${width}x${height},1920x1080,auto"
    local theme_ok=0 gfxmode_ok=0
    cmp -s "$bucket_theme" "$THEME_DIR/theme.txt" && theme_ok=1
    grep -qF "$gfxmode_line" "$DEFAULT_GRUB" 2>/dev/null && gfxmode_ok=1

    if [ "$theme_ok" = 1 ] && [ "$gfxmode_ok" = 1 ]; then
        log "theme.txt und GRUB_GFXMODE entsprechen bereits Bucket $bucket (${res}) - nichts zu tun."
        exit 0
    fi

    cp -f "$bucket_theme" "$THEME_DIR/theme.txt"

    if grep -q '^GRUB_GFXMODE=' "$DEFAULT_GRUB"; then
        sed -i "s/^GRUB_GFXMODE=.*/${gfxmode_line}/" "$DEFAULT_GRUB"
    else
        echo "$gfxmode_line" >> "$DEFAULT_GRUB"
    fi

    grub-mkconfig -o /boot/grub/grub.cfg

    log "Fertig: Bucket $bucket, ${res} ist ab dem naechsten Boot aktiv."
}

main "$@"
