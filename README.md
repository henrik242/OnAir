![](onair.png)

OnAir status indicator for macOS camera usage
==

Using a menubar indicator, and a MQTT message for Futurehome to turn on/off a light bulb

```
usage: OnAir.py [-h] [--host HOST] [--port PORT] [--topic TOPIC] [--user USER] [--password PASSWORD] [--debug]

optional arguments:
  -h, --help           show this help message and exit
  --host HOST          (default: futurehome-smarthub.local)
  --port PORT          (default: 1884)
  --topic TOPIC        (default: pt:j1/mt:cmd/rt:dev/rn:zw/ad:1/sv:out_bin_switch/ad:19_0)
  --user USER
  --password PASSWORD
  --debug              (default: False)
```

Futurehome
--
See <https://support.futurehome.no/hc/en-no/articles/360033256491-Local-API-access-over-MQTT-Beta-> for MQTT 
user/password setup

Building the app
--

```
pip3 install rumps paho-mqtt py2app
./setup.py py2app
```

This creates OnAir.app in `dist/`

`~/.onair.ini` needs to exist for OnAir.app to send MQTT messages, with the following:

```
[DEFAULT]
user=myuser
password=mypass
host=futurehome-smarthub.local
port=1884
topic=pt:j1/mt:cmd/rt:dev/rn:zw/ad:1/sv:out_bin_switch/ad:19_0
debug=False
```

Releases
--
Fetch the latest build from <https://nightly.link/henrik242/OnAir/workflows/build/main/OnAir.app.tgz.zip>

Thanks to
--

- <https://camillovisini.com/article/create-macos-menu-bar-app-pomodoro/>
- <https://www.hivemq.com/blog/mqtt-client-library-paho-python/>

