#!/usr/bin/env bash
# Wird von Calamares (shellprocess@hyprpminstall) im Ziel-System ausgefuehrt.
#
# Kopiert den vorgebauten hyprpm-State (Header + state.toml + .so, siehe
# build-hyprland-plugins.sh) vom mitgelieferten Staging-Ordner
# (/opt/trafktux-hyprpm-cache) nach /var/cache/hyprpm/<neuer-username>.
# Danach kann der Nutzer hyprpm ganz normal weiterbenutzen (update,
# enable, disable, list) - ohne beim ersten Login neu bauen zu muessen.
#
# Aufruf durch Calamares: install-hyprpm-plugins.sh '${USER}'
# (Calamares ersetzt ${USER} durch den Benutzernamen, den der Nutzer im
# "Users"-Modul angelegt hat - siehe shellprocess-aurinstall.conf fuer
# das gleiche Muster.)

set -euo pipefail

STAGE_DIR="/opt/trafktux-hyprpm-cache"
NEW_USER="${1:-}"

if [[ -z "${NEW_USER}" ]]; then
    echo "FEHLER: Kein Benutzername uebergeben (Aufruf: $0 <username>)." >&2
    exit 1
fi

if [[ ! -d "${STAGE_DIR}" ]]; then
    echo "Kein hyprpm-Staging-Ordner unter ${STAGE_DIR} gefunden, ueberspringe." >&2
    exit 0
fi

TARGET_DIR="/var/cache/hyprpm/${NEW_USER}"

echo "==> Kopiere hyprpm-State nach ${TARGET_DIR}..."
mkdir -p "${TARGET_DIR}"
cp -a "${STAGE_DIR}/." "${TARGET_DIR}/"

# hyprpm erwartet diesen Ordner root-verwaltet (so legt es ihn auch
# selbst an), unabhaengig vom Zielbenutzer.
chown -R root:root "${TARGET_DIR}"
find "${TARGET_DIR}" -type d -exec chmod 755 {} \;
find "${TARGET_DIR}" -name "*.so" -exec chmod 755 {} \;

# Staging-Ordner wird nicht mehr gebraucht, sobald er im Zielsystem liegt.
rm -rf "${STAGE_DIR}"

echo "==> hyprpm-State fuer '${NEW_USER}' fertig eingerichtet."
echo "    hyprpm update/enable/disable/list funktionieren jetzt normal."
