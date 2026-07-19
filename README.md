### THe Project is NOT Open Source, READ THE LICENSE for more!
Copyright © 2026 TrafkHop Entertainment™
All rights reserved.
# TrafkTux
An Arch + Hyprland based Distibution, designed soly for TrafkHop Entertainment and more specificly HoppiTex.
TrafkTux is not light weight by any means, it leans mroe on the maximalistic side, featuring many pictures as essential parts of the OS.

# Programms
The Preinstalled apps are:
* pamac software manager
* Ark
* Kitty
* Thunar
* Kolourpaint
* Kate
* Fastfetch
* VLC Media Player
* Qwenview
* Firefox
* Many settings
* Btop, GParted, Gnome Disks

# Optional packages

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
* flatpak install flathub io.mrarm.mcpelauncher

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
  
# Features + Theming:

### Keyboard Shortcuts:
* SUPER + Space = Kitty
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
* Super + ALT + 12345 = Dwindle,Master, Scroller, Floating, Monocycle
+ Super + 1-9 = Switch workspace
+ Super + Shift + 1-9 = move active window to workspace
* Laptop Keys also work

## Hyprland
Hyprland is styled with a light yellow shadow and a hyprbar where you can close, minimize, fullscreen, switch master and pin apps.
We have 5 Desktop Layouts that can be switched wich SUPER + ALT + 1-5: Dwindle, Master, Scroller, Floating, Monocle
There is Touchscreen support, but do not expect a great experience.
There are nice snappy animation that wobble a bit.

## Waybar
We have a nice Waybar, that autohides itself as long as the mouse is up enough. You can block the waybar from showing up with SUPER + ALT + ^, wich is useful in many games and programs.
On the Left side you can activate the ROfi app and Power Menu, a workspace overview, a hide all windows button and configurable shortcuts to apps. On the Middle there you can switch between all open workspaces and apps. On the right side there are 6 custom python widgets for audio, wifi, bluetooth, brightness, power and time. There is also a on screen keyboard button and a tray of background apps, where you can also put any app in to free up some space. With the left click you can switch to the app, right click sends it into the tray and middle click closes it.

### Widgets
1. Audio
There are 3 Tabs;
Media Devices and Apps
In Media you can see what plays at the moment, buttons for pause and next/last and the master volume
IN Devices you can select the input and output Devices
in Apps you can control the individual volume of any app
2. Internet
Here you can select all internet access points (password is not stored, you need to type it in every time you manually connect, so just wait a bit until it automaticly connects)
3. Bluetooth
Connect, disconnect, sync and delete all of your bluetooth devicces
4. Brightness
Control you screens brightness, your keyboard brightness and Nightlight intensitivity aswell (wip)
5. Battery
Look at your percentage and change the Energyprofile
6. Calender
Here you have a overview of the date, the month and so on. Also you can view the weather (can be changed to a better location) (wip)

## Rofi
We have 2 Manus:
The Power Menu, as the name says, is where you can
* close apps
* Minimize apps
* Pin Apps
* Swap apps with master
* Border Fullscreen apps
* Exclusive Fullascreen apps
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
* On every Startup you get a randomly selected backgroundimage from a folder in ~./config/hypr/wallpapers

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
* kitty
* Dunst
* GTK
* Kvantum (Kate, Kolourpaint, KDE apps)
* HyprCursor
* HyprLock
* Fastfetch

# What Still has to be Themed:
* SDDM
* GRUB
* PLYMOUTH
* GTK*
* CALAMARES*
* Optional Package Installer
* App Menu Folder Settings App (python + gtk)

* Add advanced brighness control to individual monitors and add a second tab for other devices with an openrgb integration wich will only open on a button press. either you can already detect all of the glowing devices and can control the brightness and color with an already running daemon or you start the app in the background when you press a button or we just implement a button wich will launch the app wich will open in the widget as a fixed object (1. preferred 3. last chance)
* Add for the calender an integration with a calender app for fast appointments, etc. and also add a button for UI location change.
* *Check Network for LAN and other methods of connectivity and implement snowfoxOS's Mesh connect.
* *Fix Brightness Nightlight mode, wich does not display after dragging the slider more than a tiny vit or multiple tomes
* Maybe advanced battery options
* Change everything to english or system language
* Add another widget called settings where you can access all of those widgets and other apps like the to be made app launcher editor and files like the hyprland.lua and some other settings like system language, preffered colour sceme and some other important apps and qol improvments that automaticly edits some system files like kvantum and nwg look or something else.
OK so the settings app is also a widget that will be at the right of the waybar. this widget will open many other widgets, the ones on the desktop and many new widgets for more advanced settings.

Some settings:
Display:
Resolution (some base res and a custom one)
Framerate
hdr
terring
other screeen options

Just think yourself......... idk settings, you can and should ask me, give me a list and ill think.

End of Notes
