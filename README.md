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
* discord
* ladybird (yay)
## Multimedia
* qbittorrent
* makemkv + makemkv-libaacs (yay)
  sudo sg | sudo tee -a /etc/modules-load.d/sg.conf
* asunder
* handbrake
## Work
* python
* cmake
* vscodium-bin
* jetbrains-toolbox
* bambustudio-bin
* kdenlive
* davinci-resolve (aur)
* audacity
* obs-studio
* gimp
* qalculate-gtk
* libreoffice-fresh
* onlyoffice-bin (aur)
* docker & docker-desktop(yay) &
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
## drivers
* opentabletdriver
* webcamoid
* openrgb
  makepkg -si
* webkitgtk2
* cnijfilter2 (yay)
* gnome-network-displays (yay)
## other
* timeshift
* tailscale
* trayscale
* MEGA
  wget https://mega.nz/linux/repo/Arch_Extra/x86_64/megasync-x86_64.pkg.tar.zst && sudo pacman -U "$PWD/megasync-x86_64.pkg.tar.zst"
* archiso
* clamav clamtk
  https://wiki.archlinux.org/title/ClamAV
* theclicker (aur)
## Games
* steam
* itch-bin
* heroic-games-launcher-bin
* mangohud
* winetricks wine-staging wine-gecko wine-mono
* waydroid
* gamemode
* lsfg-vk-git  
### yay:  
* openttd
* supertuxkart-git
* cubyz-bin
* prismlauncher
* airshipper
* srb2
* srb2kart
* [hytale-launcher-bin](https://aur.archlinux.org/packages/hytale-launcher-bin "https://aur.archlinux.org/packages/hytale-launcher-bin")
### flatpak
* flatpak install flathub org.vinegarhq.Sober  
* flatpak install flathub org.vinegarhq.Vinegar
* flatpak install flathub io.mrarm.mcpelauncher
### Emulators (yay):  
* stella
* bigpemu-bin 
* xemu
* xenia-edge-bin
* [azaharplus-appimage](https://aur.archlinux.org/pkgbase/azaharplus-appimage)
* 3beans-git
* parallel-launcher  
* cemu  
* dolphin-emu (pacman)
* mesen
* mgba-qt-git
* bsnes-hd
* melonds
* vita3k-git
* rpcs3-bin
* ppsspp-git
* pcsx2-git
* duckstation-preview-latest-bin
* shadps4-qtlauncher-bin
* kega-fusion
* flycast-git
* vbam-wx
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
* Fix Weather Menu
* WOrkspace Overview
* Hide All Windows / Bring all windows Back
