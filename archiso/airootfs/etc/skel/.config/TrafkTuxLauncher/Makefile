CC = gcc
PKGS = gtk+-3.0 json-glib-1.0 gio-2.0 gio-unix-2.0

HAS_LAYER_SHELL := $(shell pkg-config --exists gtk-layer-shell-0 && echo yes)

ifeq ($(HAS_LAYER_SHELL),yes)
    PKGS += gtk-layer-shell-0
    EXTRA_CFLAGS = -DHAVE_LAYER_SHELL
endif

CFLAGS = -O2 -Wall $(EXTRA_CFLAGS) $(shell pkg-config --cflags $(PKGS))
LDFLAGS = $(shell pkg-config --libs $(PKGS)) -lm

TARGET = TrafkTuxLauncher
SRC = TrafkTuxLauncher.c

all: $(TARGET)
	@if [ "$(HAS_LAYER_SHELL)" = "yes" ]; then \
		echo "-> mit gtk-layer-shell gebaut (Wayland-Overlay, exklusiver Keyboard-Fokus)"; \
	else \
		echo "-> OHNE gtk-layer-shell gebaut (Fallback: normales Dialogfenster)."; \
		echo "   Für echtes Layer-Shell-Overlay: 'gtk-layer-shell'-Dev-Paket installieren, dann neu bauen."; \
	fi

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $< -o $@ $(LDFLAGS)

clean:
	rm -f $(TARGET)

.PHONY: all clean
