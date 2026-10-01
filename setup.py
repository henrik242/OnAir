#!/usr/bin/env python3

from setuptools import setup

APP = ["OnAir.py"]
DATA_FILES = [".onair.ini", "onair.png"]
OPTIONS = {
    "argv_emulation": True,
    "iconfile": "onair.icns",
    "plist": {
        "CFBundleShortVersionString": "2.0.0",
        "LSUIElement": True,
    },
    "packages": ["rumps", "zeroconf", "ifaddr"],
}

# Dependencies are installed into the build venv from requirements.txt (see the
# Makefile), not via setup_requires/install_requires, which newer py2app rejects.
setup(
    app=APP,
    name="OnAir",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
)
