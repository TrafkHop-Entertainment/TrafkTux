#!/bin/sh
# Baut den Daemon (benoetigt gcc, pkgconf, libevdev). Binary landet neben der Quelle.
cd "$(dirname "$0")" && gcc -O2 -Wall -Wextra -o TrafkPad TrafkPad.c $(pkg-config --cflags --libs libevdev) -lm
