#!/usr/bin/env python3

from __future__ import annotations

import argparse
import configparser
import ctypes
import ctypes.util
import json
import os
import shutil
import signal
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import objc
import rumps
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSImage,
    NSImageView,
    NSLineBreakByCharWrapping,
    NSLinkAttributeName,
    NSMakeRect,
    NSMenuItem,
    NSPanel,
    NSPopUpButton,
    NSTextAlignmentCenter,
    NSTextAlignmentRight,
    NSTextField,
    NSTextView,
    NSView,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRange, NSMutableAttributedString, NSObject
from PyObjCTools import AppHelper
from rumps.text_field import Editing

HOMECONFIG = str(Path.home()) + "/.onair.ini"

# Idle icon is a transparent "On Air" silhouette shown as a template (recoloured
# to match the menubar). Active icon is the full-colour red logo. The colour logo
# cannot be used as a template because its background is opaque, which would mask
# to a solid square.
ICON_IDLE = "onair-template.png"
ICON_ACTIVE = "onair.png"

VERSION = "3.0.3"
GITHUB_URL = "https://github.com/henrik242/OnAir"


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


def _fourcc(code: str) -> int:
    return (ord(code[0]) << 24) | (ord(code[1]) << 16) | (ord(code[2]) << 8) | ord(code[3])


_CMIO_SYSTEM_OBJECT = 1
_CMIO_SCOPE_GLOBAL = _fourcc("glob")
_CMIO_PROP_DEVICES = _fourcc("dev#")
_CMIO_PROP_IS_RUNNING_SOMEWHERE = _fourcc("gone")

_cmio_lib: ctypes.CDLL | None = None


def _cmio() -> ctypes.CDLL:
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


def _cmio_devices(lib: ctypes.CDLL) -> list[int]:
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


def any_camera_in_use() -> bool:
    lib = _cmio()
    addr = _CMIOAddress(_CMIO_PROP_IS_RUNNING_SOMEWHERE, _CMIO_SCOPE_GLOBAL, 0)
    for device in _cmio_devices(lib):
        value = ctypes.c_uint32(0)
        used = ctypes.c_uint32(0)
        status = lib.CMIOObjectGetPropertyData(device, ctypes.byref(addr), 0, None, 4, ctypes.byref(used), ctypes.byref(value))
        if status == 0 and value.value:
            return True
    return False


# --- settings dialog -------------------------------------------------------


class SettingsDialog(NSObject):
    """One modal dialog for the Homey address (with autodetect), token and light.

    Lights are fetched in the background using whatever address and token are
    currently in the fields, so the list follows edits before anything is saved.
    """

    WIDTH = 460

    @objc.python_method
    def show(self, onair: OnAir) -> tuple[str, str, Any] | None:
        """Run the dialog. Returns (address, token, device) on Save, else None."""
        self.onair = onair
        self.generation = 0  # bumped per lights fetch, so stale results are dropped
        self.loaded_for = None

        width = self.WIDTH
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 164))

        def label(text: str, y: float) -> None:
            field = NSTextField.labelWithString_(text)
            field.setFrame_(NSMakeRect(0, y + 3, 64, 18))
            field.setAlignment_(NSTextAlignmentRight)
            view.addSubview_(field)

        def button(title: str, action: str, y: float) -> Any:
            btn = NSButton.buttonWithTitle_target_action_(title, self, action)
            btn.setFrame_(NSMakeRect(width - 92, y - 4, 92, 32))
            view.addSubview_(btn)
            return btn

        def text_field(value: str | None, placeholder: str, y: float, w: float, h: float = 24, wraps: bool = False) -> Any:
            field = Editing.alloc().initWithFrame_(NSMakeRect(72, y, w, h))
            field.setStringValue_(value or "")
            field.setPlaceholderString_(placeholder)
            field.setDelegate_(self)
            if wraps:
                # A token is one long unbroken string, so wrap by character to fill
                # the extra lines instead of scrolling off to the right.
                field.setUsesSingleLineMode_(False)
                cell = field.cell()
                cell.setWraps_(True)
                cell.setScrollable_(False)
                cell.setLineBreakMode_(NSLineBreakByCharWrapping)
            view.addSubview_(field)
            return field

        label("Address", 130)
        self.address = text_field(onair.args.address, "homey-xxxx.local or IP address", 130, width - 172)
        self.detect_button = button("Detect", "detect:", 130)

        label("Token", 99)  # aligned to the top of the taller, three-line token field
        self.token = text_field(onair.args.token, "Personal Access Token", 66, width - 72, h=54, wraps=True)

        label("Light", 32)
        self.light = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(70, 30, width - 166, 26), False)
        view.addSubview_(self.light)
        button("Reload", "reload:", 32)

        self.status = NSTextField.labelWithString_("")
        self.status.setFrame_(NSMakeRect(72, 4, width - 72, 16))
        self.status.setFont_(NSFont.systemFontOfSize_(NSFont.smallSystemFontSize()))
        self.status.setTextColor_(NSColor.secondaryLabelColor())
        view.addSubview_(self.status)

        alert = NSAlert.alloc().init()
        alert.setMessageText_("OnAir settings")
        alert.setInformativeText_("Create a token at my.homey.app -> Settings -> API keys.")
        alert.addButtonWithTitle_("Save")
        alert.addButtonWithTitle_("Cancel")
        alert.setAccessoryView_(view)
        alert.window().setInitialFirstResponder_(self.address)

        if self.address.stringValue():
            self._load_lights()
        else:
            self.detect_(None)

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        saved = alert.runModal() == NSAlertFirstButtonReturn
        self.generation += 1  # ignore fetches still in flight
        if not saved:
            return None
        item = self.light.selectedItem()
        device = item.representedObject() if item is not None else None
        return self.address.stringValue().strip(), self.token.stringValue().strip(), device

    # --- actions --------------------------------------------------------------

    def detect_(self, sender: Any) -> None:
        self.detect_button.setEnabled_(False)
        self.status.setStringValue_("Searching the network for a Homey…")

        def worker() -> None:
            AppHelper.callAfter(self._detected, OnAir.discover_homey())

        threading.Thread(target=worker, daemon=True).start()

    def reload_(self, sender: Any) -> None:
        self._load_lights(force=True)

    def controlTextDidEndEditing_(self, notification: Any) -> None:
        self._load_lights()

    # --- helpers --------------------------------------------------------------

    @objc.python_method
    def _detected(self, address: str | None) -> None:
        self.detect_button.setEnabled_(True)
        if address:
            self.address.setStringValue_(address)
            self.status.setStringValue_("Found Homey at %s" % address)
            self._load_lights()
        else:
            self.status.setStringValue_("No Homey found. Enter its address manually.")

    @objc.python_method
    def _load_lights(self, force: bool = False) -> None:
        address = self.address.stringValue().strip()
        token = self.token.stringValue().strip()
        if not (address and token):
            self.loaded_for = None
            self._set_lights([], "(set address and token first)")
            return
        if not force and self.loaded_for == (address, token):
            return
        self.loaded_for = (address, token)
        self.generation += 1
        generation = self.generation
        self._set_lights([], "Loading lights…")

        def worker() -> None:
            try:
                devices, error = self.onair.homey_onoff_devices(address, token), None
            except (urllib.error.URLError, OSError, ValueError) as err:
                devices, error = None, err
            AppHelper.callAfter(self._lights_loaded, generation, devices, error)

        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def _lights_loaded(
        self,
        generation: int,
        devices: list[tuple[str, str]] | None,
        error: Exception | None,
    ) -> None:
        if generation != self.generation:
            return
        if error is not None:
            self._set_lights([], "(could not reach Homey)")
            self.status.setStringValue_("Could not reach Homey: %s" % error)
        elif not devices:
            self._set_lights([], "(no on/off devices found)")
        else:
            self._set_lights(devices)
            self.status.setStringValue_("")

    @objc.python_method
    def _set_lights(self, devices: list[tuple[str, str]], placeholder: str | None = None) -> None:
        current = self.light.selectedItem()
        selected = current.representedObject() if current is not None else None
        selected = selected or self.onair.args.device
        self.light.removeAllItems()
        menu = self.light.menu()
        if placeholder:
            menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(placeholder, None, ""))
            self.light.setEnabled_(False)
            return
        self.light.setEnabled_(True)
        # Add through the menu rather than addItemWithTitle_, which drops
        # duplicate titles (two lights can share a name).
        for name, devid in devices:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(name, None, "")
            item.setRepresentedObject_(devid)
            menu.addItem_(item)
            if devid == selected:
                self.light.selectItem_(item)


class OnAir:
    def __init__(self) -> None:
        self.args = self.parse_args()
        self.air_on = False
        self.menubar_blinker_active = False
        self.camera_state_updater_active = True
        self._about_window = None
        self._sigint_installed = False

        # Monochrome "On Air" silhouette when idle; the blinker flips to the
        # full-colour red logo while a camera is on, like an on-air sign lighting up.
        self.app = rumps.App("OnAir", icon=ICON_IDLE, template=True)

        self.menuStatus = rumps.MenuItem("Homey: not configured")
        self.menuToggle = rumps.MenuItem("Turn on", callback=self.on_air)
        self.menuSettings = rumps.MenuItem("Settings…", callback=self.open_settings)

        self.app.menu = [
            self.menuStatus,
            rumps.separator,
            self.menuToggle,
            rumps.separator,
            self.menuSettings,
            rumps.separator,
            rumps.MenuItem("About OnAir…", callback=self.show_about),
        ]

        self.update_status()

    def run(self) -> None:
        threading.Thread(target=self.camera_state_updater, daemon=True).start()
        self.log(str(self.args))
        # rumps only installs a mach-port interrupt and otherwise never hands
        # control back to Python, so Ctrl-C from `make run` is never delivered.
        # A periodic main-loop timer gives the interpreter a window to run the
        # SIGINT handler installed on its first tick (after rumps installs its
        # own, so ours wins).
        rumps.Timer(self._interrupt_tick, 1).start()
        self.app.run()

    def _interrupt_tick(self, _timer: Any) -> None:
        if not self._sigint_installed:
            signal.signal(signal.SIGINT, lambda *_: rumps.quit_application())
            self._sigint_installed = True

    def log(self, msg: object) -> None:
        if self.args.debug:
            print("%s" % msg)

    @staticmethod
    def _ui(apply: Callable[[], None]) -> None:
        # AppKit is not thread-safe; the camera poll and the blinker run on
        # background threads, so route their menu/icon changes to the main thread.
        AppHelper.callAfter(apply)

    def _set_status(self, title: str) -> None:
        self._ui(lambda: setattr(self.menuStatus, "title", title))

    def show_about(self, callback_sender: Any = None) -> None:
        # A non-modal floating panel, not NSAlert.runModal(): a modal loop blocks
        # the status-item menu, so clicking the menubar while the dialog is open
        # freezes the app, and the alert can hide behind other windows.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        if self._about_window is not None:
            self._about_window.makeKeyAndOrderFront_(None)
            return

        width, height = 320, 180
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        panel.setTitle_("About OnAir")
        panel.setReleasedWhenClosed_(False)  # keep the object so it can reopen
        panel.setLevel_(NSFloatingWindowLevel)  # stay on top, not lost behind
        view = panel.contentView()

        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ICON_ACTIVE)
        icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
        if icon is not None:
            image = NSImageView.alloc().initWithFrame_(NSMakeRect((width - 72) / 2, height - 92, 72, 72))
            image.setImage_(icon)
            view.addSubview_(image)

        title = "OnAir"
        body = "%s version %s\n\n%s" % (title, VERSION, GITHUB_URL)
        content = NSMutableAttributedString.alloc().initWithString_(body)
        content.addAttribute_value_range_("NSFont", NSFont.systemFontOfSize_(13), NSMakeRange(0, content.length()))
        # "OnAir" bold, the rest regular.
        content.addAttribute_value_range_("NSFont", NSFont.boldSystemFontOfSize_(13), NSMakeRange(0, len(title)))
        # The URL as a clickable link.
        url_start = body.index(GITHUB_URL)
        content.addAttribute_value_range_(NSLinkAttributeName, GITHUB_URL, NSMakeRange(url_start, len(GITHUB_URL)))
        content.addAttribute_value_range_("NSFont", NSFont.systemFontOfSize_(12), NSMakeRange(url_start, len(GITHUB_URL)))
        content.setAlignment_range_(NSTextAlignmentCenter, NSMakeRange(0, content.length()))

        # A selectable, non-editable text view opens the link in the default
        # browser when clicked.
        text = NSTextView.alloc().initWithFrame_(NSMakeRect(10, 20, width - 20, 60))
        text.setDrawsBackground_(False)
        text.setEditable_(False)
        text.setSelectable_(True)
        text.textStorage().setAttributedString_(content)
        view.addSubview_(text)

        panel.center()
        self._about_window = panel
        panel.makeKeyAndOrderFront_(None)

    # --- camera / light state -------------------------------------------------

    def on_air(self, callback_sender: Any = None) -> None:
        if self.air_on:
            return
        self.air_on = True
        self.log("on_air()")
        self.homey_set(True)

        self.menubar_blinker_active = True
        threading.Thread(target=self.menubar_blinker, daemon=True).start()

        def apply() -> None:
            self.menuToggle.title = "Turn off"
            self.menuToggle.set_callback(callback=self.off_air)

        self._ui(apply)
        self.log("on_air() done")

    def off_air(self, callback_sender: Any = None) -> None:
        if not self.air_on:
            return
        self.air_on = False
        self.log("off_air()")
        self.homey_set(False)

        self.menubar_blinker_active = False

        def apply() -> None:
            self.menuToggle.title = "Turn on"
            self.menuToggle.set_callback(callback=self.on_air)

        self._ui(apply)
        self.log("off_air() done")

    def _show_idle_icon(self) -> None:
        def apply() -> None:
            self.app.template = True
            self.app.icon = ICON_IDLE

        self._ui(apply)

    def _show_active_icon(self) -> None:
        def apply() -> None:
            self.app.template = False
            self.app.icon = ICON_ACTIVE

        self._ui(apply)

    def menubar_blinker(self) -> None:
        self.log("menubar_blinker()")
        lit = True
        while self.menubar_blinker_active:
            if lit:
                self._show_active_icon()
            else:
                self._show_idle_icon()
            time.sleep(1)
            lit = not lit
        self._show_idle_icon()
        self.log("menubar_blinker() done")

    # --- Homey local API ------------------------------------------------------

    def homey_configured(self) -> bool:
        return bool(self.args.address and self.args.token and self.args.device)

    def homey_request(
        self,
        path: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        address: str | None = None,
        token: str | None = None,
    ) -> Any:
        host = address or self.args.address or ""
        if "://" not in host:
            host = "http://" + host
        url = host.rstrip("/") + path
        headers = {"Authorization": "Bearer %s" % (token or self.args.token)}
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

    def homey_set(self, on: bool) -> None:
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
            self._set_status("Homey: connected")
            self.log("homey_set() done")
        except (urllib.error.URLError, OSError, ValueError) as err:
            self._set_status("Homey: error (%s)" % err)
            self.log("homey_set() failed: %s" % err)

    def homey_onoff_devices(self, address: str | None = None, token: str | None = None) -> list[tuple[str, str]]:
        """Return a sorted list of (name, device_id) for devices with an onoff capability."""
        devices = self.homey_request("/api/manager/devices/device/", address=address, token=token)
        found: list[tuple[str, str]] = []
        for devid, dev in (devices or {}).items():
            if "onoff" in dev.get("capabilities", []):
                found.append((dev.get("name", "") or devid, devid))
        return sorted(found)

    # --- network discovery ----------------------------------------------------

    @classmethod
    def discover_homey(cls, timeout: float = 20, attempt_timeout: float = 5) -> str | None:
        """Find a Homey Pro via mDNS (_homey._tcp) and return its address, or None.

        Prefers the advertised hostname (homey-<id>.local), which stays valid
        across DHCP lease changes, and falls back to the raw IP address.

        Retries with a fresh Zeroconf instance until `timeout`: the first
        multicast after launch triggers macOS's Local Network permission prompt
        and is dropped while the prompt is up, so a single attempt would fail.
        """
        try:
            import zeroconf  # noqa: F401
        except ImportError:
            return None

        deadline = time.monotonic() + timeout
        while True:
            address = cls._discover_homey_once(attempt_timeout)
            if address or time.monotonic() >= deadline:
                return address

    @staticmethod
    def _discover_homey_once(timeout: float) -> str | None:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

        class _Listener(ServiceListener):
            def __init__(self) -> None:
                self.name: str | None = None
                self.type: str | None = None
                self.found = threading.Event()

            def add_service(self, zc: Any, type_: str, name: str) -> None:
                self.type, self.name = type_, name
                self.found.set()

            def update_service(self, zc: Any, type_: str, name: str) -> None:
                pass

            def remove_service(self, zc: Any, type_: str, name: str) -> None:
                pass

        zeroconf = Zeroconf()
        listener = _Listener()
        try:
            ServiceBrowser(zeroconf, "_homey._tcp.local.", listener)
            if not listener.found.wait(timeout):
                return None
            service_type, service_name = listener.type, listener.name
            if service_type is None or service_name is None:
                return None
            info = zeroconf.get_service_info(service_type, service_name, timeout=int(timeout * 1000))
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

    def open_settings(self, _: Any = None) -> None:
        result = SettingsDialog.alloc().init().show(self)
        if result is None:
            return
        address, token, device = result
        self.args.address = address
        self.args.token = token
        # Keep the old light if the list could not be loaded this time.
        self.args.device = device or self.args.device
        self.save_config()
        self.log("saved settings: address=%s device=%s" % (address, self.args.device))
        self.update_status()

    def update_status(self) -> None:
        if self.homey_configured():
            title = "Homey: ready (%s)" % self.args.address
        elif not self.args.address:
            title = "Homey: find or set an address"
        elif not self.args.token:
            title = "Homey: set a token"
        else:
            title = "Homey: choose a light"
        self._set_status(title)

    def save_config(self) -> None:
        config = configparser.ConfigParser()
        config.read(HOMECONFIG)
        config["DEFAULT"]["address"] = self.args.address or ""
        config["DEFAULT"]["token"] = self.args.token or ""
        config["DEFAULT"]["device"] = self.args.device or ""
        with open(HOMECONFIG, "w") as handle:
            config.write(handle)
        self.log("saved config to %s" % HOMECONFIG)

    def list_devices(self) -> None:
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

    def camera_state_updater(self) -> None:
        self.log("camera_state_updater() polling CoreMediaIO")
        # Only act on camera state *changes*, so a manual toggle from the menu is
        # not clobbered on the next poll when no camera is in use.
        previous: bool | None = None
        while self.camera_state_updater_active:
            try:
                in_use = any_camera_in_use()
            except OSError as err:
                self.log("camera poll failed: %s" % err)
                in_use = previous
            if in_use != previous:
                previous = in_use
                if in_use:
                    self.on_air()
                else:
                    self.off_air()
            time.sleep(1)

    @staticmethod
    def parse_args() -> argparse.Namespace:
        appconfig = ".onair.ini"

        if not os.path.isfile(HOMECONFIG):
            shutil.copy(appconfig, HOMECONFIG)

        config = configparser.ConfigParser()
        config.read(HOMECONFIG)

        address = config.get("DEFAULT", "address", fallback=None)
        token = config.get("DEFAULT", "token", fallback=None)
        device = config.get("DEFAULT", "device", fallback=None)

        parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument("--address", help="Homey Pro local IP or hostname", default=address)
        parser.add_argument("--token", help="Homey Personal Access Token", default=token)
        parser.add_argument("--device", help="Homey device id of the light", default=device)
        parser.add_argument("--list-devices", action="store_true", help="List on/off devices and exit")
        # debug is a run-time flag only (set via --debug / `make debug`), never persisted.
        parser.add_argument("--debug", action="store_true", help=" ")
        return parser.parse_args()


if __name__ == "__main__":
    app = OnAir()
    if app.args.list_devices:
        app.list_devices()
    else:
        app.run()
