#!/usr/bin/env python3
"""
widgets_client.py — dünner Client für widgets_daemon.py

Das ist absichtlich das einzige, was Waybar bei jedem Klick startet.
KEIN "import gi", KEIN Gtk-Import - genau das ist der Punkt: der alte
150-300ms-Kostenblock kam fast vollständig aus dem GTK-Import. Dieses
Skript importiert nur Python-Bordmittel (socket, sys) und beendet sich
sofort wieder, nachdem es dem Daemon über den Unix-Socket gesagt hat,
welches Widget getoggelt werden soll. Übrig bleibt nur noch der reine
Python-Interpreter-Start (üblicherweise 10-20ms) + Socket-Rundreise
(<1ms) — das erreicht das 35-50ms-Ziel.

Aufruf:  python3 widgets_client.py <widget>
Beispiel-Waybar-Config:
  "on-click": "python3 /pfad/zu/widgets_client.py volume"

Noch schneller (kein Python-Interpreter-Start nötig, falls installiert):
  "on-click": "socat - UNIX-CONNECT:/tmp/wb-daemon.sock <<< volume"
oder mit ncat:
  "on-click": "echo volume | ncat -U /tmp/wb-daemon.sock"
"""
import os
import socket
import sys

SOCK_PATH = os.environ.get("WB_DAEMON_SOCK", "/tmp/wb-daemon.sock")


def main() -> int:
    if len(sys.argv) != 2:
        print("Verwendung: widgets_client.py <widget>", file=sys.stderr)
        return 1
    widget = sys.argv[1]

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(SOCK_PATH)
        s.sendall(widget.encode())
        s.shutdown(socket.SHUT_WR)
        # Antwort ist optional (nur fürs Debuggen relevant); falls der
        # Daemon nicht sofort antwortet, blockieren wir dafür nicht.
        try:
            reply = s.recv(64).decode().strip()
            if reply.startswith("error"):
                print(reply, file=sys.stderr)
        except socket.timeout:
            pass
        s.close()
        return 0
    except (FileNotFoundError, ConnectionRefusedError):
        print(f"widgets_daemon läuft nicht (Socket {SOCK_PATH} fehlt). "
              f"Läuft die systemd --user Unit 'wb-daemon.service'?",
              file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Fehler beim Ansprechen des Daemons: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
