> **⚠️ This project is NOT Open Source — please read the LICENSE for details.**
> Copyright © 2026 TrafkHop Entertainment™. All rights reserved.

<div align="center">

# TrafkTux (v0.85)

An Arch-based Hyprland distribution with a maximalist vision and lots of QoL features!

</div>

## Preinstalled Packages

TrafkTux ships with a curated set of core apps out of the box (elementary base/system packages omitted here for brevity):

**Desktop & Shell**
- Hyprland, Waybar, Rofi, Dunst
- Hypridle, Hyprlock, xfdesktop
- wvkbd (on-screen keyboard)

**Everyday Apps**
- Firefox
- VLC Media Player
- Thunar (file manager)
- xfce4-terminal
- Ark (archive manager) + 7-Zip, unrar, zip/unzip
- VSCodium
- Pinta (image editor)
- Fastfetch, khal

**System & Monitoring**
- Htop
- GParted
- pamac (software manager)

**Networking & Security**
- Tailscale, speedtest-cli
- UFW (firewall)
- ClamAV + clamav-unofficial-sigs

**Hardware & Printing**
- OpenRGB
- ddcutil (monitor brightness/DDC control)
- CUPS, HPLIP
- pipewire and all other audio stuff
- bluetooth

**Boot & Display**
- GRUB (custom theme) + Plymouth boot splash
- SDDM (display manager)
- Calamares (installer)

**Fonts**
- Noto Fonts (incl. Emoji & CJK)
- JetBrains Mono Nerd Font

...plus a bunch of other system-related packages and sensible defaults, tuned out of the box.

## Optional Packages

A long list of additional apps that HoppiTex uses and recommends. These are **not preinstalled** — they're just suggestions, installable via a dedicated (still work-in-progress) package installer app.

### Social
- discord *(pacman)*
- ladybird *(aur)*

### Multimedia
- qbittorrent *(pacman)*
- makemkv + makemkv-libaacs *(aur)*
  ```bash
  sudo sg | sudo tee -a /etc/modules-load.d/sg.conf
  ```
- asunder *(pacman)*
- handbrake *(pacman)*

### Work
- python, cmake *(pacman)*
- jetbrains-toolbox *(aur)*
- bambustudio-bin *(aur)*
- kdenlive, audacity, obs-studio, gimp, qalculate-gtk, libreoffice-fresh, lmms *(pacman)*
- davinci-resolve, onlyoffice-bin *(aur)*
- docker & docker-desktop *(pacman & aur)*
  ```bash
  sudo systemctl start docker
  sudo systemctl enable docker
  ```
- **DaVinci Resolve:** download from the official website, then run:
  ```bash
  sudo pacman -S cuda
  sudo mkdir -p /opt/resolve/libs/disabled-libraries
  sudo mv /opt/resolve/libs/libglib-2.0.so* /opt/resolve/libs/disabled-libraries/
  sudo mv /opt/resolve/libs/libgio-2.0.so* /opt/resolve/libs/disabled-libraries/
  sudo mv /opt/resolve/libs/libgmodule-2.0.so* /opt/resolve/libs/disabled-libraries/
  sudo mv /opt/resolve/libs/libgobject-2.0.so* /opt/resolve/libs/disabled-libraries/
  ```

### Drivers
- opentabletdriver, webcamoid, webkitgtk2 *(pacman)*
- cnijfilter2, gnome-network-displays *(aur)*

### Other
- timeshift *(pacman)*
- archiso *(pacman)*
- theclicker *(aur)*
- **MEGA:**
  ```bash
  wget https://mega.nz/linux/repo/Arch_Extra/x86_64/megasync-x86_64.pkg.tar.zst && sudo pacman -U "$PWD/megasync-x86_64.pkg.tar.zst"
  ```

### Games
- steam, mangohud, winetricks wine-staging wine-gecko wine-mono, waydroid, gamemode *(pacman)*
- itch-bin, heroic-games-launcher-bin, lsfg-vk-bin, bedrock-on-linux-bin *(aur)*

**Game launchers / titles:**
- openttd, supertuxkart, prismlauncher *(pacman)*
- cubyz-bin, airshipper, srb2, srb2kart *(aur)*
- [hytale-launcher-bin](https://aur.archlinux.org/packages/hytale-launcher-bin) *(aur)*

**Flatpak:**
```bash
flatpak install flathub org.vinegarhq.Sober
flatpak install flathub org.vinegarhq.Vinegar
```

**Emulators (AUR unless noted):**
- stella, bigpemu-bin, xemu, xenia-edge-bin
- [azaharplus-appimage](https://aur.archlinux.org/pkgbase/azaharplus-appimage)
- 3beans-git, parallel-launcher, cemu, mesen, bsnes-hd, melonds, vita3k-bin, rpcs3-bin, pcsx2-latest-bin, duckstation-preview-latest-bin, shadps4-qtlauncher-bin, kega-fusion, flycast-bin, vbam-wx
- dolphin-emu, mgba-qt, ppsspp *(pacman)*

**Virtualization:**
```bash
sudo pacman -S virt-manager qemu-full libvirt dnsmasq
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt $USER
```

### Learning
```bash
sudo docker run -p 3000:3000 bkimminich/juice-shop
```
Then open `http://localhost:3000/#/`.

### AI
- ollama, ollama-cuda

### OBS
- obs-pipewire-audio-capture-bin *(aur)*

## Features & Theming

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Super + Space` | Open xfce4-terminal |
| `Super + F` | Open Thunar |
| `Super + ^` | Fullscreen (bordered) |
| `Super + Shift + ^` | Fullscreen (exclusive) |
| `Super + Ctrl + ^` | Pin app |
| `Super + Alt + ^` | Minimize app |
| `Super + Tab` | App menu |
| `Super + Escape` | Power menu |
| `Super + Alt + Tab` | Toggle Waybar visibility |
| `Super + PrtSc` | Screenshot → cliphist |
| `Super + Shift + PrtSc` | Screenshot → `~/Screenshots` |
| `Super + WASD` | Switch active window |
| `Super + Shift + WASD` | Resize active window |
| `Super + Ctrl + WASD` | Swap windows |
| `Super + Ctrl + WASDQEX<` | Snap window to one of 8 points (floating mode) |
| `Super + Left-click` | Move window |
| `Super + Right-click` | Resize window |
| `Super + Alt + 1-5` | Switch layout: Dwindle / Master / Scroller / Floating / Monocle |
| `Super + 1-9` | Switch workspace |
| `Super + Shift + 1-9` | Move active window to workspace |

Laptop media keys also work out of the box.

### Performance

TrafkTux isn't the most optimized distribution out there, but it's still lightweight compared to many other options.

**ISO size:** 3.0 GB

**RAM usage**

| State | ~RAM |
|---|---|
| Desktop, no apps open | ~1.10 GB |
| + Firefox (1–5 tabs) | +~1.35 GB |
| + Firefox (many tabs, ~30) | +~1.98 GB |
| + Thunar + xfce4-terminal open | +~0.02 GB |
| + Discord + Steam open | +~1.35 GB |

Idle RAM usage started at ~2 GB and has since been brought down to 1.35 GB, and now to 1.10 GB.

**Comparison**

| System | Idle RAM (approx.) |
|---|---|
| Windows 11 | ~3.5 GB |
| Ubuntu (GNOME) | ~1.5 GB |
| **TrafkTux** | **~1.10 GB** |
| KDE Plasma | ~900 MB |
| Arch Linux with i3 | ~400–500 MB |
| SnowFoxOS | ~350–420 MB |

**Minimum requirements**
- A somewhat modern CPU/GPU (or capable integrated graphics)
- 4 GB RAM
- 8 GB disk space

**Recommended specs**
- A mid-tier CPU/GPU
- 16 GB RAM
- Enough disk space for your needs (we use 1+ TB, but anything over 8 GB should be fine)
- A device with Internet, Bluetooth, etc.

### Security

We take security somewhat seriously — TrafkTux ships hardened by default, out of the box, no setup needed:

- **Firewall (UFW):** enabled by default, `deny` incoming / `allow` outgoing. The only exception is the `waydroid0` interface, which is left fully open (required for Waydroid networking to work at all).
- **DNS-over-TLS:** all DNS queries are encrypted by default via `systemd-resolved`, using Quad9 and Cloudflare (DNSSEC on). This overrides whatever DNS server your router/network hands out via DHCP, so encrypted DNS is enforced on every network you join, not just your home one.
- **Sysctl hardening:** a set of kernel/network/filesystem sysctl settings is applied on every boot (`/etc/sysctl.d/99-trafktux-hardening.conf`), covering kernel info-leak protection (hidden kernel pointers, restricted dmesg, restricted ptrace), network hardening (spoofing/redirect/source-route protection, SYN-flood protection), and filesystem protections (hardlink/fifo/regular-file race condition protection). `fs.protected_symlinks` is intentionally left untouched.
- **Password policy:** every account requires a password of at least 12 characters using at least 3 of the 4 character classes (upper/lowercase/digits/special chars). Enforced both at install time (Calamares) and for any later password change — not configurable or skippable.
- **Tailscale:** built in and ready to go (`tailscaled` runs in the background out of the box) — just log in whenever you want to use it.
- **Malware scanning:** ClamAV + clamtk are preinstalled and kept up to date automatically via `freshclam`, extended with community signatures (`clamav-unofficial-sigs`) for better detection.

### Other Notes

TrafkTux is a very custom arch#hyprland setup.
It uses hyprland as a window manager, but also uses the xfdesktop to
display the wallpaper and to have a desktop!
We have many custom widgets with many integrated features,
but also comes with a few preinstalled apps/features.

TrafkTux is being tested on a Lenovo IdeaPad 5 2-in-1 14AHP9 (model 83DR):
- **CPU:** AMD Ryzen 7 8845HS (16) @ 5.14 GHz
- **GPU:** AMD Radeon 780M Graphics (integrated)
- **Memory:** 13.40 GiB
- **Swap:** 4.00 GiB

TrafkTux is already optimized for laptops, with `tuned` and some extra settings for maximum performance/battery savings.

Avahi is disabled by default due to a networking bug where the OS could saturate the entire network — e.g. when a Nintendo Switch 2 on the same 2.4 GHz WiFi network prevented good online play.

### Hyprland

Hyprland is styled with a light-yellow shadow and a Hyprbar for closing, minimizing, fullscreening, swapping with master, and pinning apps.

We have 5 desktop layouts, switchable with `Super + Alt + 1-5`: Dwindle, Master, Scroller, Floating, Monocle.

Full touchscreen support is included — Rofi menus, Waybar, everything, even an on-screen keyboard. Animations are smooth and snappy, with a bit of wobble.

We also have full system sounds for almost everything! (They can be – of course – turned OFF in the setting. Even we get annoyed with them sometimes – although we like every single one of them!)

### Waybar

Waybar auto-hides itself once the mouse moves away, and can be blocked from showing entirely with `Super + Alt + ^` — useful in many games and programs.

- **Left side:** Rofi app & power menu, workspace overview, "hide all windows" button, configurable app shortcuts.
- **Middle:** switch between open workspaces and apps.
- **Right side:** standardly there are 7 custom Python widgets — Audio, WiFi, Bluetooth, Brightness, Power/System/Time/Calendar/Weather, and Settings — plus an on-screen-keyboard toggle and a tray for background apps (left-click to switch to the app, right-click to send it to the tray, middle-click to close it). The amount of widgets can be altered in the WIP TrafkTux App Editor! We have much more than 7 Widgets.

### Widgets

**1. Audio**
Three tabs:
- **Media:** shows what's currently playing, pause/next/previous buttons, master volume.
- **Devices:** select input and output devices.
- **Apps:** control the volume of individual apps.

**2. Internet**
Select WiFi access points and run a quick speed test.
- **Speed Test tab:** ping, download, and upload with a single start button.
- Ethernet/LAN connections are now shown here too, and you can change the DNS servers of the active connection, with quick presets for Auto, Cloudflare, Google, and Quad9.

**3. Bluetooth**
Connect, disconnect, sync, and delete your Bluetooth devices.

**4. Brightness**
- Control screen brightness, keyboard brightness, and Night Light intensity (WIP).
- Adjust the Night Light's color temperature directly, or turn it on/off.
- Control every RGB device via built-in OpenRGB support, with multi-monitor support.
- Every detected OpenRGB device (keyboard, mouse, motherboard, GPU, RAM, ...) gets its own brightness and color controls.

**5. Battery/System**
- View battery percentage, wattage, and change the energy profile.
- Key system stats: RAM, CPU, GPU, disk size, swap, etc.
- **Gaming Mode:** switches to the performance profile and disables CPU boost.
- **Battery Saver:** disables animations, blur, Hyprglass, and cursor effects.
- A separate System Monitor tab always shows CPU, RAM, swap, disk, and GPU stats, regardless of whether the device has a battery.

**6. Calendar**
Overview of the date, month, and upcoming appointments — add appointments via the "+ Event" button. Weather is displayed above, including a 2-day forecast, with a button to change the weather location. Appointments can now be deleted directly from the day view; the old right-click "quick add" action has been removed in favor of the "+ Event" button.

**7. Settings**
All previously mentioned settings, plus all the other widgets:

**8. Display:** change resolution to (almost) anything — 4:3, 144p, downscale from 8K, whatever you like. Now supports HDR toggling and works properly across multiple monitors, letting you set resolution, refresh rate, scale, and relative position per monitor.

**9. Appearance & Language:** a single toggle switches Light/Dark mode for GTK and Kvantum together, always applied consistently. also cursor animations, shake to find, system sounds (WIP)


### Rofi

Two menus:

**Power Menu** (`Super + Escape`)
- Close apps
- Minimize apps
- Pin apps
- Swap apps with master
- Border fullscreen apps
- Exclusive fullscreen apps
- Change the layout (all 5 of them)
- Lock, suspend, shut down, reboot, or log out
- Exit the menu

**App Menu** (`Super + Tab`)
Has 9 folders you can organize apps into (via a custom app for that), plus a folder showing all apps not sorted into a folder, a folder with all installed apps, and a folder with all installed packages. Each of the 9 main folders supports unlimited nested subfolders.

**Controls for both menus:**
- Arrow keys / WASD — move
- Q / E — switch pages
- Enter / Space / `<` — open folders/apps
- X — leave the folder/menu
- Full touch support included

### xfdesktop

On every startup, a random background image is picked from a folder in `~/.config/hypr/wallpapers`. You can re-randomize it from the brightness menu.

### Calamares

Currently a barebones installer for the base distro. You can choose:
- Name
- Time
- Language
- Drive

Formatting is preconfigured as Btrfs (manual formatting is also supported).

The installer is fully offline — no internet required.

### GRUB

A custom GRUB theme featuring:
- A logo up top
- A selection menu with `os-prober` enabled
- Our recognizable "Trafk Bubbles" for menu items
- some Zauberkraft/Mana floating around
- a vignette

### Plymouth & SDDM
pretty much the same look as grub.
in plymouth a bubble floats from the left to the right as a progressbar (animated)
in sddm in the middle are the users, then the password and on the edges 2 buttons to reboot/shutdown

### Theming

We've themed a lot of apps:
- Dunst
- GTK 2/3/4
- Kvantum
- HyprCursor v1
- HyprLock
- Fastfetch
- Clay Icon Theme (blue swapped for yellow)
- GRUB
- Plymouth
- SDDM

## Roadmap

Still to be themed / done:
- Calamares
- Optional package installer
- Mouse cursor redesign
- Editor for: rofi folders/apps, waybar widgets/shortcuts, autostart apps, standard apps
- System sounds finish and fix
- brightness reramdomize bg repair as hyprpaper was replaced with xfdesktop

## Known Bugs
- The ISO doesn't currently boot — since the distro is still in development, this is a minor issue that will be fixed soon.



### Widgets to implement (this are DEV notes from now on)

* add other methods of connection + other internet security features + vpn integration maybe, but not important + later if released implement snowfoxOSv3's Mesh Connect feature.
* maybe something that makes all apps switch the theme without needing to restart them all.
* make this script non daemon to save on performance and battery and rewrite it in c at the end

#### Security Widgets (from Security-planning session, in detail)

**1. UFW / Firewall panel**
Location: own "Security" tab in Settings, or next to WiFi/Speedtest in the Internet tab.
* Status badge at the top: Active/Inactive, read from `ufw status` (parse for "Status: active/inactive").
* Main toggle: On/Off -> `ufw enable` / `ufw disable`. Needs root, run through polkit (same pattern as our other privileged widget actions), NOT the whole widget running as root.
* Preset profile chips, each toggleable individually, each shows on/off state:
  - "Steam LAN" -> `ufw allow 27031:27036/udp`
  - "KDE Connect" -> `ufw allow 1714:1764/tcp` + `/udp`
  - "Samba/Filesharing" -> `ufw allow samba`
* Scrollable list of all active rules (parsed from `ufw status numbered`), each with a small "X" to delete (`ufw delete <number>`).
* Free-text field for custom port/protocol rules, for power users.
* Optional log viewer tab: last N lines from `/var/log/ufw.log`, filtered on `[UFW BLOCK]`, showing source IP/port/protocol - helps users see what's actually getting blocked without touching a terminal.

**2. DNS extensions (existing DNS picker in Internet tab)**
* New toggle: "Enforce DNS over TLS" (separate from picking which server) - flips `DNSOverTLS=yes` vs `opportunistic` in resolved.conf.
* New toggle: "Hotel/Guest WiFi mode" (allow captive portals) - temporarily disables `ipv4.ignore-auto-dns`/`ipv6.ignore-auto-dns` for the CURRENTLY ACTIVE connection only (`nmcli connection modify <name> ipv4.ignore-auto-dns no ipv6.ignore-auto-dns no` + reconnect), so hotel/airport/office captive portals and internal DNS work again. Does not touch the global default, new networks joined later still get encrypted DNS by default.

**3. Tailscale panel**
Location: Internet tab.
* Status line: "Not connected" / "Connected as `<hostname>`" (from `tailscale status --json`, field `Self.HostName`).
* Main "Enable Tailscale" button: on first click runs `tailscale up`, opens the returned login URL in the default browser (`xdg-open`).
* After login: show own Tailscale IP (`tailscale ip -4`).
* List of other devices in the tailnet (parsed from `tailscale status`), with an online/offline dot per device.
* Separate autostart toggle: enables/disables `tailscaled.service` itself (not the login state) - for people who want it fully out of the boot process.
* "Disconnect" button -> `tailscale logout` / `tailscale down`.
* Later: toggle for "Use as exit node" / route all traffic through Tailscale - has to be an explicit opt-in, never automatic.

**4. Privacy Panel / Hardware Kill-Switches (GrapheneOS-style)**
Location: own "Privacy" tab, or inside Settings.
* Row of toggle switches, one per piece of hardware, each with a status icon (active/blocked):
  - **WiFi:** `rfkill block wifi` / `rfkill unblock wifi`
  - **Bluetooth:** `rfkill block bluetooth` / `rfkill unblock bluetooth`
  - **WWAN/GPS** (laptops with a WWAN modem only, GPS usually sits on the same chip): `rfkill block wwan` / `rfkill unblock wwan`
  - **Camera:** unload the driver module (`rmmod uvcvideo` for most webcams) - hard but reliable, needs a "camera currently in use" error case, module gets reloaded on toggle-off
  - **Microphone:** `pactl set-source-mute @DEFAULT_SOURCE@ 1` / `0` - software mute via PipeWire, not a hardware-level cut (a compromised app with enough privileges could theoretically bypass this, unlike the rfkill-based ones)
* Optional "Lock everything" panic button that flips all toggles at once (meeting-mode style).
* Open design question for whoever builds this: should toggles reset on reboot (session-only) or persist across reboots (needs a udev rule / state file)? GrapheneOS does persistent.

**5. ClamAV panel**
Location: Settings, own "Antivirus" entry, or inside the new Security/Privacy tab.
* Status: last signature update timestamp (from freshclam log), number of known signatures.
* "Update now" button -> manually triggers `sudo freshclam`.
* On-demand scan: folder picker (e.g. defaults to `~/Downloads`) + "Start scan" button -> `clamscan -r --bell -i <path>`, with a progress indicator. Result list of found threats at the end, each with "Delete"/"Ignore" buttons.
* Optional automatic scan toggle: "Auto-scan Downloads" - would need its own systemd path-unit/inotify watcher that runs `clamscan` on newly added files, more work but most useful day to day.
* Quarantine folder view: list of isolated files, with "Delete permanently"/"Restore" buttons.



* The Apps * Editor;
3. you can add/remove autostart applications (but hide the standard ones as they are essential).
2. you can add/remove the shortcuts of apps on the waybar on the "left".
1. you will be able; Rofi launcher menu, it has 9 Folders where you can put apps in. In this third menu, you will be able to drag any app + custom commands in the folders + as many subfolders in subfolders as you want. You can sort by all packages, all apps, unordered apps, custom apps, ordered apps. This will be the main menu to sort all of your apps!
