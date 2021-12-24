#!/usr/bin/python3
#
# bulk-collect.py - Collect 
#
# Copyright (C) 2021 Linzhi Ltd.
#
# This work is licensed under the terms of the MIT License.
# A copy of the license can be found in the file COPYING.txt
#

import sys, os, re
import threading, argparse, traceback
import paho.mqtt.client as mqtt # apt-get install python3-paho-mqtt


TIMEOUT_S = 30

client = None
debug = False
no_retain = False
verbose = False
pub = []
sub = []
timeout_s = TIMEOUT_S
timer = None
failed = False


# --- Helper functions --------------------------------------------------------


def publish(topic, payload):
	if debug:
		print("PUB", topic, payload, file = sys.stderr)
	client.publish(topic, payload)


def disconnect():
	global timer

	if timer is not None:
		timer.cancel()
		timer = None	
	client.disconnect()


def timeout():
	global failed

	if verbose:
		print("Timeout", file = sys.stderr)
	failed = True
	disconnect()


# --- Message processing ------------------------------------------------------


def message(topic, payload):
	global want, got, wanted

	if debug:
		print("RECV " + topic + " " + payload, file = sys.stderr)
	if topic in want:
		del want[topic]
		wanted -= 1
		got[topic] = payload
	elif topic in got:
		got[topic] = payload
	else:
		print("unexpected topic", '"' + topic + '"', file = sys.stderr)
	if wanted == 0:
		client.disconnect()


# --- MQTT callbacks ----------------------------------------------------------


def on_disconnect(client, userdata, rc):
	try:
		if rc != 0:
			print("unexpected disconnect from " + userdata,
			    file = sys.stderr)
			failed = True
		if debug:
			print("STOP LOOP", file = sys.stderr)
		client.loop_stop()
	except Exception as e:
		traceback.print_exc()


def on_message(client, userdata, msg):
	if msg.retain and no_retain:
		return
	try:
		message(msg.topic, msg.payload.decode("ascii"))
	except Exception as e:
		traceback.print_exc()


def on_connect(client, userdata, flags, rc):
	try:
		if rc == 0:
			for s in sub:
				client.subscribe(s)
			for p in pub:
				publish(p, pub[p])
		else:
			print("could not connect to " + userdata,
			    file = sys.stderr)
			client.loop_stop()
			failed = True
	except Exception as e:
		traceback.print_exc()


# --- Handle one host ---------------------------------------------------------


def connect_host(name):
	global host, client
	global failed
	global want, wanted, got

	want = {}
	got = {}
	wanted = 0
	for key in sub:
		want[key] = None
		wanted += 1
	
	host = name
	if debug:
		print("CONNECTING", host, file = sys.stderr)

	client = mqtt.Client(userdata = host)
	client.on_connect = on_connect
	client.on_message = on_message
	client.on_disconnect = on_disconnect

	timer = threading.Timer(timeout_s, timeout)
	if verbose:
		print("CONNECT", host, file = sys.stderr)
	try:
		client.connect(host)
		timer.start()
		client.loop_forever()
	except Exception as e:
		print("could not connect to " + host, file = sys.stderr)
		failed = True
	timer.cancel()

	print(host)
	for key in got:
		print(key + "=" + got[key])


# --- Command-line processing and main loop -----------------------------------


def usage():
	print("usage: " + sys.argv[0] +
	    " [-d] [-v] command [host ...]",
	    file = sys.stderr)
	sys.exit(1)


parser = argparse.ArgumentParser()
parser.add_argument("-d", "--debug", action = "store_true",
    help = "show messages and state transitions (implies -v)")
parser.add_argument("-R", "--no-retain", action = "store_true",
    help = "ignore retained messages")
parser.add_argument("-t", "--timeout", type = int,
    help = "timeout (per host) for the entire sequence (in seconds)")
parser.add_argument("-v", "--verbose", action = "store_true",
    help = "show progress")
parser.add_argument("args", nargs = "*", default = [],
    help = "topics, messages, hosts, or files")
args = parser.parse_intermixed_args()

debug = args.debug
verbose = args.verbose or debug
no_retain = args.no_retain
if args.timeout is not None:
	timeout_s = args.timeout

pub = {}
sub = []
for arg in args.args:
	m = re.match("^(/.*?)(=(.*))?$", arg)
	if m:
		if m.group(2) is None:
			sub.append(m.group(1))
		else:
			pub[m.group(1)] = m.group(3)
	elif os.path.isfile(arg):
		with open(arg) as file:
			for line in file:
				tmp = re.sub(r"\s*#.*$", "", line)
				tmp = re.sub(r"\s.*$", "", tmp)
				if tmp != "":
					connect_host(tmp)
	else:
		connect_host(arg)

sys.exit(1 if failed else 0)
