#!/usr/bin/python3
#
# opsd.py - Interface local daemons with the ops switches of miners
#
# Copyright (C) 2022 Linzhi Ltd.
#
# This work is licensed under the terms of the MIT License.
# A copy of the license can be found in the file COPYING.txt
#

import sys, os, re, os, time
import threading, argparse, traceback
import paho.mqtt.client as mqtt # apt-get install python3-paho-mqtt


MAX_CONNECT_WAIT = 600

broker = "localhost"
debug = False
retain = True
refresh_seconds = 600
verbose = False
pending = []	# miners awaiting connection
connected = []	# miners with an active connection
topics = []	# topics we subscribe to
failed = False	# something went wrong

ops_value = 0
ops_mask = 0
lock = threading.Lock()


# --- Miner -------------------------------------------------------------------


class Miner:
	def to_pending(self):
		global pending

		self.t = time.monotonic() + self.connect_wait
		with lock:
			if self in pending:
				print("already on pending ?!?", self,
				    file = sys.stderr)
			else:
				pending.append(self)


	def on_disconnect(self, client, userdata, rc):
		global connected

		if rc != 0:
			print("unexpected disconnect from " + self.host +
			    ", rc =", rc, file = sys.stderr)
		elif debug:
			print("expected disconnect from" + self.host,
			    file = sys.stderr)

		try:
			#
			# Sometimes, we get two calls to on_disconnect instead
			# of just one. Not sure why.
			#
			if not self.connected:
				print("not connected ?!?", self,
				    file = sys.stderr)
				return
			with lock:
				self.connected = False
				if debug:
					print("  remove", self,
					    file = sys.stderr)
				connected.remove(self)
			if debug:
				print("  STOP LOOP", file = sys.stderr)
			client.loop_stop()
			self.to_pending()
		except Exception as e:
			traceback.print_exc()


	def send(self):
		msg = "0x%x 0x%x" % (ops_value, ops_mask)

		if debug:
			print(msg + " to " + self.host, self,
			    file = sys.stderr)
		self.client.publish("/power/on/ops-set", msg, 1, retain)


	def increase_connect_wait(self):
		self.connect_wait = min(self.connect_wait * 2, MAX_CONNECT_WAIT)


	def on_connect(self, client, userdata, flags, rc):
		global connected

		try:
			if rc == 0:
				if debug:
					print("connected to " + self.host,
				    	    file = sys.stderr)
				self.connected = True
				self.connect_wait = 1
				with lock:
					if debug:
						print("  append", self,
						    file = sys.stderr)
					connected.append(self)
				if ops_mask != 0:
					self.send()
			else:
				print("could not connect to " + self.host +
				    ", rc =", rc, file = sys.stderr)
				if debug:
					print("  connected:", self.connected,
					    file = sys.stderr)
				client.loop_stop()
				self.increase_connect_wait()
				self.to_pending()
		except Exception as e:
			traceback.print_exc()


	def connect(self):
		self.client = mqtt.Client()
		self.client.on_connect = self.on_connect
		self.client.on_disconnect = self.on_disconnect
		try:
			if debug:
				print("connecting to " + self.host, self,
				    file = sys.stderr)
			self.connected = False
			self.client.connect(self.host)
			self.client.loop_start()
		except Exception as e:
			if verbose:
				print("can't connect to " + self.host, self,
				    file = sys.stderr)
			self.increase_connect_wait()
			self.to_pending()


	def __init__(self, host):
		self.host = host
		self.client = None
		self.connect_wait = 1
		self.connected = False
		self.t = 0


# --- Status update/change from input -----------------------------------------


def update(on, mask):
	global ops_value, ops_mask

	if on:
		new_value = ops_value | mask
	else:
		new_value = ops_value & ~mask
	new_mask = ops_mask | mask

	if debug:
		print("update 0x%x/0x%x: 0x%x/0x%x -> 0x%x/0x%x" %
		    (on, mask, ops_value, ops_mask, new_value, new_mask),
		    file = sys.stderr)

	if ops_value == new_value and ops_mask == new_mask:
		return
	ops_value = new_value
	ops_mask = new_mask

	# is it safe to lock while we're sending out lots of messages ?
	with lock:
		for miner in connected:
			if debug:
				print("updating", miner, file = sys.stderr)
			miner.send()


def message(topic, msg):
	if debug:
		print("message %s: %s" % (topic, msg), file = sys.stderr)
	if msg != "0" and msg != "1":
		print('%s: bad bit value "%s"' % (topic, msg),
		    file = sys.stderr)
		return
	for t in topics:
		if topic == t[0]:
			update(msg == "1", t[1])
			return
	print('unknown topic "%s"' % topic, file = sys.stderr)


# --- MQTT callbacks (input) --------------------------------------------------


def input_on_disconnect(client, userdata, rc):
	try:
		if rc != 0:
			print("unexpected disconnect from " + userdata +
			    ", rc =", rc, file = sys.stderr)
			failed = True
		if debug:
			print("STOP LOOP", file = sys.stderr)
		client.loop_stop()
	except Exception as e:
		traceback.print_exc()


def input_on_message(client, userdata, msg):
	try:
		message(msg.topic, msg.payload.decode("ascii"))
	except Exception as e:
		traceback.print_exc()


def input_on_connect(client, userdata, flags, rc):
	try:
		if rc == 0:
			if verbose:
				print("connected to " + userdata,
			    	    file = sys.stderr)
			for topic in topics:
				client.subscribe(topic[0])
		else:
			print("could not connect to " + userdata +
			    ", rc =", rc, file = sys.stderr)
			client.loop_stop()
			failed = True
	except Exception as e:
		traceback.print_exc()


# --- Command-line processing and main loop -----------------------------------


parser = argparse.ArgumentParser()
parser.add_argument("-b", "--broker", type = str, help = "local MQTT broker")
parser.add_argument("-d", "--debug", action = "store_true",
    help = "show messages (implies -v)")
parser.add_argument("-n", "--no-retain", action = "store_true",
    help = "do not retain messages sent to ops-set")
parser.add_argument("-r", "--refresh", type = float,
    help = "refresh interval (seconds)")
parser.add_argument("-v", "--verbose", action = "store_true",
    help = "show progress")
parser.add_argument("items", nargs = "*", default = [],
    help = "topics, hosts, or files")
args = parser.parse_args()

if args.broker is not None:
	broker = args.broker
if args.refresh is not None:
	refresh_seconds = float(args.refresh)
debug = args.debug
retain = not args.no_retain
verbose = args.verbose or debug


for arg in args.items:
	if os.path.isfile(arg):
		with open(arg) as file:
			for line in file:
				tmp = re.sub(r"\s*#.*$", "", line)
				tmp = re.sub(r"\s.*$", "", tmp)
				if tmp != "":
					pending.append(Miner(tmp))
	else:
		a = arg.split("@")
		if len(a) == 2:
			a[1] = int(a[1], 0)
			if a[1] < 0:
				a[1] = -a[1]
				ops_mask |= a[1]
			topics.append(a)
		else:
			pending.append(Miner(arg))

input = mqtt.Client(userdata = broker)
input.on_connect = input_on_connect
input.on_message = input_on_message
input.on_disconnect = input_on_disconnect
input.connect(broker)
input.loop_start()

t0 = time.monotonic()
while not failed:
	t = time.monotonic()
	if t - t0 > refresh_seconds:
		with lock:
			for miner in connected:
				miner.send()
		t0 = t
	with lock:
		todo = pending
		pending = []
	for miner in todo:
		if t >= miner.t:
			miner.connect()
		else:
			pending.append(miner)
	time.sleep(1)

sys.exit(1 if failed else 0)
