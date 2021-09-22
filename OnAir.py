#!/usr/bin/env python3

import argparse
import os
import re
import threading
import time

import paho.mqtt.client as mqtt
import rumps


# Thanks to
# - https://camillovisini.com/article/create-macos-menu-bar-app-pomodoro/
# - https://www.hivemq.com/blog/mqtt-client-library-paho-python/

class OnAir(object):
    def __init__(self):
        self.app = rumps.App("OnAir", "🟢")
        self.args = self.parse_args()
        self.mqtt_client = self.create_mqtt_client()
        self.is_blinking = False
        self.is_reading_log = True

    def run(self):
        threading.Thread(target=self.camera_state_updater, daemon=True).start()
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
        self.log("connect rc %d." % rc)

    def mqtt_on_publish(self, client, obj, msg):
        self.log("publish: %s" % str(msg))

    def create_mqtt_client(self):
        self.log("create_mqtt_client()")
        client = mqtt.Client(protocol=mqtt.MQTTv31)
        client.username_pw_set(self.args.user[0], self.args.password[0])
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

        msg_info.wait_for_publish()
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
        parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument('--host', nargs=1, help=" ", default="futurehome-smarthub.local")
        parser.add_argument('--port', nargs=1, help=" ", type=int, default=1884)
        parser.add_argument('--topic', nargs=1, help=" ",
                            default="pt:j1/mt:cmd/rt:dev/rn:zw/ad:1/sv:out_bin_switch/ad:19_0")
        parser.add_argument('--user', nargs=1, help=" ", required=True)
        parser.add_argument('--password', nargs=1, help=" ", required=True)
        parser.add_argument('--debug', action='store_true', help=" ")
        return parser.parse_args()


if __name__ == '__main__':
    app = OnAir()
    app.run()
