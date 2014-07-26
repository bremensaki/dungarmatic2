#!/usr/bin/env python
# -*- coding: utf-8 -*-
##
## Setup stuff
##
from __future__ import with_statement

import threading
import time
import sys
import os
import re
import random
import daemon
from collections import deque
import optparse
import ConfigParser
import xmpp

basedir = sys.path[0]
sys.path.append(basedir + "/lib")

from jabberbot import JabberBot

##
## Quick reference for defaults
##
version			= '2.0.a1'
defaultconfig	= 'dungar.ini'
defaultlog		= 'dungar.log'

##
## Basic command line options, put this in another file eventually, right now it's nice to see
##
optparser = optparse.OptionParser()
optparser.add_option("-c", "--config", dest="configfile",
					help="configuration file to use (default: "+defaultconfig+")",
					default=defaultconfig)
optparser.add_option("-l", "--log", dest="logfile",
					help="log file to use (default: "+defaultlog+")",
					default=defaultlog)
optparser.add_option("-n", "--nodaemon", dest="nodaemon",
					action="store_true", help="do not detach as daemon, run in foreground",
					default=False)
(config, args) = optparser.parse_args()

# Really basic config handling, just enough to get the passwords out of the source code.
conffile = ConfigParser.ConfigParser()
conffile.read(config.configfile)

config.xmppUser = conffile.get('main', 'xmppUser')
config.xmppNick = conffile.get('main', 'xmppNick')
config.xmppPass = conffile.get('main', 'xmppPass')
config.xmppResource = config.xmppNick + ' (' + version + ')'
config.xmppChannels = []
for channel in conffile.get('main', 'xmppChannels').split(','):
	config.xmppChannels.append(channel.strip())
	
# How many messages to keep in short term memory
config.historySize = 50

# should check if this worked tbqh
outfile = open(config.logfile, 'a')

## Main bot class
class mucBot(JabberBot):
	def __init__(self, username, password, res=None, debug=False, acceptownmsgs=False):
		super(mucBot, self).__init__(username, password, res, debug, acceptownmsgs)
		print self.res

		self.__finished = False
		self.__show = None
		self.__status = None
		self.__seen = {}
		self.__threads = {}
		self.__lastping = time.time()

		self.nick = config.xmppNick
		self.messageToMe = r"^\s*" + self.nick + r"(:| :|,)\s*"

		self.seenhistory = deque('', config.historySize)
		self.saidhistory = deque('', config.historySize)

		self.later = time.time() + 30

#	def send_message(self, mess):
#		"""Send an XMPP message"""
#		self.connect().send(mess)
				
	def callback_message(self, conn, mess):
		"""A more MUC-centric message handler, not handling just explicit commands
		but assuming we want to at least take a look at any message going past.
		
		Plugin handling for extra capabilities goes here."""

		# Prepare to handle either private chats or group chats
		messtype = mess.getType()
		fromjid = mess.getFrom()
		props = mess.getProperties()
		text = mess.getBody()
		username = self.get_sender_username(mess)

		reply = None
		mustreply = False
		replyprefix = ''
		defaultreply = ''
		
		# If a message format is not supported (eg. encrypted),
		# text will be None
		if not text:
			return
		else:
			self.seenhistory.append(mess)

		# Ignore messages from before we joined
		if xmpp.NS_DELAY in props:
			return

		# conference or 1-to-1?
		if messtype == 'groupchat':
			# If this message appears to be FROM me, ignore it - for a MUC compare incoming
			# JID resource with our nick, as sender's real JID cannot be assumed to be available
			if fromjid.getResource() == config.xmppNick:
				return

			# If the message is personally directed TO me, always reply
			regex = re.compile(self.messageToMe, re.IGNORECASE)
			if regex.search(text):
				mustreply = True
				defaultreply = 'get out'

			# Make prefix in case a reply should be personally directed
			replyprefix = username + ": "
		# assuming 1-to-1 from here
		else:
		# Ignore messages from myself
			if str(fromjid) == str(self.jid):
				print "shut up, me"
				return
			else:
				mustreply = True
				defaultreply = 'leave me alone'

		# Remember the last-talked-in message thread for replies
		# FIXME i am not threadsafe
		self.__threads[fromjid] = mess.getThread()

		# Here is where real handling of messages will go

		regex = re.compile(r"(?:\s|\A)alot(?:\s|\Z)", re.IGNORECASE)
		if regex.search(text):
			reply = self.handler_alot(mess)

		regex = re.compile(r".*?:hfive:\Z", re.IGNORECASE)
		if regex.search(text):
			reply = self.handler_highfive(mess)

		# Here is where real handling of messages will end

		if reply is None and mustreply is True:
			reply = defaultreply

		if reply:
			self.saidhistory.append(reply)
			self.send_simple_reply(mess, replyprefix + reply)

	def idle_proc(self):
		"""This function will be called in the main loop.
		
		I'm still in two minds if this stuff should be done here or in
		the parent process, or maybe something in both."""
		self._idle_ping()

		# We'll do cron-like things here I reckon
		now = time.time()
		if now >= self.later:
			# 30s heartbeat <3
			print("%s <3" % self.seenhistory[-1].getBody())
			self.later += 30

	def handler_alot (self, mess):
		"""One of Dungarmatic 1's simpler routines for testing."""
		chance = {':eng101: "a lot"': 0.9, ':argh:': 0.1}
		return self.calculateChance(chance)

	def handler_highfive (self, mess):
		""":hfive:"""
		chance = {':hfive:': 0.99, ':awesome::hf::awesomelon:': 0.01}
		return self.calculateChance(chance)

	# This function is used a crazy amount in old Dungarmatic routines, needs to
	# be dumped at some point or moved to a plugin or something.
	def calculateChance(self, chance):
		"""chance should be a dictionary with the keys being a number like 0.25
			and the value a string to return, the keys should sum to a maximum 
			of <= 1.0"""
		random.seed()
		rnd = random.random()
		t = 0
		for message in chance.keys():
			c = chance[message];
			m = t
			t = t + c
			if rnd < t and rnd >= m:
				return message
		return None

def core():
	core_bot = mucBot(config.xmppUser, config.xmppPass, res=config.xmppResource, debug=True)
	for channel in config.xmppChannels:
		core_bot.muc_join_room(channel, username=config.xmppNick)
	core_thread = threading.Thread(target=core_bot.serve_forever)
	core_thread.setDaemon(True)
	core_thread.setName(config.xmppUser)
	core_thread.start()

	return core_thread

##
## The "make bot go now" block
##

if __name__ == "__main__":
	print "%s (%s): %i START" % (config.xmppNick, version, os.getpid())
	if config.nodaemon:
		core_thread = core()
	else:
		dungard = daemon.DaemonContext(
			working_directory=basedir,
			stdout=outfile,
			stderr=outfile,
			)
		with dungard:
			core_thread = core()

	while core_thread.isAlive():
		sys.stdout.flush()
		sys.stderr.flush()
		time.sleep(1)
	print "%s (%s): %i END" % (config.xmppNick, version, os.getpid())
