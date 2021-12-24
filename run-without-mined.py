#!/usr/bin/python3
#
# run-without-mined.py - Stop mining daemon(s), run command(s), restart mined(s)
#
# Copyright (C) 2021 Linzhi Ltd.
#
# This work is licensed under the terms of the MIT License.
# A copy of the license can be found in the file COPYING.txt
#

from enum import Enum
import sys, os, re
import threading, argparse, traceback
import paho.mqtt.client as mqtt # apt-get install python3-paho-mqtt


class State(Enum):
	DISCOVER	= 0
	TRANSITION	= 1
	RESTORE		= 2

TIMEOUT_S = 30


running = {
	"":	None,	# shared
	"0":	None,	# slot 0, separate
	"1":	None	# slot 1, separate
}
initial = {}
state = State.DISCOVER

client = None
command = None
debug = False
verbose = False
timeout_s = TIMEOUT_S
timer = None
failed = False


# --- Helper functions --------------------------------------------------------


def publish(topic, payload):
	if debug:
		print("PUB", topic, payload, file = sys.stderr)
	client.publish(topic, payload)


def start(slot):
	publish("/daemon/mined" + slot + "/start", "x")


def stop(slot):
	publish("/daemon/mined" + slot + "/stop", "x")


def change_state(new):
	global state

	if debug:
		print("STATE", state.name, "->", new.name)
	state = new


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


def run_command():
	global failed

	cmd = command.replace("{}", host)
	if debug:
		print("CMD", cmd, file = sys.stderr)
	status = os.system(cmd)
	if os.waitstatus_to_exitcode(status):
		if verbose:
			print("Exit code", os.waitstatus_to_exitcode(status),
			    file = sys.stderr)
		failed = True
	if running[""] is not None:
		if initial[""]:
			change_state(State.RESTORE)
			start("")
		else:
			client.disconnect()
	else:
		if initial["0"] or initial["1"]:
			change_state(State.RESTORE)
			if initial["0"]:
				start("0")
			if initial["1"]:
				start("1")
		else:
			client.disconnect()

	
def got(slot, is_running):
	global running, initial

	if running[slot] == None:
		initial[slot] = is_running
	running[slot] = is_running
	if state == State.DISCOVER:
		if running[""] is not None:
			if running[""]:
				change_state(State.TRANSITION)
				stop("")
			else:
				run_command()
		elif running["0"] is not None and running["1"] is not None:
			if running["0"] or running["0"]:
				change_state(State.TRANSITION)
				if running["0"]:
					stop("0")
				if running["1"]:
					stop("1")
			else:
				run_command()
	elif state == State.TRANSITION:
		if running[""] is not None:
			if not running[""]:
				run_command()
		else:
			if not running["0"] and not running["1"]:
				run_command()
	elif state == State.RESTORE:
		if running[""] is not None:
			if running[""]:
				client.disconnect()
		else:
			if running["0"] == initial["0"] and \
			    running["1"] == initial["1"]:
				client.disconnect()
		
	else:
		raise Exception("Unknown state", state)
	

def message(topic, payload):
	if debug:
		print("RECV " + topic + " " + payload, file = sys.stderr)
	if topic == "/daemon/mined/time":
		got("", payload != "0")
	elif topic == "/daemon/mined0/time":
		got("0", payload != "0")
	elif topic == "/daemon/mined1/time":
		got("1", payload != "0")
	else:
		print('unrecognized topic "' + topic + '"', file = sys.stderr)


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
	try:
		message(msg.topic, msg.payload.decode("ascii"))
	except Exception as e:
		traceback.print_exc()


def on_connect(client, userdata, flags, rc):
	try:
		if rc == 0:
			client.subscribe("/daemon/mined/time")
			client.subscribe("/daemon/mined0/time")
			client.subscribe("/daemon/mined1/time")
		else:
			print("could not connect to " + userdata,
			    file = sys.stderr)
			client.loop_stop()
			failed = True
	except Exception as e:
		traceback.print_exc()


# --- Handle one host ---------------------------------------------------------


def connect_host(name):
	global host, client, state, timer
	global failed

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
		state = State.DISCOVER
		client.connect(host)
		timer.start()
		client.loop_forever()
	except Exception as e:
		print("could not connect to " + host, file = sys.stderr)
		failed = True
	if timer is not None:
		timer.cancel()
		timer = None


# --- Command-line processing and main loop -----------------------------------


def usage():
	print("usage: " + sys.argv[0] +
	    " [-d] [-v] command [host ...]",
	    file = sys.stderr)
	sys.exit(1)


parser = argparse.ArgumentParser()
parser.add_argument("-d", "--debug", action = "store_true",
    help = "show messages and state transitions (implies -v)")
parser.add_argument("-t", "--timeout", type = int,
    help = "timeout (per host) for the entire sequence (in seconds)")
parser.add_argument("-v", "--verbose", action = "store_true",
    help = "show progress")
parser.add_argument("command",
    help = "shell command. {} is replaced with host name.")
parser.add_argument("hosts", nargs = "*", default = [], help = "hosts or files")
args = parser.parse_args()

debug = args.debug
verbose = args.verbose or debug
if args.timeout is not None:
	timeout_s = args.timeout
command = args.command

for arg in args.hosts:
	if os.path.isfile(arg):
		with open(arg) as file:
			for line in file:
				tmp = re.sub(r"\s*#.*$", "", line)
				tmp = re.sub(r"\s.*$", "", tmp)
				if tmp != "":
					connect_host(tmp)
	else:
		connect_host(arg)

sys.exit(1 if failed else 0)
