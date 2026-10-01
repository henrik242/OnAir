#!/usr/bin/env python3

import argparse
import configparser
import ctypes
import ctypes.util
import json
import os
import shutil
import ssl
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import rumps

HOMECONFIG = str(Path.home()) + "/.onair.ini"

# Idle icon is a transparent "On Air" silhouette shown as a template (recoloured
# to match the menubar). Active icon is the full-colour red logo. The colour logo
# cannot be used as a template because its background is opaque, which would mask
# to a solid square.
ICON_IDLE = "onair-template.png"
ICON_ACTIVE = "onair.png"


# --- camera usage via CoreMediaIO -------------------------------------------
#
# Ask CoreMediaIO whether any camera is in use by any process. This is reliable
# across macOS versions and needs no camera permission, unlike scraping the
# unified log, whose "Cameras changed to" message cannot distinguish on from off
# on macOS 26+ (it lists the same cameras either way and never reports an empty
# set when a camera is released).


class _CMIOAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


def _fourcc(code):
    return (ord(code[0]) << 24) | (ord(code[1]) << 16) | (ord(code[2]) << 8) | ord(code[3])


_CMIO_SYSTEM_OBJECT = 1
_CMIO_SCOPE_GLOBAL = _fourcc("glob")
_CMIO_PROP_DEVICES = _fourcc("dev#")
_CMIO_PROP_IS_RUNNING_SOMEWHERE = _fourcc("gone")

_cmio_lib = None


def _cmio():
    global _cmio_lib
    if _cmio_lib is None:
        lib = ctypes.CDLL("/System/Library/Frameworks/CoreMediaIO.framework/CoreMediaIO")
        ptr_addr = ctypes.POINTER(_CMIOAddress)
        u32 = ctypes.c_uint32
        pu32 = ctypes.POINTER(u32)
        lib.CMIOObjectGetPropertyDataSize.argtypes = [u32, ptr_addr, u32, ctypes.c_void_p, pu32]
        lib.CMIOObjectGetPropertyData.argtypes = [u32, ptr_addr, u32, ctypes.c_void_p, u32, pu32, ctypes.c_void_p]
        _cmio_lib = lib
    return _cmio_lib


def _cmio_devices(lib):
    addr = _CMIOAddress(_CMIO_PROP_DEVICES, _CMIO_SCOPE_GLOBAL, 0)
    size = ctypes.c_uint32(0)
    if lib.CMIOObjectGetPropertyDataSize(_CMIO_SYSTEM_OBJECT, ctypes.byref(addr), 0, None, ctypes.byref(size)) != 0:
        return []
    count = size.value // ctypes.sizeof(ctypes.c_uint32)
    if count == 0:
        return []
    ids = (ctypes.c_uint32 * count)()
    used = ctypes.c_uint32(0)
    if lib.CMIOObjectGetPropertyData(_CMIO_SYSTEM_OBJECT, ctypes.byref(addr), 0, None, size, ctypes.byref(used), ids) != 0:
        return []
    return list(ids)


def any_camera_in_use():
    lib = _cmio()
    addr = _CMIOAddress(_CMIO_PROP_IS_RUNNING_SOMEWHERE, _CMIO_SCOPE_GLOBAL, 0)
    for device in _cmio_devices(lib):
        value = ctypes.c_uint32(0)
        used = ctypes.c_uint32(0)
        status = lib.CMIOObjectGetPropertyData(device, ctypes.byref(addr), 0, None, 4, ctypes.byref(used), ctypes.byref(value))
        if status == 0 and value.value:
            return True
    return False


class OnAir(object):
    def __init__(self):
        self.args = self.parse_args()
        self.air_on = False
        self.menubar_blinker_active = False
        self.camera_state_updater_active = True

        # Monochrome "On Air" silhouette when idle; the blinker flips to the
        # full-colour red logo while a camera is on, like an on-air sign lighting up.
        self.app = rumps.App("OnAir", icon=ICON_IDLE, template=True)

        self.menuStatus = rumps.MenuItem("Homey: not configured")
        self.menuToggle = rumps.MenuItem("Turn on", callback=self.on_air)
        self.menuDetect = rumps.MenuItem("Detect Homey on network", callback=self.detect_homey)
        self.menuAddress = rumps.MenuItem("Set Homey address…", callback=self.set_address)
        self.menuToken = rumps.MenuItem("Set token…", callback=self.set_token)
        self.menuLight = rumps.MenuItem("Choose light")

        self.app.menu = [
            self.menuStatus,
            rumps.separator,
            self.menuToggle,
            rumps.separator,
            self.menuDetect,
            self.menuAddress,
            self.menuToken,
            self.menuLight,
            rumps.separator,
            rumps.MenuItem("About OnAir…", callback=self.open_onair_url),
        ]

        self.update_status()

    def run(self):
        threading.Thread(target=self.camera_state_updater, daemon=True).start()
        threading.Thread(target=self.refresh_lights, daemon=True).start()
        self.log(str(self.args))
        self.app.run()

    def log(self, msg):
        if self.args.debug:
            print("%s" % msg)

    @staticmethod
    def open_onair_url(callback_sender=None):
        webbrowser.open_new_tab("https://github.com/henrik242/OnAir")

    # --- camera / light state -------------------------------------------------

    def on_air(self, callback_sender=None):
        if self.air_on:
            return
        self.air_on = True
        self.log("on_air()")
        self.homey_set(True)

        self.menubar_blinker_active = True
        threading.Thread(target=self.menubar_blinker, daemon=True).start()

        self.menuToggle.title = "Turn off"
        self.menuToggle.set_callback(callback=self.off_air)
        self.log("on_air() done")

    def off_air(self, callback_sender=None):
        if not self.air_on:
            return
        self.air_on = False
        self.log("off_air()")
        self.homey_set(False)

        self.menubar_blinker_active = False

        self.menuToggle.title = "Turn on"
        self.menuToggle.set_callback(callback=self.on_air)
        self.log("off_air() done")

    def _show_idle_icon(self):
        self.app.template = True
        self.app.icon = ICON_IDLE

    def _show_active_icon(self):
        self.app.template = False
        self.app.icon = ICON_ACTIVE

    def menubar_blinker(self):
        self.log("menubar_blinker()")
        lit = True
        while self.menubar_blinker_active:
            self._show_active_icon() if lit else self._show_idle_icon()
            time.sleep(1)
            lit = not lit
        self._show_idle_icon()
        self.log("menubar_blinker() done")

    # --- Homey local API ------------------------------------------------------

    def homey_configured(self):
        return bool(self.args.address and self.args.token and self.args.device)

    def homey_request(self, path, method="GET", body=None):
        address = self.args.address
        if "://" not in address:
            address = "http://" + address
        url = address.rstrip("/") + path
        headers = {"Authorization": "Bearer %s" % self.args.token}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        # Homey Pro's local HTTPS uses a self-signed cert; the Bearer token is the
        # real authentication, so skip cert verification when talking to it directly.
        context = ssl._create_unverified_context() if url.startswith("https") else None
        with urllib.request.urlopen(req, timeout=5, context=context) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else None

    def homey_set(self, on):
        self.log("homey_set(%s)" % on)
        if not self.homey_configured():
            self.update_status()
            self.log("homey_set() skipped: not fully configured")
            return
        try:
            self.homey_request(
                "/api/manager/devices/device/%s/capability/onoff" % self.args.device,
                method="PUT",
                body={"value": bool(on)},
            )
            self.menuStatus.title = "Homey: connected"
            self.log("homey_set() done")
        except (urllib.error.URLError, OSError, ValueError) as err:
            self.menuStatus.title = "Homey: error (%s)" % err
            self.log("homey_set() failed: %s" % err)

    def homey_onoff_devices(self):
        """Return a sorted list of (name, device_id) for devices with an onoff capability."""
        devices = self.homey_request("/api/manager/devices/device/")
        found = []
        for devid, dev in (devices or {}).items():
            if "onoff" in dev.get("capabilities", []):
                found.append((dev.get("name", "") or devid, devid))
        return sorted(found)

    # --- network discovery ----------------------------------------------------

    @staticmethod
    def discover_homey(timeout=5):
        """Find a Homey Pro via mDNS (_homey._tcp) and return its address, or None.

        Prefers the advertised hostname (homey-<id>.local), which stays valid
        across DHCP lease changes, and falls back to the raw IP address.
        """
        try:
            from zeroconf import ServiceBrowser, Zeroconf
        except ImportError:
            return None

        class _Listener:
            def __init__(self):
                self.name = None
                self.type = None
                self.found = threading.Event()

            def add_service(self, zc, type_, name):
                self.type, self.name = type_, name
                self.found.set()

            def update_service(self, zc, type_, name):
                pass

            def remove_service(self, zc, type_, name):
                pass

        zeroconf = Zeroconf()
        listener = _Listener()
        try:
            ServiceBrowser(zeroconf, "_homey._tcp.local.", listener)
            if not listener.found.wait(timeout):
                return None
            info = zeroconf.get_service_info(listener.type, listener.name, timeout=int(timeout * 1000))
        finally:
            zeroconf.close()

        if not info:
            return None
        host = (info.server or "").rstrip(".")
        if not host:
            addresses = info.parsed_addresses()
            host = addresses[0] if addresses else ""
        if not host:
            return None
        return host if info.port in (80, None) else "%s:%d" % (host, info.port)

    # --- menu actions ---------------------------------------------------------

    def detect_homey(self, _=None):
        self.menuStatus.title = "Homey: searching…"
        threading.Thread(target=self._detect_worker, daemon=True).start()

    def _detect_worker(self):
        address = self.discover_homey()
        if address:
            self.args.address = address
            self.save_config()
            self.log("discovered Homey at %s" % address)
            self.refresh_lights()
        else:
            self.menuStatus.title = "Homey: not found"
            self.log("no Homey found on network")
        # NSAlert must run on the main thread.
        from PyObjCTools import AppHelper

        AppHelper.callAfter(self._detect_alert, address)

    @staticmethod
    def _detect_alert(address):
        if address:
            rumps.alert(title="OnAir", message="Found Homey at\n%s" % address)
        else:
            rumps.alert(
                title="OnAir",
                message="No Homey found on the network.\nUse 'Set Homey address…' to enter it manually.",
            )

    def set_address(self, _=None):
        response = rumps.Window(
            message="Homey Pro IP address or hostname:",
            title="Homey address",
            default_text=self.args.address or "",
            ok="Save",
            cancel="Cancel",
            dimensions=(360, 24),
        ).run()
        if response.clicked:
            self.args.address = response.text.strip()
            self.save_config()
            self.refresh_lights()

    def set_token(self, _=None):
        response = rumps.Window(
            message="Paste your Homey Personal Access Token\n(my.homey.app -> Settings -> API keys):",
            title="Homey token",
            default_text=self.args.token or "",
            ok="Save",
            cancel="Cancel",
            dimensions=(480, 24),
        ).run()
        if response.clicked:
            self.args.token = response.text.strip()
            self.save_config()
            self.refresh_lights()

    def refresh_lights(self):
        """Rebuild the 'Choose light' submenu from the devices on the Homey."""
        # clear() touches the underlying NSMenu, which only exists once something
        # has been added, so guard the first (empty) rebuild.
        if len(self.menuLight):
            self.menuLight.clear()
        if not (self.args.address and self.args.token):
            self.menuLight.add(rumps.MenuItem("(set address and token first)"))
            self.update_status()
            return
        try:
            devices = self.homey_onoff_devices()
        except (urllib.error.URLError, OSError, ValueError) as err:
            self.menuLight.add(rumps.MenuItem("(could not reach Homey)"))
            self.menuStatus.title = "Homey: error (%s)" % err
            self.log("refresh_lights() failed: %s" % err)
            return
        if not devices:
            self.menuLight.add(rumps.MenuItem("(no on/off devices found)"))
        for name, devid in devices:
            item = rumps.MenuItem(name, callback=self.choose_light)
            item._devid = devid
            item.state = 1 if devid == self.args.device else 0
            self.menuLight.add(item)
        self.update_status()

    def choose_light(self, sender):
        self.args.device = getattr(sender, "_devid", None)
        self.save_config()
        for item in self.menuLight.values():
            item.state = 1 if getattr(item, "_devid", None) == self.args.device else 0
        self.log("selected device %s" % self.args.device)
        self.update_status()

    def update_status(self):
        if self.homey_configured():
            self.menuStatus.title = "Homey: ready (%s)" % self.args.address
        elif not self.args.address:
            self.menuStatus.title = "Homey: find or set an address"
        elif not self.args.token:
            self.menuStatus.title = "Homey: set a token"
        else:
            self.menuStatus.title = "Homey: choose a light"

    def save_config(self):
        config = configparser.ConfigParser()
        config.read(HOMECONFIG)
        config["DEFAULT"]["address"] = self.args.address or ""
        config["DEFAULT"]["token"] = self.args.token or ""
        config["DEFAULT"]["device"] = self.args.device or ""
        config["DEFAULT"]["debug"] = str(self.args.debug)
        with open(HOMECONFIG, "w") as handle:
            config.write(handle)
        self.log("saved config to %s" % HOMECONFIG)

    def list_devices(self):
        if not (self.args.address and self.args.token):
            print("Set address and token in ~/.onair.ini (or pass --address/--token) first.")
            return
        try:
            devices = self.homey_onoff_devices()
        except (urllib.error.URLError, OSError, ValueError) as err:
            print("Could not reach Homey at %s: %s" % (self.args.address, err))
            return
        print("%-28s  %s" % ("device id", "name"))
        for name, devid in devices:
            print("%-28s  %s" % (devid, name))

    def camera_state_updater(self):
        self.log("camera_state_updater() polling CoreMediaIO")
        while self.camera_state_updater_active:
            try:
                in_use = any_camera_in_use()
            except OSError as err:
                self.log("camera poll failed: %s" % err)
                in_use = self.air_on
            if in_use:
                self.on_air()
            else:
                self.off_air()
            time.sleep(1)

    @staticmethod
    def parse_args():
        appconfig = ".onair.ini"

        if not os.path.isfile(HOMECONFIG):
            shutil.copy(appconfig, HOMECONFIG)

        config = configparser.ConfigParser()
        config.read(HOMECONFIG)

        address = config.get("DEFAULT", "address", fallback=None)
        token = config.get("DEFAULT", "token", fallback=None)
        device = config.get("DEFAULT", "device", fallback=None)
        debug = config.getboolean("DEFAULT", "debug", fallback=False)

        parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument("--address", help="Homey Pro local IP or hostname", default=address)
        parser.add_argument("--token", help="Homey Personal Access Token", default=token)
        parser.add_argument("--device", help="Homey device id of the light", default=device)
        parser.add_argument("--list-devices", action="store_true", help="List on/off devices and exit")
        parser.add_argument("--debug", action="store_true", help=" ", default=debug)
        return parser.parse_args()


if __name__ == "__main__":
    app = OnAir()
    if app.args.list_devices:
        app.list_devices()
    else:
        app.run()
