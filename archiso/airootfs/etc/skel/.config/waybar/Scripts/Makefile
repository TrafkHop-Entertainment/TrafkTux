CC      = gcc
CFLAGS  = -Wall -Wextra -O2 $(shell pkg-config --cflags dbus-1)
LDFLAGS = $(shell pkg-config --libs dbus-1) -lpthread

TARGET  = ScreenRotationDaemon
SRC     = ScreenRotationDaemon.c

INSTALL_DIR = $(HOME)/.config/waybar/Scripts
SERVICE_DIR = $(HOME)/.config/systemd/user
SERVICE     = ScreenRotationDaemon.service

.PHONY: all clean install uninstall

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $(TARGET) $(SRC) $(LDFLAGS)

# Baut UND installiert die Binary + den systemd-User-Service dorthin, wo
# ScreenRotationDaemon.service sie erwartet (%h/.config/waybar/Scripts/
# ScreenRotationDaemon). Vorher gab's nur "all", das die Binary bloss im
# aktuellen Verzeichnis abgelegt hat - der Service-File-Pfad zeigte
# dadurch ins Leere, ExecStart lief nie an (deshalb u.a. leere
# journalctl-Ausgabe: der Daemon wurde nie gestartet, nicht mal versucht).
install: $(TARGET)
	mkdir -p $(INSTALL_DIR)
	install -m 755 $(TARGET) $(INSTALL_DIR)/$(TARGET)
	mkdir -p $(SERVICE_DIR)
	install -m 644 $(SERVICE) $(SERVICE_DIR)/$(SERVICE)
	systemctl --user daemon-reload
	@echo "Installiert. Aktivieren mit:"
	@echo "  systemctl --user enable --now ScreenRotationDaemon.service"

uninstall:
	systemctl --user disable --now ScreenRotationDaemon.service 2>/dev/null || true
	rm -f $(INSTALL_DIR)/$(TARGET)
	rm -f $(SERVICE_DIR)/$(SERVICE)
	systemctl --user daemon-reload

clean:
	rm -f $(TARGET)
