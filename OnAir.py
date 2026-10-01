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


class OnAir(object):
    def __init__(self):
        self.app = rumps.App("OnAir", "⚪")

        self.menuStatus = rumps.MenuItem("Homey: not configured")
        self.app.menu.add(self.menuStatus)

        self.menuToggle = rumps.MenuItem("Turn on", callback=self.on_air)
        self.app.menu.add(self.menuToggle)

        self.app.menu.add(rumps.MenuItem("About OnAir…", callback=self.open_onair_url))

        self.args = self.parse_args()
        self.air_on = False
        self.menubar_blinker_active = False
        self.camera_state_updater_active = True

        if self.homey_configured():
            self.menuStatus.title = "Homey: ready"

    def run(self):
        threading.Thread(target=self.camera_state_updater, daemon=True).start()
        self.log(str(self.args))
        self.app.run()

    def log(self, msg):
        if self.args.debug:
            print("%s" % msg)

    @staticmethod
    def open_onair_url(callback_sender=None):
        webbrowser.open_new_tab("https://github.com/henrik242/OnAir")

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
            self.menuStatus.title = "Homey: not configured"
            self.log("homey_set() skipped: missing address/token/device")
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

    def list_devices(self):
        if not (self.args.address and self.args.token):
            print("Set address and token in ~/.onair.ini (or pass --address/--token) first.")
            return
        try:
            devices = self.homey_request("/api/manager/devices/device/")
        except (urllib.error.URLError, OSError, ValueError) as err:
            print("Could not reach Homey at %s: %s" % (self.args.address, err))
            return
        print("%-28s  %s" % ("device id", "name"))
        for devid, dev in sorted(devices.items(), key=lambda kv: kv[1].get("name", "")):
            if "onoff" in dev.get("capabilities", []):
                print("%-28s  %s" % (devid, dev.get("name", "")))

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
        homeconfig = str(Path.home()) + "/.onair.ini"

        if not os.path.isfile(homeconfig):
            shutil.copy(appconfig, homeconfig)

        config = configparser.ConfigParser()
        config.read(homeconfig)

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
