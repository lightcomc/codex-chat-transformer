#!/usr/bin/env python3
"""
Codex Sync Tray — system tray widget for controlling the sync server.

Optional component. Requires: pip install pystray Pillow

Usage:
  python sync_tray.py

Colors:
  Red    — server stopped
  Yellow — server idle, waiting for connections
  Green  — active sync in progress
"""

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("ERROR: pystray and Pillow are required.")
    print("Install: pip install pystray Pillow")
    sys.exit(1)

import codex_sync

LOCK_FILE = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sync_tray.lock"

ICON_COLORS = {
    "stopped": (243, 139, 168, 255),  # Red (#f38ba8)
    "idle":    (249, 226, 175, 255),  # Yellow (#f9e2af)
    "syncing": (166, 227, 161, 255),  # Green (#a6e3a1)
    "error":   (250, 100, 100, 255),
}


def _create_icon_image(color_rgba, size=64):
    """Generate a solid-color circle icon using Pillow."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color_rgba)
    return img


def _check_single_instance():
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            os.kill(pid, 0)
            print("Another instance is already running (PID {}).".format(pid))
            sys.exit(0)
        except (ProcessLookupError, ValueError, PermissionError):
            pass
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))


def _remove_lock():
    try:
        if LOCK_FILE.exists():
            pid = int(LOCK_FILE.read_text().strip())
            if pid == os.getpid():
                LOCK_FILE.unlink()
    except Exception:
        pass


class SyncTrayApp:
    def __init__(self):
        self._server = None
        self._pin = ""
        self._port = 0
        self._icon = None
        self._status = "stopped"
        self._autorun = self._read_autorun()
        self._beacon_thread = None
        self._poll_thread = None

    def _create_menu(self):
        return pystray.Menu(
            pystray.MenuItem("Start Server", self._toggle_server),
            pystray.MenuItem("Open Dashboard", self._open_dashboard, enabled=self._is_server_running),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Autorun on startup", self._toggle_autorun, checked=lambda item: self._autorun),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        )

    def _is_server_running(self, item):
        return self._server is not None

    def _toggle_server(self, icon, item):
        if self._server:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        try:
            server, pin, port = codex_sync.start_server(port=None)
            self._server = server
            self._pin = pin
            self._port = port
            self._status = "idle"
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self._update_icon()
            self._update_tooltip()
            self._start_beacon()
            self._start_status_poll()
        except Exception as e:
            self._status = "error"
            self._update_icon()
            if self._icon:
                self._icon.notify("Failed to start: {}".format(e))
            print("Server start error:", e)

    def _stop_server(self):
        if self._server:
            codex_sync.stop_server(self._server)
            self._server = None
            self._status = "stopped"
            self._update_icon()
            self._update_tooltip()
        if self._beacon_thread and self._beacon_thread.is_alive():
            self._beacon_thread = None
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread = None

    def _open_dashboard(self, icon, item):
        if self._port:
            webbrowser.open("http://127.0.0.1:{}/dashboard".format(self._port))

    def _toggle_autorun(self, icon, item):
        self._autorun = not self._autorun
        if self._autorun:
            self._enable_autorun()
        else:
            self._disable_autorun()

    def _exit(self, icon, item):
        self._stop_server()
        _remove_lock()
        icon.stop()

    def _update_icon(self):
        if not self._icon:
            return
        color = ICON_COLORS.get(self._status, ICON_COLORS["stopped"])
        try:
            self._icon.icon = _create_icon_image(color)
        except Exception:
            pass

    def _update_tooltip(self):
        if not self._icon:
            return
        if self._status == "stopped":
            self._icon.title = "Codex Sync: Stopped"
        elif self._status == "idle":
            ip = codex_sync.get_local_ip()
            self._icon.title = "Codex Sync: {}:{} PIN: {}".format(ip, self._port, self._pin)
        elif self._status == "syncing":
            self._icon.title = "Codex Sync: Syncing..."
        else:
            self._icon.title = "Codex Sync: Error"

    def _start_beacon(self):
        if not self._server:
            return
        try:
            self._beacon_thread = threading.Thread(
                target=codex_sync.start_beacon,
                args=(self._port, self._pin),
                daemon=True,
            )
            self._beacon_thread.start()
        except Exception:
            pass

    def _start_status_poll(self):
        """Background thread: check data_changed flag, update icon color."""

        def _poll():
            while self._server:
                try:
                    if codex_sync.data_changed:
                        codex_sync.data_changed = False
                        self._status = "syncing"
                        self._update_icon()
                        self._update_tooltip()
                        time.sleep(2)
                        self._status = "idle"
                        self._update_icon()
                        self._update_tooltip()
                except Exception:
                    pass
                time.sleep(1)

        self._poll_thread = threading.Thread(target=_poll, daemon=True)
        self._poll_thread.start()

    # ── Autorun ───────────────────────────────────────────────────────────

    def _read_autorun(self):
        import platform
        if platform.system() == "Windows":
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     r"Software\Microsoft\Windows\CurrentVersion\Run",
                                     0, winreg.KEY_READ)
                val, _ = winreg.QueryValueEx(key, "CodexSyncTray")
                key.Close()
                return True
            except (WindowsError, OSError):
                return False
        elif platform.system() == "Darwin":
            plist = Path.home() / "Library/LaunchAgents/com.codex.synctray.plist"
            return plist.exists()
        return False

    def _enable_autorun(self):
        import platform
        if platform.system() == "Windows":
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     r"Software\Microsoft\Windows\CurrentVersion\Run",
                                     0, winreg.KEY_WRITE)
                script = str(Path(__file__).resolve())
                python_exe = sys.executable
                winreg.SetValueEx(key, "CodexSyncTray", 0, winreg.REG_SZ,
                                  '"{}" "{}"'.format(python_exe, script))
                key.Close()
            except Exception as e:
                print("Autorun enable error:", e)
        elif platform.system() == "Darwin":
            plist_content = '<?xml version="1.0" encoding="UTF-8"?>\n' \
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"' \
                ' "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n' \
                '<plist version="1.0"><dict>' \
                '<key>Label</key><string>com.codex.synctray</string>' \
                '<key>ProgramArguments</key><array>' \
                '<string>{}</string><string>{}</string>' \
                '</array><key>RunAtLoad</key><true/></dict></plist>'.format(
                    sys.executable, Path(__file__).resolve())
            plist_path = Path.home() / "Library/LaunchAgents/com.codex.synctray.plist"
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(plist_content)

    def _disable_autorun(self):
        import platform
        if platform.system() == "Windows":
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     r"Software\Microsoft\Windows\CurrentVersion\Run",
                                     0, winreg.KEY_WRITE)
                winreg.DeleteValue(key, "CodexSyncTray")
                key.Close()
            except (WindowsError, OSError):
                pass
        elif platform.system() == "Darwin":
            plist = Path.home() / "Library/LaunchAgents/com.codex.synctray.plist"
            if plist.exists():
                plist.unlink()

    # ── Run ───────────────────────────────────────────────────────────────

    def run(self):
        _check_single_instance()
        icon_image = _create_icon_image(ICON_COLORS["stopped"])
        self._icon = pystray.Icon(
            "codex_sync",
            icon=icon_image,
            title="Codex Sync: Stopped",
            menu=self._create_menu(),
        )
        try:
            self._icon.run()
        finally:
            _remove_lock()


if __name__ == "__main__":
    app = SyncTrayApp()
    app.run()
