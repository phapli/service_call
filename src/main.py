#!/usr/bin/env python
import binascii
import sys
import os
import signal
import serial
import time
import threading
from iteadsdk import *
from threading import Timer
from time import localtime, strftime
import RPi.GPIO as GPIO
import logging
import os.path
import re
from logging.handlers import RotatingFileHandler
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import json
import random

logger = logging.getLogger(__name__)
def initialize_logger(output_dir):
	logger.setLevel(logging.INFO)
	# create console handler and set level to INFO
	handler = logging.StreamHandler()
	handler.setLevel(logging.INFO)
	logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
	handler.setFormatter(logFormatter)
	logger.addHandler(handler)
	  # create error file handler and set level to error
	handler = RotatingFileHandler(os.path.join(output_dir, "error.log"),"a", maxBytes=100*1024*1024, 
	  backupCount=2, encoding=None, delay=0)
	handler.setLevel(logging.ERROR)
	logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
	handler.setFormatter(logFormatter)
	logger.addHandler(handler)
	  # create INFO file handler and set level to info
	handler = RotatingFileHandler(os.path.join(output_dir, "application.log"),"a", maxBytes=100*1024*1024, 
	  backupCount=2, encoding=None, delay=0)
	handler.setLevel(logging.INFO)
	logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
	handler.setFormatter(logFormatter)
	logger.addHandler(handler)

initialize_logger("/var/log/service_call")

###############################################################################
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(12, GPIO.OUT) #Buzzer
GPIO.setup(23, GPIO.OUT) #GREEN led
GPIO.setup(25, GPIO.OUT) #RED led

RF_PORT = "/dev/ttyUSB0"
RF_BAUDRATE = 9600

LCD_PORT = "/dev/ttyAMA0"
LCD_BAUDRATE = 9600

LCD_STATE_NORMAL = 0
LCD_STATE_CONFIG = 1

breakevent = threading.Event()

STATUS_DONE = 0
STATUS_NEW = 1
STATUS_PROCESS = 2

last_update = time.time()
lcd_state = LCD_STATE_NORMAL
bell = 0

room_map = None
lcd = None
rf_controller = None



###############################################################################
class SignalHandler:
	stopper = None
	workers = None
	def __init__(self, stopper,workers):
		self.stopper = stopper
		self.workers = workers
	def __call__(self, signum, frame):
		self.stopper.set()
		sys.exit(0)

###############################################################################		
class LCD_Process(threading.Thread):
	stopper = None
	lcd = None
	def __init__(self, stopper, lcd):
		super(LCD_Process, self).__init__()
		self.stopper = stopper
		self.lcd = lcd
	def run(self):
		while not self.stopper.is_set():
			lcd.read()
###############################################################################		
class RF_Process(threading.Thread):
	stopper = None
	rf = None
	def __init__(self, stopper, rf):
		super(RF_Process, self).__init__()
		self.stopper = stopper
		self.rf = rf
	def run(self):
		start = time.time()
		for room in room_map:
			lcd.init_info(room)
			lcd.change_status(room)
		while not self.stopper.is_set():
			# logger.info("process time " + str(time.time() - start))
			start = time.time()
			check_data = rf_controller.read()
			
			for room in room_map:
				if time.time() - room.last_update >= 7*60:
					temp = -1
					humit = -1
					batt = -1
					lcd.update_info(room, temp, humit, batt)
			
###############################################################################		
class AlarmSystem(threading.Thread):
	stopper = None
	def __init__(self, stopper):
		super(AlarmSystem, self).__init__()
		self.stopper = stopper
	def run(self):	
		global room_map
		while not self.stopper.is_set():
			alarm_status = 0
			for room in room_map:
				if room.status == STATUS_NEW:
					alarm_status = 2
					break
				elif room.status == STATUS_PROCESS:
					alarm_status = 1
			if alarm_status == 0:
				#  green status
				GPIO.output(25, 1)
				GPIO.output(12, 0)
				GPIO.output(23, 0)
				time.sleep(2)
				GPIO.output(23, 1)
				time.sleep(2)
			elif alarm_status == 1:
				# yellow status
				logger.info("yellow status")
				GPIO.output(23, 1)
				GPIO.output(12, 0)
				GPIO.output(25, 0)
				time.sleep(2)
				GPIO.output(25, 1)
				time.sleep(2)
			elif alarm_status == 2:
				# red status
				logger.info("red status")
				GPIO.output(23, 1)
				GPIO.output(12, 1)
				GPIO.output(25, 0)
				time.sleep(2)
				GPIO.output(25, 1)
				time.sleep(2)

##############################################################################
class Room:
	"""class for room status"""
	id = -1
	room_id = 0
	status = 0
	temp = -1
	humit = -1
	battery = -1
	last_update = 0
	pending_cmd = False
	last_send_time = 0
	retry_count = 0

	def __init__(self, room_id):
		self.room_id = room_id
		self.status = 0
		self.temp = -1
		self.humit = -1
		self.battery = -1
		self.last_update = 0
		self.pending_cmd = False
		self.last_send_time = 0
		self.retry_count = 0
	
###############################################################################
class RF_Controller:
	ser = serial.Serial()
	state = -1
	buff_read = bytearray([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

	CMD_IDLE = 0x00
	CMD_REQ_ID = 0x01
	CMD_REQ_SER = 0x02
	CMD_REQ_DONE = 0x04
	CMD_PROCESSING = 0x08
	CMD_REQ_ID_OK = 0x10

	def __init__(self, port, baudrate, timeout):
		self.ser.port = port
		self.ser.baudrate = baudrate
		self.ser.timeout = timeout
		self.ser.open()
		if self.ser.isOpen():
			logger.info("Open RF controller on port: " + self.ser.portstr)
		else:
			logger.error("Error when open RF controller on port: " + self.ser.portstr)


	# def read(self):
	# 	temp_buff_read = self.ser.read(11)
	# 	self.ser.flushInput()
	# 	if len(temp_buff_read) < 11:
	# 		return -1
	# 	logger.info("receive: " + binascii.hexlify(temp_buff_read))
	# 	for index in range(2,7):
	# 		self.buff_read[index-2] = temp_buff_read[index]
	# 	self.process_data(self.buff_read)

	def read(self):
		#logger.info("try read data")
		global last_update
		temp_buff_read = self.ser.read(11)
		self.ser.flushInput()
		if len(temp_buff_read) > 0:
			logger.info("receive: " + binascii.hexlify(temp_buff_read))
			data_process = bytearray(len(temp_buff_read))
			for index in range(len(temp_buff_read)):
				data_process[index] = temp_buff_read[index]
			return self.queue_data(data_process)
		else:
			return -1

	def queue_data(self, data_process):
		for index in range(len(data_process)):
			if self.state > 0:
				self.state = self.state + 1
				self.buff_read[self.state] = data_process[index]
				if self.state == 9:
					if data_process[index] != 255:
						self.state = -1
				if self.state == 10:
					self.state = -1
					if data_process[index] == 255:
						logger.info("data: " + binascii.hexlify(self.buff_read))
						return self.process_data(self.buff_read)
			else:
				if self.state == 0:
					if data_process[index] == 170:
						self.state = 1
						self.buff_read[self.state] = data_process[index]
					else:
						self.state = -1
				else:
					if data_process[index] == 85:
						self.state = 0
						self.buff_read[self.state] = data_process[index]
		return -1

	def write(self, data):
		logger.info("send " + binascii.hexlify(data))
		for index in range(len(data)):
			#time.sleep(0.004)
			self.ser.write(bytearray([data[index]]))

	def write_process(self, room):
		# room.pending_cmd = True
		# room.last_send_time = time.time()
		# data = bytearray([self.CMD_REQ_DONE, room.room_id, 0x00, 0x00, 0x00])
		# self.write(data)
		room.status = STATUS_PROCESS
		lcd.change_status(room)

	def write_ack(self, id, room_id, cmd_id, status):
		logger.info("write ack")
		data = bytearray([0x55, 0xAA, id, room_id, cmd_id, status, 0x00, 0x00, 0x00, 0xFF, 0xFF])
		self.write(data)

	def write_id(self, id, room_id, cmd_id, status, new_id, new_room_id):
		logger.info("write ack")
		data = bytearray([0x55, 0xAA, id, room_id, cmd_id, status, new_id, new_room_id, 0x00, 0xFF, 0xFF])
		self.write(data)

	def process_data(self, data):
		global lcd, lcd_state, req_id, req_room_id, req_cmd_id
		if lcd_state == LCD_STATE_NORMAL:
			logger.info("process data")
			id = data[2]
			room_id = data[3]
			cmd_id = data[4]
			status = data[5]
			temp = data[6]
			humit = data[7]
			batt = data[8]
			if status == self.CMD_IDLE:
				logger.info("CMD_IDLE")
				if room_id >= 1 and room_id <= 6: 
					room = room_map[room_id-1]
					if room:
						lcd.update_info(room, temp, humit, batt)
						if room.status != STATUS_DONE:
							logger.info("change status")
							room.status = STATUS_DONE
							lcd.change_status(room)
						self.write_ack(id, room_id, cmd_id, status)
					return 0
			elif status == self.CMD_REQ_SER:
				logger.info("CMD_REQ_SER")
				if room_id >= 1 and room_id <= 6: 
					room = room_map[room_id-1]
					if room:
						logger.info(room.status)
						lcd.update_info(room, temp, humit, batt)
						if room.status != STATUS_NEW:
							logger.info("change status")
							room.status = STATUS_NEW
							lcd.change_status(room)
						self.write_ack(id, room_id, cmd_id, self.CMD_REQ_DONE)
					return 0
			elif status == self.CMD_REQ_DONE:
				logger.info("CMD_REQ_DONE")
				if room_id >= 1 and room_id <= 6: 
					room = room_map[room_id-1]
					if room:
						logger.info(room.status)
						lcd.update_info(room, temp, humit, batt)
						if room.status == STATUS_DONE:
							logger.info("change status")
							room.status = STATUS_NEW
							lcd.change_status(room)
						if room.status == STATUS_NEW:
							self.write_ack(id, room_id, cmd_id, self.CMD_REQ_DONE)
						if room.status == STATUS_PROCESS:
							self.write_ack(id, room_id, cmd_id, self.CMD_PROCESSING)
					return 0
			elif status == self.CMD_PROCESSING:
				logger.info("CMD_PROCESSING")
				if room_id >= 1 and room_id <= 6: 
					room = room_map[room_id-1]
					if room:
						logger.info(room.status)
						lcd.update_info(room, temp, humit, batt)
						self.write_ack(id, room_id, cmd_id, self.CMD_PROCESSING)
					return 0
			elif status == self.CMD_REQ_ID:
				logger.info("CMD_REQ_ID")
				req_id = id
				req_room_id = room_id
				req_cmd_id = cmd_id
				lcd.switch(LCD_STATE_CONFIG)
				return 0

###############################################################################
class LCD_Controller:

	FIELD_TEMP = 0
	FIELD_HUMIT = 1
	FIELD_BATTERY = 2

	ser = serial.Serial()
	buff_read = bytearray([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

	def __init__(self, port, baudrate, timeout):
		self.ser.port = port
		self.ser.baudrate = baudrate
		self.ser.timeout = timeout
		self.ser.open()
		if self.ser.isOpen():
			logger.info("Open LCD controller on port: " + self.ser.portstr)
		else:
			logger.error("Error when open LCD controller on port: " + self.ser.portstr)

	def refesh(self):
		self.write("page 1")

	def switch(self, state):
		global lcd_state
		if lcd_state != state:
			if state == LCD_STATE_NORMAL:
				self.write("page 0")
			else:
				self.write("page 4")
		lcd_state = state

	def write(self, cmd):
		logger.info("send " + cmd)
		self.ser.write(cmd)
		self.end_cmd()

	def read(self):
		temp_buff_read = self.ser.read(7)
		self.ser.flushInput()
		if len(temp_buff_read) < 7:
			return -1
		logger.info("receive: " + binascii.hexlify(temp_buff_read))
		for index in range(len(temp_buff_read)):
			self.buff_read[index] = temp_buff_read[index]
		self.process_data(self.buff_read)

	def process_data(self, data):
		global room_map, rf_controller, lcd_state, req_id, req_room_id, req_cmd_id
		room_id = 0
		if data[0] == 0x65 and data[3] == 0x00 and data[4] == 0xff and data[5] == 0xff and data[6] == 0xff:
			logger.info("button " + str(data[2]))
			if data[2] == 0x67 or data[2] == 0x0b:
				room_id = 1
			elif data[2] == 0x68 or data[2] == 0x0c:
				room_id = 2
			elif data[2] == 0x69 or data[2] == 0x0d:
				room_id = 3
			elif data[2] == 0x6a or data[2] == 0x0e:
				room_id = 4
			elif data[2] == 0x6b or data[2] == 0x0f:
				room_id = 5
			elif data[2] == 0x6c or data[2] == 0x10:
				room_id = 6
			logger.info("room " + str(room_id))
			if room_id != 0:
				if room_id >= 1 and room_id <= 6: 
					room = room_map[room_id-1]
					if lcd_state == LCD_STATE_CONFIG:
						new_room_id = room_id
						new_id = random.randint(0,255)
						self.write_id(id, room_id, cmd_id, self.CMD_REQ_ID_OK, new_id, new_room_id)
						lcd.switch(LCD_STATE_NORMAL)
					else:
						if room and room.status == STATUS_NEW:
							rf_controller.write_process(room)
	def update_data(self, field, index, data):
		logger.info("update info room: " + str(index + 1) + " field: " + str(field) + " data: " + str(data))
		if data > 100:
			data = 100
		self.update_icon(field, index, data)
		if data > 0:
			senddata =  "t" + str(index*3 + field) + ".txt=\"" + str(data) + "\""
		else:
			senddata =  "t" + str(index*3 + field) + ".txt=\"-\""
		self.write(senddata)

	def update_icon(self, field, index, data):
		if field == self.FIELD_TEMP:
			if data < 30 or data > 40:
				self.write("vis p" + str(index*9) + ",1")
				self.write("vis p" + str(index*9 + 1) + ",0")
				self.write("vis p" + str(index*9 + 2) + ",0")
			elif data > 35 and data <= 40:
				self.write("vis p" + str(index*9) + ",0")
				self.write("vis p" + str(index*9 + 1) + ",1")
				self.write("vis p" + str(index*9 + 2) + ",0")
			else:
				self.write("vis p" + str(index*9) + ",0")
				self.write("vis p" + str(index*9 + 1) + ",0")
				self.write("vis p" + str(index*9 + 2) + ",1")
		elif field == self.FIELD_HUMIT:
			if data > 70 and data < 0:
				self.write("vis p" + str(index*9 + 3) + ",1")
				self.write("vis p" + str(index*9 + 4) + ",0")
				self.write("vis p" + str(index*9 + 5) + ",0")
			elif data >= 60 and data <= 70:
				self.write("vis p" + str(index*9 + 3) + ",0")
				self.write("vis p" + str(index*9 + 4) + ",1")
				self.write("vis p" + str(index*9 + 5) + ",0")
			else:
				self.write("vis p" + str(index*9 + 3) + ",0")
				self.write("vis p" + str(index*9 + 4) + ",0")
				self.write("vis p" + str(index*9 + 5) + ",1")
		elif field == self.FIELD_BATTERY:
			if data <= 5:
				self.write("vis p" + str(index*9 + 6) + ",1")
				self.write("vis p" + str(index*9 + 7) + ",0")
				self.write("vis p" + str(index*9 + 8) + ",0")
			elif data > 5 and data <= 20:
				self.write("vis p" + str(index*9 + 6) + ",0")
				self.write("vis p" + str(index*9 + 7) + ",1")
				self.write("vis p" + str(index*9 + 8) + ",0")
			else:
				self.write("vis p" + str(index*9 + 6) + ",0")
				self.write("vis p" + str(index*9 + 7) + ",0")
				self.write("vis p" + str(index*9 + 8) + ",1")

	def update_info(self, room, temp, humit, batt):
		room.last_update = time.time()
		if room.temp != temp:
			room.temp = temp
			self.update_data(self.FIELD_TEMP, room.room_id - 1, room.temp)
		if room.humit != humit:
			room.humit = humit
			self.update_data(self.FIELD_HUMIT, room.room_id - 1, room.humit)
		if room.battery != batt:
			room.battery = batt
			self.update_data(self.FIELD_BATTERY, room.room_id - 1, room.battery)

	def init_info(self, room):
		self.update_data(self.FIELD_TEMP, room.room_id - 1, room.temp)
		self.update_data(self.FIELD_HUMIT, room.room_id - 1, room.humit)
		self.update_data(self.FIELD_BATTERY, room.room_id - 1, room.battery)

	def change_status(self, room):
		logger.info(room.status)
		if room.status == STATUS_DONE:
			self.write("vis t" + str(18 + (room.room_id - 1)*2) + ",0")
			self.write("vis t" + str(18 + (room.room_id - 1)*2 + 1) + ",0")
			self.write("vis n" + str((room.room_id - 1)*3) + ",1")
			self.write("vis n" + str((room.room_id - 1)*3 + 1) + ",0")
			self.write("vis n" + str((room.room_id - 1)*3 + 2) + ",0")
		elif room.status == STATUS_NEW:
			print("NEW")
			self.write("vis t" + str(18 + (room.room_id - 1)*2 + 1) + ",0")
			self.write("vis t" + str(18 + (room.room_id - 1)*2) + ",1")
			self.write("vis n" + str((room.room_id - 1)*3) + ",0")
			self.write("vis n" + str((room.room_id - 1)*3 + 1) + ",1")
			self.write("vis n" + str((room.room_id - 1)*3 + 2) + ",0")
		elif room.status == STATUS_PROCESS:
			print("PROCESS")
			self.write("vis t" + str(18 + (room.room_id - 1)*2) + ",0")
			self.write("vis t" + str(18 + (room.room_id - 1)*2 + 1) + ",1")
			self.write("vis n" + str((room.room_id - 1)*3) + ",0")
			self.write("vis n" + str((room.room_id - 1)*3 + 1) + ",0")
			self.write("vis n" + str((room.room_id - 1)*3 + 2) + ",1")


	def end_cmd(self):
		self.ser.write(bytearray([0xFF, 0xFF, 0xFF]))	

def obj_dict(obj):
	return obj.__dict__

def init_system():
	global room_map, lcd, breakevent, rf_controller
	room_map = [Room(1), Room(2), Room(3), Room(4), Room(5), Room(6)]
	lcd = LCD_Controller(LCD_PORT, LCD_BAUDRATE, 0.2)
	lcd.refesh()
	rf_controller = RF_Controller(RF_PORT, RF_BAUDRATE, 0.2)

	alarm_system = AlarmSystem(breakevent)
	handler_alarm = SignalHandler(breakevent,alarm_system)
	signal.signal(signal.SIGINT, handler_alarm)
	alarm_system.start()

	lcd_process = LCD_Process(breakevent, lcd)
	handler_lcd = SignalHandler(breakevent,lcd_process)
	signal.signal(signal.SIGINT, handler_lcd)
	lcd_process.start()

	rf_process = RF_Process(breakevent, rf_controller)
	handler_rf = SignalHandler(breakevent,rf_process)
	signal.signal(signal.SIGINT, handler_rf)
	rf_process.start()
###############################################################################
class Server(BaseHTTPRequestHandler):
	def _set_headers(self, content_type='text/html'):
		self.send_response(200)
		self.send_header('Content-type', 'text/html')
		self.end_headers()
		
	def do_GET(self):
		#self._set_headers()
		#self.wfile.write("<html><body><h1>hi!</h1></body></html>")
		global room_map
                self._set_headers()
                data = json.dumps(room_map, default=obj_dict)
                self.wfile.write(data)	

	def do_HEAD(self):
		self._set_headers()
		
	def do_POST(self):
		global room_map
		self._set_headers()
		data = json.dumps(room_map, default=obj_dict)
		self.wfile.write(data)

###############################################################################
def main(server_class=HTTPServer, handler_class=Server, port=80):

	logger.info("Init ...")
	init_system()
	server_address = ('', port)
	httpd = server_class(server_address, handler_class)
	logger.info("Calling Service Start ...")
	httpd.serve_forever()
###############################################################################
# Run
###############################################################################
if __name__ == '__main__': 
	from sys import argv

	if len(argv) == 2:
		main(port=int(argv[1]))
	else:
		main()
