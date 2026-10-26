#!/usr/bin/env bash
# LiveInstallerShortcut.sh
#
# Legt im LIVE-System (liveuser) einen Verknuepfungs-Eintrag fuer den
# TrafkTux-Installer an:
#   1) auf dem Desktop (~/Desktop)
#   2) im Anwendungsmenue (~/.local/share/applications) - wird von
#      TrafkTuxLauncher automatisch gescannt (siehe TrafkTuxLauncher.c,
#      collect_desktop_apps_impl()/walk_desktop_files() - jedes gueltige
#      *.desktop unter XDG_DATA_DIRS/applications wird gefunden, OHNE
#      dass Usermenu.json angefasst werden muss).
#
# WICHTIG, LIVE-ONLY: Darf NUR im Live-Medium laufen, NIE auf einem fertig
# installierten System - sonst haette JEDES TrafkTux-System dauerhaft
# einen "TrafkTux installieren"-Eintrag.
# Guard 1: archiso meldet den Live-Benutzer IMMER als "liveuser" an (fest
#          in archiso selbst, nicht TrafkTux-spezifisch) - ein fertig
#          installiertes System hat diesen Benutzernamen nie.
# Guard 2 (zusaetzliche Absicherung): /run/archiso/bootmnt ist nur im
#          Live-Medium gemountet (das ISO9660/FAT-Medium selbst).
#
# AUFRAEUMEN nach erfolgreicher Installation: siehe settings.conf, neue
# Instanz shellprocess@liveshortcutcleanup (dontChroot: true - laeuft
# also auf GENAU diesem Live-System, nicht im chroot des Zielsystems).
# Calamares bricht seine exec-Sequenz beim ersten fehlschlagenden Job ab,
# d.h. dieser Cleanup-Job laeuft nur, wenn ALLE Jobs davor (inkl. der
# eigentlichen Installation) erfolgreich waren - loescht dann exakt die
# beiden hier angelegten Dateien aus dem Home-Verzeichnis von liveuser
# wieder. Schlaegt die Installation fehl, bleibt die Verknuepfung fuer
# einen erneuten Versuch einfach stehen.
set -euo pipefail

[[ "${USER:-}" == "liveuser" ]] || exit 0
mountpoint -q /run/archiso/bootmnt || exit 0

# Icon: airootfs/usr/share/pixmaps/trafktux-installer.png (liegt direkt im
# Projekt, wird 1:1 mit auf die ISO kopiert - absoluter Pfad in Icon= statt
# nur eines Namens, damit TrafkTuxLauncher.c's load_icon_pixbuf() ihn ueber
# den ersten Zweig (g_path_is_absolute()) garantiert findet, unabhaengig
# vom GTK-Icon-Theme-Cache.
ICON="/usr/share/pixmaps/trafktux-installer.png"
DESKTOP_DIR="${HOME}/Desktop"
APPS_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE_NAME="trafktux-installer.desktop"

mkdir -p "${DESKTOP_DIR}" "${APPS_DIR}"

TMP_DESKTOP_FILE="$(mktemp)"
cat > "${TMP_DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=TrafkTux installieren
Comment=TrafkTux auf diesem Rechner installieren
Exec=sudo --preserve-env=WAYLAND_DISPLAY,XDG_RUNTIME_DIR env QT_QPA_PLATFORM=wayland calamares
Icon=${ICON}
Terminal=false
Categories=System;
EOF

for target_dir in "${DESKTOP_DIR}" "${APPS_DIR}"; do
    install -m 0755 "${TMP_DESKTOP_FILE}" "${target_dir}/${DESKTOP_FILE_NAME}"
    # "Trusted"-Flag setzen - ohne das zeigt z.B. xfdesktop/ein GTK-
    # Dateimanager beim Doppelklick erst eine "Vertrauen?"-Nachfrage statt
    # direkt zu starten (GIO-Metadaten-Attribut, GTK/XFCE-Standard).
    gio set "${target_dir}/${DESKTOP_FILE_NAME}" "metadata::trusted" true 2>/dev/null || true
done

rm -f "${TMP_DESKTOP_FILE}"
