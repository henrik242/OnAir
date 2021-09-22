OnAir status indicator for macOS camera usage
==

Using a menubar indicator and a MQTT message to FutureHome to turn on/off a bulb

```
$ ./OnAir.py --help
usage: OnAir.py [-h] [--host HOST] [--port PORT] [--topic TOPIC] --user USER --password PASSWORD [--debug]

optional arguments:
  -h, --help           show this help message and exit
  --host HOST          (default: futurehome-smarthub.local)
  --port PORT          (default: 1884)
  --topic TOPIC        (default: pt:j1/mt:cmd/rt:dev/rn:zw/ad:1/sv:out_bin_switch/ad:19_0)
  --user USER          (default: None)
  --password PASSWORD  (default: None)
  --debug              (default: False)
```

Futurehome
--
See https://support.futurehome.no/hc/en-no/articles/360033256491-Local-API-access-over-MQTT-Beta- for MQTT user/pass setup

Building the app
--
```
./setup.py py2app
```
This creates OnAir.app in `dist/`

A proper `~/.onair.ini` needs to exist for OnAir.app to run, with the following:
```
[DEFAULT]
user=myuser
password=mypass
host=futurehome-smarthub.local
port=1884
topic=pt:j1/mt:cmd/rt:dev/rn:zw/ad:1/sv:out_bin_switch/ad:19_0
debug=False
```
