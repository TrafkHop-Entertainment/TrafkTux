#!/usr/bin/env bash
# Baut die benoetigten Hyprland-Plugins per hyprpm auf DIESEM Rechner
# (hier muss Hyprland laufen, da hyprpm intern "hyprctl version" braucht)
# und kopiert den KOMPLETTEN hyprpm-State (Header + state.toml + .so)
# dauerhaft nach airootfs/opt/trafktux-hyprpm-cache - genau wie
# build-local-repo.sh sein trafktux-repo direkt in airootfs/opt ablegt.
#
# WARUM DER KOMPLETTE STATE UND NICHT NUR DIE .so-DATEIEN:
# Aktuelle hyprpm-Versionen speichern ihren State systemweit unter
# /var/cache/hyprpm/<username>/... (Stand: Hyprland-Quellcode,
# hyprpm/src/core/DataState.cpp). Der Username steckt NUR im Ordnernamen,
# nicht in den state.toml-Dateien selbst. Wird der komplette Ordner beim
# Post-Install-Skript nach /var/cache/hyprpm/<neuer-username> kopiert,
# haelt hyprpm das fuer einen bereits gebauten, gueltigen State - und
# "hyprpm update/enable/disable/list" funktionieren beim Endnutzer ganz
# normal weiter, statt dass die Plugins nur hart per "plugin = /pfad.so"
# reinkopiert waeren.
#
# WICHTIG: Der State ist ABI-gebunden an die exakte Hyprland-Version,
# mit der hier gebaut wird. Diese sollte identisch mit dem Hyprland-
# Paket sein, das packages.x86_64 in die ISO zieht. Am besten also kurz
# vor dem naechsten ISO-Build ausfuehren, ohne dass zwischendurch ein
# Hyprland-Update auf diesem Rechner passiert.

set -euo pipefail

PROFILE_DIR="$(cd "$(dirname "$0")" && pwd)"
HYPRPM_STATE_STAGE="${PROFILE_DIR}/airootfs/opt/trafktux-hyprpm-cache"

mkdir -p "${HYPRPM_STATE_STAGE}"

if ! hyprctl version >/dev/null 2>&1; then
    echo "FEHLER: Es laeuft gerade kein Hyprland." >&2
    echo "Dieses Skript muss INNERHALB einer aktiven Hyprland-Session" >&2
    echo "ausgefuehrt werden, weil hyprpm den laufenden Hyprland-Commit" >&2
    echo "kennen muss, um die passenden Header zu ziehen." >&2
    exit 1
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
)

for repo in "${!REPO_PLUGINS[@]}"; do
    echo "==> hyprpm add ${repo}"
    # hyprpm fragt interaktiv nach Bestaetigung (Trust-Warnung) - via
    # "yes" automatisch bestaetigen. Wenn das Repo schon bekannt ist,
    # meckert hyprpm ggf., das ist unkritisch (|| true).
    yes | hyprpm add "${repo}" || true
done

echo "==> hyprpm update (zieht + baut alle registrierten Plugins auf den aktuellen Stand)"
hyprpm update

for repo in "${!REPO_PLUGINS[@]}"; do
    for name in ${REPO_PLUGINS[$repo]}; do
        echo "==> aktiviere ${name}"
        hyprpm enable "${name}"
    done
done

# Aktuelle hyprpm-Versionen legen ihren State NICHT mehr unter
# ~/.local/share/hyprpm ab, sondern systemweit unter
# /var/cache/hyprpm/<username>/ (root-verwaltet, daher sudo hier).
HYPRPM_CACHE_DIR="/var/cache/hyprpm/$(id -un)"

if [[ ! -d "${HYPRPM_CACHE_DIR}" ]]; then
    echo "FEHLER: ${HYPRPM_CACHE_DIR} existiert nicht." >&2
    echo "Falls hyprpm bei dir einen anderen Pfad verwendet, hier nachschauen" >&2
    echo "und HYPRPM_CACHE_DIR im Skript anpassen:" >&2
    sudo find /var/cache/hyprpm -maxdepth 2 2>&1 >&2 || true
    exit 1
fi

if [[ -z "$(sudo find "${HYPRPM_CACHE_DIR}" -mindepth 2 -maxdepth 2 -name "*.so" -not -path "*/headersRoot/*" -print -quit)" ]]; then
    echo "WARNUNG: Keine .so-Dateien unter ${HYPRPM_CACHE_DIR} gefunden." >&2
    echo "Tatsaechlicher Inhalt zur Fehlersuche:" >&2
    sudo find "${HYPRPM_CACHE_DIR}" -maxdepth 2 2>&1 >&2 || true
    echo "" >&2
    echo "Pruefe auch 'hyprpm list', ob die Plugins ueberhaupt als installiert" >&2
    echo "gelten (build fehlgeschlagen? falscher Name bei hyprpm enable?)." >&2
    exit 1
fi

echo ""
echo "==> Kopiere kompletten hyprpm-State (Header + state.toml + .so) nach ${HYPRPM_STATE_STAGE}"
rm -rf "${HYPRPM_STATE_STAGE}"
mkdir -p "${HYPRPM_STATE_STAGE}"
sudo cp -a "${HYPRPM_CACHE_DIR}/." "${HYPRPM_STATE_STAGE}/"
sudo chown -R "$(id -u):$(id -g)" "${HYPRPM_STATE_STAGE}"

echo ""
echo "Fertig. Kompletter hyprpm-State liegt dauerhaft in: ${HYPRPM_STATE_STAGE}"
echo ""
echo "Das Post-Install-Skript install-hyprpm-plugins.sh (per Calamares"
echo "shellprocess) kopiert diesen State beim Installieren automatisch"
echo "nach /var/cache/hyprpm/<neuer-username> und aktiviert 'hyprpm reload'"
echo "beim ersten Login."
