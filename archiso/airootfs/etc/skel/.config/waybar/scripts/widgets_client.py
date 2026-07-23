#!/usr/bin/env python3
"""
widgets_client.py — thin client for widgets_daemon.py

This is intentionally the only script Waybar launches on click.
NO "import gi", NO GTK imports — keeping overhead strictly minimal (10-20ms).

Usage:  python3 widgets_client.py <widget>
Example Waybar config:
  "on-click": "python3 /path/to/widgets_client.py volume"
"""
import os
import socket
import sys

SOCK_PATH = os.environ.get("WB_DAEMON_SOCK", "/tmp/wb-daemon.sock")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: widgets_client.py <widget>", file=sys.stderr)
        return 1
    widget = sys.argv[1]

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(SOCK_PATH)
        s.sendall(widget.encode())
        s.shutdown(socket.SHUT_WR)
        try:
            reply = s.recv(64).decode().strip()
            if reply.startswith("error"):
                print(reply, file=sys.stderr)
        except socket.timeout:
            pass
        s.close()
        return 0
    except (FileNotFoundError, ConnectionRefusedError):
        print(f"widgets_daemon is not running (Socket {SOCK_PATH} missing). "
              f"Is the systemd --user unit 'wb-daemon.service' running?",
              file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error communicating with daemon: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())