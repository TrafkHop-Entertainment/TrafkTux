#!/usr/bin/env bash
# Baut das fertige TrafkTux-ISO aus dem archiso-Profil im aktuellen Ordner.
# Muss mit sudo/root laufen. archiso-Paket muss auf der Build-Maschine
# installiert sein (sudo pacman -S archiso).

set -euo pipefail

PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${PROFILE_DIR}/work"
OUT_DIR="${PROFILE_DIR}/out"

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

mkarchiso -v -w "${WORK_DIR}" -o "${OUT_DIR}" "${PROFILE_DIR}"

echo ""
echo "Fertig! ISO liegt in: ${OUT_DIR}"
