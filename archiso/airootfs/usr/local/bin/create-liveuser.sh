#!/usr/bin/env bash
# Wird einmalig ueber den pacman-hook liveuser.hook waehrend des ISO-Baus ausgefuehrt.
# Legt den Live-User "liveuser" an (kein Passwort noetig, Autologin uebernimmt das).
set -euo pipefail

USERNAME="liveuser"

if ! id -u "${USERNAME}" &>/dev/null; then
    useradd -m \
        -s /bin/bash \
        -G wheel,seat,video,audio,input,storage,optical,network,power,rfkill,lp \
        "${USERNAME}"
    # kein Passwort -> Autologin macht den Login, Passwort waere fuer sudo eh nicht
    # noetig da wheel in /etc/sudoers.d/99-liveuser NOPASSWD bekommt
    passwd -d "${USERNAME}"
fi

# /etc/skel wurde schon beim useradd -m kopiert, aber falls das Overlay danach
# noch was reingelegt hat, Rechte nochmal sauberziehen:
chown -R "${USERNAME}:${USERNAME}" "/home/${USERNAME}"
