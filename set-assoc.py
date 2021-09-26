#!/usr/bin/python3
#
# set-assoc.py - Set configuration variable that is an associativee array
#
# Copyright (C) 2021 Linzhi Ltd.
#
# This work is licensed under the terms of the MIT License.
# A copy of the license can be found in the file COPYING.txt
#


import sys, re
import traceback
import paho.mqtt.client as mqtt # apt-get install python3-paho-mqtt


delete = False
verbose = False
set = {}
hosts = []
failed = False
pending = 0


# --- Get/set logic -----------------------------------------------------------


def set_new(old = []):
	global pending

	tmp = set.copy()
	for key in old:
		if key not in tmp:
			tmp[key] = ""
	keys = tmp.keys()
	if len(keys) == 0:
		client.disconnect()
	else:
		pending = len(keys)
		for key in keys:
			topic = "/config/user/" + base + "/" + key + "/set"
			if verbose:
				print("SEND " + topic + " " + tmp[key],
				    file = sys.stderr)
			client.publish(topic, tmp[key])


def message(topic, payload):
	if verbose:
		print("RECV " + topic + " " + payload, file = sys.stderr)
	if payload == "-":
		set_new()
	else:
		set_new(payload.split(" "))


def get_existing():
	topic = "/config/user/" + base
	if verbose:
		print("SUB " + topic, file = sys.stderr)
	client.subscribe(topic)


# --- MQTT callbacks ----------------------------------------------------------


def on_disconnect(client, userdata, rc):
	try:
		if rc != 0:
			print("unexpected disconnect from " + userdata,
			    file = sys.stderr)
			failed = True
			# weird - needs this or it'll try reconnecting forever
			client.disconnect()
		if verbose:
			print("STOP LOOP", file = sys.stderr)
		client.loop_stop()
	except Exception as e:
		traceback.print_exc()


def on_publish(client, userdata, mid):
	global pending

	try:
		pending -= 1
		if pending == 0:
			client.disconnect()
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
			if delete:
				get_existing()
			else:
				set_new()
		else:
			print("could not connect to " + userdata,
			    file = sys.stderr)
			client.loop_stop()
			failed = True
	except Exception as e:
		traceback.print_exc()


# --- Command-line processing and loop over hosts  ----------------------------


def usage():
	print("usage: " + sys.argv[0] +
	    " [-d] [-v] base_name [key=value|host] ...",
	    file = sys.stderr)
	sys.exit(1)


if len(sys.argv) < 2:
	usage()
base = None
first = True
for arg in sys.argv[1:]:
	if arg == "-d":
		delete = True
	elif arg == "-v":
		verbose = True
	elif re.search("^-", arg) is not None:
		usage()
	elif first:
		base = arg
		first = False
	else:
		a = arg.split("=", 1)
		if len(a) == 2:
			set[a[0]] = a[1]
		else:
			hosts.append(arg)

if base is None:
	usage()

for host in hosts:
	client = mqtt.Client(userdata = host)
	client.on_connect = on_connect
	client.on_publish = on_publish
	client.on_message = on_message
	client.on_disconnect = on_disconnect
	if verbose:
		print("CONNECT " + host, file = sys.stderr)
	try:
		client.connect(host)
		client.loop_forever()
	except Exception as e:
		print("could not connect to " + host, file = sys.stderr)
		failed = True

sys.exit(1 if failed else 0)
