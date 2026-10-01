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

Setup
--
Everything is configured from the menubar, no command line needed:

1. Create a Personal Access Token at <https://my.homey.app> (Settings -> API
   keys).
2. In the OnAir menu, click **Detect Homey on network** to find your Homey Pro
   automatically (via mDNS). If it is not found, use **Set Homey address…** to
   enter its IP or hostname.
3. Click **Set token…** and paste the token from step 1.
4. Open **Choose light** and pick the device you want to control. The menu lists
   every Homey device that has an on/off switch.

That's it. When any camera turns on, OnAir turns the light on (and blinks the
menubar icon); when all cameras are off, it turns the light off. You can also
toggle it manually from the menubar.

Configuration
--
The settings above are stored in `~/.onair.ini`, which is also created on first
run from the bundled template. You can edit it directly instead of using the
menu:
```
[DEFAULT]
address=homey-xxxxxxxx.local
token=your-personal-access-token
device=abcd1234-5678-90ab-cdef-1234567890ab
debug=False
```
`--list-devices` prints the same device list as the **Choose light** menu, for
reference.

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
- <https://github.com/python-zeroconf/python-zeroconf>
- <https://github.com/ronaldoussoren/py2app>
- <https://camillovisini.com/article/create-macos-menu-bar-app-pomodoro/>
