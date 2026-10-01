![](onair.png)

OnAir
==

A macOS menubar app that turns a light on and off through your
[Athom Homey Pro](https://homey.app/) whenever a camera is in use, so the people
around you know when you are in a call.

Camera usage is detected via CoreMediaIO (no camera permission needed), and the
light is driven directly over Homey's local HTTP API, so there is no cloud
roundtrip.

Install
--
Download the latest build from
<https://nightly.link/henrik242/OnAir/workflows/build/main/OnAir.app.tgz.zip>,
unpack it, and move `OnAir.app` to `/Applications`. Or build from source (below).

Setup
--
Everything is configured from the menubar:

1. Create a Personal Access Token at <https://my.homey.app> (Settings -> API keys).
2. **Detect Homey on network** finds your Homey Pro automatically via mDNS. If it
   is not found, use **Set Homey address…** to enter its IP or hostname.
3. **Set token…** and paste the token from step 1.
4. **Choose light** and pick the device to control. The menu lists every Homey
   device that has an on/off switch.

The menubar icon shows a grey "On Air" when idle and blinks red while a camera is
on. You can also toggle the light manually from the menu.

Configuration file
--
Settings are stored in `~/.onair.ini` (created on first run). You can edit it
directly instead of using the menu:

```
[DEFAULT]
address=homey-xxxxxxxx.local
token=your-personal-access-token
device=abcd1234-5678-90ab-cdef-1234567890ab
debug=False
```

The light is switched with
`PUT http://<address>/api/manager/devices/device/<device>/capability/onoff`.

Build and run from source
--
`make` creates a local `.venv` and installs the dependencies there, so it never
touches your system Python.

```
make          # build OnAir.app into dist/
make debug    # run from source with debug logging
make run      # run from source
```

To list on/off devices from the command line: `.venv/bin/python OnAir.py --list-devices`.

Thanks to
--
- <https://github.com/jaredks/rumps>
- <https://github.com/python-zeroconf/python-zeroconf>
- <https://github.com/ronaldoussoren/py2app>
- <https://camillovisini.com/article/create-macos-menu-bar-app-pomodoro/>
