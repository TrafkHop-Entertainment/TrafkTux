# Makefile für SoundCenter (SoundDaemon + SoundControl).
#
# Bewusst KEIN "install"-Target - wohin die beiden Binaries kopiert werden,
# ist komplett dir überlassen (ArchISO/eigenes Overlay etc.). Einzige
# Voraussetzung: beide müssen über $PATH auffindbar sein, wenn sie
# aufgerufen werden (siehe README.md, Abschnitt "Platzierung").
#
# Build-Abhängigkeiten (nur zum Kompilieren, Laufzeit braucht nur die
# .so-Dateien, die durch ein funktionierendes pw-play sowieso schon da
# sind):
#   Arch:          pacman -S pipewire libvorbis base-devel pkgconf
#   Debian/Ubuntu: apt install libpipewire-0.3-dev libspa-0.2-dev libvorbis-dev build-essential pkg-config

CC       ?= gcc
CFLAGS   ?= -O2 -Wall -Wextra -std=gnu11 -Wno-format-truncation -Wno-stringop-truncation
PW_CFLAGS   := $(shell pkg-config --cflags libpipewire-0.3)
PW_LIBS     := $(shell pkg-config --libs libpipewire-0.3)
VORBIS_LIBS := $(shell pkg-config --libs vorbisfile)

.PHONY: all clean

all: SoundDaemon SoundControl

SoundDaemon: src/SoundDaemon.c
	$(CC) $(CFLAGS) $(PW_CFLAGS) -o $@ $< $(PW_LIBS) $(VORBIS_LIBS)

SoundControl: src/SoundControl.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f SoundDaemon SoundControl
