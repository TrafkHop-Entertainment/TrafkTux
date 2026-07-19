#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="TrafkTux"
iso_label="TrafkTux_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="TrafkHop Entertainment <https://trafkhop-entertainment.github.io/TrafkSite>"
iso_application="TrafkTux Live ISO / Rescue ISO"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')

# UEFI per GRUB + BIOS per Syslinux (archiso bietet Legacy-BIOS nur ueber
# Syslinux an, nicht ueber GRUB - daher die Mischung aus beidem)
bootmodes=('bios.syslinux'
           'uefi.grub')

pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'xz' '-Xbcj' 'x86' '-b' '1M' '-Xdict-size' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')

file_permissions=(
  # Live-User Setup
  ["/etc/sudoers.d/99-liveuser"]="0:0:440"
  ["/etc/pacman.d/hooks/liveuser.hook"]="0:0:644"
  ["/usr/local/bin/create-liveuser.sh"]="0:0:755"

  ["/usr/local/bin/install-aur-packages.sh"]="0:0:755"

  # Calamares-Starter + Skripte
  ["/usr/local/bin/Installation_guide"]="0:0:755"

  # deine Hypr-Skripte (unveraendert)
  ["/etc/skel/.config/hypr/layout_switcher.sh"]="0:0:755"
  ["/etc/skel/.config/hypr/random_wallpaper.sh"]="0:0:755"
  ["/etc/skel/.config/hypr/TrafkCursor_Build/build_theme.sh"]="0:0:755"
)
