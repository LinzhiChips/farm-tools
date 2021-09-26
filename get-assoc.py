#!/usr/bin/python3
#
# get-assoc.py - Retrieve configuration variable that is an associativee array
#
# Copyright (C) 2021 Linzhi Ltd.
#
# This work is licensed under the terms of the MIT License.
# A copy of the license can be found in the file COPYING.txt
#


import sys, re
import traceback
import paho.mqtt.client as mqtt # apt-get install python3-paho-mqtt


verbose = False
hosts = []
failed = False
keys = None
got = {}


# --- Get/set logic -----------------------------------------------------------


def got_keys(payload):
	global keys

	keys = payload.split(" ")
	for k in keys:
		if k not in got:
			return
	client.disconnect()


def got_element(key, payload):
	global got

	got[key] = payload
	if keys is None:
		return
	else:
		for k in keys:
			if k not in got:
				return
	client.disconnect()


def message(topic, payload):
	if verbose:
		print("RECV " + topic + " " + payload, file = sys.stderr)
	if topic == "/config/user/" + base:
		got_keys("" if payload == "-" else payload)
	else:
		a = topic.split("/")
		got_element(a[-1], payload)


def get_vars():
	topic = "/config/user/" + base
	if verbose:
		print("SUB " + topic, file = sys.stderr)
		print("SUB " + topic + "/+", file = sys.stderr)
	client.subscribe(topic)
	client.subscribe(topic + "/+")


# --- MQTT callbacks ----------------------------------------------------------


def on_disconnect(client, userdata, rc):
	try:
		if rc != 0:
			print("unexpected disconnect from " + userdata,
			    file = sys.stderr)
			failed = True
		if verbose:
			print("STOP LOOP", file = sys.stderr)
		client.loop_stop()
	except Exception as e:
		traceback.print_exc()


def on_message(client, userdata, msg):
	try:
		message(msg.topic, msg.payload.decode("ascii"))
	except Exception as e:
		traceback.print_exc()


def on_connect(client, userdata, flags, rc):
	try:
		if rc == 0:
			get_vars()
		else:
			print("could not connect to " + userdata,
			    file = sys.stderr)
			client.loop_stop()
			failed = True
	except Exception as e:
		traceback.print_exc()


# --- Command-line processing and loop over hosts  ----------------------------


def usage():
	print("usage: " + sys.argv[0] + " [-v] base_name [host] ...",
	    file = sys.stderr)
	sys.exit(1)


if len(sys.argv) < 2:
	usage()
base = None
first = True
for arg in sys.argv[1:]:
	if arg == "-v":
		verbose = True
	elif re.search("^-", arg) is not None:
		usage()
	elif first:
		base = arg
		first = False
	else:
		hosts.append(arg)

if base is None:
	usage()

for host in hosts:
	if verbose:
		print("# " + host)
	keys = None
	got = {}
	client = mqtt.Client(userdata = host)
	client.on_connect = on_connect
	client.on_message = on_message
	client.on_disconnect = on_disconnect
	if verbose:
		print("CONNECT " + host, file = sys.stderr)
	client.connect(host)
	client.loop_forever()
	for k in sorted(got.keys()):
		print(base + "_" + k + "=" + got[k])

sys.exit(1 if failed else 0)
