### THe Project is NOT Open Source, READ THE LICENSE for more!
Copyright © 2026 TrafkHop Entertainment™
All rights reserved.
<div align=center>
# TrafkTux
An Arch based Hyprland Distribution with a maximalistic Vision and many qol features!
![Version](https://img.shields.io/badge/version-v0.7-9B59B6?style=flat-square)
![Arch](https://img.shields.io/badge/base-Arch%2012-A81D33?style=flat-square&logo=debian&logoColor=white)
![Hyprland](https://img.shields.io/badge/desktop-Hyprland%2FX11-3a86ff?style=flat-square)
![License](https://img.shields.io/badge/license-TrafkHop%20Entertainment%20Source%20Availavle%20License%20v4-9B59B6?style=flat-square)
</div>
# Programms
The Core apps that are always preinstalled are:
* pamac software manager
* Ark
* xfce4-terminal
* Thunar
* pinta
* xed (texteditor)
* Fastfetch
* VLC Media Player
* loupe
* Firefox
* Many settings
* Btop, GParted, Gnome Disks
* other system related packages

# Optional packages

Optional Packages is a very long list of apps that HoppiTex uses and approves of). 
They can be installed in the settings menu under the App launcher editor.

## Social
* discord (pacman)
* ladybird (aur)

## Multimedia
* qbittorrent (pacman)
* makemkv + makemkv-libaacs (aur)
  sudo sg | sudo tee -a /etc/modules-load.d/sg.conf
* asunder (pacman)
* handbrake (pacman)

## Work
* python (pacman)
* cmake (pacman)
* vscodium-bin (aur)
* jetbrains-toolbox (aur)
* bambustudio-bin (aur)
* kdenlive (pacman)
* davinci-resolve (aur)
* audacity (pacman)
* obs-studio (pacman)
* gimp (pacman)
* qalculate-gtk (pacman)
* libreoffice-fresh (pacman)
* lmms (pacman)
* onlyoffice-bin (aur)
* docker & docker-desktop (pacman & aur)
sudo systemctl start docker
sudo systemctl enable docker
*
* For Davinci, download from official website and do this:
sudo pacman -S cuba
sudo mkdir -p /opt/resolve/libs/disabled-libraries
sudo mv /opt/resolve/libs/libglib-2.0.so* /opt/resolve/libs/disabled-libraries/
sudo mv /opt/resolve/libs/libgio-2.0.so* /opt/resolve/libs/disabled-libraries/
sudo mv /opt/resolve/libs/libgmodule-2.0.so* /opt/resolve/libs/disabled-libraries/
sudo mv /opt/resolve/libs/libgobject-2.0.so* /opt/resolve/libs/disabled-libraries/

## Drivers
* opentabletdriver (pacman)
* webcamoid (pacman)
* openrgb (aur)
  makepkg -si
* webkitgtk2 (pacman)
* cnijfilter2 (aur)
* gnome-network-displays (aur)

## Other
* timeshift (pacman)
* tailscale (pacman)
* trayscale (pacman)
* MEGA
  wget https://mega.nz/linux/repo/Arch_Extra/x86_64/megasync-x86_64.pkg.tar.zst && sudo pacman -U "$PWD/megasync-x86_64.pkg.tar.zst"
* archiso (pacman)
* clamav clamtk (pacman)
  https://wiki.archlinux.org/title/ClamAV
* theclicker (aur)

## Games
* steam (pacman)
* itch-bin (aur)
* heroic-games-launcher-bin (aur)
* mangohud (pacman)
* winetricks wine-staging wine-gecko wine-mono (pacman)
* waydroid (pacman)
* gamemode (pacman)
* lsfg-vk-bin (aur)
* bedrock-on-linux-bin (aur) 

### aur:
* openttd (pacman)
* supertuxkart (pacman)
* cubyz-bin (aur)
* prismlauncher (pacman)
* airshipper (aur)
* srb2 (aur)
* srb2kart (aur)
* [hytale-launcher-bin](https://aur.archlinux.org/packages/hytale-launcher-bin "https://aur.archlinux.org/packages/hytale-launcher-bin") (aur)

### flatpak
* flatpak install flathub org.vinegarhq.Sober
* flatpak install flathub org.vinegarhq.Vinegar

### Emulators (aur):
* stella (aur)
* bigpemu-bin (aur)
* xemu (aur)
* xenia-edge-bin (aur)
* [azaharplus-appimage](https://aur.archlinux.org/pkgbase/azaharplus-appimage) (aur)
* 3beans-git (aur)
* parallel-launcher (aur)
* cemu (aur)
* dolphin-emu (pacman)
* mesen (aur)
* mgba-qt (pacman)
* bsnes-hd (aur)
* melonds (aur)
* vita3k-bin (aur)
* rpcs3-bin (aur)
* ppsspp (pacman)
* pcsx2-latest-bin (aur)
* duckstation-preview-latest-bin (aur)
* shadps4-qtlauncher-bin (aur)
* kega-fusion (aur)
* flycast-bin (aur)
* vbam-wx (aur)
* sudo pacman -S virt-manager qemu-full libvirt dnsmasq
  sudo systemctl enable --now libvirtd
  sudo usermod -aG libvirt $USER

## Learning:
* sudo docker run -p 3000:3000 bkimminich/juice-shop 
http://localhost:3000/#/

## AI
ollama, ollama-cuda

## OBS
* obs-pipewire-audio-capture-bin (aur)
  
# Features + Theming:

### Keyboard Shortcuts:
* SUPER + Space = xfce4-terminal
* Super + F = Thunar
* Super + ^ Fullscreeen 1
* Super + Shift + ^ = Fullscreen 0
* Super + CTRL + ^ = pin app
* Super + ALT + ^ Minimize App
* Super + Tab = App Manu
* Super + ESCAPE = Power Menu
* Super + alt + tab = block waybar
* Super + Druck = Screenshot in cliphist
* Super + Shift + Druck = Screenshot in ~/Screenshots
* Super + WASD = Change active window
* Super + Shift + WASD = change active window size
* Super + CTRL + WASD = Swap windows
* Super + CTRL + WASDQEX< = snap window to one of 8 points on active display on floating environment
* Super + leftklick = Move Window
* Super + rightclick resize window
* Super + ALT + 12345 = Dwindle,Master, Scroller, Floating, Monocycle
+ Super + 1-9 = Switch workspace
+ Super + Shift + 1-9 = move active window to workspace
* Laptop Keys also work

## Performance

TrafkTux may not be the most optimised Distribution out there, but it is still leightweight compared to some other OS's!
(credits to xr7-code)

ISO size: 3.0GB

### Stats

| State | ~ RAM |
|---|---|
| Desktop no open Apps | ~1,10 GB |
| + Firefox (1–5 Tabs) | + ~ 1,35 GB |
| + Firefox (many Tabs; ~30) | + ~ 1,98 GB |
| + Thunar + Xfce4-terminal open | + ~ 0,02 GB |
| + Discord + Steam open | + ~ 1,35 GB |
(Originally, our Distro used 2GB of ram in idle, after that we got it down to 1,35gb and right now 1,1gb)
## Comparison

| System | Idle RAM (approx.) |
|---|---|
| Windows 11 | ~3.5 GB |
| Ubuntu (GNOME) | ~1.5 GB |
| **TrafkTux** | **~1,10 GB** |
| KDE Plasma | ~900 MB |
| Arch Linux with i3 | ~400–500 MB |
| SnowFoxOS | ~350–420 MB |


## Minimum Requirements:
A somewhat modern CPU+GPU / integrated graphics
4GB of ram
8GB of Disk Space

## Reccomended Specs
A mid tier cpu+gpu
16GB of ram
Enough Disk Space for yourself (8+GB)
Internet + Bluetooth + ETC capable Device


## Hyprland
Hyprland is styled with a light yellow shadow and a hyprbar where you can close, minimize, fullscreen, switch master and pin apps.
We have 5 Desktop Layouts that can be switched wich SUPER + ALT + 1-5: Dwindle, Master, Scroller, Floating, Monocle
There is full Touchscreen support! Rofi Menus, waybar, everything, even an onscreen keyboard.
There are nice snappy animation that wobble a bit.

## Waybar
We have a nice Waybar, that autohides itself as long as the mouse is up enough. You can block the waybar from showing up with SUPER + ALT + ^, wich is useful in many games and programs.
On the Left side you can activate the ROfi app and Power Menu, a workspace overview, a hide all windows button and configurable shortcuts to apps. On the Middle there you can switch between all open workspaces and apps. On the right side there are standardly 7 custom python widgets for audio, wifi, bluetooth, brightness, power/system time/calender/weather and settings. There is also a on screen keyboard button and a tray of background apps, where you can also put any app in to free up some space. With the left click you can switch to the app, right click sends it into the tray and middle click closes it.

### Widgets
1. Audio
There are 3 Tabs;
Media Devices and Apps
In Media you can see what plays at the moment, buttons for pause and next/last and the master volume
IN Devices you can select the input and output Devices
in Apps you can control the individual volume of any app
2. Internet
Here you can select all internet access points and also do a quick speed test
3. Bluetooth
Connect, disconnect, sync and delete all of your bluetooth devicces
4. Brightness
Control you screens brightness, your keyboard brightness and Nightlight intensitivity aswell (wip).
Also control every one of you rgb devices with built in openrgb!
Multimonitor support?!
5. Battery/System
Look at your percentage, Watts and change the Energyprofile.
Also some key system overview like ram, cpu, gpu, disk size, swap, etc.
6. Calender
Here you have a overview of the date, the month and so on. You can insert appointsments. The Weather is displayed above, with 2 days in advance as well and it also has a button to change the weather location.
7. Settings
Here are all of the previosly mentioned settings + extra ones, like Display, where you can change the resolution to anything you desire; want 4:3, sure, want a 144p diplay? sure! Want to downscale from 8k? please do!
Here also lies (will lie) the App Launcher Editor and also a color sceme changer and many more settings!

## Rofi
We have 2 Manus:
The Power Menu, as the name says, is where you can
* close apps
* Minimize apps
* Pin Apps
* Swap apps with master
* Border Fullscreen apps
* Exclusive Fullascreen apps
* change the layout (all 5 of them)
* Lock the PC
* Suspend the PC
* Shut it down
* reboot it
* log out
* and exit the Menu

It can be opened with SUPER + ESCAPE

The App Menu
It has 9 Folders, where you can put all of you apps in (with a custom application to do so), a folder that shows all apps not in the folders, a folder with all installs apps and a folder with all installed packages. In the 9 Main Folders, you can add as many usbfolders as you like! It can be accessed with SUPER + TAB

Both menus can be controlled with:
Arrow keys + wasd for movement
q and e for switching pages
Enter + Space + < for opening folders/apps
x for leaving the folder/menu
It also has touch support!

## Hyprpaper
* On every Startup you get a randomly selected backgroundimage from a folder in ~./config/hypr/wallpapers. you can rerandomize it in the brightness menu.

## Calamares
* For now a very barebones installer of the base Distro
You can choose
* Name
* Time
* Language
* drive
Preconfigered is the formatting (you can manually do it too), btrfs is the chosen format.

The Installer is completely offline! No Internet required!

## Theming
We have themed a lot of apps:
* Dunst
* GTK 2-3-4
* Kvantum
* HyprCursor v1
* HyprLock
* Fastfetch
* Clay Icon Theme (we changed the blue to yellow)

# What Still has to be Themed/Done:
* SDDM
* GRUB
* PLYMOUTH
* CALAMARES
* Optional Package Installer
* App Menu Folder Settings App (python + gtk)
* Mouse Cursor redesign
* Widgets Redesign!!
* App Editor
* new Kernel + security things (optimisation somewhat done)

## Known Bugs:
* The ISO does not boot at the moment.... but as this distro is still in development, this is mostly a nin issue that will be fixed sooner than later

The Internet when connected to the Distro, if you want to play a game on e.g. a switch 2 like e.g. Fortnite, the game is almost unplayable duo the lack of internet. There is a permanent yellow or red arrow. This is only if the same internet is connected to the OS. This needs to be fixed asap!!!


### Widgets to implement

* advanced brightness and night mode control for individual monitors and make the second tab be always shown to see that you have currently no things to change colour.
* In the Internet Tab add a little speed Test, nothing special, just upload, download and ping and stuff like that. That should be a second tab with a start button.
* In the Calender, add the function to delete appointments and remove the right click action
* check if lan connections show up in network + add other methods of connection + dns change + other internet security features + vpn integration maybe, but not important + later if released implement snowfoxOSv3's Mesh Connect feature.
* In settings/Display, add a hdr toggle + other hyprland display options (per monitor ofc). And fix that you cannot configure other monitors as they are not written in the config or something like that.
* Appearance + Language The Dark/Lightmode should always be changed, even if in the settings, the setting was not changed + fix not always applying the themes (gtk + kvantum, kvantum is even worse). + maybe something that makes all apps switch the theme without needing to restart them all.
* The Apps * Editor;
3. you can add/remove autostart applications (but hide the standard ones as they are essential).
2. you can add/remove the shortcuts of apps on the waybar on the "left".
1. you will be able; Rofi launcher menu, it has 9 Folders where you can put apps in. In this third menu, you will be able to drag any app + custom commands in the folders + as many subfolders in subfolders as you want. You can sort by all packages, all apps, unordered apps, custom apps, ordered apps. This will be the main menu to sort all of your apps!
