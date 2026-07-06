#!/usr/bin/env bash
# Wird von Calamares (shellprocess@aurinstall) im Ziel-System ausgefuehrt,
# NACH Partitionierung/Basisinstallation, aber VOR dem Aufraeum-Schritt
# (der die passwortlosen sudo/polkit-Regeln wieder entfernt).
#
# Braucht Internet im Chroot (sollte durch networkcfg vorher stehen).
set -euo pipefail

TARGET_USER="${1:-}"

if [[ -z "${TARGET_USER}" ]] || ! id -u "${TARGET_USER}" &>/dev/null; then
    echo "Kein gueltiger Ziel-User uebergeben (' ${TARGET_USER} '), ueberspringe AUR-Installation." >&2
    exit 0
fi

BUILD_DIR="/tmp/aur-build"
mkdir -p "${BUILD_DIR}"
chown "${TARGET_USER}:${TARGET_USER}" "${BUILD_DIR}"

run_as_user() {
    su - "${TARGET_USER}" -c "$1"
}

# yay bauen, falls noch nicht vorhanden
if ! command -v yay &>/dev/null; then
    echo "==> Baue yay..."
    run_as_user "cd ${BUILD_DIR} && rm -rf yay && git clone https://aur.archlinux.org/yay.git && cd yay && makepkg -si --noconfirm"
fi

echo "==> Installiere Zusatzpakete via yay..."
run_as_user "yay -S --noconfirm --needed xwaylandvideobridge pamac-all hyprshade hyprland-minimizer-git wvkbd"

rm -rf "${BUILD_DIR}"
echo "==> AUR-Zusatzpakete fertig installiert."
