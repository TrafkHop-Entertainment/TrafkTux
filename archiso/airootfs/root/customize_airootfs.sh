#!/usr/bin/env bash
# TrafkTux - customize_airootfs.sh
#
# Offizieller archiso-Hook: laeuft laut mkarchiso-Quellcode
# (_make_customize_airootfs) GARANTIERT nach pacstrap (_make_packages) und
# VOR dem eigentlichen Image-Bau, innerhalb eines "arch-chroot" auf das neue
# Root. Diese Datei wird von ISO.sh NICHT mehr automatisch erzeugt oder
# ergaenzt - sie ist eine normale, von euch gepflegte Datei im Repo.
#
# ISO.sh prueft vor jedem Build nur noch, dass diese Datei existiert,
# ausfuehrbar ist und den Late-Overlay-Restore-Block enthaelt (siehe
# unten) - sonst bricht der Build sofort ab.

set -e

#############################################################################
# 1) Late-Overlay zurueckspielen
#############################################################################
# ISO.sh verschiebt VOR pacstrap den kompletten eigenen airootfs/-Inhalt
# (bis auf ein paar synchron-waehrend-pacstrap benoetigte Ausnahmen, z.B.
# mkinitcpio.conf.d/) nach airootfs/opt/trafktux-late-overlay/, damit pacman
# beim Installieren der Pakete nicht mit "exists in filesystem" abbricht.
# Dieser Block holt den ausgelagerten Inhalt hier, NACH pacstrap, wieder
# zurueck und ueberschreibt damit gezielt nur das, was ohnehin schon
# vorher da war.
#
# WARUM TAR UND NICHT EINFACH "cp -a"? Per mkarchiso-Quellcode verifiziert
# (_make_custom_airootfs() in mkarchiso): mkarchiso kopiert airootfs/ VOR
# diesem Hook IMMER mit "cp -af --no-preserve=ownership,mode" - das wirft
# bei JEDER Datei Owner UND Modus (inkl. Executable-Bit!) weg, auch beim
# late-overlay-Ordner selbst. Ein loses Verzeichnis waere zu diesem
# Zeitpunkt also schon kaputt (keine +x mehr). ISO.sh packt den
# Late-Overlay-Inhalt deshalb VOR dem mkarchiso-Lauf in ein tar-Archiv -
# Dateimodi bleiben als Metadaten IM Archiv erhalten, unabhaengig davon,
# mit welchen cp-Flags die (einzelne) .tar-Datei selbst kopiert wird.
# "tar -xp" hier stellt die echten Rechte beim Auspacken wieder her.
#
# WICHTIG: Dieser Marker-Pfad ("/opt/trafktux-late-overlay") wird von
# ISO.sh per grep gesucht, um sicherzustellen, dass dieser Block hier nicht
# aus Versehen entfernt wurde. Nicht umbenennen/entfernen.
if [[ -f /opt/trafktux-late-overlay.tar ]]; then
    tar -xpf /opt/trafktux-late-overlay.tar -C /
    rm -f /opt/trafktux-late-overlay.tar
fi

#############################################################################
# 2) Live-User anlegen
#############################################################################
# Ohne eigenen User zeigt SDDM beim Booten niemanden zum Einloggen an (root
# ist per Default gesperrt/kein Passwort gesetzt - siehe /etc/shadow aus dem
# linux/base-Paket). Daher hier EXPLIZIT einen "liveuser" anlegen, analog
# zum ueblichen Muster anderer Arch-basierter Live-Distros.
useradd -m -G wheel,storage,optical,audio,video,network,lp,scanner,power -s /usr/bin/bash liveuser

# Hyprland-Plugins (ISO.sh Schritt 1/5): hyprpm sucht seinen State
# systemweit unter /var/cache/hyprpm/<username> (per Quellcode verifiziert,
# DataState::getDataStatePath()) - fuer liveuser muss der vorgebaute Cache
# also dorthin kopiert werden, sonst findet "hyprpm reload" (siehe
# Autostart.lua) beim Boot keine enabled Plugins zum Laden.
if [[ -d /opt/trafktux-hyprpm-cache ]]; then
    mkdir -p /var/cache/hyprpm
    cp -a /opt/trafktux-hyprpm-cache /var/cache/hyprpm/liveuser
    chown -R liveuser:liveuser /var/cache/hyprpm/liveuser

    # WICHTIG: Die *.pc-Dateien im Cache (z.B. headersRoot/share/pkgconfig/
    # hyprland.pc) wurden beim Bauen in Schritt 1/5 auf dem Host-Rechner
    # erzeugt und enthalten deshalb "prefix=/var/cache/hyprpm/<Host-User>/
    # headersRoot/include" fest einprogrammiert - mit DEINEM Benutzernamen,
    # nicht "liveuser". hyprpm (genauer: headersValid() in PluginManager.cpp)
    # fragt beim Reload per "pkgconf --cflags hyprland" genau diesen Pfad ab
    # und versucht darueber <prefix>/hyprland/src/version.h zu lesen. Zeigt
    # der Pfad auf den (auf der ISO nicht existierenden) Host-Usernamen,
    # schlaegt das lesen fehl -> HEADERS_CORRUPTED -> "hyprpm reload" meldet
    # pauschal "headers are not up-to-date, please run hyprpm update.",
    # obwohl Commit-Hash und ABI in Wahrheit exakt passen. Daher hier den
    # Pfad auf den tatsaechlichen Ziel-User "liveuser" umschreiben.
    find /var/cache/hyprpm/liveuser -name '*.pc' -exec \
        sed -i "s#^prefix=.*#prefix=/var/cache/hyprpm/liveuser/headersRoot/include#" {} \;
fi

# Kein Passwort fuer liveuser (direktes Einloggen im Live-System). PAM
# erlaubt leere Passwoerter nur, wenn "nullok" in den relevanten
# /etc/pam.d/*-Dateien gesetzt ist - pruefen/ergaenzen, falls Login trotz
# "passwd -d" ein Passwort verlangt.
passwd -d liveuser

#############################################################################
# 3) Services aktivieren
#############################################################################
# "systemctl enable" legt nur Symlinks unter /etc/systemd/system/*.wants/
# an - die Unit-Dateien selbst kommen aus den Paketen (nicht aus airootfs/),
# die Reihenfolge zu Block 1) oben spielt also keine Rolle.
systemctl enable NetworkManager.service
systemctl enable sddm.service