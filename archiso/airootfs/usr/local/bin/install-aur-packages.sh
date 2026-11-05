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
  # snapd/snapd-glib/libpamac-full/pamac-cli: pamac-all's volle
  # Abhaengigkeitskette (siehe ISO.sh AUR_PACKAGES-Kommentar) - alle vier
  # muessen hier mitgelistet werden, sonst findet "pacman -S pamac-all"
  # sie nicht (dieses [trafktux]-Repo ist die einzige Quelle dafuer, sie
  # sind in keinem offiziellen Repo).
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
  # ckbcomp: reines AUR-Paket (existiert in KEINEM offiziellen Repo - "target
  # not found" beim pacstrap-Versuch ueber alle core/extra/multilib bestaetigt
  # das), muss also hier bleiben und aus dem lokalen trafktux-Repo kommen.
  ckbcomp
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

# Temporaere Config = die echte Ziel-Config + [trafktux], aber VOR
# core/extra/multilib eingefuegt (nicht einfach ans Ende angehaengt).
#
# BUGFIX (siehe Chat): "ckbcomp" existiert sowohl als offizielles
# Arch-Paket (core/extra - Calamares selbst sucht danach, siehe
# "ckbcomp not found" Warnung im Log) ALS AUCH als eigener Eintrag in
# unserer PACKAGES-Liste/trafktux-Repo. Stand [trafktux] hinter
# core/extra/multifa, hat pacman bei diesem Namenskonflikt immer die
# ZUERST gelistete Quelle gewaehlt (also extra statt trafktux) - und
# extra hat im Zielsystem absichtlich keinen Server konfiguriert (100%
# offline), daher "no servers configured for repository: extra". Gleiches
# Muster/gleicher Grund wie bei ISO.sh's "[trafktux] steht ABSICHTLICH vor
# core/extra"-Kommentar fuer den Build-Host - hier fehlte das bisher.
#
# Fix: den [trafktux]-Block per awk VOR die erste Repo-Sektion nach
# [options] einfuegen (statt stumpf anzuhaengen), damit trafktux bei jedem
# Namenskonflikt mit einem offiziellen Paket IMMER gewinnt.
TMP_CONF="$(mktemp)"
trap 'rm -f "${TMP_CONF}"' EXIT
TRAFKTUX_BLOCK="
[${REPO_NAME}]
SigLevel = Optional TrustAll
Server = file://${REPO_DIR}
"
awk -v block="${TRAFKTUX_BLOCK}" '
    /^\[/ && $0 !~ /^\[options\]/ && !inserted { print block; inserted = 1 }
    { print }
' /etc/pacman.conf > "${TMP_CONF}"
# Absicherung, falls /etc/pacman.conf wider Erwarten nur [options] enthielte
grep -q "^\[${REPO_NAME}\]" "${TMP_CONF}" || printf '%s\n' "${TRAFKTUX_BLOCK}" >> "${TMP_CONF}"

echo "==> Installiere Zusatzpakete aus lokalem Repo (${REPO_NAME})..."
# --overwrite: pamac-all/libpamac-full/pamac-cli stammen alle aus demselben
# Upstream-Quellbaum (pamac) und werden als separate AUR-Pakete gebaut -
# dabei landen vereinzelt dieselben generischen Icon-Dateien
# (/usr/share/icons/hicolor/.../system-software-install.svg,
# pamac-tray-*.svg usw.) in mehreren dieser Pakete gleichzeitig. pacman
# bricht normalerweise bei "exists in filesystem"-Konflikten komplett ab,
# obwohl die Datei inhaltlich dieselbe ist (keine echte Inkompatibilitaet,
# nur eine unsaubere Paket-Aufteilung im AUR). --overwrite laesst pacman
# solche Dateien stattdessen einfach ueberschreiben statt abzubrechen.
pacman --config "${TMP_CONF}" -S --noconfirm --needed --overwrite '*' "${PACKAGES[@]}"

echo "==> AUR-Zusatzpakete fertig installiert (offline, aus lokalem Repo)."
