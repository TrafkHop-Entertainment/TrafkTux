> **This Project is NOT Open Source, read the LICENSE for more!**
> Copyright 2026 TrafkHop Entertainment, all Rights reserved.

# TrafkTux v0.85
*''Unique Creativity meets QOL and Streamlining''*

**TrafkTux** is an **Arch + Hyprland** based Linux DIstribution with the focus of an easy to use and streamlined system.
It prides itself with its very distinct look and feel. It is also quite user friendly!

TrafkTux is a **Wayland** based System, wich means better security, HRD compatabillity and more.

TrafkTux has a fully functional Desktop Environment with background images, functional desktop icons and interactions, an app launcher, settings menus and more! (more in Software Stack and other Points)
It also comes with many preinstalled Programs for the best out of box experience!

---

## Installation
TrafkTux can be installed via in ISO file.

**Download:** `DISTROISNOTAVAILABEASOFTHISMOMENT.htmllink`

1. Download the ISO via our link!
2. Download Fedora Media Writer and burn the ISO onto a media of you choosing
3. insert the media into your Computer
4. Start it and boot into the installer
5. Complete the Installaton and reboot

Now you have sucessfully installed the OS!

**Installation Tutorial on our YT Channel:** `INSERTLINKHERE`

---

## Performance & Requirements

TrafkTux may not be the sleekest of Distro's out there, buuut it is still way sleeker than some other Operating Systems!

> **Note:** TrafkTux does not support SecureBoot at the Moment.

TrafkTux is already optimized for laptops, with `tuned` and some extra settings for maximum performance/battery savings.

Avahi is disabled by default due to a networking bug where the OS could saturate the entire network – e.g. a Nintendo Switch 2 on the same 2.4GHz WiFi network prevented good online play.

### Performance

**ISO size:** 3.0 GB

The system uses:

| State | ~RAM |
|---|---|
| **Idle** | **1,15GB** |
| + Firefox (1-5 Tabs) | +1-5GB |
| + Firefox (viele Tabs, ~30) | +~1,98GB |
| + Terminal or File Manager | +0,1GB |
| + Discord + Steam offen | +~1,35GB |

Idle RAM usage started at ~2GB and has since been brought down to 1,35GB, and now to 1,15GB.

**Background apps** include *(they do not impact performance)*:
- Dunst
- xfdesktop
- WaybarAutohide
- WidgetsHelper

#### Comparison

| System | Idle RAM (approx.) |
|---|---|
| Windows 11 | ~3.5 GB |
| Ubuntu (GNOME) | ~1.5 GB |
| **TrafkTux** | **~1.15 GB** |
| KDE Plasma | ~900 MB |
| Arch Linux with i3 | ~400-500 MB |

### Minimum Requirements
We have not testet TrafkTux on many machines.
Therefore this is only an estimation:

- A CPU + GPU less than 20 Years old
- 2 GB of RAM
- 4 GB of Storage Space

This should be enough to run the OS – you will not run any Browser though.

### Usable Specs

- Low-Mid-Tier CPU + GPU
- 8GB RAM
- \>= 64GB of Storage

With something like this you can use the system pretty well.

### Reccomended Specs

- Mid-Tier+ CPU + GPU
- 12+GB of RAM
- 1+TB of Storage

This is what HoppiTex uses.

### Testmachine
TrafkTux is currently being tested on a Lenovo IdeaPad 5 2-in-1 14AHP9 (model 83DR):
- **CPU:** AMD Ryzen 7 8845HS (16) @ 5.14 GHz
- **GPU:** AMD Radeon 780M Graphics (integrated)
- **Memory:** 13.40 GiB
- **Swap:** 4.00 GiB

---

## Update
As it is Arch based, it constantly updates! But as System Updates are seperate from normal Updates, you can menually update the system seperate from everything else – Which is also a good thing as a system update will **RESET** any changes you as a user made.
As this is the Case, we often reffer TrafkTux as an immutible system – not that you cannot change it no, it really is just not advised and reccomended in any way.

We would also like to explain, *WHY* we use arch and its update rolls:
As you may or may not know, Arch Linux Updates all the time with the newest versions. This has the disatvantage that sometimes updates break certain apps. We think that **this is not a problem**!
TrafkTux is used by HoppiTex, the sole maintainer and if something breaks, he will fix is soon. And the **advantage** of rolling releases are, that you have the newest programs and features, wich you do not get on distributions like debian or fedora.

---

## Shortcuts
The Distro is designed in a way that
1. Everything can be used with a mouse or Touchpad
2. Everything is easier with our keyboard shortcuts

### Shortcutlist
Our shortcuts are designed with a gamer in mind. everything can be done with the left hand, keeping the right hand free for the mouse, wich also is used a lot!

| Shortcut | Action |
|---|---|
| `Super + Space` | Open Terminal |
| `Super + F` | Open Filemanager |
| `Super + Tab` | Open App-Launcher |
| `Super + Escape` | Open Power Menu |
| `Super + ^` | Fullscreen (bordered) |
| `Super + Shift + ^` | Fullscreen (exclusive) |
| `Super + Alt + ^` | Minimize App |
| `Super + Ctrl + ^` | Pin App (Picture-in-Picture) |
| `Super + Alt + Tab` | Toggle Waybar visibility |
| `Super + Print` | Screenshot (region → clipboard) |
| `Super + Shift + Print` | Screenshot (region → save as PNG) |
| `Super + H` | Hide/show all Windows |
| `Super + WASD` | Switch active Window |
| `Super + Shift + WASD` | Resize active Window |
| `Super + Ctrl + WASD` | Swap Windows |
| `Super + Ctrl + QEX<` | Snap Window to one of the 4 corners (Floating mode) |
| `Super + Left-click` | Move Window |
| `Super + Right-click` | Resize Window |
| `Super + Alt + 1-5` | Switch Layout: Master / Dwindle / Scroller / Floating / Monocle |
| `Super + 1-9` | Switch Workspace |
| `Super + Shift + 1-9` | Move active Window to Workspace |
| `Super + Ctrl + Tab` | Workspace Overview (Hyprexpo) |

Laptop media keys (Volume, Brightness, Play/Pause/Next/Prev) also work out of the box.

### Touchscreen
TrafkTux also is fully Touchscreen compatible! Everything after the User Login can be done a Keyboard (there is an on screen Keyboard for after the login to type stuff).

---

## Security
TrafkTux comes secury out of the box! We take security somewhat seriously – everything below is enabled by default, no setup needed:

- **Firewall (UFW):** enabled by default, `deny` incoming / `allow` outgoing. The only exception is the `waydroid0` interface, wich is left fully open (needed for Waydroid networking to even work).
- **DNS-over-TLS:** all DNS queries are encrypted by default via `systemd-resolved`, using Quad9 and Cloudflare (DNSSEC on). This overrides whatever DNS server your router hands out, so encrypted DNS is enforced on every network you join – not just your home one.
- **Sysctl-Hardening:** a bunch of kernel/network/filesystem settings get applied on every boot (`/etc/sysctl.d/99-trafktux-hardening.conf`):
  - **Kernel info-leak protection:**
    - `kernel.kptr_restrict = 2` – hides kernel pointers in `/proc` from normal users, makes exploits that rely on memory addresses much harder to pull off
    - `kernel.dmesg_restrict = 1` – hides the kernel log ringbuffer (`dmesg`) from normal users, readable with sudo/root only
    - `kernel.yama.ptrace_scope = 1` – only direct parent-child processes are allowed to `ptrace` attach to each other (the Ubuntu-standard compromise value, not 2 or 3, so normal debugging/profiling doesn't get fully blocked)
    - `kernel.randomize_va_space = 2` – ASLR explicitly pinned to full strength (already Arch's default, but locked in here in case any package/tool ever lowers it)
  - **Network hardening:**
    - `net.ipv4.conf.all/default.rp_filter = 1` – strict Reverse Path Filtering, protects against IP-spoofing
    - `net.ipv4.tcp_syncookies = 1` – SYN-Cookies, protection against SYN-flood/DoS attacks
    - `net.ipv4/ipv6.conf.all/default.accept_redirects = 0` – doesn't accept ICMP redirects, protects against MITM attacks on the local network (e.g. hotel/guest WiFi)
    - `net.ipv4.conf.all/default.send_redirects = 0` – doesn't send ICMP redirects itself either (only relevant if the machine ever acts as a gateway/router for other devices)
    - `net.ipv4/ipv6.conf.all/default.accept_source_route = 0` – rejects source-routing, an old IP option that's barely used legitimately today and can be abused for spoofing/routing attacks
  - **Filesystem protection:**
    - `fs.protected_hardlinks = 1` – normal users can't create hardlinks to files they don't actually have write access to (e.g. setuid binaries)
    - `fs.protected_fifos = 2` / `fs.protected_regular = 2` – protects FIFOs/regular files in world-writable+sticky directories (e.g. `/tmp`), level 2 is the value recommended by the kernel devs themselves, protects against race-condition tricks when writing files
  - (`fs.protected_symlinks` is intentionally left untouched, that was our own decision)
- **Password Policy:** every account needs a password of at least 12 characters using at least 3 of the 4 character classes (upper/lowercase/digits/special chars). Enforced at install time AND for any later password change – not skippable.
- **Tailscale:** built in and ready to go, just log in whenever you want to use it.
- **Malware Scanning:** ClamAV + clamtk are preinstalled and kept up to date automatically via `freshclam`, extended with community signatures (`clamav-unofficial-sigs`) for even better detection.

---

## Software Stack
TrafkTux comes Preinstalled with a bunch of Software while still not overdoing it:

### Preinstalles Apps

**Desktop & Shell**
- Hyprland, Waybar, Rofi, Dunst
- Hypridle, Hyprlock, xfdesktop
- wvkbd (on-screen keyboard)

**Everyday Apps**
- Firefox
- VLC Media Player
- Thunar (file manager) + xfce4-terminal
- Ark (archive manager) + 7-Zip, unrar, zip/unzip
- VSCodium
- Pinta (image editor)
- Fastfetch, khal

**System & Monitoring**
- Htop
- GParted, Fedora Media Writer
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

**Boot & Display**
- GRUB + Plymouth boot splash
- SDDM (display manager)
- Calamares (installer)

**Fonts**
- Noto Fonts (incl. Emoji & CJK)
- JetBrains Mono Nerd Font

...plus a bunch of other system-related packages and sensible defaults, tuned out of the box.


As you can see, TrafkTux throws a bunch of unreleated packages together and creates something truely unique!
A Arch + Hyprland Setup, which uses the XFCE Desktop + File Manger + Terminal, has many custom Programms/Scripts, but also heavily relies on 3rd party software.

### Optional Packages
Those Apps are **NOT PREINSTALLED** and can be installed via the App Settings Menu!

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

**Drivers**
- opentabletdriver, webcamoid, webkitgtk2 *(pacman)*
- cnijfilter2, gnome-network-displays *(aur)*

**Other**
- timeshift *(pacman)*
- archiso *(pacman)*
- theclicker *(aur)*
- **MEGA:**
  ```bash
  wget https://mega.nz/linux/repo/Arch_Extra/x86_64/megasync-x86_64.pkg.tar.zst && sudo pacman -U "$PWD/megasync-x86_64.pkg.tar.zst"
  ```

**Games**
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

**Learning**
```bash
sudo docker run -p 3000:3000 bkimminich/juice-shop
```
Then open `http://localhost:3000/#/`.

**AI**
- ollama, ollama-cuda

**OBS**
- obs-pipewire-audio-capture-bin *(aur)*

---

## Customisation
TrafkTux is **HEAVILY** customized.
We do not have a "TrafkTux Desktop" App or a "TrafkTux App Selector" App in a normal Linux Sense.
Everything is a part of TrafkTux – without our customisation, it is just a secure Arch installation.

So you will not be able to install one of our features to your Linux Desktop, as everything works together in our Distribution.

### Hyprland
We have a strongly customized Hyprland Setup:
Firstly our windows have a glow in the colour is ''#fff495'' and a hyprbad in the same colour.

TrafkTux has **5** Layouts that are all fully functional and integrated: Dwindle, Master, Floating, Monocle and Scroller!
Our favourites are Scroller and Floating.
Floating has also window snapping!

The Hyprbar has 5 buttons: Close, Minimize, BorderFullscreen, SwitchWithMaster and Pin.

We also have the Hyprglass Plugin that makes the windows look a bit like they are made out of glass!

Also included: **Hyprexpo** for a workspace overview, **Hyprbars/Hyprfocus** and full **touchscreen support** across all of it.

We also have full system sounds for almost everything! (They can be – of course – turned OFF in the setting. Even we get annoyed with them sometimes – although we like every single one of them!)

#### Minimizing
We have a plugin called Hyprland Minimizer which allows for windows to be minimized and put into a tray on ouw waybar for reopening!

### Cursor
We have our own cursor that works EVERYWHERE*!

Also we use the Hyprland Plugin Dynamic Cursors to make the cusor more dynamic, it leans in the movement direction for example.

### Icon Theme
We use a recoloured Theme called "Clay"! *(blue swapped for yellow)*

### GTK, Kvantum, Theming
We have Themes for GTK2-3-4 and Kvantum to enshure consistent looks across most applications (excluding Apps like Firefox, Steam, Programms with custom colours)

We've also themed: Dunst, HyprCursor, HyprLock, Fastfetch, GRUB, Plymouth and SDDM.

### Waybar
We have a waybar, that – like in Windos/KDEPlasma – hides itself as long as the mouse in not at the bottom of the screen/s!
To compleately disable the waybar, press `SUPER+ALT+Tab` – This is very useful for many, many games!

On the **Left** you have your buttons for the App Launcher, The Power Menu, the Workspace Overview and a hideall windows button°
In The **Middle** is the workspace and app overview, wich shows all open apps!
And on the **Right** are our widgets! Prelocated on the bar are:
- Audio
- Internet
- Bluetooth
- Brightness
- Battery/SystemMonitor
- **-** A Tray for hidden apps – not part of the widgets
- **-** On Screen Keyboard
- Calender + Weather
- Settings – Access to ALL widgets

And with the Hyprland Plugin Hyprgrass it also has touch support – just wish your finger from the bottom of the screen up and there it is!

### Dunst
A basic Notification Service that is also styled to resemble a Trafkbubble.

### xfdesktop
The Desktop shows a randomly selected image – which you can reroll in the brightness Widget.
Also the files in your Desktop Folder are shown here – And as any Desktop you can interact with the files.

### Thunar
We have added a "open Terminal here" button and right click menu.

### Calamares
Currently a barebones installer for the base distro. You can choose:
- Name
- Time
- Language
- Drive

Formatting is preconfigured as Btrfs (manual formatting is also supported).

The installer is fully offline – no internet required.

### GRUB
A custom GRUB theme featuring:
- A logo up top
- A selection menu with `os-prober` enabled
- Our recognizable "Trafk Bubbles" for menu items
- some Zauberkraft/Mana floating around
- a vignette

### Plymouth & SDDM
Pretty much the same look as GRUB.
In Plymouth, a bubble floats from the left to the right as an (animated) progress bar.
In SDDM, the users are in the middle, then the password, and on the edges 2 buttons to reboot/shutdown.

### ROFI
We have **2 CUSTOM*** Rofi Menus:

**App Launcher**
It is a grid od 12 TrafkBubbles that act as folders/buttons.
In the roof folder there are 12 folders in a 4x3 grid and a 5th column where you can sync missing icons and exit.
The first **9** Folders are yours – here you can **sort** everything how you want – with our App Settings app!
The next 3 apps show you:
- Unordered Apps
- All Installed Apps
- All installed Packages

And the fith row if of switching the pages and going back!

**POWER MENU**
Here you have actions:
- Closing an App
- Pinning an App
- Minimizing, fullscreening an App
- Switching between the 5 Layouts
- Shutting down, rebooting, lock, suspend
- Exit the Menu

**Controls for both menus:**
- Arrow keys / WASD – move
- Q / E – switch pages
- Enter / Space / `<` – open folders/apps
- X – leave the folder/menu
- Full touch support included

### System Sounds
We have added sounds to our Distro!
Yes a bold choice, but it adds some beautiful flair!
- Open
- Close
- Switch
- Click
- Notification
- Error
- Accept
- BackgroundMusic (with vlc playlist setting)

### Widgets
Our Control System for every setting and more!

#### Sound
1. **Tab:** Here you see what plays, also System Volume and media controls
2. **Tab:** Input and Output Devices
3. **Tab:** Volume Control for individual apps and Input Devices

#### Internet
1. **Tab:** Ethernet & Wlan connecting
2. **Tab:** Internet Speed Test

#### Bluetooth
Connect, Pair and Remove Devices!

#### Brightness
1. **Tab:** Monitor Brightness and Night Mode
2. **Tab:** Device Brightness and Colour

#### Battery & System Monitor
1. **Tab:**
   - View Battery % and Watts
   - Change Energy Profile
   - Change Gaming mode, which removes the GPU boost and gives the GPU more Power
   - Change Battery Saver mode, which deactivates many Effects
2. **Tab:** View:
   - CPU
   - RAM
   - Storage
   - GPU

#### Calender & Weather
- **In The Waybar:** You can see the Time and also the Date if toggled

1. **Tab:** Weather right now
   - Degrees in Celsius
   - Moistness in the ari
   - Rain in mm
   - change location
   - forecast for the next 2 days
   - Date and Time

2. **Tab:** Calender
   - Create, View and Delete Appointments
   - Also you can change the save location of the calender files

#### Settings
The hub for all widgets

#### Display
Change the Resolution of the screen to ANYTHING
- want to play in 144p? sure
- want to upscale from 8k? wonderful
- want to play in 4:2, absolutely

Change the Scale (to a cartain degree)
Toggle HRD
Change where your other monitors are.

#### Appearance & Language
1. **Tab:** Change The Theme, Cursor effects and Shake and find
2. **Tab:** Change keyboard and system language

### Summary of custom apps
- App Launcher
- Power Menu
- App Settings
- Widgets
- WidgetsHelper
- WaybarAutohide
- SystemSounds
- RandomWallpaper

---

## Roadmap
Still to be themed / done:
- Calamares
- Optional package installer
- Mouse cursor redesign
- Editor for: Rofi folders/apps, Waybar widgets/shortcuts, autostart apps, default apps
- Finish and fix System Sounds
- Input/Output Device volumes
- Brightness Rework
- System Monitor add dynamic storage like external ssds, eingehängte ISOs, Floppy Disks, etc
Also add a 3rd tab wich shows – maybe via htop – all programs and to kill them and so stuff
- On Board Keyboard button on waybar should be automaticly not shown if screen does not support touch
- System Sounds move to a 4th audio tab (over the other 3, like a pyramide)
- add security widgets


## Known Bugs
- The ISO doesn't currently boot – since the distro is still in development, this is a minor issue that will be fixed soon.

---
---
---

# To Be Done
***THOSE ARE DEVELOPER NOTES***

### Widgets to implement

* add other methods of connection + other internet security features + vpn integration maybe, but not important + later if released implement snowfoxOSv3's Mesh Connect feature.
* make this script non daemon to save on performance and battery and rewrite it in c at the end

**The App Editor**
1. Rofi App Launcher, it has 9 Folders where you can put apps in. In this menu, you will be able to drag any app + custom commands in the folders + as many subfolders in subfolders as you want. You can sort by all packages, all apps, unordered apps, custom apps, ordered apps. This will be the main menu to sort all of your apps!
2. you can add/remove the shortcuts of apps on the waybar on the "left".
3. you can add/remove autostart applications (but hide the standard ones as they are essential).
4. You can set the default applications for files


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