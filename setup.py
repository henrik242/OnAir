#!/usr/bin/env python3

import re

from setuptools import setup

APP = ["OnAir.py"]
_match = re.search(r'^VERSION = "([^"]+)"', open("OnAir.py").read(), re.MULTILINE)
assert _match, "VERSION not found in OnAir.py"
VERSION = _match.group(1)
DATA_FILES = [".onair.ini", "onair.png", "onair-template.png"]
OPTIONS = {
    "argv_emulation": True,
    "iconfile": "onair.icns",
    "plist": {
        "CFBundleShortVersionString": VERSION,
        "LSUIElement": True,
        "NSLocalNetworkUsageDescription": "OnAir looks for your Homey Pro on the local network.",
        "NSBonjourServices": ["_homey._tcp"],
    },
    "packages": ["rumps", "zeroconf", "ifaddr"],
    # tkinter is unused but gets pulled in transitively; python.org's Tcl/Tk 9
    # frameworks contain static stub libs that make py2app's codesign fail.
    "excludes": ["tkinter", "_tkinter"],
}

# Dependencies are installed into the build venv from requirements.txt (see the
# Makefile), not via setup_requires/install_requires, which newer py2app rejects.
setup(
    app=APP,
    name="OnAir",
    data_files=DATA_FILES,  # type: ignore[arg-type]  # py2app accepts a flat file list
    options={"py2app": OPTIONS},
)
