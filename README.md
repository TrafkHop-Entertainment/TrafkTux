
---
> Copyright © 2026 TrafkHop Entertainment™
> All rights reserved.
---
>This Project is Source Available, NOT Open Source!
---
>This Project was coded partially by A with strict human superventionI! Visuals, controls and every other part has been fully made by humans!
---
# TrafkTux v0.85

*"Creativity meets QOL"*
## About

**TrafkTux** is an **Arch + Hyprland** based Linux distribution with the focus of being an easy to use and streamlined system.

It prides itself on its very distinct look and feel. It is also quite user friendly!

TrafkTux is a **Wayland** based system, which means better security, HDR compatibility and more.

TrafkTux has a fully functional desktop environment with background images, functional desktop icons and interactions, an app launcher, settings menus and more! (more under Software Stack and other sections below)

It also comes with many preinstalled programs for the best out-of-box experience!

## Installation

TrafkTux can be installed via an ISO file.

**Download:** DISTROISNOTAVAILABEASOFTHISMOMENT.htmllink:)

1. Download the ISO via our link!
2. Download Fedora Media Writer and burn the ISO onto a media of your choosing
3. Insert the media into your computer
4. Start it and boot into the installer
5. Complete the installation and reboot

Now you have successfully installed the OS!

**Installation tutorial on our YT channel:** INSERTLINKHERE

## Performance & Requirements

TrafkTux may not be the sleekest of distros out there, buuut it is still way sleeker than some other operating systems!

> **Note:** TrafkTux does not support SecureBoot

TrafkTux is already optimized for laptops, with tuned and some extra settings for maximum performance/battery savings.

### Performance

**ISO size:** 3.0 GB

The system uses:

| State                       | ~RAM      |
| --------------------------- | --------- |
| Idle                        | 1.31 GB   |
| + Firefox (1-5 Tabs)        | +1-5 GB   |
| + Firefox (viele Tabs, ~30) | +~1.98 GB |
| + Terminal or File Manager  | +0.1 GB   |
| + Discord + Steam offen     | +~1.35 GB |

Idle RAM usage started at ~2 GB and has since been brought down to 1.35 GB, and then to 1.15 GB and now its back to 1.35GB. We are still optimising!

**Background apps** include *(they do not impact performance)*:
- Swaync (Notifications)
- xfdesktop
- WaybarAutohide
- WidgetsHelper

### Comparison

| System             | Idle RAM (approx.) |
| ------------------ | ------------------ |
| Windows 11         | ~3.5 GB            |
| Ubuntu (GNOME)     | ~1.5 GB            |
| **TrafkTux**       | **~1.15 GB**       |
| KDE Plasma         | ~900 MB            |
| Arch Linux with i3 | ~400-500 MB        |
| SnowFoxOS          | ~180 MB            |

### Minimum Requirements

We have not tested TrafkTux on many machines. Therefore this is only an estimation:

- A CPU + GPU less than 15 years old
- 2 GB of RAM
- 12 GB of storage space (right after a complete installation, it takes up ~ 7.5GIB - ~ 11.8GIB – how you want to count it ig)

This should be enough to run the OS – you will not run any browser though.

### Usable Specs

- Low-mid-tier CPU + GPU
- 8 GB RAM
- ≥ 64 GB of storage

With something like this you can use the system "pretty" well.

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
You can update the system via the pamac software center located in the Launcher app under stores! We have a custom Repo with some meta packages and 3 TrafkTux System Update Packages that allows the user to upgrade the TrafkHop Side of the system from the newest github repo commit that if verified!

As it is Arch based, it constantly updates! But as system updates are separate from normal updates, you can manually update the system separately from everything else – which is also a good thing, as a system update will **RESET** any changes you as a user made.

As this is the case, we often refer to TrafkTux as an immutable system – not that you cannot change it, no, it really is just not advised and recommended in any way.

We would also like to explain *why* we use Arch and its update rolls:

As you may or may not know, Arch Linux updates all the time with the newest versions. This has the disadvantage that sometimes updates break certain apps. We think that **this is not a problem**!

TrafkTux is used by HoppiTex, the sole maintainer, and if something breaks, he will fix it soon. And the **advantage** of rolling releases is that you have the newest programs and features, which you do not get on distributions like Debian or Fedora.

But we do have to warn you, that we cannot garantie that it will work on your specific system. it should work though!

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
| Super + Shift + Tab | Open Settings widget at the mouse pointer (then WASD / Enter / Q·E tabs / X back / Esc close) |
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

### Controller mode (TrafkPad)

Any gamepad = keyboard + mouse for the whole OS (daemon: `~/.config/TrafkTuxPad/TrafkPad`, started from Autostart.lua, config: `~/.config/TrafkTuxPad/TrafkPad.conf`, managed by Settings → Controller). Default: ON. Toggle: hold **L1 + R1 + Select + Start** for 1 s (rumble + notification). While OFF, pads are not grabbed (games see them normally) and only the combo is watched. Disable the Home button in Steam.

| Pad | Result |
| --- | --- |
| Left stick / D-pad | W A S D (or arrows, setting) / arrow keys |
| Right stick | Mouse |
| A / B / X / Y | Space / Ctrl / Tab / F |
| Start / Select | Enter / Esc |
| L1 / R1 / L3 | Q / E / Shift |
| L2 / R2 / R3 | Left / right / middle click |
| Home + right stick | Scroll (4 directions) |
| Home + L2 / R2 | Super + left / right click (move / resize windows) |
| Home + X / Y | Workspace overview (Hyprexpo) / Screenshot |
| Home + A / B | unassigned |
| Home + D-pad up / down | Pin / Hide window (with R3 held: Hide all) |
| Home + D-pad left / right | Fullscreen 1 (with R3 held: Fullscreen 0) / lock Bar autohide |
| Home + Start / Select | Launcher (with R3 held: Settings at pointer) / Power menu |
| Home + L1 / R1 | Previous / next workspace |
| Home + left stick | Focus window (like Super + WASD) |

Wiimote (default): B / A = left / right click, 1 / 2 = scroll up / down, + / − = Enter / Esc, D-pad = arrows, Nunchuk stick = WASD, Z / C = Q / E. With Home: A / B = Super + right / left click, D-pad up / down / left / right = Launcher / Power menu / Settings at pointer / Hyprexpo, + / − = Launcher / Power menu, 1 = Screenshot, 2 = Hide all, Z / C = previous / next workspace.

Settings → Controller (tabs **State, Mapping, Combos, Feel, Wiimote**). *State*: mode Keyboard / Off (a third mode “Controller”, which turns pads like the Wiimote into a standard gamepad, is planned), master switch, feedback (rumble / notification / sound). Starting with controller mode ON at login is set in Settings → Apps & Shortcuts → Autostart. *Mapping* (sub-tabs Normal, Wii, Layouts): one button per controller input showing its current binding. Click it and press the key or key combination on the keyboard (Super works, Esc is a normal key; a lone modifier like Super is taken when you release it). The popup closes by itself after 5 s without input. Mouse buttons, scroll, media keys, *None* and *Default* are picked in the same popup. Base and Home layer are separate. While the Mapping or Combos tab is open all pad / Wiimote input is blocked and only highlighted. *Combos*: click a field, hold the buttons on the controller together and let go (gamepad ON / OFF, Wiimote ON / OFF, Wiimote pointer mode, hold times). *Feel* (Pointer, Sticks): pointer speed / curve / dead zone, scroll speed, invert scroll; Nintendo layout (swaps A/B and X/Y), left stick WASD/arrows, swap D-pad and left stick (both layers: Home + D-pad then = window focus), mouse on left stick (right stick off; with the swap: Home + L3 = launcher, Home + R3 = power menu). If a pad sends Home only as a short pulse, tap Home once and then press the next button (`home_tap`). Debug: `debug = true` in `TrafkPad.conf`, log in `/tmp/TrafkPad.log`.

The pad does not talk to Hyprland directly: for actions like Launcher or Screenshot it sends fixed keys (F13–F24, with Shift / Ctrl for variants; no real keyboard has them). What Hyprland does with them lives in `~/.config/hypr/HyprlandUserConfigs/ControllerBinds.lua`, which the widgets generate (rewritten and Hyprland reloaded once when it changes) and `Controls.lua` (section 4) loads, same pattern as `UserAutostart.lua`. Binds only work while controller mode is ON. In the Mapping popup every button can be set to a typed key combination, a mouse / scroll / media entry, or a *Hyprland action* from a list; the Home layer shows the meaning, e.g. “F13 · Launcher”. With Home + R3 (right stick click) held — the shift layer — Shift is added to the key and the right stick does nothing (no scroll, no mouse). L3 is not involved: L3 + Home stays movement/focus. Which click is the shift button is set in Feel → Sticks → “Shift button” (`shift_btn = R3` or `L3` in `TrafkPad.conf`). Extra buttons of a pad (paddles, macro keys …) show up automatically as *Extra 1…8* in the Mapping tab (unassigned by default). The controller settings only appear while a controller is connected; the Normal / Wii mapping tabs follow the connected device types. Wiimote pointer area “active workspace”: the daemon asks Hyprland (`hyprctl monitors -j`) for the real geometry of the focused monitor (on focus change and every 3 s), so different resolutions / scales work; `wii_edge` (default 3 %) makes the screen corners reachable.

**Wiimote** (hid-wiimote, no pairing needed): hold 1 + 2, then Settings → Devices → Wiimote → *Connect* (or `~/.config/TrafkTuxPad/wiimote-connect.sh`). After every login TrafkPad also looks for a Wiimote for 5 minutes (notification; `wiimote-autoconnect.sh`, switch in Autostart), so you can connect without opening a widget. Needs `ClassicBondedOnly=false` in `/etc/bluetooth/input.conf` (shipped). A / B = left / right click, 1 / 2 = Space / X, + / − = Enter / Esc, D-pad = arrows, Home = Home layer; Nunchuk: stick = WASD, Z / C = Q / E; the IR sensor bar moves the pointer (absolute, all screens / one monitor / active monitor, set in Settings → Devices; smoothness 1–5 with 5 = raw; calibration in Settings → Controller → Wiimote → Calibrate). Rotation compensation: the tilt of the Wiimote (angle between the two IR dots) is subtracted, so pointing up while rolled −90° still moves up (switch `wii_roll`). Toggle ON/OFF: hold + and − for 1 s. Pointer mode normal ⇄ game mode (relative / joystick for games that capture the mouse): hold 1 and 2 for 0.6 s (no auto-detection). Both combos can be changed in Combos. After updating `TrafkPad.c` rebuild it (`~/.config/TrafkTuxPad/build.sh`) and restart the daemon (`pkill TrafkPad`, the watchdog restarts it); `TrafkPad --ctl version` must say `proto=4`.


### Touchscreen

TrafkTux is also fully touchscreen compatible! Everything after the user login can be done without a keyboard (there is an on-screen keyboard for after the login to type stuff).

## Gaming

We have gamescope and wine preinstalled! We also have a custom script that puts any launched wine game into gamescope, so that all games – be it Crazy Chicken, Austin Cooper S Racing, Road Rash, or other old games – can run in a scalable windowed mode the same way any other program can!

## Security

TrafkTux comes secure out of the box! We take security somewhat "seriously" – everything below is enabled by default, no setup needed:

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

* We also support some laptop finger print scanners!...
* Also FIDO2 Key, although we really do not reccomend it (it has not been tested)

## Software Stack

TrafkTux comes preinstalled with a bunch of software while still not overdoing it:

### Preinstalled Apps

**Desktop & Shell**
- Hyprland, Swaync
- Hypridle, Hyprlock, xfdesktop
- wvkbd (on-screen keyboard)
- TrafkTuxBar, TrafkTuxLauncher, Widgets

**Everyday Apps**
- Firefox
- VLC Media Player
- Thunar (file manager) + xfce4-terminal
- Ark (archive manager) + 7-Zip, unrar, zip/unzip
- VSCodium, Gimp
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
- Canon printer drivers (cnijfilter2)
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
- Custom Wine Gamemode wrapper + 2 dgvoodoo2 versions preinstalled for game compatability

...plus a bunch of other system-related packages and sensible defaults, tuned out of the box.

As you can see, TrafkTux throws a bunch of unrelated packages together and creates something truly unique! An Arch + Hyprland setup which uses the XFCE desktop + file manager + terminal, has many custom programs/scripts, but also heavily relies on 3rd-party software.

### Optional Packages
We have a custom repo with some meta packages that you can install! There are quite a bunch of app bundles to choose from! Available in the Pamac Store under Repositories.

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

The pinned apps and the widgets on the right are yours to change: **Settings → Apps & Shortcuts → Bar** lets you add, remove and reorder pinned apps and choose and reorder the widgets – the bar reloads itself live. *Add widget* offers **every** widget (not just the preset ones), every widget tab (e.g. *Battery & System → Processes*, *Network → Speed Test*, *Calendar & Weather → Weather*) and every Settings page, so you can pin exactly the tab you use (clicking a tab button of an already open widget switches the tab instead of closing it). Your choices are stored in `~/.config/TrafkTuxBar/Userbar.jsonc`, a file the bar creates itself on its first start (it is not part of the system files, so updates never overwrite it). The Settings widget and the fixed buttons (launcher, power menu, clock, tray) can't be removed. Delete `Userbar.jsonc` to get the defaults back.

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

Connect, pair and remove devices! Opening the widget automatically searches for new devices for 30 seconds (the search button starts and stops it by hand); nearby devices show up under *New devices* with a *Pair* button. Pairing also handles code confirmation and PIN entry in a small dialog, then trusts and connects the device. A Wiimote can't be paired, so it shows *Connect* instead of *Pair* (hold 1 + 2 first). Nameless beacons are hidden.

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
3. **Idle tab** (also on desktops without a battery): the screen-off, lock and suspend timers (hypridle), lock before sleep, and whether a playing video keeps the system awake. The widgets start and manage hypridle themselves and keep its config in `~/.config/hypr/HyprlandUserConfigs/hypridle.conf`.

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

**Apps & Shortcuts**
1. **Tab:** Launcher – edit the app launcher: create folders, add installed or custom apps, reorder, change icons, move apps between folders and hide your own folders from the root menu (system entries are read-only). Saving also removes apps you added from the list that are no longer installed (custom apps are never removed)
2. **Tab:** Bar – *Pinned apps* and *Widgets* of the bar (add any widget or widget tab, remove, reorder, items per row, reset to default); see Waybar above
3. **Tab:** Autostart – pick any installed app (or type a command) to start with the session
4. **Tab:** Defaults – default applications (not built yet)
5. **Tab:** Wine – Gamescope for Wine: scaling filter, scaler, sharpness, dgVoodoo2 version, and per game switches to run it without Gamescope or without dgVoodoo2

**Security**
1. **Tab:** Privacy – hardware kill switches for WiFi, Bluetooth, WWAN/GPS, Camera and Microphone, plus a "Lock everything" panic button
2. **Tab:** DNS – change DNS servers (Cloudflare/Google/Quad9/custom), enforce DNS-over-TLS, Hotel/Guest WiFi mode (temporarily allow captive portals on the current network only)
3. **Tab:** Tailscale – connect/disconnect/log out, see your IP and other tailnet devices, autostart toggle, options for accepting routes, MagicDNS, Tailscale SSH and Shields Up
4. **Tab:** Firewall (UFW) – status, one-tap presets (Steam LAN, KDE Connect, Samba), full rule list, custom port/protocol rules, delete existing rules, log viewer sub-tab
5. **Tab:** ClamAV – signature database status + manual update, on-demand scans (any single file or folder, including a one-tap full system scan) with a threat list you can quarantine/ignore from, a quarantine view to restore or permanently delete isolated files, and an automatic re-scan toggle for ~/Downloads
6. **Tab:** Login – skip the login screen (SDDM autologin) and disable the lock screen (hyprlock), so a pad-only system never gets stuck at a password prompt


# To Be Done

> ***These are developer notes.***
## Roadmap

Still to be themed / done:
- Calamares
- App Editor: only the *Default Apps* tab is still missing (see App Editor below)
- In the Launcher:
  1. update pre installed applications
  2. make it so that some applications are hidden pre installed ones ofc without user config.
- NEW HYPRLAND LAYOUT: INFINITE DESKTOP!!!!! there are some options available online, but a custom layout would probably be the more safe option if there is no good version online like regular updates and stuff.

## Known Bugs

- The HideAll feature does not work correctly with the app backgrounds. if one is active, the script will become very slow and you will be transported to the hidden workspace of the hidden apps, wich does not happen without it. the script fails to send the background image app into the other workspace – it should ignore it instead.
- The navigation also does not work correctly with apps as wallpapers as they block... idk it does not work correctly
- Die Background app still registers in the bar as a normal app
- BIG STUFF
  1. Der xfdesktop oder hyprwinwrap oder hyprpaper entziehen der apps das tastaturtippen. man will was in ner app mit der tastatur machen, aber es geht auf den desktop (man merkt es besonders mit 2 monitoren) ok es ist nicht wegen hyprwinwrap, ist auch ohne so.
- xfdesktop can crash and there is no daemon restarting it
- hyprlock is ass! 1. it does not scale with resolution 2. when you type in the RIGHT password, it mostoften goes green but NOTHING happens and it SOFTLOCKS you out of YOUR OWN SYSTEM and if you type in the wrong password, it goes GREEN you wait 10s ca and THEN it turns RED..... shitty thing it is
- HYPRLAND:
  1. hyprland sagt es wird ohne umgebungsvariable gestartet, was aber nicht stimmen sollte
  2. hyprgrass meldet beim hyprland systemstart, dass es deaktiviert ist (gute 10-12 Mal btw)... ES IST NICHT DEAKTIVIERT.....

### Other Stuff
- Finish System Sounds - tortenboxer
  - Bar and launcher now call `SoundCenter.sh <Event>` with the exact event names (the daemon only knows PascalCase: Click, RightClick, MiddleClick, Open, Close, FocusChange, Pip, Minimize, LayoutSwitch, Dunst, Error, Toggle, Enter). Still to check: every other script (PictureInPicture.sh, LayoutSwitcher.sh, HideAll.sh, RofiTrafkBubbleMenus.c, Controls.lua ...) for the removed `soundctl.sh` or lowercase event names: `grep -rn soundctl ~/.config`
  - No sound files yet for `Pip` and `Toggle` (those events stay silent until `Pip.ogg` / `Toggle.ogg` exist in `~/.config/hypr/Sounds/`)
- make sddm idle animations  – turboprinz
- add the calender option for the human one. the 12000 year one. the one that the our world in a nutshell or how the channel is called calender.
- Make SDDM Buttons
- Make custom Buttons for GUI
- Mouse cursor redesign
- Transfer Widgets FIles to new Folder and other FIles still in old waybar folder
- Transfer all sound related stuff in SoundCenter
- redo trafkbubble animation for opening and closing (siehe png)
- LAUNCHER:
  1. scrolling with the mouse should scroll the pages
  2. 2 new sorting options: 1. Size on Disk – sorts all apps in its size – scans from the root directory of the application the data. stored in a file and only updated when a new app gets added and stuff. 2. play time – 3. point
  3. Play Time:
     Every app will be tracked on how long it was open for. This will be system wide!!!!!!!!!!!!! NOT ONLY LAUNCHER!!!!! every app will get this. maybe also system processes if every everything should be tracked. or only applications that have a .desktop entry. no. everything. not everything has a .desktop entry! THIS is a GREAT feature!
- CONTROLLER / TrafkPad (basics done: gamepads, Wiimote + Nunchuk + IR pointer, Settings → Controller). Still open:
  1. **Relative mouse for the Wiimote pointer** – built (relative and joystick mode, switch by button combo 1 + 2, no auto-detection), still needs a hardware test in Minecraft / Moorhuhn.
  2. **uDraw tablet (Wii)** – plugs into the Wiimote extension port, not supported by hid-wiimote (hid-udraw only covers the PS3/Xbox USB version). Would need the raw HID reports (hidraw) and the extension protocol. Needs data first (`lsusb` for the USB version / hidraw dump for the Wii one).
  3. **Mapping editor** – built (one button per input, key popup, per-device layers, combos, layouts, input blocked while the tab is open); needs hardware testing. The default keybinds are to be gone through once more.
  4. **Scrolling and window resizing** – solved via the mapping editor (scroll on any button, scroll-only stick); still open: window swap / snap layers.
  5. **SDDM login with a controller** (not built; only the autologin toggle exists) + on-screen keyboard.
  6. Wiimote: "Wii Motion Plus Required" joke, scrolling, remote-wide options (rumble feedback).
  7. Launcher: scroll pages with the mouse wheel (see Launcher list above).
  8. **Gyro aiming** (gyro mouse via Motion Plus / Joy-Con IMU).
  9. **Switch Joy-Con** support (later), **Switch 2 Joy-Con** with mouse mode.
  10. **Controller mode** (gamepad emulation): translate pads the OS does not accept as a gamepad (Wiimote ...) into a standard virtual gamepad, as a second mode next to keyboard & mouse (State tab has the button, disabled for now).
  11. Wiimote rotation at exactly ±90° on first sight is ambiguous (could use the accelerometer).

### App Editor

Built: Launcher tab (including editing the icon / hide flag of your own folders and moving apps between folders), Bar tab (pinned apps and widgets, live reload via SIGHUP, `Userbar.jsonc` created by the bar from built-in defaults), Autostart tab (app picker dialog), Wine/GameScope tab (the wrapper creates its own config files on the first Wine launch).

**Default Apps (Tab 4) – nie gebaut**

- Soll xdg-mime/`~/.config/mimeapps.list` verwalten
- Offene technische Fragen vorher: mehrere mögliche `mimeapps.list`-Pfade mit unterschiedlicher Priorität, GIO-Cache-Invalidierung, Thunar-spezifisches Fehlverhalten (“nimmt zuletzt benutzte App statt echtem Default”)

**Kleinere offene Punkte**

- Launcher-Tab: Icon/Hidden-Flag der **System**-Ordner (`menu.json`) lassen sich nicht ändern – der C-Launcher ignoriert beim Mergen Icon/`hidden` aus `Usermenu.json` (`merge_user_node`). Eigene Ordner gehen.
- `Userbar.jsonc` ersetzt die Item-Listen der zwei Bar-Bereiche komplett: neue Standard-Widgets aus einem Update tauchen dort nicht automatisch auf (Datei löschen = die Bar legt sie neu aus den eingebauten Standardwerten an). Die eingebauten Werte stehen in `BUILTIN_MODULE_DEFAULTS` (TrafkTuxBar.c) und `_BAR_BUILTIN_DEFAULTS` (WidgetsDaemon.py) und müssen gleich bleiben.
- hypridle: Stürzt es ab, startet es niemand neu, bis der WidgetsDaemon neu startet (bewusst keine Überwachung wegen möglicher Neustart-Schleife bei kaputter Config).
- Widget-Tabs in der Bar: Der Socket des WidgetsDaemon versteht `<widget>#<Tab>` (mehrere Ebenen mit `>`, danach optional `@kbd`/`@cursor`), z. B. `akku#Processes`, `network#Speed Test`, `settings#Apps & Shortcuts>Wine`. Der Tab-Name wird gegen die Beschriftung der Tab-Leiste verglichen (Symbole und Groß-/Kleinschreibung egal). Ein **neuer Tab** erscheint im *Add widget*-Dialog erst, wenn er in `_BAR_WIDGET_TABS` (WidgetsDaemon.py) steht; die Settings-Seiten kommen automatisch aus `SETTINGS_CATEGORIES`. Unter-Tabs von Settings-Seiten stehen nicht im Dialog, lassen sich aber von Hand in `Userbar.jsonc` eintragen.
- Settings-Hub „In Waybar“: Die Einteilung richtet sich nach der echten Bar (`Userbar.jsonc` + feste Module). Die alte Waybar-Config wird nur noch gelesen, wenn die Bar-Config fehlt.
- Hyprland native screenshot tool benutzen anstatt das was jetzt ist + screenshot pfad fixen
- 2 bash git files via widgets machen.
- Neustes Update hat gefixt: 1. apps die beim installieren automatisch sich zum autostart hinzufügen wo auch immer starten nun + paketmanager han nun ne notificaion.
  Neuestes Update hat gebrochen: Wallpaper beim start vom laptop. manuell via widgets gehts aber noch.
  Neuestes update (mit update mein ich pacman btw) braucht 2 fixes: 1. wallpaper beheben 2. beim autostart widget müssen auch die anderen autostart sachen die nicht in der hyprland drinnen stehen verwaltbar sein (löschen hald, hinzufügen machen wir ja über hyprland)
- battery remaining time not shown/displayed. should be above Watts.
- Wiimote connecten hängt system ganz kurz auf (bruchteil einer sekunde, aber sichtbar) UND audio ist für ca 40 sekunden stumm..... also man hört nix. medien spielen normal weiter, aber man hört nix.
