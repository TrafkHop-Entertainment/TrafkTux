#!/usr/bin/env bash
# Wird von Calamares (shellprocess@aurinstall) im Ziel-System ausgefuehrt.
#
# Installiert die vorgebauten AUR-Zusatzpakete rein lokal aus dem
# mitgelieferten [trafktux]-Repo (airootfs/opt/trafktux-repo). Braucht
# KEIN Internet und KEIN yay/makepkg mehr, da alle Pakete bereits von
# build-local-repo.sh vorgebaut wurden.
#
# Das [trafktux]-Repo steht NICHT in der dauerhaften /etc/pacman.conf des
# Zielsystems. Es wird hier nur fuer diesen einen pacman-Aufruf ueber eine
# temporaere Config dazugegeben. Dadurch bleibt nach der Installation nichts
# zu bereinigen (das Cleanup loescht nur noch /opt/trafktux-repo + DB).
set -euo pipefail

REPO_DIR="/opt/trafktux-repo"
REPO_NAME="trafktux"
OPT_DIR="/opt/TrafkTuxOptional"
OPT_NAME="TrafkTuxOptional"
SYNC_DIR="/var/lib/pacman/sync"

PACKAGES=(
  xwaylandvideobridge
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
)

if [[ ! -d "${REPO_DIR}" ]]; then
    echo "Kein lokales Repo unter ${REPO_DIR} gefunden, ueberspringe AUR-Installation." >&2
    exit 0
fi

# Die lokalen Repo-Datenbanken direkt einspielen, statt "pacman -Sy"
# aufzurufen. "pacman -Sy" wuerde ALLE konfigurierten Repos (also auch
# core/extra ueber's Internet) synchronisieren wollen und ohne
# Internetverbindung fehlschlagen - das hier bleibt komplett offline.
mkdir -p "${SYNC_DIR}"
cp -f "${REPO_DIR}/${REPO_NAME}.db.tar.gz" "${SYNC_DIR}/${REPO_NAME}.db"

# Optional-Repo: nur die DB einspielen, damit pacman die in /etc/pacman.conf
# eingetragene Datenbank findet und Pamac die Metapakete sofort anzeigt.
if [[ -f "${OPT_DIR}/${OPT_NAME}.db.tar.gz" ]]; then
    cp -f "${OPT_DIR}/${OPT_NAME}.db.tar.gz" "${SYNC_DIR}/${OPT_NAME}.db"
fi

# Temporaere Config = die echte Ziel-Config + [trafktux] ganz hinten
TMP_CONF="$(mktemp)"
trap 'rm -f "${TMP_CONF}"' EXIT
cp -f /etc/pacman.conf "${TMP_CONF}"
cat >> "${TMP_CONF}" <<EOF

[${REPO_NAME}]
SigLevel = Optional TrustAll
Server = file://${REPO_DIR}
EOF

echo "==> Installiere Zusatzpakete aus lokalem Repo (${REPO_NAME})..."
pacman --config "${TMP_CONF}" -S --noconfirm --needed "${PACKAGES[@]}"

echo "==> AUR-Zusatzpakete fertig installiert (offline, aus lokalem Repo)."
