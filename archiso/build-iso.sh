#!/usr/bin/env bash
# Baut das fertige TrafkTux-ISO aus dem archiso-Profil im aktuellen Ordner.
# Muss mit sudo/root laufen. archiso-Paket muss auf der Build-Maschine
# installiert sein (sudo pacman -S archiso).

set -euo pipefail

PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${PROFILE_DIR}/work"
OUT_DIR="${PROFILE_DIR}"

if [[ $EUID -ne 0 ]]; then
    echo "Bitte mit sudo ausfuehren: sudo ./build-iso.sh" >&2
    exit 1
fi

if ! command -v mkarchiso &>/dev/null; then
    echo "mkarchiso nicht gefunden. Installiere das archiso-Paket zuerst:" >&2
    echo "  pacman -S --needed archiso" >&2
    exit 1
fi

mkdir -p "${WORK_DIR}" "${OUT_DIR}"

# Lokales trafktux-Repo liegt im Profil selbst (airootfs/opt/trafktux-repo).
# pacman.conf braucht dafuer einen absoluten Pfad (file://...), der aber je
# nach Mount-Punkt/Laufwerk variieren kann. Deshalb wird hier eine temporaere
# pacman.conf erzeugt, in der der Platzhalter @@TRAFKTUX_REPO_DIR@@ durch den
# tatsaechlichen, aktuellen Pfad ersetzt wird. So muss NICHTS auf der
# Hauptplatte (z.B. /opt/trafktux-repo) angelegt oder verlinkt werden.
REPO_DIR="${PROFILE_DIR}/airootfs/opt/trafktux-repo"

if [[ ! -f "${REPO_DIR}/trafktux.db" ]]; then
    echo "FEHLER: ${REPO_DIR}/trafktux.db nicht gefunden." >&2
    echo "Bitte zuerst ./build-local-repo.sh ausfuehren." >&2
    exit 1
fi

# Hinweis (keine harte Voraussetzung): der komplette hyprpm-State liegt,
# falls schonmal gebaut, dauerhaft unter airootfs/opt/trafktux-hyprpm-cache
# und wird beim Post-Install-Schritt (install-hyprpm-plugins.sh) auf den
# neuen Benutzer uebertragen. Braucht hier keine Sonderbehandlung, mkarchiso
# packt den Ordner einfach mit airootfs mit ein.
HYPRPM_CACHE_STAGE="${PROFILE_DIR}/airootfs/opt/trafktux-hyprpm-cache"
if [[ ! -d "${HYPRPM_CACHE_STAGE}" ]] || [[ -z "$(ls -A "${HYPRPM_CACHE_STAGE}" 2>/dev/null)" ]]; then
    echo "HINWEIS: ${HYPRPM_CACHE_STAGE} ist leer oder existiert nicht -" >&2
    echo "ISO wird ohne Hyprland-Plugins gebaut. Falls gewuenscht, vorher" >&2
    echo "./build-hyprland-plugins.sh ausfuehren." >&2
fi

TMP_PACMAN_CONF="$(mktemp)"
trap 'rm -f "${TMP_PACMAN_CONF}"' EXIT
sed "s#@@TRAFKTUX_REPO_DIR@@#${REPO_DIR}#g" "${PROFILE_DIR}/pacman.conf" > "${TMP_PACMAN_CONF}"

echo "DEBUG: REPO_DIR=${REPO_DIR}"
echo "DEBUG: trafktux-Zeile in temp pacman.conf:"
grep -A2 '\[trafktux\]' "${TMP_PACMAN_CONF}"

mkarchiso -v -w "${WORK_DIR}" -C "${TMP_PACMAN_CONF}" -o "${OUT_DIR}" "${PROFILE_DIR}"

rm -rf "${WORK_DIR}"
echo ""
echo "Fertig! ISO liegt in: ${OUT_DIR}"
