#!/usr/bin/env python3

import argparse
import configparser
import json
import os
import platform
import re
import shutil
import ssl
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import rumps

macos_version = int(platform.mac_ver()[0].split(".")[0])

HOMECONFIG = str(Path.home()) + "/.onair.ini"


class OnAir(object):
    def __init__(self):
        self.args = self.parse_args()
        self.air_on = False
        self.menubar_blinker_active = False
        self.camera_state_updater_active = True

        self.app = rumps.App("OnAir", "⚪")

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

    def menubar_blinker(self):
        self.log("menubar_blinker()")
        green = True
        while self.menubar_blinker_active:
            self.app.title = "🟢" if green else "⚪️"
            time.sleep(1)
            green = not green
        self.app.title = "⚪"
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
            self.menuStatus.title = "Homey: not found (use Set Homey address…)"
            self.log("no Homey found on network")

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

    def quit(self):
        self.menubar_blinker_active = False
        self.camera_state_updater_active = False
        rumps.quit_application()

    def camera_state_updater(self):
        self.log("camera_state_updater()")

        predicate = 'subsystem == "com.apple.UVCExtension" and composedMessage contains "Post PowerLog"'
        extraopts = ""
        searchexpr = "guid:(.+)]"
        onitem = "Start"
        offitem = "Stop"
        if macos_version == 12:
            predicate = 'eventMessage contains "Post event kCameraStream"'
            extraopts = "--style ndjson"
            searchexpr = 'VDCAssistant_Device_GUID\\\\" = \\\\"(.+)\\\\";'
            onitem = "= On;"
            offitem = "= Off;"
        if macos_version >= 13:
            predicate = 'eventMessage contains "Cameras changed to"'
            extraopts = "--style ndjson"
            # The message lists every camera and can be long enough that the unified
            # log truncates it with "<…>", so don't require the closing bracket here.
            searchexpr = r"Cameras changed to (\[.*)"
            onitem = "to [ControlCenter"
            offitem = "to []"

        log_stream = os.popen("""/usr/bin/log stream %s --predicate '%s'""" % (extraopts, predicate), "r")
        cameras = dict()

        while self.camera_state_updater_active:
            item = log_stream.readline()
            self.log("reading '%s'" % item.strip())

            if item == "":
                self.log("log stream died")
                break

            match = re.search(searchexpr, item)
            if match is not None:
                if macos_version < 13:
                    device = match.group(1)
                else:
                    device = "dummy"

                if onitem in item:
                    cameras[device] = True
                elif offitem in item:
                    cameras[device] = False
                else:
                    self.log("Unknown activity: %s" % item)

                self.log(cameras)
                if any(cameras.values()):
                    self.log("Camera %s is on" % device)
                    self.on_air()
                else:
                    self.log("Camera %s is off" % device)
                    self.off_air()

        self.quit()

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
