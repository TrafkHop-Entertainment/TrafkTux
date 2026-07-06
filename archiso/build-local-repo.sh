#!/usr/bin/env bash
# Baut Calamares (aus dem AUR) zu einem eigenen lokalen pacman-Repo.
# Laeuft auf einer NORMALEN Arch-Maschine (nicht in mkarchiso!).
#
# Alle anderen AUR-Pakete (xwaylandvideobridge, pamac-all, hyprshade,
# hyprland-minimizer-git, wvkbd) werden NICHT mehr hier vorgebaut -
# die installiert Calamares selbst live per yay waehrend der
# Installation (siehe install-aur-packages.sh).
#
# Ergebnis landet in ./trafktux-repo/ - diesen Ordner packst du
# anschliessend 1:1 nach airootfs/opt/trafktux-repo/ in dein Profil,
# damit er auch im fertig installierten System (via unpackfs) verfuegbar
# bleibt.

set -euo pipefail

REPO_NAME="trafktux"
REPO_DIR="$(pwd)/trafktux-repo"
BUILD_DIR="$(pwd)/aur-build"

AUR_PACKAGES=(
  calamares
)

mkdir -p "${REPO_DIR}" "${BUILD_DIR}"

# base-devel + git muessen vorhanden sein
sudo pacman -S --needed --noconfirm base-devel git

for pkg in "${AUR_PACKAGES[@]}"; do
    echo "==> Baue ${pkg}..."
    pkg_build_dir="${BUILD_DIR}/${pkg}"
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

echo "==> Erzeuge Repo-Datenbank..."
cd "${REPO_DIR}"
repo-add "${REPO_NAME}.db.tar.gz" ./*.pkg.tar.zst

echo ""
echo "Fertig. Repo liegt in: ${REPO_DIR}"
echo "Naechste Schritte:"
echo "  1. Ordner nach airootfs/opt/trafktux-repo/ kopieren"
echo "  2. In deiner pacman.conf folgendes ergaenzen (siehe pacman.conf.snippet):"
echo "       [${REPO_NAME}]"
echo "       SigLevel = Optional TrustAll"
echo "       Server = file:///opt/trafktux-repo"
