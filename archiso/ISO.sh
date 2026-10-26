#!/usr/bin/env bash
# TrafkTux - vereintes Build-Skript
#
# Fasst zusammen (und ersetzt):
#   - build-hyprland-plugins.sh
#   - build-local-repo.sh
#   - BuildOptionalRepo.sh
#   - build-iso.sh (alt)
#
# Reihenfolge: 1) Hyprland-Plugins  2) AUR-Repo  3) Optional-Repo
#              4) Late-Overlay vorbereiten  5) ISO
# (Hyprland-Plugins zuerst, weil hyprpm eine laufende Hyprland-Session
#  braucht - das will man als erstes erledigt haben.)
#
# FEHLERVERHALTEN:
#   Das Skript bricht bei JEDEM Fehler sofort ab (set -euo pipefail).
#   EINZIGE AUSNAHME: hyprgrass. Schlaegt der Build/das Enable von
#   hyprgrass per hyprpm fehl, wird NICHT abgebrochen, sondern einfach
#   die im hyprpm-System-Cache bereits vorhandene hyprgrass-.so (z.B.
#   von einem frueheren Lauf) weiterverwendet. Existiert dort ueberhaupt
#   keine hyprgrass-.so (auch keine alte), bricht das Skript trotzdem ab.
#
# WICHTIG: Als NORMALER User ausfuehren, NICHT als root/sudo.
#   makepkg und BuildOptionalRepo-Logik verweigern root komplett.
#   Fuer die Dinge, die wirklich root brauchen (pacman -S, hyprpm-Cache
#   unter /var/cache lesen, mkarchiso), ruft das Skript gezielt sudo auf
#   und fragt dafuer ggf. mehrfach nach dem Passwort.
#
# WARUM ES VORHER MIT "exists in filesystem" ABGEBROCHEN IST:
#   mkarchiso kopiert das airootfs/-Profilverzeichnis IMMER ZUERST in das
#   neue Root (_make_custom_airootfs) und installiert ERST DANACH die
#   Pakete aus packages.x86_64 per pacstrap (_make_packages) - siehe
#   archiso-Quellcode (mkarchiso, Funktionen _make_custom_airootfs /
#   _make_packages, aufgerufen in dieser Reihenfolge in build()). Liegen
#   also schon eigene Dateien (z.B. Theme-/Icon-Dateien) unter airootfs/
#   an Pfaden, die auch ein zu installierendes Paket (oder eine seiner
#   Abhaengigkeiten!) mitbringt, bricht pacman beim Install mit
#   "failed to commit transaction (conflicting files)" ab - unabhaengig
#   davon, ob das work-Verzeichnis vorher sauber geleert wurde.
#
#   FIX (Schritt 4/5 unten): Statt vorab zu versuchen zu ERRATEN, welche
#   einzelnen airootfs-Dateien mit welchem Paket kollidieren wuerden (das
#   hat sich ueber mehrere Anlaeufe als unzuverlaessig erwiesen - siehe
#   Git-/Chat-Historie: einmal falsche Paketanzahl wegen Host- statt
#   Leer-Root-Aufloesung, danach trotz korrekter Paketanzahl immer noch
#   dutzende uebersehene Dateien), wird VOR dem mkarchiso-Lauf der
#   KOMPLETTE eigene Inhalt von airootfs/ (bis auf den Hook selbst)
#   temporaer nach airootfs/opt/trafktux-late-overlay/ verschoben. mkarchiso
#   kopiert dadurch praktisch nichts Eigenes mehr vorab in einen Pfad, den
#   ein Paket beanspruchen koennte - Konflikte sind damit unabhaengig davon
#   ausgeschlossen, welche Pakete im Detail welche Dateien mitbringen. Der
#   offizielle archiso-Hook airootfs/root/customize_airootfs.sh (laeuft
#   GARANTIERT nach pacstrap, aber vor dem eigentlichen Image-Bau - siehe
#   archiso build()-Reihenfolge) kopiert den ausgelagerten Inhalt danach
#   komplett zurueck an seinen Zielpfad und ueberschreibt damit nur das,
#   was ohnehin schon vorher da war.
#   Ein mkarchiso-Lauf "pausieren" und manuell zwischen zwei Aufrufen
#   Dateien zurueckschieben geht NICHT sauber - mkarchiso hat dafuer keine
#   Stop-Option, und ein Killen mitten in der pacman-Transaktion waere
#   riskant (angebrochene Paket-Datenbank). Der customize_airootfs.sh-Hook
#   ist der dafuer vorgesehene archiso-Mechanismus.
#
# Aufruf:  ./ISO.sh
#
# BUILD-OPTIONEN (werden ganz am Anfang interaktiv abgefragt, siehe unten):
#   1) Vorhandene, bereits gebaute AUR-Pakete (Schritt 2/5) UND bereits
#      gebaute Hyprland-Plugins (Schritt 1/5) wiederverwenden statt bei
#      jedem Lauf neu zu bauen (spart Zeit, siehe REUSE_EXISTING_AUR_PKGS).
#      Schritt 1/5 wird dabei komplett uebersprungen (kein hyprpm add/
#      update/enable, keine laufende Hyprland-Session noetig), sofern im
#      hyprpm-Cache-Ordner bereits gebaute Plugins liegen.
#   2) Lokale AUR-Paketdateien UND den gebauten Hyprland-Plugin-Cache nach
#      dem ISO-Build wieder loeschen, z.B. weil einzelne Pakete zu gross
#      fuers Git-Repo sind (siehe CLEAN_AUR_REPO_AFTER_BUILD).

set -euo pipefail

die() { echo "FEHLER: $*" >&2; exit 1; }

[[ $EUID -ne 0 ]] || die "Bitte NICHT als root/sudo ausfuehren - einzelne Schritte holen sich sudo selbst, wenn sie es brauchen."

PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# sudo-Ticket gleich zu Beginn holen und waehrend des GESAMTEN Laufs alle
# 60s im Hintergrund auffrischen. Ohne das kann sudo nach den vielen
# Minuten AUR-/Optional-Builds beim finalen "sudo mkarchiso" (Schritt 5)
# auf einen neuen, unbeaufsichtigten Passwort-Prompt laufen und per
# Timeout abbrechen ("Zeitueberschreitung beim Lesen des Passworts").
echo "==> Bitte einmal sudo-Passwort eingeben (wird fuer den ganzen Lauf warmgehalten):"
sudo -v || die "sudo-Authentifizierung fehlgeschlagen."
( while true; do sudo -n -v; sleep 60; done ) &
SUDO_KEEPALIVE_PID=$!

#############################################################################
# Build-Optionen abfragen (einmal ganz am Anfang, damit man danach nicht
# mehr vor dem Rechner sitzen muss)
#############################################################################
REUSE_EXISTING_AUR_PKGS="0"
CLEAN_AUR_REPO_AFTER_BUILD="0"

echo ""
read -rp "==> Vorhandene, bereits gebaute AUR-Pakete (Schritt 2/5) UND bereits gebaute Hyprland-Plugins (Schritt 1/5) wiederverwenden statt neu zu bauen? [j/N] " reuse_answer
[[ "${reuse_answer,,}" =~ ^j(a)?$ ]] && REUSE_EXISTING_AUR_PKGS="1"

read -rp "==> Lokale AUR-Paketdateien UND den gebauten Hyprland-Plugin-Cache (Schritt 1/5 + 2/5) nach dem ISO-Build wieder loeschen (z.B. weil einzelne Pakete zu gross fuers Git-Repo sind)? [j/N] " clean_answer
[[ "${clean_answer,,}" =~ ^j(a)?$ ]] && CLEAN_AUR_REPO_AFTER_BUILD="1"
echo ""

declare -a CLEANUP_PATHS=()
declare -a SUDO_CLEANUP_PATHS=()

# WICHTIG: airootfs/ im echten Projektordner (PROFILE_DIR) wird AB HIER NIE
# WIEDER angefasst - kein mv, kein rm, keine Umbenennung. Schritt 4/5 baut
# dafuer eine komplette WEGWERF-KOPIE des Profils in BUILD_PROFILE_DIR (ein
# mktemp-Verzeichnis ausserhalb des Projektordners) und macht die ganze
# Late-Overlay-Umsortierung NUR auf dieser Kopie. mkarchiso baut am Ende aus
# BUILD_PROFILE_DIR, nicht aus PROFILE_DIR. Stuerzt das Skript mittendrin ab
# (Fehler, Strg+C, Stromausfall, was auch immer) - die eigenen Dateien unter
# PROFILE_DIR/airootfs/ sind davon komplett unberuehrt, weil nie etwas aus
# ihnen HERAUS verschoben wurde. Siehe BUILD_PROFILE_DIR weiter unten in
# Schritt 4/5.
#
# AUSNAHME (unveraendert seit jeher, nicht Teil der obigen Regel): die
# beiden lokalen Repo-Ordner airootfs/opt/trafktux-repo (REPO_DIR, Schritt
# 2/5) und airootfs/opt/TrafkTuxOptional (OPTIONAL_REPO_DIR, Schritt 3/5)
# werden WEITERHIN direkt im echten PROFILE_DIR/airootfs befuellt (nicht in
# der Wegwerf-Kopie) - das sind bewusst dauerhaft im Projekt lebende
# Build-Artefakte, kein "spontanes Verschieben/Verlieren" eurer eigenen
# Dateien.

# EIN einziger Exit-Trap fuer alles (sudo-Keepalive stoppen, temporaere
# Pfade loeschen - inkl. BUILD_PROFILE_DIR). Vorher gab es zwei separate
# "trap ... EXIT"-Aufrufe hintereinander, wodurch der zweite den ersten
# STILL ueberschrieben hat - der sudo-Keepalive-Hintergrundprozess lief
# dadurch nach Skriptende einfach munter weiter. Das ist hier mit behoben.
cleanup() {
    local p
    for p in "${CLEANUP_PATHS[@]+"${CLEANUP_PATHS[@]}"}"; do
        [[ -n "${p:-}" ]] && rm -rf "${p}" 2>/dev/null
    done
    # Manche Pfade (z.B. RESOLVE_ROOT/var/lib/pacman) enthalten root-eigene
    # Dateien von "sudo pacman -Sy --root ..." - die kriegt ein normaler
    # "rm -rf" als dieser User nicht weg, daher hier gezielt mit sudo.
    for p in "${SUDO_CLEANUP_PATHS[@]+"${SUDO_CLEANUP_PATHS[@]}"}"; do
        [[ -n "${p:-}" ]] && sudo rm -rf "${p}" 2>/dev/null
    done
    # sudo-Keepalive als LETZTES stoppen, falls einer der obigen Schritte
    # selbst noch sudo braucht.
    kill "${SUDO_KEEPALIVE_PID}" 2>/dev/null || true
    return 0
}
trap cleanup EXIT

#############################################################################
# 1/5: Hyprland-Plugins (hyprpm)
#############################################################################
echo "############################################################"
echo "# 1/5: Hyprland-Plugins (hyprpm)"
echo "############################################################"

HYPRPM_STATE_STAGE="${PROFILE_DIR}/airootfs/opt/trafktux-hyprpm-cache"
mkdir -p "${HYPRPM_STATE_STAGE}"

# REUSE_EXISTING_AUR_PKGS=1: wenn im hyprpm-Cache-Ordner schon gebaute
# Plugins liegen (von einem frueheren Lauf - der Ordner wird NICHT von
# diesem Skript geloescht, ausser CLEAN_AUR_REPO_AFTER_BUILD=1 war beim
# letzten Lauf gesetzt), wird Schritt 1/5 komplett uebersprungen. Dafuer
# muss noch nicht mal eine Hyprland-Session laufen - der hyprctl-Check
# weiter unten passiert nur im "echten" Build-Zweig.
HYPRPM_CACHE_REUSABLE="0"
if [[ "${REUSE_EXISTING_AUR_PKGS}" == "1" ]] \
    && [[ -n "$(find "${HYPRPM_STATE_STAGE}" -mindepth 2 -maxdepth 2 -name "*.so" -not -path "*/headersRoot/*" -print -quit 2>/dev/null)" ]]; then
    HYPRPM_CACHE_REUSABLE="1"
fi

if [[ "${HYPRPM_CACHE_REUSABLE}" == "1" ]]; then
    echo "==> Vorhandener hyprpm-Plugin-Cache in ${HYPRPM_STATE_STAGE} wird wiederverwendet, kein Rebuild (REUSE_EXISTING_AUR_PKGS=1)."
    echo "Hyprland-Plugins uebersprungen."
    echo ""
else

if ! hyprctl version >/dev/null 2>&1; then
    die "Es laeuft kein Hyprland. Dieses Skript muss INNERHALB einer aktiven Hyprland-Session laufen, weil hyprpm den laufenden Hyprland-Commit kennen muss, um die passenden Header zu ziehen."
fi

echo "==> Hyprland-Version auf diesem Rechner:"
hyprctl version | head -n1
echo ""
echo "Stelle sicher, dass dies exakt der Version entspricht, die euer"
echo "packages.x86_64 fuer die ISO installiert. Enter zum Fortfahren, Strg+C zum Abbrechen."
read -r

# Repo -> Plugin-Name(n), die aktiviert werden sollen
declare -A REPO_PLUGINS=(
  ["https://github.com/hyprwm/hyprland-plugins"]="hyprbars hyprfocus"
  ["https://github.com/sandwichfarm/hyprexpo"]="hyprexpo"
  ["https://github.com/hyprnux/hyprglass"]="hyprglass"
  ["https://github.com/virtcode/hypr-dynamic-cursors"]="dynamic-cursors"
  ["https://github.com/horriblename/hyprgrass"]="hyprgrass"
  ["https://github.com/savonovv/hypr-kinetic-scroll"]="hypr-kinetic-scroll"
  ["https://github.com/gen3vra/hyprwinwrap"]="hyprwinwrap"
)

for repo in "${!REPO_PLUGINS[@]}"; do
    echo "==> hyprpm add ${repo}"
    # hyprpm fragt interaktiv nach Bestaetigung (Trust-Warnung) - via "yes"
    # automatisch bestaetigen. Wenn das Repo schon bekannt ist, meckert
    # hyprpm ggf., das ist unkritisch (daher || true, kein echter Fehler).
    yes | hyprpm add "${repo}" || true
done

echo "==> hyprpm update (zieht + baut alle registrierten Plugins auf den aktuellen Stand)"
HYPRPM_UPDATE_LOG="$(mktemp)"
CLEANUP_PATHS+=("${HYPRPM_UPDATE_LOG}")

set +e
hyprpm update 2>&1 | tee "${HYPRPM_UPDATE_LOG}"
update_rc=${PIPESTATUS[0]}
set -e

if [[ ${update_rc} -ne 0 ]]; then
    # Nur "failed to update the following repositories: hyprgrass" wird
    # toleriert (z.B. weil die Zusatz-Plugins hyprgrass-backlight/-pulse
    # auf dieser Hyprland-Version nicht bauen). Alles andere ist ein
    # echter Abbruchgrund.
    fail_line="$(grep -E 'failed to update the following repositories:' "${HYPRPM_UPDATE_LOG}" || true)"
    failed_repos="${fail_line#*: }"
    failed_repos="$(echo "${failed_repos}" | xargs || true)"

    if [[ -n "${failed_repos}" && "${failed_repos}" == "hyprgrass" ]]; then
        echo "WARNUNG: hyprgrass (bzw. dessen Zusatz-Plugins) konnte(n) nicht gebaut werden." >&2
        echo "Es wird weiter unten versucht, auf eine evtl. bereits vorhandene Version" >&2
        echo "aus dem hyprpm-Cache zurueckzufallen, statt abzubrechen." >&2
    else
        die "hyprpm update ist fehlgeschlagen (Exit ${update_rc}), und zwar nicht nur wegen hyprgrass (betroffen: '${failed_repos:-unbekannt}'). Siehe Log oben."
    fi
fi

for repo in "${!REPO_PLUGINS[@]}"; do
    for name in ${REPO_PLUGINS[$repo]}; do
        echo "==> aktiviere ${name}"
        if [[ "${name}" == "hyprgrass" ]]; then
            if ! hyprpm enable "${name}"; then
                echo "WARNUNG: 'hyprpm enable hyprgrass' fehlgeschlagen - wird unten ueber den Cache abgefangen, kein Abbruch." >&2
            fi
        else
            hyprpm enable "${name}"
        fi
    done
done

# Aktuelle hyprpm-Versionen legen ihren State systemweit unter
# /var/cache/hyprpm/<username>/ ab (root-verwaltet, daher sudo hier).
HYPRPM_CACHE_DIR="/var/cache/hyprpm/$(id -un)"

if [[ ! -d "${HYPRPM_CACHE_DIR}" ]]; then
    echo "Inhalt von /var/cache/hyprpm zur Fehlersuche:" >&2
    sudo find /var/cache/hyprpm -maxdepth 2 2>&1 >&2 || true
    die "${HYPRPM_CACHE_DIR} existiert nicht. Falls hyprpm bei dir einen anderen Pfad verwendet, HYPRPM_CACHE_DIR im Skript anpassen."
fi

if [[ -z "$(sudo find "${HYPRPM_CACHE_DIR}" -mindepth 2 -maxdepth 2 -name "*.so" -not -path "*/headersRoot/*" -print -quit)" ]]; then
    echo "Tatsaechlicher Inhalt zur Fehlersuche:" >&2
    sudo find "${HYPRPM_CACHE_DIR}" -maxdepth 2 2>&1 >&2 || true
    die "Keine .so-Dateien unter ${HYPRPM_CACHE_DIR} gefunden (Build fehlgeschlagen? falscher Name bei hyprpm enable?)."
fi

# Extra-Pruefung NUR fuer hyprgrass: wenn Build/Enable oben fehlgeschlagen
# ist, MUSS trotzdem wenigstens irgendeine hyprgrass-.so (auch eine aeltere,
# vom letzten erfolgreichen Lauf) im Cache liegen - sonst doch Abbruch.
if [[ -z "$(sudo find "${HYPRPM_CACHE_DIR}" -iname "*hyprgrass*.so" -print -quit)" ]]; then
    die "Weder ein frischer noch ein alter Build von hyprgrass im hyprpm-Cache (${HYPRPM_CACHE_DIR}) gefunden - Abbruch."
fi

echo ""
echo "==> Kopiere kompletten hyprpm-State (Header + state.toml + .so) nach ${HYPRPM_STATE_STAGE}"
rm -rf "${HYPRPM_STATE_STAGE}"
mkdir -p "${HYPRPM_STATE_STAGE}"
sudo cp -a "${HYPRPM_CACHE_DIR}/." "${HYPRPM_STATE_STAGE}/"
sudo chown -R "$(id -u):$(id -g)" "${HYPRPM_STATE_STAGE}"
echo "Hyprland-Plugins fertig."
echo ""

fi

#############################################################################
# 2/5: Lokales AUR-Repo (trafktux-repo)
#############################################################################
echo "############################################################"
echo "# 2/5: Lokales AUR-Repo (trafktux-repo)"
echo "############################################################"

REPO_NAME="trafktux"
REPO_DIR="${PROFILE_DIR}/airootfs/opt/${REPO_NAME}-repo"
AUR_BUILD_DIR="$(pwd)/aur-build"
CLEANUP_PATHS+=("${AUR_BUILD_DIR}")

AUR_PACKAGES=(
  calamares
  # libpamac-full und pamac-cli sind KEINE Split-Pakete von pamac-all,
  # sondern eigene AUR-Pakete mit eigenem PKGBUILD (verifiziert: pamac-all
  # und libpamac-full sind laut AUR-Forenberichten getrennte Pakete). Ohne
  # sie hier wird pamac-all zwar gebaut und landet in der ${REPO_NAME}-DB,
  # aber "pacman -S pamac-all" im Zielsystem (install-aur-packages.sh)
  # bricht mit "could not satisfy dependencies" ab, weil die beiden
  # Abhaengigkeiten in keinem Repo existieren. Muessen deshalb hier
  # explizit mitgebaut werden, damit ihre .pkg.tar.zst ebenfalls in
  # ${REPO_DIR} landen und von repo-add (am Ende dieses Schritts) erfasst
  # werden - die Reihenfolge in diesem Array ist dafuer egal, da repo-add
  # erst NACH der kompletten Schleife einmal ueber alle Paketdateien laeuft.
  #
  # libpamac-full seinerseits haengt an snapd + snapd-glib (ebenfalls
  # eigene AUR-Pakete, kein offizielles Repo) - ohne die bricht der naechste
  # "pacman -S" im Zielsystem an GENAU derselben Stelle, nur eine Ebene
  # tiefer ("cannot resolve snapd/snapd-glib, a dependency of
  # libpamac-full"). Bewusste Entscheidung: vollen Snap-Support mitbauen,
  # nicht auf das schlankere "libpamac" (ohne -full, nur Flatpak)
  # ausweichen.
  snapd
  snapd-glib
  libpamac-full
  pamac-cli
  pamac-all
  hyprshade
  hyprland-minimizer-git
  wvkbd
  python-openrgb-git
  vscodium-bin
  clamav-unofficial-sigs
  mediawriter
  cnijfilter2
  gnome-network-displays
  ckbcomp
)

mkdir -p "${REPO_DIR}" "${AUR_BUILD_DIR}"

sudo pacman -S --needed --noconfirm base-devel git

# --- Pacman-Sync-Datenbanken fuer das Zielsystem cachen ------------------
# GRUND (per mkarchiso-Quellcode verifiziert, nicht geraten - siehe
# mkarchiso, _cleanup_pacstrap_dir(), aufgerufen NACH unserem
# customize_airootfs.sh-Hook in build()):
#   # Delete pacman database sync cache files (*.tar.gz)
#   find "${pacstrap_dir}/var/lib/pacman" -maxdepth 1 -type f -delete
#   # Delete pacman database sync cache
#   find "${pacstrap_dir}/var/lib/pacman/sync" -delete
# mkarchiso entfernt die kompletten Pacman-Sync-Datenbanken (core.db,
# extra.db, multilib.db, ...) aus der Live-ISO - IMMER, Standard-Verhalten,
# nicht beeinflussbar ueber Profil-Einstellungen. Die Live-ISO (und damit
# auch alles, was Calamares' unpackfs 1:1 aufs Zielsystem kopiert) hat also
# NIE eigene Sync-Datenbanken. install-aur-packages.sh (laeuft als
# shellprocess@aurinstall im Zielsystem, siehe settings.conf) braucht die
# aber, um per "pacman -S" offizielle Abhaengigkeiten aufzuloesen - ohne
# das: "error: failed to prepare transaction (could not find database)".
#
# Fix: analog zum Kernel-Problem (shellprocess@bootkernel) die aktuellen
# Sync-Datenbanken HIER, auf dem Build-Host (der hat sie ja, das ganze
# Skript braucht funktionierendes pacman), nach einem Pfad unter
# airootfs/opt/ cachen, der NICHT von _cleanup_pacstrap_dir() angefasst
# wird (die loescht nur unter var/lib/pacman/... und var/cache/pacman/pkg).
# Calamares (shellprocess@pacmansync, laeuft VOR aurinstall, siehe
# settings.conf) kopiert diese dann im Zielsystem nach /var/lib/pacman/sync
# zurueck - 100% offline, kein "pacman -Sy" ueber Netzwerk noetig.
#
# Welche Repo-Namen gecacht werden, wird NICHT hart kodiert, sondern direkt
# aus airootfs/etc/pacman.conf ausgelesen (das ist die /etc/pacman.conf,
# die am Ende im Live-/Zielsystem landet) - damit passt das automatisch zu
# euren tatsaechlich aktivierten Repos (aktuell: core-testing, core,
# extra-testing, extra, multilib-testing, multilib), ohne das hier bei
# jeder Pacman.conf-Aenderung von Hand nachpflegen zu muessen. "options"
# und das eigene "${REPO_NAME}" (trafktux, wird gleich frisch erzeugt)
# werden ausgeschlossen.
#
# WICHTIG: bewusst NICHT von REUSE_EXISTING_AUR_PKGS betroffen - die
# Sync-Datenbanken sollen bei JEDEM Lauf frisch sein (sie veralten schnell,
# und ein veraltetes core.db kann im Zielsystem auf nicht mehr existierende
# Paketversionen zeigen).
echo "==> Cache aktuelle Pacman-Sync-Datenbanken fuer das Zielsystem (fuer install-aur-packages.sh)..."
PACMAN_SYNC_CACHE_DIR="${PROFILE_DIR}/airootfs/opt/trafktux-pacman-sync-cache"
TARGET_PACMAN_CONF="${PROFILE_DIR}/airootfs/etc/pacman.conf"
[[ -f "${TARGET_PACMAN_CONF}" ]] || die "${TARGET_PACMAN_CONF} nicht gefunden - wird gebraucht, um zu wissen, welche Pacman-Sync-Datenbanken fuers Zielsystem gecacht werden muessen."

mkdir -p "${PACMAN_SYNC_CACHE_DIR}"
rm -f "${PACMAN_SYNC_CACHE_DIR}"/*.db

sudo pacman -Sy

mapfile -t SYNC_REPO_NAMES < <(grep -oP '^\[\K[A-Za-z0-9_.+-]+(?=\]$)' "${TARGET_PACMAN_CONF}" | grep -vx -e 'options' -e "${REPO_NAME}")
((${#SYNC_REPO_NAMES[@]})) || die "Keine Repo-Namen in ${TARGET_PACMAN_CONF} gefunden (ausser 'options'/'${REPO_NAME}')."

for repo in "${SYNC_REPO_NAMES[@]}"; do
    sync_src="/var/lib/pacman/sync/${repo}.db"
    if [[ -f "${sync_src}" ]]; then
        cp -v "${sync_src}" "${PACMAN_SYNC_CACHE_DIR}/"
    else
        echo "WARNUNG: ${sync_src} nicht gefunden (Repo '${repo}' auf diesem Build-Host nicht erreichbar/synchronisiert?) - wird uebersprungen. 'pacman -S' fuer dieses Repo wird im Zielsystem fehlschlagen." >&2
    fi
done
echo ""

for pkg in "${AUR_PACKAGES[@]}"; do
    # REUSE_EXISTING_AUR_PKGS=1: ueberspringt den kompletten Rebuild, wenn
    # im lokalen Repo bereits eine Paketdatei liegt, deren Name mit
    # "<pkg>-" beginnt. HEURISTIK, kein 100%iger Treffer: funktioniert fuer
    # alle hier gelisteten Pakete AUSSER "pamac-all" - dessen PKGBUILD baut
    # mehrere Binaerpakete (z.B. pamac-tray-appindicator), die NICHT mit
    # "pamac-all-" anfangen. Fuer pamac-all greift die Wiederverwendung
    # also nicht zuverlaessig - wird im Zweifel einfach neu gebaut.
    if [[ "${REUSE_EXISTING_AUR_PKGS}" == "1" ]]; then
        existing_pkg="$(find "${REPO_DIR}" -maxdepth 1 -name "${pkg}-*.pkg.tar.*" -print -quit)"
        if [[ -n "${existing_pkg}" ]]; then
            echo "==> ${pkg}: vorhandene Paketdatei wird wiederverwendet (${existing_pkg##*/}), kein Rebuild."
            continue
        fi
    fi

    echo "==> Baue ${pkg}..."
    # Alte Version(en) dieses Pakets vorher entfernen, sonst sammeln sich
    # bei jedem Rebuild mehrere pkgver-Stände im Repo an, und repo-add
    # weiss nicht mehr, welche davon die aktuelle ist.
    rm -f "${REPO_DIR}/${pkg}-"*.pkg.tar.* 2>/dev/null || true
    pkg_build_dir="${AUR_BUILD_DIR}/${pkg}"
    rm -rf "${pkg_build_dir}"
    git clone "https://aur.archlinux.org/${pkg}.git" "${pkg_build_dir}"
    (
        cd "${pkg_build_dir}"
        # -s: fehlende Build-Abhaengigkeiten mit pacman nachziehen
        # -c: Build-Ordner danach aufraeumen
        makepkg -sc --noconfirm
        cp -v ./*.pkg.tar.zst "${REPO_DIR}/"
    )
done

# --- hyprland-Paket exakt pinnen -----------------------------------------
# GRUND: hyprpm hat in Schritt 1/5 die Plugins gegen das hyprland gebaut,
# das GERADE auf diesem Rechner installiert/laeuft. packages.x86_64 listet
# "hyprland" aber nur als Namen OHNE Version - pacstrap in Schritt 5/5
# wuerde sich sonst einfach nehmen, was die Arch-Mirrors in DEM Moment
# gerade anbieten. Liegen zwischen Schritt 1/5 und 5/5 Stunden (AUR-/
# Optional-Builds brauchen oft lange) und pushen die Mirrors in der
# Zwischenzeit ein hyprland-Update, baut die ISO eine ANDERE Version als
# die, gegen die die Plugin-Header gebaut wurden - genau das fuehrte zum
# "Headers corrupted"-Fehler beim ersten Boot.
#
# Fix: die exakt installierte .pkg.tar-Datei direkt aus dem Pacman-Cache
# in dieses lokale Repo legen. [trafktux] steht in pacman.conf ABSICHTLICH
# vor core/extra (siehe dortiger Kommentar) - pacstrap nimmt bei gleichem
# Paketnamen immer die Version aus dem zuerst gelisteten Repo, zieht
# "hyprland" also garantiert aus dieser gepinnten Datei statt von den
# Mirrors, egal was dort inzwischen aktuell ist.
#
# WICHTIG: Diese Datei wird bewusst NICHT von REUSE_EXISTING_AUR_PKGS
# beeinflusst - sie MUSS bei jedem Lauf frisch gegen die aktuell gebauten
# Plugin-Header (Schritt 1/5) gepinnt werden, sonst drohen wieder genau
# die "Headers corrupted"-Probleme von vorher.
rm -f "${REPO_DIR}/hyprland-"*.pkg.tar.* 2>/dev/null || true
echo "==> Pinne installierte hyprland-Version fuer die ISO (muss exakt zu den Plugin-Headern aus Schritt 1/5 passen)..."
HYPR_VER="$(pacman -Q hyprland | awk '{print $2}')"
HYPR_PKG_FILE="$(find /var/cache/pacman/pkg -maxdepth 1 -name "hyprland-${HYPR_VER}-*.pkg.tar.*" -print -quit)"
[[ -n "${HYPR_PKG_FILE}" ]] || die "Installierte hyprland-Version ${HYPR_VER} nicht mehr im Pacman-Cache (/var/cache/pacman/pkg) gefunden (z.B. 'pacman -Scc' gelaufen?). Ohne die exakte Paketdatei kann die ISO nicht garantiert dieselbe Version wie die eben gebauten Plugin-Header bekommen. Fix: 'sudo pacman -S hyprland' erneut ausfuehren (installiert zwar nur neu, holt die Datei aber wieder in den Cache), dann ISO.sh erneut starten."
cp -v "${HYPR_PKG_FILE}" "${REPO_DIR}/"
echo "==> hyprland gepinnt auf Version ${HYPR_VER} (${HYPR_PKG_FILE})"

echo "==> Erzeuge Repo-Datenbank (${REPO_NAME})..."
( cd "${REPO_DIR}" && repo-add "${REPO_NAME}.db.tar.gz" ./*.pkg.tar.* )

rm -rf "${AUR_BUILD_DIR}"
echo "AUR-Repo fertig: ${REPO_DIR}"
echo ""

#############################################################################
# 3/5: Optional-Repo (TrafkTuxOptional Metapakete)
#############################################################################
echo "############################################################"
echo "# 3/5: Optional-Repo (TrafkTuxOptional)"
echo "############################################################"

OPTIONAL_CONF="${PROFILE_DIR}/OptionalGroups.conf"
OPTIONAL_REPO_NAME="TrafkTuxOptional"
OPTIONAL_REPO_DIR="${PROFILE_DIR}/airootfs/opt/${OPTIONAL_REPO_NAME}"
OPTIONAL_LIST_TARGET="/usr/share/TrafkTux/Optional"
OPTIONAL_PKGVER="${PKGVER:-$(date +%Y.%m.%d)}"
OPTIONAL_AUR_RPC="https://aur.archlinux.org/rpc/"

for cmd in pacman curl jq makepkg repo-add; do
    command -v "${cmd}" >/dev/null 2>&1 || die "'${cmd}' nicht gefunden (fuer das Optional-Repo benoetigt)."
done
[[ -f "${OPTIONAL_CONF}" ]] || die "${OPTIONAL_CONF} nicht gefunden."

OPTIONAL_WORK_DIR="$(mktemp -d)"
CLEANUP_PATHS+=("${OPTIONAL_WORK_DIR}")

declare -A OPT_CFG=()
OPT_GROUP_NAMES=()
opt_current=""
while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "${line}" ]] && continue

    if [[ "${line}" =~ ^\[([A-Za-z0-9._+-]+)\]$ ]]; then
        opt_current="${BASH_REMATCH[1]}"
        OPT_GROUP_NAMES+=("${opt_current}")
    elif [[ "${line}" =~ ^([A-Za-z]+)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
        [[ -n "${opt_current}" ]] || die "Eintrag vor der ersten [Gruppe] in OptionalGroups.conf: ${line}"
        OPT_CFG["${opt_current}|${BASH_REMATCH[1]}"]="${BASH_REMATCH[2]}"
    else
        die "Zeile in OptionalGroups.conf nicht lesbar: ${line}"
    fi
done < "${OPTIONAL_CONF}"

((${#OPT_GROUP_NAMES[@]})) || die "Keine Gruppen in ${OPTIONAL_CONF} gefunden."

opt_cfg() { printf '%s' "${OPT_CFG["$1|$2"]:-}"; }

opt_classify() {
    OPT_REPO_PKGS=()
    OPT_AUR_PKGS=()
    local p missing=() args=() found=""

    for p in "$@"; do
        if pacman -Si "${p}" >/dev/null 2>&1; then
            OPT_REPO_PKGS+=("${p}")
        else
            missing+=("${p}")
        fi
    done

    ((${#missing[@]})) || return 0

    for p in "${missing[@]}"; do
        args+=(--data-urlencode "arg[]=${p}")
    done
    found="$(curl -fsSG "${OPTIONAL_AUR_RPC}" \
        --data-urlencode "v=5" --data-urlencode "type=info" "${args[@]}" \
        | jq -r '.results[].Name')" || die "AUR-Abfrage fehlgeschlagen (Internet?)."

    for p in "${missing[@]}"; do
        if grep -qxF -- "${p}" <<<"${found}"; then
            OPT_AUR_PKGS+=("${p}")
        else
            die "'${p}' (Gruppe ${OPT_CURRENT_GROUP}) ist weder in den Arch-Repos (pacman -Sy vergessen?) noch im AUR."
        fi
    done
}

opt_sanitize() {
    local s="$1"
    s="${s//\"/}"
    s="${s//\'/}"
    s="${s//\$/}"
    s="${s//\`/}"
    s="${s//\\/}"
    printf '%s' "${s}"
}

opt_quoted() { local x; for x in "$@"; do printf "'%s' " "${x}"; done; }

OPT_SUMMARY=()

opt_make_group() {
    local g="$1"
    OPT_CURRENT_GROUP="${g}"
    local pkgname
    pkgname="$(opt_cfg "${g}" Name)"
    pkgname="${pkgname:-${OPTIONAL_REPO_NAME}-${g}}"
    [[ "${pkgname}" =~ ^[A-Za-z0-9@._+-]+$ ]] || die "Ungueltiger Paketname '${pkgname}' (Gruppe ${g})."
    local dir="${OPTIONAL_WORK_DIR}/${pkgname}"
    local desc packages=() flatpaks=() services=() modules=() groups=() urls=() updates=()
    local extras=() list_lines=() p f s m gr u

    desc="$(opt_sanitize "$(opt_cfg "${g}" Description)")"
    desc="${desc:-${g}}"
    read -r -a packages <<<"$(opt_cfg "${g}" Packages)"
    read -r -a flatpaks <<<"$(opt_cfg "${g}" Flatpaks)"
    read -r -a services <<<"$(opt_cfg "${g}" Services)"
    read -r -a modules  <<<"$(opt_cfg "${g}" ModulesLoad)"
    read -r -a groups   <<<"$(opt_cfg "${g}" Groups)"
    read -r -a urls     <<<"$(opt_cfg "${g}" PkgUrls)"
    read -r -a updates  <<<"$(opt_cfg "${g}" Update)"

    for u in "${updates[@]}"; do
        [[ "${u}" =~ ^(fast|fastfull|full)$ ]] || die "Update=${u} (Gruppe ${g}) ungueltig, erlaubt: fast, fastfull, full."
    done

    echo "==> ${pkgname}"
    opt_classify "${packages[@]}"

    for p in "${OPT_AUR_PKGS[@]}"; do
        extras+=("${p}")
        list_lines+=("aur ${p}")
    done
    for f in "${flatpaks[@]}"; do
        extras+=("${f} (Flatpak)")
        list_lines+=("flatpak ${f}")
    done
    for u in "${urls[@]}"; do
        extras+=("${u##*/}")
        list_lines+=("pkgurl ${u}")
    done
    for gr in "${groups[@]}"; do
        extras+=("Gruppe ${gr}")
        list_lines+=("group ${gr}")
    done
    for u in "${updates[@]}"; do
        extras+=("Systemupdate ${u}")
        list_lines+=("update ${u}")
    done

    if ((${#extras[@]})); then
        local joined
        printf -v joined '%s, ' "${extras[@]}"
        desc="$(opt_sanitize "${desc} | Wird danach automatisch ergaenzt: ${joined%, }")"
    fi

    local depends=("${OPT_REPO_PKGS[@]}")
    ((${#flatpaks[@]})) && depends+=(flatpak)

    mkdir -p "${dir}"
    local sources=()

    if ((${#list_lines[@]})); then
        {
            echo "# TrafkTuxOptional-${g}: wird von OptionalSync.sh gelesen"
            printf '%s\n' "${list_lines[@]}"
        } > "${dir}/Optional.list"
        sources+=("Optional.list")
    fi

    if ((${#modules[@]})); then
        printf '%s\n' "${modules[@]}" > "${dir}/ModulesLoad.conf"
        sources+=("ModulesLoad.conf")
    fi

    local install_line=""
    if ((${#services[@]})) || ((${#modules[@]})); then
        {
            echo "post_install() {"
            for m in "${modules[@]}"; do echo "    modprobe ${m} 2>/dev/null || true"; done
            for s in "${services[@]}"; do echo "    systemctl enable --now ${s} || true"; done
            echo "}"
            echo "post_upgrade() { post_install; }"
        } > "${dir}/${pkgname}.install"
        install_line="install=${pkgname}.install"
    fi

    {
        echo "# Automatisch erzeugt von ISO.sh (Optional-Repo-Teil) - nicht von Hand bearbeiten"
        echo "pkgname=${pkgname}"
        echo "pkgver=${OPTIONAL_PKGVER}"
        echo "pkgrel=1"
        echo "pkgdesc=\"${desc}\""
        echo "arch=('any')"
        echo "url='https://trafkhop-entertainment.github.io/TrafkSite'"
        echo "license=('custom')"
        # Gruppe fuer IgnoreGroup=TrafkTuxNoAutoUpdate in pacman.conf: damit
        # bleibt dieses Metapaket bei normalen System-Updates aussen vor.
        echo "groups=('TrafkTuxNoAutoUpdate')"
        echo "depends=($(opt_quoted "${depends[@]}"))"
        [[ -n "${install_line}" ]] && echo "${install_line}"
        echo "source=($(opt_quoted "${sources[@]}"))"
        echo "sha256sums=($(for _ in "${sources[@]}"; do printf "'SKIP' "; done))"
        echo ""
        echo "package() {"
        if ((${#list_lines[@]})); then
            echo "    install -Dm644 \"\${srcdir}/Optional.list\" \"\${pkgdir}${OPTIONAL_LIST_TARGET}/${g}.list\""
        fi
        if ((${#modules[@]})); then
            echo "    install -Dm644 \"\${srcdir}/ModulesLoad.conf\" \"\${pkgdir}/usr/lib/modules-load.d/${pkgname}.conf\""
        fi
        echo "    true"
        echo "}"
    } > "${dir}/PKGBUILD"

    OPT_SUMMARY+=("$(printf '%-34s repo: %-2d  AUR: %-2d  Flatpak: %-2d  Sonstiges: %d' \
        "${pkgname}" "${#OPT_REPO_PKGS[@]}" "${#OPT_AUR_PKGS[@]}" "${#flatpaks[@]}" \
        "$((${#urls[@]} + ${#groups[@]} + ${#updates[@]}))")")

    (
        cd "${dir}"
        PKGDEST="${OPTIONAL_REPO_DIR}" PKGEXT=".pkg.tar.zst" makepkg -fdC --noconfirm
    )
}

mkdir -p "${OPTIONAL_REPO_DIR}"
rm -f "${OPTIONAL_REPO_DIR}"/*

OPT_CURRENT_GROUP=""
for g in "${OPT_GROUP_NAMES[@]}"; do
    opt_make_group "${g}"
done

echo "==> Erzeuge Repo-Datenbank (${OPTIONAL_REPO_NAME})..."
repo-add -q "${OPTIONAL_REPO_DIR}/${OPTIONAL_REPO_NAME}.db.tar.gz" "${OPTIONAL_REPO_DIR}"/*.pkg.tar.zst
rm -f "${OPTIONAL_REPO_DIR}"/*.old

echo ""
echo "Optional-Repo Zusammenfassung:"
printf '  %s\n' "${OPT_SUMMARY[@]}"
echo "Optional-Repo fertig: ${OPTIONAL_REPO_DIR}"
echo ""

#############################################################################
# 4/5: Wegwerf-Kopie bauen + Late-Overlay darauf vorbereiten
#############################################################################
echo "############################################################"
echo "# 4/5: Wegwerf-Kopie + Late-Overlay vorbereiten"
echo "############################################################"

WORK_DIR="${PROFILE_DIR}/work"
OUT_DIR="${PROFILE_DIR}"

command -v mkarchiso &>/dev/null || die "mkarchiso nicht gefunden. Vorher installieren: sudo pacman -S --needed archiso"

echo "==> Entferne evtl. vorhandenes, unvollstaendiges work-Verzeichnis von einem frueheren Lauf"
echo "    (sonst kann 'failed to commit transaction (conflicting files)' auftreten, weil"
echo "     Dateien aus einem abgebrochenen Vorlauf schon auf der Platte liegen, aber nicht"
echo "     korrekt in der pacman-Datenbank des neuen Roots verzeichnet sind)."
sudo rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}" "${OUT_DIR}"

[[ -f "${REPO_DIR}/trafktux.db" ]] || die "${REPO_DIR}/trafktux.db nicht gefunden (sollte in Schritt 2/5 entstanden sein)."
[[ -f "${OPTIONAL_REPO_DIR}/TrafkTuxOptional.db" ]] || die "${OPTIONAL_REPO_DIR}/TrafkTuxOptional.db nicht gefunden (sollte in Schritt 3/5 entstanden sein)."

if [[ ! -d "${HYPRPM_STATE_STAGE}" ]] || [[ -z "$(ls -A "${HYPRPM_STATE_STAGE}" 2>/dev/null)" ]]; then
    echo "HINWEIS: ${HYPRPM_STATE_STAGE} ist leer - ISO wird ohne Hyprland-Plugins gebaut." >&2
fi

# --- Wegwerf-Kopie des kompletten Profils --------------------------------
# NEUE REGEL (seit Boot-Debugging-Panik): PROFILE_DIR/airootfs/ wird NIE
# WIEDER verschoben/veraendert. Stattdessen bauen wir hier eine komplette
# Kopie des Profils in BUILD_PROFILE_DIR (mktemp, liegt AUSSERHALB des
# Projektordners) und lassen mkarchiso spaeter NUR gegen diese Kopie
# laufen. Alle folgenden "mv"-Operationen (Late-Overlay) passieren
# ausschliesslich innerhalb dieser Kopie - die echten Dateien im
# Projektordner werden dabei nur noch GELESEN, nie verschoben oder
# geloescht.
#
# Top-Level-Eintraege (profiledef.sh, packages.x86_64, pacman.conf,
# syslinux/, grub/, efiboot/, ...) werden nur SYMLINKT, weil die ohnehin
# nicht veraendert werden - billig und funktioniert fuer beliebige
# Profilstrukturen, ohne Dateinamen hier hart zu kodieren. NUR airootfs/
# wird echt kopiert (per "cp -a --reflink=auto": auf btrfs/xfs quasi
# kostenlos per Copy-on-Write, faellt sonst automatisch auf eine normale
# Kopie zurueck), weil genau das gleich umsortiert wird.
BUILD_PROFILE_DIR="$(mktemp -d)"
CLEANUP_PATHS+=("${BUILD_PROFILE_DIR}")

for entry in "${PROFILE_DIR}"/*; do
    name="$(basename "${entry}")"
    [[ "${name}" == "airootfs" ]] && continue
    [[ "${name}" == "work" ]] && continue
    ln -s "${entry}" "${BUILD_PROFILE_DIR}/${name}"
done

echo "==> Kopiere airootfs/ nach ${BUILD_PROFILE_DIR} (PROFILE_DIR/airootfs bleibt dabei unangetastet)..."
cp -a --reflink=auto "${PROFILE_DIR}/airootfs" "${BUILD_PROFILE_DIR}/airootfs"

LATE_OVERLAY_STAGE="${BUILD_PROFILE_DIR}/airootfs/opt/trafktux-late-overlay"

# pacman.conf braucht einen absoluten Pfad (file://...) fuer das lokale
# trafktux-Repo. Platzhalter @@TRAFKTUX_REPO_DIR@@ wird hier durch den
# tatsaechlichen, aktuellen Pfad ersetzt. REPO_DIR zeigt bewusst weiter auf
# PROFILE_DIR (nicht die Kopie) - pacman liest das waehrend Schritt 5/5
# direkt vom Host-Dateisystem per file://, unabhaengig von der Kopie.
TMP_PACMAN_CONF="$(mktemp)"
CLEANUP_PATHS+=("${TMP_PACMAN_CONF}")
sed "s#@@TRAFKTUX_REPO_DIR@@#${REPO_DIR}#g" "${PROFILE_DIR}/pacman.conf" > "${TMP_PACMAN_CONF}"

echo "DEBUG: REPO_DIR=${REPO_DIR}"
echo "DEBUG: trafktux-Zeile in temp pacman.conf:"
grep -A2 '\[trafktux\]' "${TMP_PACMAN_CONF}"

# --- Warum dieser Schritt ueberhaupt noetig ist, und warum NICHT mehr ----
#     versucht wird, nur die "betroffenen" Dateien vorab zu erraten -------
# mkarchiso kopiert airootfs/ IMMER ZUERST ins neue Root und installiert
# ERST DANACH die Pakete per pacstrap (siehe mkarchiso-Quellcode:
# _make_custom_airootfs laeuft vor _make_packages). Jede eigene Datei unter
# airootfs/, die auch ein zu installierendes Paket (oder irgendeine seiner
# transitiven Abhaengigkeiten) mitbringt, laesst pacman dann mit "exists in
# filesystem" abbrechen.
#
# Eine FRUEHERE Version dieses Skripts hat versucht, vorab GENAU zu
# berechnen, welche Dateien das betrifft (per "pacman -Sp"-Aufloesung gegen
# ein leeres Root + "pacman -Sw"-Download in den Cache + "bsdtar -tf" auf
# jedes .pkg.tar.zst). In der Praxis hat das ueber zwei Build-Laeufe hinweg
# trotzdem nicht alle echten Konflikte gefunden - u.a. weil auf dem
# Host-System selbst (und damit vermutlich auch in airootfs/) teils schon
# Dateien liegen, die zwar am Pfad eines Pakets liegen, aber NICHT (mehr)
# von pacman als dessen Eigentum verzeichnet sind (siehe z.B. "pacman -S
# kate" direkt auf dem Host, das unabhaengig von diesem Skript exakt mit
# dem gleichen Fehlerbild abbricht). Jeder Versuch, das vorab exakt
# nachzubilden, ist dadurch strukturell fehleranfaellig.
#
# Robusterer Ansatz: STATT zu erraten, welche Dateien kollidieren koennten,
# wird der KOMPLETTE eigene Inhalt der airootfs-KOPIE (bis auf den Hook
# selbst, s.u.) OHNE Ausnahme nach .../opt/trafktux-late-overlay/
# verschoben. Das "mv" passiert ausschliesslich innerhalb von
# BUILD_PROFILE_DIR - die echten Dateien unter PROFILE_DIR/airootfs/ sind
# zu diesem Zeitpunkt schon vollstaendig (read-only) gelesen und bleiben
# unangetastet liegen. mkarchiso kopiert dadurch vor pacstrap praktisch
# nichts Eigenes mehr an einen Pfad, den ein Paket beanspruchen koennte -
# Konflikte sind damit unabhaengig davon ausgeschlossen, welche Pakete im
# Detail welche Dateien mitbringen (und unabhaengig von eventuellen
# verwaisten Dateien auf dem Host). Der offizielle archiso-Hook
# airootfs/root/customize_airootfs.sh (laeuft GARANTIERT nach pacstrap,
# aber vor dem eigentlichen Image-Bau - siehe archiso build()-Reihenfolge)
# kopiert danach den kompletten ausgelagerten Inhalt wieder an seinen
# echten Platz zurueck (innerhalb des Images, nicht im Projektordner!) und
# ueberschreibt damit gezielt nur das, was vorher schon da war.
# ---------------------------------------------------------------------------

CONFLICT_COUNT=0
while IFS= read -r -d '' f; do
    rel="${f#"${BUILD_PROFILE_DIR}"/airootfs}"
    # Unseren eigenen Staging-Ordner und den customize_airootfs.sh-Hook
    # selbst natuerlich nie verschieben - der Hook muss ja liegen bleiben,
    # damit mkarchiso ihn ueberhaupt findet und ausfuehrt.
    [[ "${rel}" == /opt/trafktux-late-overlay/* ]] && continue
    [[ "${rel}" == /root/customize_airootfs.sh ]] && continue
    # WICHTIG: REPO_DIR und OPTIONAL_REPO_DIR (airootfs/opt/trafktux-repo
    # bzw. airootfs/opt/TrafkTuxOptional) duerfen NICHT verschoben werden!
    # TMP_PACMAN_CONF enthaelt fuer "[trafktux]" ein file://-Server-Eintrag
    # mit dem ABSOLUTEN Host-Pfad von REPO_DIR (siehe sed-Ersetzung von
    # @@TRAFKTUX_REPO_DIR@@ oben) - pacman/pacstrap liest diesen waehrend
    # Schritt 5/5 DIREKT vom Host-Dateisystem, nicht aus dem (erst danach
    # befuellten) pacstrap-Zielroot. Wuerden wir diese Ordner mit auslagern,
    # faende pacstrap das lokale Repo nicht mehr und koennte die eigenen
    # (AUR-/Optional-)Pakete nicht installieren. Da unter diesen Pfaden
    # ohnehin nichts liegt, das mit einem offiziellen Paket kollidieren
    # koennte, ist es unschaedlich, sie einfach unangetastet zu lassen.
    [[ "${rel}" == "/opt/${REPO_NAME}-repo"/* ]] && continue
    [[ "${rel}" == "/opt/${OPTIONAL_REPO_NAME}"/* ]] && continue
    # Pacman-Sync-DB-Cache (siehe Begruendung in Schritt 2/5) - selber
    # Grund wie REPO_DIR/OPTIONAL_REPO_DIR: muss im Live-System an Ort und
    # Stelle liegen bleiben, damit shellprocess@pacmansync es im
    # Zielsystem wiederfindet (unpackfs kopiert es 1:1 mit rueber).
    [[ "${rel}" == /opt/trafktux-pacman-sync-cache/* ]] && continue
    # WICHTIG (gefunden nach einem Boot-Fehler "Failed to start Switch Root"):
    # mkinitcpio wird NICHT von unserem customize_airootfs.sh-Hook aufgerufen,
    # sondern automatisch von pacmans eigenem Post-Install-Hook, SOBALD das
    # Paket "linux" waehrend pacstrap installiert wird - also mitten in
    # Schritt 5/5, lange BEVOR unser Late-Overlay-Restore (der ja erst NACH
    # pacstrap laeuft) irgendwelche Dateien zurueckkopiert. Wuerden wir
    # airootfs/etc/mkinitcpio.conf.d/archiso.conf (HOOKS=... archiso ...)
    # mitverschieben, baut mkinitcpio ein initramfs OHNE den archiso-Hook,
    # und das Live-System findet beim Booten sein eigenes Root nicht mehr
    # ("Failed to start Switch Root"). Diese Dateien muessen also die ganze
    # Zeit an Ort und Stelle bleiben, nicht erst nachtraeglich zurueckkopiert
    # werden.
    [[ "${rel}" == /etc/mkinitcpio.conf ]] && continue
    [[ "${rel}" == /etc/mkinitcpio.conf.d/* ]] && continue
    [[ "${rel}" == /etc/mkinitcpio.d/* ]] && continue
    [[ "${rel}" == /etc/vconsole.conf ]] && continue
    dest="${LATE_OVERLAY_STAGE}${rel}"
    mkdir -p "$(dirname "${dest}")"
    mv -- "${f}" "${dest}"
    ((++CONFLICT_COUNT))
done < <(find "${BUILD_PROFILE_DIR}/airootfs" -type f -print0)

# --- Late-Overlay als TAR verpacken (nicht als lose Dateien liegen lassen!) --
# GRUND (per mkarchiso-Quellcode verifiziert, nicht geraten - siehe
# _make_custom_airootfs() in mkarchiso): mkarchiso kopiert airootfs/ IMMER
# mit "cp -af --no-preserve=ownership,mode" - das wirft fuer JEDE Datei/jeden
# Ordner Owner UND Modus (inkl. Executable-Bit!) weg und setzt sie auf einen
# UMASK-Default zurueck. Nur Pfade, die explizit in profiledef.sh's
# file_permissions-Map stehen, kriegen ihre Rechte danach gezielt per chmod
# zurueck - alles andere (also praktisch der GESAMTE Late-Overlay-Inhalt)
# bliebe sonst ohne +x. Das passiert SCHON bei diesem allerersten Kopieren,
# lange bevor unser customize_airootfs.sh-Restore-Hook ueberhaupt laeuft -
# der kopiert mit "cp -a" danach nur noch treu die bereits kaputten Rechte.
#
# Fix: den kompletten Late-Overlay-Inhalt in EIN tar-Archiv packen. Innerhalb
# eines tar bleiben Dateimodi als Metadaten im Archiv-Datenstrom erhalten -
# UNABHAENGIG davon, mit welchen cp-Flags die (einzelne) .tar-Datei selbst
# kopiert wird. Der Restore-Hook in customize_airootfs.sh packt das Archiv
# danach per "tar -xp" wieder aus und stellt damit die echten Rechte wieder
# her, statt sich auf eine verlustfreie Kopie der losen Dateien zu verlassen.
#
# WICHTIG: --owner=0 --group=0 beim Packen ist Pflicht, nicht optional!
# Ohne das speichert tar die Ownership so, wie die Dateien gerade auf DIESEM
# Rechner daliegen - also dir (dem Host-User, der das Repo besitzt), nicht
# root. "tar -xp" stellt als root im customize_airootfs.sh-Hook exakt diese
# gespeicherte Ownership wieder her und ueberschreibt damit z.B.
# /etc/sudoers.d mit deiner Host-UID statt root:root - sudo verweigert dann
# JEDE sudoers.d-Datei (auch g_wheel) mit "owned by uid 1000, should be 0"
# und jeder non-interaktive sudo-Aufruf (hyprpm-Header-Install,
# grub-theme-sync-Service-Restart, ...) schlaegt lautlos fehl. Vor dem
# Wechsel auf tar (cp --no-preserve=ownership) wurde die Ownership beim
# Kopieren einfach verworfen und lief dadurch implizit auf root hinaus -
# diese Zeile stellt das wieder explizit sicher, ohne die (per tar weiterhin
# korrekt erhaltenen) Modus-/Executable-Bits anzutasten.
LATE_OVERLAY_TAR="${BUILD_PROFILE_DIR}/airootfs/opt/trafktux-late-overlay.tar"
echo "==> Packe Late-Overlay als tar (sonst wirft mkarchiso beim Kopieren alle Rechte weg)..."
tar --owner=0 --group=0 -cpf "${LATE_OVERLAY_TAR}" -C "${LATE_OVERLAY_STAGE}" .
rm -rf "${LATE_OVERLAY_STAGE}"

# WICHTIG: Hier absichtlich KEIN "leere Verzeichnisse aufraeumen" (mehr)!
# "mv" einzelner Dateien loescht ihre (jetzt leeren) Elternverzeichnisse
# ohnehin nie von selbst - die bleiben also automatisch stehen, und genau
# das wird gebraucht: mkarchiso prueft in _make_custom_airootfs() fuer jeden
# file_permissions-Eintrag aus profiledef.sh per "realpath -q", ob der Pfad
# innerhalb des neuen Roots liegt - und zwar SOFORT nach dem Kopieren von
# airootfs/, also NOCH VOR pacstrap und unserem Restore-Hook. "realpath -q"
# verlangt, dass ALLE Elternverzeichnisse existieren (nur die letzte Datei
# selbst darf fehlen) - fehlt ein Elternverzeichnis komplett, liefert
# realpath nichts zurueck, mkarchiso haelt das faelschlich fuer einen
# Pfad-Traversal-Versuch ("Outside of valid path") und bricht SOFORT HART
# ab, statt nur zu warnen. Wuerden wir hier leere Verzeichnisse loeschen
# (wie eine fruehere Version dieses Skripts es tat), wuerde genau das fuer
# jeden file_permissions-Eintrag passieren, dessen Elternordner dadurch
# komplett verschwindet (z.B. etc/sudoers.d/) - mit fataler Folge.
echo "==> ${CONFLICT_COUNT} Datei(en) aus airootfs/ ausgelagert und in ${LATE_OVERLAY_TAR} verpackt"
echo "    (werden erst NACH pacstrap, per customize_airootfs.sh-Hook, per tar -xp zurueckgeholt)."

# customize_airootfs.sh wird NICHT mehr von ISO.sh generiert/ergaenzt -
# das ist jetzt eine normale, von euch im Repo gepflegte Datei. Hier nur
# noch ein Sanity-Check: ohne den Late-Overlay-Restore-Block drin wuerden
# die in Schritt 4/5 ausgelagerten Dateien NIE zurueckkopiert, und
# mkarchiso wuerde ein kaputtes Image bauen (fehlende Configs, fehlende
# User-Daten, etc.) - deshalb hier hart abbrechen statt still weiterzubauen.
CUSTOMIZE_SCRIPT="${BUILD_PROFILE_DIR}/airootfs/root/customize_airootfs.sh"
[[ -f "${CUSTOMIZE_SCRIPT}" ]] || die "${CUSTOMIZE_SCRIPT} fehlt. Muss den Late-Overlay-Restore-Block enthalten (siehe customize_airootfs.sh-Vorlage)."
[[ -x "${CUSTOMIZE_SCRIPT}" ]] || die "${CUSTOMIZE_SCRIPT} ist nicht ausfuehrbar - chmod +x fehlt?"
grep -qF '/opt/trafktux-late-overlay' "${CUSTOMIZE_SCRIPT}" || die "${CUSTOMIZE_SCRIPT} enthaelt keinen Late-Overlay-Restore-Block (Suche nach '/opt/trafktux-late-overlay' schlug fehl). Ohne den baut mkarchiso ein kaputtes Image."
echo "==> ${CUSTOMIZE_SCRIPT} vorhanden, ausfuehrbar und enthaelt den Restore-Block."
echo ""

#############################################################################
# 5/5: ISO bauen (mkarchiso)
#############################################################################
echo "############################################################"
echo "# 5/5: ISO bauen (mkarchiso)"
echo "############################################################"

sudo mkarchiso -v -w "${WORK_DIR}" -C "${TMP_PACMAN_CONF}" -o "${OUT_DIR}" "${BUILD_PROFILE_DIR}"

sudo rm -rf "${WORK_DIR}"

# CLEAN_AUR_REPO_AFTER_BUILD=1: entfernt die lokalen AUR-Paketdateien samt
# Repo-Datenbank aus REPO_DIR, UND den gebauten Hyprland-Plugin-Cache aus
# HYPRPM_STATE_STAGE, NACHDEM mkarchiso beides bereits erfolgreich ins
# Image eingebaut hat - z.B. damit einzelne grosse Pakete (vscodium-bin,
# nvidia-Zeug & Co.) oder der (durchaus auch nicht kleine) Plugin-Cache
# nicht dauerhaft im Git-Repo herumliegen. Betrifft NUR REPO_DIR (Schritt
# 2/5) und HYPRPM_STATE_STAGE (Schritt 1/5); das Optional-Repo (Schritt
# 3/5) bleibt unberuehrt, weil dessen Metapakete winzig sind und ausserdem
# laut dessen eigenem Build-Kommentar (post-ISO von Pamac weiterverwendet
# werden sollen).
# Der naechste Lauf baut beides beim naechsten "Schritt 1/5"/"Schritt 2/5"
# ohnehin neu auf (mkdir -p) - bei geloeschten Dateien greift
# REUSE_EXISTING_AUR_PKGS dann logischerweise nicht mehr, es wird einfach
# alles neu gebaut.
if [[ "${CLEAN_AUR_REPO_AFTER_BUILD}" == "1" ]]; then
    echo "==> Entferne lokale AUR-Paketdateien aus ${REPO_DIR} (CLEAN_AUR_REPO_AFTER_BUILD=1)..."
    rm -f "${REPO_DIR}"/*.pkg.tar.* "${REPO_DIR}"/*.db* "${REPO_DIR}"/*.files* "${REPO_DIR}"/*.old 2>/dev/null || true

    echo "==> Entferne gebauten Hyprland-Plugin-Cache aus ${HYPRPM_STATE_STAGE} (CLEAN_AUR_REPO_AFTER_BUILD=1)..."
    if [[ -n "${HYPRPM_STATE_STAGE:-}" && -d "${HYPRPM_STATE_STAGE}" ]]; then
        rm -rf "${HYPRPM_STATE_STAGE:?}"/* 2>/dev/null || true
    fi
fi

echo ""
echo "############################################################"
echo "Alles fertig! ISO liegt in: ${OUT_DIR}"
echo "############################################################"
