![](onair.png)

OnAir status indicator for macOS camera usage
==

A menubar indicator that watches macOS camera usage and turns a light on/off
through your [Athom Homey Pro](https://homey.app/) using its local HTTP API.

```
usage: OnAir.py [-h] [--address ADDRESS] [--token TOKEN] [--device DEVICE] [--list-devices] [--debug]

options:
  -h, --help         show this help message and exit
  --address ADDRESS  Homey Pro local IP or hostname
  --token TOKEN      Homey Personal Access Token
  --device DEVICE    Homey device id of the light
  --list-devices     List on/off devices and exit
  --debug
```

Configuration
--
`~/.onair.ini` holds the Homey settings. It is created automatically on the
first run from the bundled template. Example:
```
[DEFAULT]
address=192.168.1.42
token=your-personal-access-token
device=abcd1234-5678-90ab-cdef-1234567890ab
debug=False
```

Setup
--
1. Find your Homey Pro's IP address (Homey app -> Settings -> General, or your
   router). Put it in `address`.
2. Create a Personal Access Token at <https://my.homey.app> (Settings -> API
   keys). Put it in `token`.
3. List the devices that have an on/off capability and pick your light's id:
   ```
   ./OnAir.py --list-devices
   ```
   Put the id in `device`.

That's it. When any camera turns on, OnAir turns the light on (and blinks the
menubar icon); when all cameras are off, it turns the light off. You can also
toggle it manually from the menubar.

The app talks to Homey directly on your LAN over
`PUT http://<address>/api/manager/devices/device/<device>/capability/onoff`,
so there is no cloud roundtrip and no extra dependencies beyond `rumps`.

Building the app
--

```
pip3 install -r requirements.txt
./setup.py py2app
```

This creates OnAir.app in `dist/`

Releases
--
Fetch the latest app build from <https://nightly.link/henrik242/OnAir/workflows/build/main/OnAir.app.tgz.zip>

Thanks to
--

- <https://github.com/jaredks/rumps>
- <https://github.com/ronaldoussoren/py2app>
- <https://camillovisini.com/article/create-macos-menu-bar-app-pomodoro/>
