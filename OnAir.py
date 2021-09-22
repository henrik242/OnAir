#!/usr/bin/env python3

import argparse
import configparser
import os
import re
import shutil
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import rumps


class OnAir(object):
    def __init__(self):
        self.app = rumps.App("OnAir", "🟢")
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

    def on_air(self):
        self.log("on_air()")
        self.mqtt_publish("true")
        self.is_blinking = True
        threading.Thread(target=self.menubar_blinker, daemon=True).start()
        self.log("on_air() done")

    def off_air(self):
        self.log("off_air()")
        self.mqtt_publish("false")
        self.is_blinking = False
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

    def mqtt_on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.log("MQTT connected")
            self.app.menu['connected'] = rumps.MenuItem(title="MQTT connected")
        else:
            self.log("MQTT not connected (error=%s, user=%s, host=%s)" % (rc, self.args.user, self.args.host))
            self.app.menu['connected'] = rumps.MenuItem(
                title="MQTT not connected (error=%s, user=%s, host=%s)" % (rc, self.args.user, self.args.host))

    def mqtt_on_publish(self, client, obj, msg):
        self.log("publish: %s" % str(msg))

    def create_mqtt_client(self):
        self.log("create_mqtt_client()")
        client = mqtt.Client(protocol=mqtt.MQTTv31)
        user = self.args.user if type(self.args.user) is str else self.args.user[0]
        password = self.args.password if type(self.args.password) is str else self.args.password[0]
        client.username_pw_set(user, password)
        client.on_connect = self.mqtt_on_connect
        client.on_publish = self.mqtt_on_publish
        client.connect(self.args.host, self.args.port)
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
        parser.add_argument('--user', nargs=1, required=(user is None), default=user)
        parser.add_argument('--password', nargs=1, required=(user is None), default=password)
        parser.add_argument('--debug', action='store_true', help=" ", default=debug)
        return parser.parse_args()


if __name__ == '__main__':
    app = OnAir()
    app.run()
