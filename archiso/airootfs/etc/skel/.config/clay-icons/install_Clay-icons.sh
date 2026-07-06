#!/bin/bash

sudo cp -r ~/.config/clay-icons/Clay  /usr/share/icons/
sudo cp -r ~/.config/clay-icons/Clay-Light  /usr/share/icons/
sudo cp -r ~/.config/clay-icons/Clay-Dark  /usr/share/icons/

sudo gtk-update-icon-cache /usr/share/icons/Clay
sudo gtk-update-icon-cache /usr/share/icons/Clay-Light
sudo gtk-update-icon-cache /usr/share/icons/Clay-Dark
