#!/usr/bin/env bash
# Wird von Calamares (shellprocess@aurinstall) im Ziel-System ausgefuehrt.
#
# Installiert die vorgebauten AUR-Zusatzpakete rein lokal aus dem
# mitgelieferten [trafktux]-Repo (airootfs/opt/trafktux-repo). Braucht
# KEIN Internet und KEIN yay/makepkg mehr, da alle Pakete bereits von
# build-local-repo.sh vorgebaut wurden.
set -euo pipefail

REPO_DIR="/opt/trafktux-repo"
REPO_NAME="trafktux"
SYNC_DB="/var/lib/pacman/sync/${REPO_NAME}.db"

PACKAGES=(
  xwaylandvideobridge
  pamac-all
  hyprshade
  hyprland-minimizer-git
  wvkbd
  python-openrgb-git
)

if [[ ! -d "${REPO_DIR}" ]]; then
    echo "Kein lokales Repo unter ${REPO_DIR} gefunden, ueberspringe AUR-Installation." >&2
    exit 0
fi

# Die lokale Repo-Datenbank direkt einspielen, statt "pacman -Sy"
# aufzurufen. "pacman -Sy" wuerde ALLE konfigurierten Repos (also auch
# core/extra ueber's Internet) synchronisieren wollen und ohne
# Internetverbindung fehlschlagen - das hier bleibt komplett offline.
mkdir -p "$(dirname "${SYNC_DB}")"
cp -f "${REPO_DIR}/${REPO_NAME}.db.tar.gz" "${SYNC_DB}"

echo "==> Installiere Zusatzpakete aus lokalem Repo (${REPO_NAME})..."
pacman -S --noconfirm --needed "${PACKAGES[@]}"

echo "==> AUR-Zusatzpakete fertig installiert (offline, aus lokalem Repo)."
