#!/usr/bin/env python3

import argparse
import configparser
import os
import re
import shutil
import threading
import time
import webbrowser
from pathlib import Path

import paho.mqtt.client as mqtt
import rumps


class OnAir(object):
    menuAbout = "About OnAir…"
    menuToggle = "Toggle light"
    menuMqtt = "MQTT not connected"

    def __init__(self):
        self.app = rumps.App("OnAir", "🟢")
        self.app.menu.add(rumps.MenuItem(title=self.menuMqtt))
        self.app.menu.add(rumps.MenuItem(title=self.menuToggle, callback=self.on_air))
        self.app.menu.add(rumps.MenuItem(title=self.menuAbout, callback=self.open_onair_url))
        self.args = self.parse_args()
        self.mqtt_client = self.create_mqtt_client()
        self.is_blinking = False
        self.is_reading_log = True

    def run(self):
        threading.Thread(target=self.camera_state_updater, daemon=True).start()
        self.log(str(self.args))
        self.app.run()

    def log(self, msg):
        if self.args.debug:
            print("%s" % msg)

    @staticmethod
    def open_onair_url(callback_sender=None):
        webbrowser.open_new_tab("https://github.com/henrik242/OnAir")

    def on_air(self, callback_sender=None):
        self.log("on_air()")
        self.mqtt_publish("true")
        self.is_blinking = True
        threading.Thread(target=self.menubar_blinker, daemon=True).start()
        self.app.menu.pop(self.menuToggle)
        self.app.menu.insert_before(self.menuAbout, rumps.MenuItem(title=self.menuToggle, callback=self.off_air))
        self.log("on_air() done")

    def off_air(self, callback_sender=None):
        self.log("off_air()")
        self.mqtt_publish("false")
        self.is_blinking = False
        self.app.menu.pop(self.menuToggle)
        self.app.menu.insert_before(self.menuAbout, rumps.MenuItem(title=self.menuToggle, callback=self.on_air))
        self.log("off_air() done")

    def menubar_blinker(self):
        self.log("menubar_blinker()")
        red = True
        while self.is_blinking:
            self.app.title = "🔴" if red else "⚪️"
            time.sleep(1)
            red = not red
        self.app.title = "🟢"
        self.log("menubar_blinker() done")

    def mqtt_drop_menu(self):
        self.app.menu.pop(self.menuMqtt)

    def mqtt_on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.mqtt_drop_menu()
            self.menuMqtt = "MQTT connected"
            self.log(self.menuMqtt)
            self.app.menu.insert_before(self.menuToggle, rumps.MenuItem(title=self.menuMqtt))
        else:
            self.mqtt_drop_menu()
            msg = self.mqtt_err_code(rc)
            self.menuMqtt = "MQTT not connected (error=%s, user=%s, host=%s)" % (msg, self.args.user, self.args.host)
            self.log(self.menuMqtt)
            self.app.menu.insert_before(self.menuToggle, rumps.MenuItem(title=self.menuMqtt))

    @staticmethod
    def mqtt_err_code(code):
        return {
            0: "connection successful",
            1: "incorrect protocol version",
            2: "invalid client identifier",
            3: "server unavailable",
            4: "bad username or password",
            5: "not authorised"
        }[code]

    def mqtt_on_publish(self, client, obj, msg):
        self.log("publish: %s" % str(msg))

    @staticmethod
    def flatten(obj):
        return obj[0] if type(obj) is list else obj

    def create_mqtt_client(self):
        self.log("create_mqtt_client()")
        client = mqtt.Client(protocol=mqtt.MQTTv31)
        client.username_pw_set(self.flatten(self.args.user), self.flatten(self.args.password))
        client.on_connect = self.mqtt_on_connect
        client.on_publish = self.mqtt_on_publish
        client.connect(self.flatten(self.args.host), self.flatten(self.args.port))
        client.loop_start()
        return client

    def mqtt_publish(self, state):
        self.log("mqtt_publish()")
        msg_info = self.mqtt_client.publish(self.args.topic, ("""{
          "serv": "out_bin_switch",
          "type": "cmd.binary.set",
          "val_t": "bool",
          "val": %s,
          "props": {},
          "tags": null 
        }""" % state))

        self.log("mqtt_publish() done: %s" % msg_info.is_published())

    def quit(self):
        self.is_blinking = False
        self.is_reading_log = False
        rumps.quit_application()

    def camera_state_updater(self):
        self.log("camera_state_updater()")
        log_stream = os.popen(
            """/usr/bin/log stream --predicate 'eventMessage contains "Post event kCameraStream"'""", 'r')
        cameras = dict()

        while self.is_reading_log:
            item = log_stream.readline()
            self.log("reading '%s'" % item.strip())

            if item == '':
                self.log("log stream died")
                break

            match = re.search("guid:(.+)]", item)
            if match is not None:
                device = match.group(1)

                if "Start" in item:
                    cameras[device] = True
                elif "Stop" in item:
                    cameras[device] = False
                else:
                    self.log("Unknown activity: %s" % item)

                self.log(cameras)
                if any(cameras.values()):
                    self.log("Camera %s is on" % device)
                    self.on_air()
                else:
                    self.log("Camera %s is off" % device)
                    self.off_air()

        self.quit()

    @staticmethod
    def parse_args():
        appconfig = ".onair.ini"
        homeconfig = str(Path.home()) + "/.onair.ini"

        if not os.path.isfile(homeconfig):
            shutil.copy(appconfig, homeconfig)

        config = configparser.ConfigParser()
        config.read(homeconfig)

        user = config.get('DEFAULT', 'user', fallback=None)
        password = config.get('DEFAULT', 'password', fallback=None)
        host = config.get('DEFAULT', 'host', fallback="futurehome-smarthub.local")
        port = config.getint('DEFAULT', 'port', fallback=1884)
        topic = config.get('DEFAULT', 'topic', fallback="pt:j1/mt:cmd/rt:dev/rn:zw/ad:1/sv:out_bin_switch/ad:19_0")
        debug = config.getboolean('DEFAULT', 'debug', fallback=False)

        parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument('--host', nargs=1, help=" ", default=host)
        parser.add_argument('--port', nargs=1, help=" ", type=int, default=port)
        parser.add_argument('--topic', nargs=1, help=" ", default=topic)
        parser.add_argument('--user', nargs=1, default=user)
        parser.add_argument('--password', nargs=1, default=password)
        parser.add_argument('--debug', action='store_true', help=" ", default=debug)
        return parser.parse_args()


if __name__ == '__main__':
    app = OnAir()
    app.run()
