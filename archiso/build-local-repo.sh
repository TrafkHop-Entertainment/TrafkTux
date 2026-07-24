#!/usr/bin/env bash
# Baut Calamares + die AUR-Zusatzpakete zu einem eigenen lokalen
# pacman-Repo. Das Repo wird direkt in das airootfs/opt/trafktux-repo
# deines Profils abgelegt – es muss später nicht mehr kopiert werden.
#
# Alle Pakete werden hier vorgebaut und landen als fertige .pkg.tar.zst
# im Repo - waehrend der Installation braucht install-aur-packages.sh
# dadurch KEIN Internet mehr, sondern installiert sie rein lokal aus
# dem [trafktux]-Repo (siehe install-aur-packages.sh).

set -euo pipefail

REPO_NAME="trafktux"

# Zielverzeichnis: relativ zum Skriptort unter airootfs/opt/trafktux-repo
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="${SCRIPT_DIR}/airootfs/opt/${REPO_NAME}-repo"

# Temporärer Build-Ordner (kann nach dem Lauf gelöscht werden)
BUILD_DIR="$(pwd)/aur-build"

AUR_PACKAGES=(
  calamares
  xwaylandvideobridge
  pamac-all
  hyprshade
  hyprland-minimizer-git
  wvkbd
  python-openrgb-git
)

mkdir -p "${REPO_DIR}" "${BUILD_DIR}"

# base-devel + git müssen vorhanden sein
sudo pacman -S --needed --noconfirm base-devel git

for pkg in "${AUR_PACKAGES[@]}"; do
    echo "==> Baue ${pkg}..."
    pkg_build_dir="${BUILD_DIR}/${pkg}"
    rm -rf "${pkg_build_dir}"
    git clone "https://aur.archlinux.org/${pkg}.git" "${pkg_build_dir}"
    (
        cd "${pkg_build_dir}"
        # -s: fehlende Build-Abhängigkeiten mit pacman nachziehen
        # -c: Build-Ordner danach aufräumen
        makepkg -sc --noconfirm
        cp -v ./*.pkg.tar.zst "${REPO_DIR}/"
    )
done

echo "==> Erzeuge Repo-Datenbank..."
cd "${REPO_DIR}"
repo-add "${REPO_NAME}.db.tar.gz" ./*.pkg.tar.zst

rm -rf "$BUILD_DIR"

echo ""
echo "Fertig. Repo liegt in: ${REPO_DIR}"
echo "Der Ordner ist bereits am richtigen Platz für dein ISO-Profil."
