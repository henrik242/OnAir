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

Configuration
--
`~/.onair.ini` is used for MQTT configuration. It will be created automatically on the first run. Here's an example:
```
[DEFAULT]
user=myuser
password=mypass
host=futurehome-smarthub.local
port=1884
topic=pt:j1/mt:cmd/rt:dev/rn:zw/ad:1/sv:out_bin_switch/ad:19_0
debug=False
```
See
<https://support.futurehome.no/hc/en-no/articles/360033256491-Local-API-access-over-MQTT-Beta-> for MQTT user/password setup.

Releases
--
Fetch the latest app build from <https://nightly.link/henrik242/OnAir/workflows/build/main/OnAir.app.tgz.zip>


Futurehome and MQTT testing
--
Go to <http://futurehome-smarthub.local:8081/fimp/timeline> and set the Service filter to `out_bin_switch`.
Turn off/on your desired light to discover the topic for it, e.g. `pt:j1/mt:cmd/rt:dev/rn:zw/ad:1/sv:out_bin_switch/ad:19_0`,
and the actual message, e.g.
```
{
    "serv": "out_bin_switch",
    "type": "cmd.binary.set",
    "val_t": "bool",
    "val": true,
    "props": null,
    "tags": null
}
```

Use a MQTT client such as [mqtt-cli](https://github.com/hivemq/mqtt-cli) or [MQTT Explorer](http://mqtt-explorer.com/)
to send a message to turn the light on or off (`val` set to `true` or `false`). 
Note that the MQTT version 5 doesn't work, it needs to be v3.

Here's an example from mqtt-cli:
```
$ mqtt pub -v -V 3 -h futurehome-smarthub.local -p 1884 \
       -u my_username -pw my_password \
       -t pt:j1/mt:cmd/rt:dev/rn:zw/ad:1/sv:out_bin_switch/ad:19_0 \
       -m '{
            "serv": "out_bin_switch",
            "type": "cmd.binary.set",
            "val_t": "bool",
            "val": true,
            "props": null,
            "tags": null
        }'
```

Building the app
--

```
pip3 install -r requirements.txt
./setup.py py2app
```

This creates OnAir.app in `dist/`

Thanks to
--

- <https://github.com/jaredks/rumps>
- <https://github.com/ronaldoussoren/py2app>
- <https://camillovisini.com/article/create-macos-menu-bar-app-pomodoro/>
- <https://www.hivemq.com/blog/mqtt-client-library-paho-python/>

