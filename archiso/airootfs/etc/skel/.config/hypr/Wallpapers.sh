#!/usr/bin/env bash
#
# Wallpapers.sh
# Setzt beim Start ein zufälliges Wallpaper pro Hyprland-Monitor.
#
# ─────────────────────────────────────────────────────────────────
# UMBAU (siehe Chat): xfdesktop kann auf diesem System aus bisher
# ungeklärten Gründen auf externen Monitoren unter Hyprland/Wayland
# KEIN Hintergrundbild mehr zeichnen - und zwar nicht nur über dieses
# Skript, sondern nachweislich auch über die offizielle
# xfce4-desktop-Settings-GUI selbst (dort geht's inzwischen auf GAR
# keinem Monitor mehr, nicht mal intern). Property-Zuordnung
# (xfconf-Keys pro Monitor) war die ganze Zeit korrekt - das Problem
# sitzt tiefer in xfdesktop selbst (passt zur Warnung
# "Window<->Workspace association is not available on your
# compositor" - xfdesktop läuft unter Hyprland in einem
# Kompatibilitäts-/Degraded-Modus).
#
# Daher: das eigentliche Hintergrundbild kommt jetzt von hyprpaper
# (Hyprlands eigener, nativer Wallpaper-Daemon - gebaut genau für
# Multi-Monitor-Wayland, kein X11-Kompatibilitätsgedöns). xfdesktop
# bleibt parallel aktiv, aber NUR noch für die Desktop-Icons - sein
# eigener Hintergrund wird auf "kein Bild" + "durchsichtig" gesetzt
# (ensure_xfdesktop_transparent()), damit hyprpapers Layer darunter
# sichtbar durchscheint. Netter Nebeneffekt: kein `killall xfdesktop`
# mehr nötig -> kein Schwarz-Flackern mehr beim Rerollen.
#
# Voraussetzung: hyprpaper ist installiert und läuft (per systemd-User-
# Service oder exec-once in hyprland.lua) - dieses Skript versucht es
# notfalls selbst zu starten, falls es (noch) nicht läuft.
# ─────────────────────────────────────────────────────────────────
#
# Neue Ordnerstruktur:
#   ~/.config/hypr/Wallpapers/<ratio>/
#   Ratio-Keys: 11, 1610, 169, 219, 329, 43
#   Default/Fallback: 169
#
# Verifikation ohne Anwenden:
#   DRY_RUN=1 ~/.config/hypr/Wallpapers.sh
#
# Explizite Auswahl statt Zufall (siehe apply_image_to_monitor() unten):
#   ~/.config/hypr/Wallpapers.sh --set /pfad/zum/bild.jpg [MONITOR]
#
# Diagnose der Monitor->xfconf-Zuordnung (nur noch relevant fürs
# Icon-Layer/die Transparenz, nicht mehr fürs Bild selbst):
#   ~/.config/hypr/Wallpapers.sh --debug-monitors

WALLPAPER_DIR="$HOME/.config/hypr/Wallpapers"
CHANNEL="xfce4-desktop"
DEFAULT_RATIO="169"
DRY_RUN="${DRY_RUN:-0}"

# ─────────────────────────────────────────────────────────────────
# DEBUG-LOGGING (temporär, zur Diagnose des Hotplug/Lock-Problems).
# Schreibt nach ~/.cache/wallpapers-debug.log, jede Zeile mit Zeit,
# PID und Laufzeit seit Skriptstart (SECONDS), damit man im Log sieht,
# WELCHER Lauf WIE LANGE wo hängt.
# ─────────────────────────────────────────────────────────────────
WB_LOG="$HOME/.cache/wallpapers-debug.log"
wb_log() {
    printf '%s PID=%s SECONDS=%s %s\n' "$(date +%T.%N)" "$$" "$SECONDS" "$1" >> "$WB_LOG"
}
wb_log "START args=[$*]"

random_index() {
    local n="$1"
    local r
    r=$(od -An -N2 -tu2 < /dev/urandom | tr -d ' ')
    echo $(( r % n ))
}

pick_image() {
    local dir="$1"
    local -a imgs

    mapfile -t imgs < <(find "$dir" -maxdepth 1 -type f \( \
        -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.webp" \
    \) 2>/dev/null)

    [ "${#imgs[@]}" -eq 0 ] && return 1

    local idx
    idx=$(random_index "${#imgs[@]}")
    printf '%s\n' "${imgs[$idx]}"
}

ratio_key() {
    local w="$1" h="$2"

    awk -v w="$w" -v h="$h" '
    BEGIN {
        r = w / h

        # Key:Ratio
        n = split("11:1 1610:1.6 169:1.7777777778 219:2.3333333333 329:3.5555555556 43:1.3333333333", a, " ")

        best = "169"
        bestdiff = 999

        for (i = 1; i <= n; i++) {
            split(a[i], kv, ":")
            d = r - kv[2]
            if (d < 0) d = -d

            if (d < bestdiff) {
                bestdiff = d
                best = kv[1]
            }
        }

        # Wenn keine Ratio gut genug passt, Default verwenden
        if (bestdiff > 0.08) best = "169"

        print best
    }'
}

set_prop() {
    local path="$1" type="$2" value="$3"

    if xfconf-query -c "$CHANNEL" -p "$path" >/dev/null 2>&1; then
        xfconf-query -c "$CHANNEL" -p "$path" -s "$value"
    else
        xfconf-query -c "$CHANNEL" -p "$path" -n -t "$type" -s "$value"
    fi
}

# ─────────────────────────────────────────────────────────────────
# Nur noch fürs Icon-Layer relevant: xfdesktop soll pro Monitor KEIN
# eigenes Bild mehr zeichnen und durchsichtig bleiben, damit hyprpaper
# darunter sichtbar ist. Schreibt defensiv auf BEIDE denkbaren
# xfconf-Pfad-Varianten (Connector-Name UND GDK-Modellname, siehe
# discover_xfconf_monitor_map/resolve_xfkeys) - welche davon diese
# xfdesktop-Version tatsächlich für die Icon-Platzierung nutzt, ist
# unklar, schadet aber nicht, beide zu pflegen.
# ─────────────────────────────────────────────────────────────────
declare -gA XFKEY_FOR_MON=()

discover_xfconf_monitor_map() {
    wb_log "discover_xfconf_monitor_map: start"
    local -a hypr_lines gdk_lines
    mapfile -t hypr_lines < <(
        hyprctl monitors -j 2>/dev/null \
            | jq -r '.[] | [.name, (.x|tostring), (.y|tostring), (.width|tostring), (.height|tostring)] | @tsv'
    )
    if [ "${#hypr_lines[@]}" -eq 0 ]; then
        wb_log "discover_xfconf_monitor_map: keine hyprctl-Monitore, abbruch"
        return 1
    fi

    wb_log "discover_xfconf_monitor_map: starte python3/GDK-Abfrage"
    mapfile -t gdk_lines < <(python3 - <<'PYEOF' 2>/dev/null
import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
d = Gdk.Display.get_default()
if d is None:
    raise SystemExit(1)
for i in range(d.get_n_monitors()):
    m = d.get_monitor(i)
    g = m.get_geometry()
    model = (m.get_model() or "").strip()
    print(f"{g.x}\t{g.y}\t{g.width}\t{g.height}\t{model}")
PYEOF
    )
    wb_log "discover_xfconf_monitor_map: python3/GDK-Abfrage fertig, ${#gdk_lines[@]} Zeilen"
    if [ "${#gdk_lines[@]}" -eq 0 ]; then
        wb_log "discover_xfconf_monitor_map: keine GDK-Monitore, abbruch"
        return 1
    fi

    local hline
    for hline in "${hypr_lines[@]}"; do
        IFS=$'\t' read -r hname hx hy hw hh <<< "$hline"
        local matched=""
        local gline
        for gline in "${gdk_lines[@]}"; do
            IFS=$'\t' read -r gx gy gw gh gmodel <<< "$gline"
            if [ "$gx" = "$hx" ] && [ "$gy" = "$hy" ]; then
                matched="$gmodel"; break
            fi
        done
        if [ -z "$matched" ]; then
            for gline in "${gdk_lines[@]}"; do
                IFS=$'\t' read -r gx gy gw gh gmodel <<< "$gline"
                if [ "$gw" = "$hw" ] && [ "$gh" = "$hh" ]; then
                    matched="$gmodel"; break
                fi
            done
        fi
        if [ -n "$matched" ]; then
            local sanitized
            sanitized=$(printf '%s' "$matched" | tr -cd 'A-Za-z0-9')
            [ -n "$sanitized" ] && XFKEY_FOR_MON["$hname"]="monitor${sanitized}"
        fi
    done
    wb_log "discover_xfconf_monitor_map: fertig, ${#XFKEY_FOR_MON[@]} Einträge in XFKEY_FOR_MON"
    [ "${#XFKEY_FOR_MON[@]}" -gt 0 ]
}

resolve_xfkeys() {
    local mon="$1"
    local -a keys=("monitor${mon}")
    if [ -n "${XFKEY_FOR_MON[$mon]:-}" ] && [ "${XFKEY_FOR_MON[$mon]}" != "monitor${mon}" ]; then
        keys+=("${XFKEY_FOR_MON[$mon]}")
    fi
    printf '%s\n' "${keys[@]}"
}

ensure_xfdesktop_transparent() {
    wb_log "ensure_xfdesktop_transparent: start"
    local mon xfkey
    local -a mons
    mapfile -t mons < <(hyprctl monitors -j 2>/dev/null | jq -r '.[].name')
    for mon in "${mons[@]}"; do
        while IFS= read -r xfkey; do
            local base="/backdrop/screen0/${xfkey}/workspace0"
            set_prop "$base/image-style" int 0   # 0 = Kein Bild (hyprpaper übernimmt)
            set_prop "$base/color-style" int 0   # 0 = Durchsichtig
            wb_log "ensure_xfdesktop_transparent: $mon -> $base"
        done < <(resolve_xfkeys "$mon")
    done
    wb_log "ensure_xfdesktop_transparent: fertig"
}

# ─────────────────────────────────────────────────────────────────
# LOCK: verhindert, dass zwei Instanzen dieses Skripts gleichzeitig
# in den hyprpaper-berührenden Teil laufen (normaler Autostart-Lauf
# UND der "Sicherheitsnetz"-Aufruf von WallpaperHotplug.sh direkt
# beim Boot, oder zwei schnell aufeinanderfolgende Hotplug-Events).
#
# Das war die Ursache fürs "Upgrade kaputt"-Problem:
#   - Autostart.lua feuert "Wallpapers.sh" UND "WallpaperHotplug.sh &"
#     praktisch gleichzeitig. WallpaperHotplug.sh ruft sein
#     Sicherheitsnetz (--fill-missing) sofort auf, ohne auf den
#     ersten Lauf zu warten.
#   - Beide Instanzen prüfen in ensure_hyprpaper_running() parallel
#     "läuft hyprpaper schon?" (beide sehen: nein) und starten JEDE
#     ihre eigene hyprpaper-Instanz. Zwei hyprpaper-Prozesse rendern
#     dann kurzzeitig parallel auf denselben Outputs - die zweite,
#     noch leere Instanz ersetzt die erste mit einem nackten/weißen
#     Layer. Genau das beobachtete Verhalten: ein Wallpaper wird
#     gesetzt und nach ein paar ms durch Weiß ersetzt.
#   - Zusätzlich gab es eine Read-Modify-Write-Race auf der
#     KEEP_IMAGES-Statedatei in hyprpaper_unload_unused(): Lauf B
#     entlädt ein Bild wieder, das Lauf A gerade erst gesetzt hat,
#     weil B es beim Lesen von "listactive" noch nicht als aktiv sah.
#     Dadurch bekamen weitere Monitore gar kein Bild mehr.
#
# Fix: ein flock-basierter Mutex um den gesamten restlichen Teil des
# Skripts (außer --debug-monitors, das rein lesend ist). Alle
# Instanzen (normaler Lauf, --fill-missing, --set) warten jetzt
# höchstens 15s aufeinander statt sich gegenseitig zu überschreiben.
# Dadurch läuft z.B. der Sicherheitsnetz-Aufruf von
# WallpaperHotplug.sh einfach direkt NACH dem ersten Lauf (statt
# gleichzeitig) und findet alle Monitore schon versorgt vor - genau
# das gewünschte Verhalten, kein Flackern.
# ─────────────────────────────────────────────────────────────────
if [ "${1:-}" != "--debug-monitors" ]; then
    LOCKFILE="${XDG_RUNTIME_DIR:-/tmp}/wb-wallpapers.lock"
    wb_log "LOCKFILE=$LOCKFILE - warte auf Lock (max 15s)"
    exec 9>"$LOCKFILE"
    if ! flock -w 15 9; then
        # ─────────────────────────────────────────────────────────
        # FIX (Lock-Hänger nach Skript-Update): Falls der Halter ein
        # hyprpaper ist, der noch von der alten, fehlerhaften Version
        # stammt (fd 9 geerbt → hält den Lock bis zum Reboot), killen
        # wir ihn und versuchen den Lock nochmal. Das macht das Skript
        # selbstheilend, ohne dass der User rebooten muss.
        # ─────────────────────────────────────────────────────────
        LOCK_HOLDERS=$(fuser "$LOCKFILE" 2>/dev/null | tr -s ' ' ' ' | sed 's/^ //;s/ $//')
        wb_log "LOCK TIMEOUT nach 15s - Halter-PIDs: ${LOCK_HOLDERS:-unbekannt (fuser fehlt?)}"

        HP_PID=$(pgrep -x hyprpaper 2>/dev/null | head -n1)
        if [ -n "$HP_PID" ] && [ -n "$LOCK_HOLDERS" ] \
           && printf ' %s ' "$LOCK_HOLDERS" | grep -q " $HP_PID "; then
            wb_log "hyprpaper (PID $HP_PID) hält den Lock (alter fd-9-Bug) - kille & retry"
            pkill -9 -x hyprpaper 2>/dev/null
            sleep 0.5
            if ! flock -w 10 9; then
                wb_log "Lock auch nach hyprpaper-Kill nicht bekommen - exit 1"
                notify-send "Wallpaper" "Konnte Wallpaper-Lock nicht bekommen (hängt eine andere Instanz fest?) - abgebrochen." 2>/dev/null
                exit 1
            fi
            wb_log "Lock nach hyprpaper-Kill bekommen"
        else
            wb_log "Lock-Halter ist nicht hyprpaper - exit 1 (manueller Eingriff nötig)"
            notify-send "Wallpaper" "Konnte Wallpaper-Lock nicht bekommen (hängt eine andere Instanz fest?) - abgebrochen." 2>/dev/null
            exit 1
        fi
    fi
    wb_log "Lock bekommen"
fi

if [ "${1:-}" = "--debug-monitors" ]; then
    echo "hyprctl monitors:"
    hyprctl monitors -j | jq -r '.[] | "  \(.name)  pos=\(.x),\(.y)  size=\(.width)x\(.height)"'
    echo
    discover_xfconf_monitor_map || true
    echo "Icon-Layer xfconf-Zuordnung (NICHT mehr fürs Bild zuständig - nur Transparenz/Icons):"
    for k in "${!XFKEY_FOR_MON[@]}"; do
        echo "  $k  ->  /backdrop/screen0/${XFKEY_FOR_MON[$k]}/workspace0"
    done
    echo
    echo "hyprpaper Status:"
    if pgrep -x hyprpaper >/dev/null 2>&1; then
        echo "  läuft (PID $(pgrep -x hyprpaper | tr '\n' ' '))"
        echo "  aktive Zuordnung:"; hyprctl hyprpaper listactive 2>/dev/null | sed 's/^/    /'
        echo "  vom letzten Lauf dieses Skripts geladen gehaltene Bilder"
        echo "  (listloaded gibt's in deiner hyprpaper-Version nicht mehr,"
        echo "  siehe hyprpaper_unload_unused()):"
        if [ -f "$HOME/.cache/wb-wallpapers-hyprpaper-loaded" ]; then
            sed 's/^/    /' "$HOME/.cache/wb-wallpapers-hyprpaper-loaded"
        else
            echo "    (noch kein echter Lauf mit diesem Skript - Datei fehlt noch)"
        fi
    else
        echo "  LÄUFT NICHT"
    fi
    exit 0
fi

# ─────────────────────────────────────────────────────────────────
# hyprpaper-Anbindung - das eigentliche Hintergrundbild läuft jetzt
# komplett hierüber, nicht mehr über xfconf.
# ─────────────────────────────────────────────────────────────────
ensure_hyprpaper_running() {
    wb_log "ensure_hyprpaper_running: start"
    # FIX ("Konnte Wallpaper-Lock nicht bekommen"): pgrep -x prüft nur,
    # ob der PROZESS existiert - nicht, ob er noch auf seinem IPC-Socket
    # ANTWORTET. Ein hängender/abgestürzter-aber-noch-im-Prozessbaum
    # steckender hyprpaper besteht diesen Check weiterhin, obwohl JEDER
    # nachfolgende `hyprctl hyprpaper ...`-Aufruf dann für immer
    # blockiert - und damit auch den flock-Mutex weiter unten für immer
    # hält. Genau DAS war der Grund für "hängt eine andere Instanz
    # fest?": die "andere Instanz" wartet selbst nur auf eine tote
    # hyprpaper-Antwort. Deshalb jetzt ein echter Health-Check (kurzer
    # Timeout) statt nur "läuft der Prozess".
    if pgrep -x hyprpaper >/dev/null 2>&1; then
        # FIX (2 Bugs in der vorigen Fassung dieses Health-Checks):
        #  1) "timeout 3 ..." ohne -k ist KEIN hartes Limit - schickt nur
        #     SIGTERM nach 3s und wartet danach weiter, falls der Prozess
        #     das ignoriert/nicht sofort verarbeitet (genau der Hänger-Fall,
        #     den der Check eigentlich abfangen soll). "-k 3" erzwingt nach
        #     weiteren 3s ein hartes SIGKILL, falls SIGTERM nicht reicht.
        #  2) 3s sind beim Boot zu knapp: Autostart.lua startet ~15 Dienste
        #     fast gleichzeitig (TrafkTuxBar, Launcher, Daemons, hyprctl
        #     reload fuer Plugins, ...) - unter der Last kann ein KORREKT
        #     laufendes hyprpaper locker mal >3s zum Antworten brauchen.
        #     Mit nur 3s wurde ein gesundes, gerade erst gesetztes
        #     hyprpaper vom naechsten Aufruf (z.B. Hotplug-Sicherheitsnetz)
        #     faelschlich als "haengt" gekillt - das Wallpaper verschwand
        #     dadurch wieder. Jetzt 6s, grosszuegiger fuer Boot-Last.
        if timeout -k 3 6 hyprctl hyprpaper listactive >/dev/null 2>&1; then
            wb_log "ensure_hyprpaper_running: läuft und antwortet (PID $(pgrep -x hyprpaper | tr '\n' ' '))"
            return 0
        fi
        wb_log "ensure_hyprpaper_running: Prozess da, antwortet aber NICHT innerhalb 6s (rc=$?) - töte & starte neu"
        pkill -9 -x hyprpaper 2>/dev/null
        sleep 0.3
    fi

    wb_log "ensure_hyprpaper_running: läuft nicht (oder wurde gerade als hängend beendet), starte selbst"
    # ─────────────────────────────────────────────────────────────
    # FIX (fd-9-Leak, das eigentliche "Upgrade kaputt"-Problem):
    # fd 9 ist der flock-Mutex dieses Skripts. Bash setzt bei
    # `exec 9>...` KEIN FD_CLOEXEC. Ein via `setsid hyprpaper`
    # gestarteter Daemon erbt deshalb fd 9 - und weil flock-Locks an
    # der "open file description" hängen (nicht am Prozess), bleibt
    # der Lock bestehen, SOLANGE hyprpaper lebt. hyprpaper lebt bis
    # zum Reboot. Ergebnis: jeder weitere Wallpapers.sh-Aufruf
    # (Sicherheitsnetz von WallpaperHotplug.sh, Hotplug-Events,
    # manuelle Rerolls) läuft 15s in den Lock-Timeout mit genau der
    # beobachteten Meldung "hängt eine andere Instanz fest?". Deshalb
    # hier explizit `9>&-`, damit der Daemon den fd NICHT erbt.
    # ─────────────────────────────────────────────────────────────
    (setsid hyprpaper </dev/null >/dev/null 2>&1 9>&- &)
    # ─────────────────────────────────────────────────────────────
    # FIX (Boot-Timing, das eigentliche "kein Wallpaper beim Start"-
    # Problem): der alte Code machte nach dem Spawn nur `sleep 0.5`
    # und EINEN Check. Beim Boot (kalter Page-Cache, Live-ISO,
    # Hyprland noch am Hochfahren, parallele Dienste) braucht
    # hyprpaper oft deutlich länger als 0,5s, bis es auf hyprctl
    # antwortet - dann gab ensure_hyprpaper_running() auf, das
    # Skript exitete 1, und es wurde NIE ein Wallpaper gesetzt. Das
    # frisch gestartete hyprpaper lief aber weiter (mit geerbtem
    # fd 9!) und hielt fortan den Lock → genau die Kombination aus
    # "kein Wallpaper" + "andere Instanz hängt" beim Boot. Jetzt
    # Retry-Loop bis ~10s, hyprpaper darf so lange hochkommen.
    # ─────────────────────────────────────────────────────────────
    local _hp_start=$SECONDS
    local _hp_deadline=$((_hp_start + 10))
    while [ "$SECONDS" -lt "$_hp_deadline" ]; do
        if pgrep -x hyprpaper >/dev/null 2>&1 \
           && timeout -k 2 3 hyprctl hyprpaper listactive >/dev/null 2>&1; then
            wb_log "ensure_hyprpaper_running: nach Start oben und antwortet (nach $((SECONDS - _hp_start))s, PID $(pgrep -x hyprpaper | tr '\n' ' '))"
            return 0
        fi
        sleep 0.2
    done
    wb_log "ensure_hyprpaper_running: FEHLGESCHLAGEN, auch nach ~10s Retry nicht erreichbar"
    notify-send "Wallpaper" "hyprpaper läuft nicht/antwortet nicht und konnte nicht automatisch (neu) gestartet werden - bitte manuell prüfen (hyprpaper installiert? in hyprland.lua/systemd per exec-once eingebunden?)." 2>/dev/null || true
    return 1
}

hyprpaper_set() {
    local mon="$1" image="$2"
    local t0 t1
    t0=$SECONDS
    # FIX: `timeout 10` um JEDEN hyprctl-hyprpaper-Aufruf - vorher
    # konnte ein hängendes hyprpaper hier für immer blockieren und
    # damit den flock-Mutex des ganzen Skripts auf ewig besetzt halten
    # (siehe ensure_hyprpaper_running() oben für die volle Erklärung).
    # Jetzt gibt der Aufruf spätestens nach 10s auf, der Lock wird
    # freigegeben, und der NÄCHSTE Lauf bekommt über den Health-Check
    # oben die Chance, hyprpaper neu zu starten statt wieder zu hängen.
    if ! timeout -k 3 10 hyprctl hyprpaper preload "$image" >/dev/null 2>&1; then
        wb_log "hyprpaper_set: preload $image TIMEOUT/FEHLGESCHLAGEN nach $((SECONDS - t0))s"
        return 1
    fi
    t1=$SECONDS
    wb_log "hyprpaper_set: preload $image dauerte $((t1 - t0))s"
    if ! timeout -k 3 10 hyprctl hyprpaper wallpaper "${mon},${image}" >/dev/null 2>&1; then
        wb_log "hyprpaper_set: wallpaper-Zuweisung $mon TIMEOUT/FEHLGESCHLAGEN nach $((SECONDS - t1))s"
        return 1
    fi
    wb_log "hyprpaper_set: wallpaper-Zuweisung $mon dauerte $((SECONDS - t1))s"
}

# Nicht mehr gebrauchte, zuvor geladene Bilder wieder aus hyprpapers
# RAM-Cache entfernen, damit der über viele Rerolls hinweg nicht
# unbegrenzt wächst. KEEP_IMAGES wird vom Hauptdurchlauf befüllt.
#
# WICHTIG: `hyprctl hyprpaper listloaded` existiert in neueren
# hyprpaper-Versionen nicht mehr (siehe Chat - "invalid hyprpaper
# request" bei dir). Statt das abzufragen, merkt sich dieses Skript
# daher SELBST in einer kleinen State-Datei, welche Bilder es beim
# letzten Lauf geladen hat, und entlädt davon nur die, die jetzt nicht
# mehr gebraucht werden - funktioniert unabhängig davon, ob/wie
# `listloaded` bei dir gerade heißt.
declare -ga KEEP_IMAGES=()
HYPRPAPER_LOADED_STATE="$HOME/.cache/wb-wallpapers-hyprpaper-loaded"

hyprpaper_unload_unused() {
    mkdir -p "$(dirname "$HYPRPAPER_LOADED_STATE")"
    local -a previously_loaded
    mapfile -t previously_loaded 2>/dev/null < "$HYPRPAPER_LOADED_STATE"

    local img keep k
    for img in "${previously_loaded[@]}"; do
        [ -z "$img" ] && continue
        keep=0
        for k in "${KEEP_IMAGES[@]}"; do
            [ "$img" = "$k" ] && { keep=1; break; }
        done
        [ "$keep" = "0" ] && timeout -k 3 10 hyprctl hyprpaper unload "$img" >/dev/null 2>&1
    done

    printf '%s\n' "${KEEP_IMAGES[@]}" > "$HYPRPAPER_LOADED_STATE"
}

# ─────────────────────────────────────────────────────────────────
# Nur fehlende Monitore füllen (für WallpaperHotplug.sh)
#   Wallpapers.sh --fill-missing
# Setzt ausschließlich für Monitore, die laut hyprpaper aktuell KEIN
# Wallpaper haben, ein neues Zufallsbild. Bereits versorgte Monitore
# bleiben unangetastet (kein Flackern bei Hotplug).
# ─────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--fill-missing" ]; then
    wb_log "--fill-missing: start"
    ensure_hyprpaper_running || { wb_log "--fill-missing: ENDE exit 1 (ensure_hyprpaper_running fehlgeschlagen)"; exit 1; }
    discover_xfconf_monitor_map || true
    ensure_xfdesktop_transparent

    # Aktive Bilder als "behalten" markieren, damit hyprpaper_unload_unused
    # sie NICHT entlädt (sonst würden bestehende Wallpaper verschwinden).
    mapfile -t _active_imgs < <(hyprctl hyprpaper listactive 2>/dev/null | sed 's/^[^:]*: //')
    for img in "${_active_imgs[@]}"; do
        [ -n "$img" ] && KEEP_IMAGES+=("$img")
    done

    # Monitore, die laut hyprpaper bereits ein Wallpaper haben
    declare -A HAS=()
    while IFS= read -r m; do
        [ -n "$m" ] && HAS["$m"]=1
    done < <(hyprctl hyprpaper listactive 2>/dev/null | awk -F': ' '{print $1}')

    mapfile -t MONITORS < <(
        hyprctl monitors -j | jq -r '.[] | [.name, (.width|tostring), (.height|tostring)] | @tsv'
    )
    wb_log "--fill-missing: hyprctl meldet ${#MONITORS[@]} Monitor(e): $(printf '%s ' "${MONITORS[@]}")"
    wb_log "--fill-missing: bereits versorgt laut hyprpaper: $(printf '%s ' "${!HAS[@]}")"

    for line in "${MONITORS[@]}"; do
        IFS=$'\t' read -r MON W H <<< "$line"
        if [ -n "${HAS[$MON]:-}" ]; then
            wb_log "--fill-missing: $MON übersprungen (hat schon ein Bild)"
            continue
        fi

        KEY=$(ratio_key "$W" "$H")
        IMAGE=""
        if IMAGE="$(pick_image "$WALLPAPER_DIR/$KEY")"; then
            :
        elif [ "$KEY" != "$DEFAULT_RATIO" ] && IMAGE="$(pick_image "$WALLPAPER_DIR/$DEFAULT_RATIO")"; then
            :
        else
            wb_log "--fill-missing: $MON ($W x $H) - KEIN Bild gefunden"
            notify-send "Wallpaper" "Kein Bild für $MON ($W x $H) gefunden." 2>/dev/null
            continue
        fi

        wb_log "--fill-missing: setze $MON -> $IMAGE"
        hyprpaper_set "$MON" "$IMAGE"
        KEEP_IMAGES+=("$IMAGE")
    done

    hyprpaper_unload_unused
    wb_log "--fill-missing: ENDE exit 0"
    exit 0
fi

# ─────────────────────────────────────────────────────────────────
# Explizite Auswahl (fürs Wallpapers-Tab in den Widgets):
#   Wallpapers.sh --set /pfad/zum/bild.jpg [MONITORNAME]
# ─────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--set" ]; then
    wb_log "--set: start"
    IMAGE="${2:-}"
    TARGET_MON="${3:-}"

    if [ -z "$IMAGE" ] || [ ! -f "$IMAGE" ]; then
        echo "Usage: Wallpapers.sh --set /path/to/image [MONITOR]" >&2
        exit 1
    fi

    if [ -n "$TARGET_MON" ]; then
        MONS=("$TARGET_MON")
    else
        mapfile -t MONS < <(hyprctl monitors -j | jq -r '.[].name')
    fi

    if [ "${#MONS[@]}" -eq 0 ]; then
        notify-send "Wallpaper" "Keine Monitore von hyprctl erhalten." 2>/dev/null
        exit 1
    fi

    ensure_hyprpaper_running || exit 1
    discover_xfconf_monitor_map || true
    ensure_xfdesktop_transparent

    for MON in "${MONS[@]}"; do
        hyprpaper_set "$MON" "$IMAGE"
        KEEP_IMAGES+=("$IMAGE")
    done
    hyprpaper_unload_unused
    wb_log "--set: ENDE exit 0"
    exit 0
fi

# ─────────────────────────────────────────────────────────────────
# Normaler Zufalls-Durchlauf
# ─────────────────────────────────────────────────────────────────
wb_log "normaler Durchlauf: start"
mapfile -t MONITORS < <(
    hyprctl monitors -j | jq -r '.[] | [.name, (.width|tostring), (.height|tostring)] | @tsv'
)
wb_log "normaler Durchlauf: hyprctl meldet ${#MONITORS[@]} Monitor(e): $(printf '%s ' "${MONITORS[@]}")"

if [ "${#MONITORS[@]}" -eq 0 ]; then
    wb_log "normaler Durchlauf: ENDE exit 1 (keine Monitore)"
    notify-send "Wallpaper" "Keine Monitore von hyprctl erhalten." 2>/dev/null
    exit 1
fi

if [ "$DRY_RUN" != "1" ]; then
    ensure_hyprpaper_running || { wb_log "normaler Durchlauf: ENDE exit 1 (ensure_hyprpaper_running fehlgeschlagen)"; exit 1; }
    discover_xfconf_monitor_map || true
    ensure_xfdesktop_transparent
fi

for line in "${MONITORS[@]}"; do
    IFS=$'\t' read -r MON W H <<< "$line"

    KEY=$(ratio_key "$W" "$H")
    SRC="$KEY"
    IMAGE=""

    if IMAGE="$(pick_image "$WALLPAPER_DIR/$KEY")"; then
        SRC="$KEY"
    elif [ "$KEY" != "$DEFAULT_RATIO" ] && IMAGE="$(pick_image "$WALLPAPER_DIR/$DEFAULT_RATIO")"; then
        SRC="$DEFAULT_RATIO"
    else
        wb_log "normaler Durchlauf: $MON ($W x $H, Ratio $KEY) - KEIN Bild gefunden"
        notify-send "Wallpaper" "Kein Bild für $MON ($W x $H, Ratio $KEY) und Fallback $DEFAULT_RATIO leer." 2>/dev/null
        continue
    fi

    if [ "$DRY_RUN" = "1" ]; then
        echo "$MON: ${W}x${H} -> ratio $KEY -> source $SRC -> $IMAGE (hyprpaper)"
        continue
    fi

    wb_log "normaler Durchlauf: setze $MON -> $IMAGE"
    hyprpaper_set "$MON" "$IMAGE"
    KEEP_IMAGES+=("$IMAGE")
done

if [ "$DRY_RUN" = "1" ]; then
    exit 0
fi

hyprpaper_unload_unused
wb_log "normaler Durchlauf: ENDE exit 0"