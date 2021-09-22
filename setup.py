#!/usr/bin/env python3

from setuptools import setup

APP = ['OnAir.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': True,
    'iconfile': 'onair.icns',
    'plist': {
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,
    },
    'packages': ['rumps'],
}

setup(
    app=APP,
    name='OnAir',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'], install_requires=['rumps']
)