# TrafkTux v0.85

*"Unique Creativity meets QOL and Streamlining"*

> **This project is NOT Open Source — read the LICENSE for more!**
> Copyright © 2026 TrafkHop Entertainment. All rights reserved.

## About

**TrafkTux** is an **Arch + Hyprland** based Linux distribution with the focus of being an easy to use and streamlined system.

It prides itself on its very distinct look and feel. It is also quite user friendly!

TrafkTux is a **Wayland** based system, which means better security, HDR compatibility and more.

TrafkTux has a fully functional desktop environment with background images, functional desktop icons and interactions, an app launcher, settings menus and more! (more under Software Stack and other sections below)

It also comes with many preinstalled programs for the best out-of-box experience!

## Installation

TrafkTux can be installed via an ISO file.

**Download:** DISTROISNOTAVAILABEASOFTHISMOMENT.htmllink

1. Download the ISO via our link!
2. Download Fedora Media Writer and burn the ISO onto a media of your choosing
3. Insert the media into your computer
4. Start it and boot into the installer
5. Complete the installation and reboot

Now you have successfully installed the OS!

**Installation tutorial on our YT channel:** INSERTLINKHERE

## Performance & Requirements

TrafkTux may not be the sleekest of distros out there, buuut it is still way sleeker than some other operating systems!

> **Note:** TrafkTux does not support SecureBoot at the moment.

TrafkTux is already optimized for laptops, with tuned and some extra settings for maximum performance/battery savings.

Avahi is disabled by default due to a networking bug where the OS could saturate the entire network – e.g. a Nintendo Switch 2 on the same 2.4GHz WiFi network prevented good online play.

### Performance

**ISO size:** 3.0 GB

The system uses:

| State | ~RAM |
|---|---|
| Idle | 1.15 GB |
| + Firefox (1-5 Tabs) | +1-5 GB |
| + Firefox (viele Tabs, ~30) | +~1.98 GB |
| + Terminal or File Manager | +0.1 GB |
| + Discord + Steam offen | +~1.35 GB |

Idle RAM usage started at ~2 GB and has since been brought down to 1.35 GB, and now to 1.15 GB.

**Background apps** include *(they do not impact performance)*:
- Swaync (Notifications)
- xfdesktop
- WaybarAutohide
- WidgetsHelper

### Comparison

| System | Idle RAM (approx.) |
|---|---|
| Windows 11 | ~3.5 GB |
| Ubuntu (GNOME) | ~1.5 GB |
| **TrafkTux** | **~1.15 GB** |
| KDE Plasma | ~900 MB |
| Arch Linux with i3 | ~400-500 MB |

### Minimum Requirements

We have not tested TrafkTux on many machines. Therefore this is only an estimation:

- A CPU + GPU less than 20 years old
- 2 GB of RAM
- 4 GB of storage space

This should be enough to run the OS – you will not run any browser though.

### Usable Specs

- Low-mid-tier CPU + GPU
- 8 GB RAM
- ≥ 64 GB of storage

With something like this you can use the system pretty well.

### Recommended Specs

- Mid-tier+ CPU + GPU
- 12+ GB of RAM
- 1+ TB of storage

This is what HoppiTex uses.

### Test Machine

TrafkTux is currently being tested on a Lenovo IdeaPad 5 2-in-1 14AHP9 (model 83DR):

- **CPU:** AMD Ryzen 7 8845HS (16) @ 5.14 GHz
- **GPU:** AMD Radeon 780M Graphics (integrated)
- **Memory:** 13.40 GiB
- **Swap:** 4.00 GiB

## Update

As it is Arch based, it constantly updates! But as system updates are separate from normal updates, you can manually update the system separately from everything else – which is also a good thing, as a system update will **RESET** any changes you as a user made.

As this is the case, we often refer to TrafkTux as an immutable system – not that you cannot change it, no, it really is just not advised and recommended in any way.

We would also like to explain *why* we use Arch and its update rolls:

As you may or may not know, Arch Linux updates all the time with the newest versions. This has the disadvantage that sometimes updates break certain apps. We think that **this is not a problem**!

TrafkTux is used by HoppiTex, the sole maintainer, and if something breaks, he will fix it soon. And the **advantage** of rolling releases is that you have the newest programs and features, which you do not get on distributions like Debian or Fedora.

## Shortcuts

The distro is designed in a way that:

1. Everything can be used with a mouse or touchpad
2. Everything is easier with our keyboard shortcuts

### Shortcut List

Our shortcuts are designed with a gamer in mind. Everything can be done with the left hand, keeping the right hand free for the mouse, which also is used a lot!

| Shortcut | Action |
|---|---|
| Super + Space | Open Terminal |
| Super + F | Open Filemanager |
| Super + Tab | Open App-Launcher |
| Super + Escape | Open Power Menu |
| Super + ^ | Fullscreen (bordered) |
| Super + Shift + ^ | Fullscreen (exclusive) |
| Super + Alt + ^ | Minimize App |
| Super + Ctrl + ^ | Pin App (Picture-in-Picture) |
| Super + Alt + Tab | Toggle Waybar visibility |
| Super + Print | Screenshot (region → clipboard) |
| Super + Shift + Print | Screenshot (region → save as PNG) |
| Super + H | Hide/show all Windows |
| Super + WASD | Switch active Window |
| Super + Shift + WASD | Resize active Window |
| Super + Ctrl + WASD | Swap Windows |
| Super + Ctrl + QEX< | Snap Window to one of the 4 corners (Floating mode) |
| Super + Left-click | Move Window |
| Super + Right-click | Resize Window |
| Super + Alt + 1-5 | Switch Layout: Master / Dwindle / Scroller / Floating / Monocle |
| Super + 1-9 | Switch Workspace |
| Super + Shift + 1-9 | Move active Window to Workspace |
| Super + Ctrl + Tab | Workspace Overview (Hyprexpo) |

Laptop media keys (Volume, Brightness, Play/Pause/Next/Prev) also work out of the box.

### Touchscreen

TrafkTux is also fully touchscreen compatible! Everything after the user login can be done without a keyboard (there is an on-screen keyboard for after the login to type stuff).

## Gaming

We have gamescope and wine preinstalled! We also have a custom script that puts any launched wine game into gamescope, so that all games – be it Crazy Chicken, Austin Cooper S Racing, Road Rash, or other old games – can run in a scalable windowed mode the same way any other program can!

## Security

TrafkTux comes secure out of the box! We take security somewhat seriously – everything below is enabled by default, no setup needed:

- **Firewall (UFW):** enabled by default, deny incoming / allow outgoing. The only exception is the waydroid0 interface, which is left fully open (needed for Waydroid networking to even work).
- **DNS-over-TLS:** all DNS queries are encrypted by default via systemd-resolved, using Quad9 and Cloudflare (DNSSEC on). This overrides whatever DNS server your router hands out, so encrypted DNS is enforced on every network you join – not just your home one.
- **Sysctl hardening:** a bunch of kernel/network/filesystem settings get applied on every boot (`/etc/sysctl.d/99-trafktux-hardening.conf`):

  **Kernel info-leak protection:**
  - `kernel.kptr_restrict = 2` – hides kernel pointers in /proc from normal users, makes exploits that rely on memory addresses much harder to pull off
  - `kernel.dmesg_restrict = 1` – hides the kernel log ringbuffer (dmesg) from normal users, readable with sudo/root only
  - `kernel.yama.ptrace_scope = 1` – only direct parent-child processes are allowed to ptrace attach to each other (the Ubuntu-standard compromise value, not 2 or 3, so normal debugging/profiling doesn't get fully blocked)
  - `kernel.randomize_va_space = 2` – ASLR explicitly pinned to full strength (already Arch's default, but locked in here in case any package/tool ever lowers it)

  **Network hardening:**
  - `net.ipv4.conf.all/default.rp_filter = 1` – strict Reverse Path Filtering, protects against IP spoofing
  - `net.ipv4.tcp_syncookies = 1` – SYN cookies, protection against SYN-flood/DoS attacks
  - `net.ipv4/ipv6.conf.all/default.accept_redirects = 0` – doesn't accept ICMP redirects, protects against MITM attacks on the local network (e.g. hotel/guest WiFi)
  - `net.ipv4.conf.all/default.send_redirects = 0` – doesn't send ICMP redirects itself either (only relevant if the machine ever acts as a gateway/router for other devices)
  - `net.ipv4/ipv6.conf.all/default.accept_source_route = 0` – rejects source routing, an old IP option that's barely used legitimately today and can be abused for spoofing/routing attacks

  **Filesystem protection:**
  - `fs.protected_hardlinks = 1` – normal users can't create hardlinks to files they don't actually have write access to (e.g. setuid binaries)
  - `fs.protected_fifos = 2` / `fs.protected_regular = 2` – protects FIFOs/regular files in world-writable+sticky directories (e.g. /tmp); level 2 is the value recommended by the kernel devs themselves, protects against race-condition tricks when writing files
  - (`fs.protected_symlinks` is intentionally left untouched – that was our own decision)

- **Password policy:** every account needs a password of at least 12 characters using at least 3 of the 4 character classes (upper/lowercase/digits/special chars). Enforced at install time AND for any later password change – not skippable.
- **Tailscale:** built in and ready to go, just log in whenever you want to use it.
- **Malware scanning:** ClamAV + clamtk are preinstalled and kept up to date automatically via freshclam, extended with community signatures (clamav-unofficial-sigs) for even better detection.

## Software Stack

TrafkTux comes preinstalled with a bunch of software while still not overdoing it:

### Preinstalled Apps

**Desktop & Shell**
- Hyprland, Waybar, Rofi, Swaync
- Hypridle, Hyprlock, xfdesktop
- wvkbd (on-screen keyboard)

**Everyday Apps**
- Firefox
- VLC Media Player
- Thunar (file manager) + xfce4-terminal
- Ark (archive manager) + 7-Zip, unrar, zip/unzip
- VSCodium
- Viewnior
- Fastfetch, khal

**System & Monitoring**
- Htop
- gnome-disk-utility, Fedora Media Writer
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
- Bluetooth
- Canon printer drivers
- gnome-network-displays

**Boot & Display**
- GRUB + Plymouth
- SDDM
- Calamares (installer)

**Fonts**
- Noto Fonts (incl. Emoji & CJK)
- JetBrains Mono Nerd Font

**Gaming**
- mangohud
- winetricks & wine-staging & wine-gecko
- gamemode

...plus a bunch of other system-related packages and sensible defaults, tuned out of the box.

As you can see, TrafkTux throws a bunch of unrelated packages together and creates something truly unique! An Arch + Hyprland setup which uses the XFCE desktop + file manager + terminal, has many custom programs/scripts, but also heavily relies on 3rd-party software.

### Optional Packages

Those apps are **NOT PREINSTALLED** and can be installed via the App Settings menu!

**Social**
- discord *(pacman)*
- ladybird *(aur)*

**Multimedia**
- qbittorrent *(pacman)*
- makemkv + makemkv-libaacs *(aur)*
  ```bash
  sudo sg | sudo tee -a /etc/modules-load.d/sg.conf
  ```
- asunder *(pacman)*
- handbrake *(pacman)*

**Work**
- jetbrains-toolbox *(aur)*
- bambustudio-bin *(aur)*
- audacity, obs-studio, gimp, qalculate-gtk, libreoffice-fresh, lmms *(pacman)*
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

**Drivers**
- opentabletdriver, webcamoid

**Other**
- timeshift *(pacman)*
- archiso *(pacman)*
- theclicker *(aur)*
- **MEGA:**
  ```bash
  wget https://mega.nz/linux/repo/Arch_Extra/x86_64/megasync-x86_64.pkg.tar.zst && sudo pacman -U "$PWD/megasync-x86_64.pkg.tar.zst"
  ```

**Games**
- steam, waydroid *(pacman)*
- itch-bin, heroic-games-launcher-bin, lsfg-vk-bin, bedrock-on-linux-bin *(aur)*

**Game launchers / titles:**
- openttd, supertuxkart, prismlauncher *(pacman)*
- cubyz-bin, airshipper, srb2, srb2kart *(aur)*
- [hytale-launcher-bin (aur)](https://aur.archlinux.org/packages/hytale-launcher-bin)

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

**Learning**
```bash
sudo docker run -p 3000:3000 bkimminich/juice-shop
```
Then open http://localhost:3000/#/.

**AI**
- ollama, ollama-cuda

**OBS**
- obs-pipewire-audio-capture-bin *(aur)*

## Customisation

TrafkTux is **HEAVILY** customized. We do not have a "TrafkTux Desktop" app or a "TrafkTux App Selector" app in a normal Linux sense – everything is a part of TrafkTux. Without our customisation, it is just a secure Arch installation. So you will not be able to install one of our features on your Linux desktop, as everything works together in our distribution.

### Hyprland

We have a strongly customized Hyprland setup: our windows have a glow in the colour `#fff495` and a hyprbar in the same colour.

TrafkTux has **5** layouts that are all fully functional and integrated: Dwindle, Master, Floating, Monocle and Scroller! Our favourites are Scroller and Floating. Floating also has window snapping!

The Hyprbar has 5 buttons: Close, Minimize, BorderFullscreen, SwitchWithMaster and Pin.

We also have the Hyprglass plugin that makes the windows look a bit like they are made out of glass! Also included: **Hyprexpo** for a workspace overview, **Hyprbars/Hyprfocus**, and full **touchscreen support** across all of it.

We also have full system sounds for almost everything! (They can, of course, be turned off in the settings. Even we get annoyed with them sometimes – although we like every single one of them!)

**Minimizing:** we have a plugin called Hyprland Minimizer which allows windows to be minimized and put into a tray on our waybar for reopening!

### Cursor

We have our own cursor that works EVERYWHERE*! We also use the Hyprland plugin Dynamic Cursors to make the cursor more dynamic – it leans in the movement direction, for example.

### Icon Theme

We use a recoloured theme called "Clay"! *(blue swapped for yellow)*

### GTK, Kvantum, Theming

We have completely custom themes for GTK2-3-4 and Kvantum to ensure consistent looks across almost all applications (excluding apps like Firefox, Steam, and programs with custom colours). They are all heavily altered versions of popular themes edited to fit our style!

We've also themed: Swaync, HyprCursor, HyprLock, Fastfetch, GRUB, Plymouth, SDDM and more!

### Waybar

We have a waybar that – like in Windows/KDE Plasma – hides itself as long as the mouse is not at the bottom of the screen(s)! To completely disable the waybar, press Super+Alt+Tab – this is very useful for many, many games!

- **Left:** buttons for the App Launcher, the Power Menu, the Workspace Overview, and a hide-all-windows button
- **Middle:** the workspace and app overview, which shows all open apps
- **Right:** our widgets – pre-located on the bar are:
  - Audio
  - Internet
  - Bluetooth
  - Brightness
  - Battery/System Monitor
  - A tray for hidden apps (not part of the widgets)
  - On-screen keyboard
  - Calendar + Weather
  - Settings – access to ALL widgets

And with the Hyprland plugin Hyprgrass it also has touch support – just swipe your finger from the bottom of the screen up and there it is!

### Dunst

A basic notification service that is also styled to resemble a Trafkbubble.

### xfdesktop

The desktop shows a randomly selected image, which you can reroll in the Brightness widget. Also, the files in your Desktop folder are shown here – and like any desktop, you can interact with the files.

### Thunar

We have added an "Open Terminal Here" button and right-click menu.

### Calamares

Currently a barebones installer for the base distro. You can choose:
- Name
- Time
- Language
- Drive

Formatting is preconfigured as Btrfs (manual formatting is also supported). The installer is fully offline – no internet required.

### GRUB

A custom GRUB theme featuring:
- A logo up top
- A selection menu with os-prober enabled
- Our recognizable "Trafk Bubbles" for menu items
- Some Zauberkraft/Mana floating around
- A vignette

### Plymouth & SDDM

Pretty much the same look as GRUB.

In Plymouth, a bubble floats from the left to the right as an (animated) progress bar.

In SDDM, the users are in the middle, then the password, and on the edges 2 buttons to reboot/shutdown.

### Rofi

We have **2 custom** Rofi menus:

**App Launcher**

It is a grid of 12 TrafkBubbles that act as folders/buttons. In the root folder there are 12 folders in a 4x3 grid and a 5th column where you can sync missing icons and exit.

The first **9** folders are yours – here you can **sort** everything how you want, with our App Settings app!

The next 3 apps show you:
- Unordered Apps
- All Installed Apps
- All Installed Packages

And the fifth row is for switching pages and going back!

**Power Menu**

Here you have actions:
- Closing an app
- Pinning an app
- Minimizing, fullscreening an app
- Switching between the 5 layouts
- Shutting down, rebooting, lock, suspend
- Exit the menu

**Controls for both menus:**
- Arrow keys / WASD – move
- Q / E – switch pages
- Enter / Space / ← – open folders/apps
- X – leave the folder/menu
- Full touch support included

### System Sounds

We have added sounds to our distro! Yes, a bold choice, but it adds some beautiful flair!

- Open
- Close
- Switch
- Click
- Notification
- Error
- Accept
- Background music (with VLC playlist setting)

### Widgets

Our control system for every setting and more!

**Sound**
1. **Tab:** here you see what plays, also system volume and media controls
2. **Tab:** input and output devices
3. **Tab:** volume control for individual apps and input devices

**Internet**
1. **Tab:** Ethernet & WLAN connecting
2. **Tab:** internet speed test

**Bluetooth**

Connect, pair and remove devices!

**Brightness**
1. **Tab:** monitor brightness and night mode
2. **Tab:** device brightness and colour

**Battery & System Monitor**
1. **Tab:**
   - View battery % and watts
   - Change energy profile
   - Change gaming mode, which removes the GPU boost and gives the GPU more power
   - Change battery saver mode, which deactivates many effects
2. **Tab:** view:
   - CPU
   - RAM
   - Storage
   - GPU

**Calendar & Weather**
- **In the waybar:** you can see the time and also the date if toggled
1. **Tab:** weather right now
   - Degrees in Celsius
   - Humidity in the air
   - Rain in mm
   - Change location
   - Forecast for the next 2 days
   - Date and time
2. **Tab:** calendar
   - Create, view and delete appointments
   - Also change the save location of the calendar files

**Settings**

The hub for all widgets.

**Display**

Change the resolution of the screen to ANYTHING:
- Want to play in 144p? Sure.
- Want to upscale from 8K? Wonderful.
- Want to play in 4:2? Absolutely.

Change the scale (to a certain degree). Toggle HDR. Change where your other monitors are.

**Appearance & Language**
1. **Tab:** change the theme, cursor effects, and Shake and Find
2. **Tab:** change keyboard and system language

**Security**
1. **Tab:** Privacy – hardware kill switches for WiFi, Bluetooth, WWAN/GPS, Camera and Microphone, plus a "Lock everything" panic button
2. **Tab:** DNS – change DNS servers (Cloudflare/Google/Quad9/custom), enforce DNS-over-TLS, Hotel/Guest WiFi mode (temporarily allow captive portals on the current network only)
3. **Tab:** Tailscale – connect/disconnect/log out, see your IP and other tailnet devices, autostart toggle, options for accepting routes, MagicDNS, Tailscale SSH and Shields Up
4. **Tab:** Firewall (UFW) – status, one-tap presets (Steam LAN, KDE Connect, Samba), full rule list, custom port/protocol rules, delete existing rules, log viewer sub-tab
5. **Tab:** ClamAV – signature database status + manual update, on-demand scans (any single file or folder, including a one-tap full system scan) with a threat list you can quarantine/ignore from, a quarantine view to restore or permanently delete isolated files, and an automatic re-scan toggle for ~/Downloads

### Summary of Custom Apps

- App Launcher
- Power Menu
- App Settings
- Widgets
- WidgetsHelper
- WaybarAutohide
- SystemSounds
- RandomWallpaper

## Roadmap

Still to be themed / done:
- Calamares
- Optional package installer
- Mouse cursor redesign
- Waybar redesign aka TrafkTuxBar
- GRUB, Plymouth, SDDM redesign
- Editor for: Rofi folders/apps, Waybar widgets/shortcuts, autostart apps, default apps
- Finish System Sounds
- On-screen keyboard button on waybar should be automatically hidden if the screen does not support touch

## Known Bugs

- The ISO doesn't currently boot – since the distro is still in development, this is a minor issue that will be fixed soon.
- When Firefox is in fullscreen, keyboard inputs are most of the time transferred to another window (Thunar in our case, always), but Firefox is still the active window and the mouse can be used. If fullscreen is left, the Firefox window goes (in Scroller) to the left side, not the right – meaning the right side does not have a window, which should not be possible. To get keyboard input back to Firefox, you have to switch the active window to another window and back. This is a Firefox issue and we cannot fix it!
- xfce4desktop sometimes crashes... this does not happen as quickly/often as swaync's issue, but it can happen. Normally it crashes after a few hours but is very inconsistent and does not happen often.

## To Be Done

> ***These are developer notes.***

### Widgets to Implement
- Later, if released, implement snowfoxOSv3's Mesh Connect feature.
- Rewrite Widgets.py in C or Rust at the end.

### The App Editor
1. Rofi App Launcher – it has 9 folders where you can put apps in. In this menu you will be able to drag any app + custom commands into the folders, plus as many subfolders in subfolders as you want. You can sort by all packages, all apps, unordered apps, custom apps, ordered apps. This will be the main menu to sort all of your apps!
2. You can add/remove the shortcuts of apps on the waybar on the "left".
3. You can add/remove autostart applications (but hide the standard ones, as they are essential).
4. You can set the default applications for files.
