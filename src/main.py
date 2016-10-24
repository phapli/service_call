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

breakevent = threading.Event()

STATUS_DONE = 0
STATUS_NEW = 1
STATUS_PROCESS = 2

trangthai = 0
ping_status = 0
last_update = time.time()
bell = 0

room_map = None
lcd = None

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
			logger.info("LCD_Process")
			lcd.read()
###############################################################################		
class AlarmSystem(threading.Thread):
	stopper = None
	def __init__(self, stopper):
		super(AlarmSystem, self).__init__()
		self.stopper = stopper
	def run(self):	
		global trangthai, bell, last_update, ping_status
		logger.info("debug")
		time.sleep(2)
		# while not self.stopper.is_set():
			# if ping_status == 1:
			# 	GPIO.output(23, 1)
			# 	GPIO.output(25, 1)
			# else:
			# 	if(trangthai == 1):
			# 		GPIO.output(23, 1)
			# 		GPIO.output(25, 0)
			# 		GPIO.output(12, 1)
			# 		if(bell == 1):
	# 			time.sleep(0.25)
			# 		else:
	# 		GPIO.output(25, 1)
			# 		GPIO.output(12, 0)
			# 		time.sleep(0.25)
			# 		GPIO.output(25, 0)
			# 		GPIO.output(12, 1)
			# 		time.sleep(0.25)
			# 		GPIO.output(25, 1)
			# 		GPIO.output(12, 0)
			# 		time.sleep(0.25)
			# 	else:
			# 		GPIO.output(25, 1)
			# 		GPIO.output(12, 0)
			# 		GPIO.output(23, 0)
			# 		time.sleep(2)
			# 		GPIO.output(23, 1)
			# 		time.sleep(2)

##############################################################################
class Room:
	"""class for room status"""
	id = 0
	status = 0
	temp = -1
	humit = -1
	battery = -1
	def __init__(self, room_id):
		self.id = room_id
	
###############################################################################
class RF_Controller:
	ser = serial.Serial()
	buff_read = bytearray([0x00, 0x00, 0x00, 0x00, 0x00])

	CMD_UPDATE = 0x01
	CMD_NEW = 0x02
	CMD_PROCESS = 0x03
	CMD_DONE = 0x04
	CMD_ACK = 0x05

	def __init__(self, port, baudrate, timeout):
		self.ser.port = port
		self.ser.baudrate = baudrate
		self.ser.timeout = timeout
		self.ser.open()
		if self.ser.isOpen():
			logger.info("Open RF controller on port: " + self.ser.portstr)
		else:
			logger.error("Error when open RF controller on port: " + self.ser.portstr)


	def read(self):
		temp_buff_read = self.ser.read(5)
		self.ser.flushInput()
		if len(temp_buff_read) < 5:
			return -1
		logger.info("receive: " + binascii.hexlify(temp_buff_read))
		for index in range(len(temp_buff_read)):
			self.buff_read[index] = temp_buff_read[index]
		self.process_data(self.buff_read)

	def write(self, data):
		logger.info("send " + binascii.hexlify(data))
		self.ser.write(data)

	def write_process(self, room):
		data = bytearray([self.CMD_PROCESS, room, 0x00, 0x00, 0x00])
		self.write(data)

	def write_ack(self, cmd, room):
		data = bytearray([self.CMD_ACK, cmd, room, 0x00, 0x00])
		self.write(data)

	def process_data(self, data):
		global lcd
		logger.info("process data")
		if data[0] == self.CMD_UPDATE:
			logger.info("CMD UPDATE")
			room_id = data[1]
			room = room_map[room_id-1]
			if room:
				room.temp = data[2]
				room.humit = data[3]
				room.battery = data[4]
				lcd.update_info(room)
				self.write_ack(self.CMD_UPDATE,room_id)
			return 0
		elif data[0] == self.CMD_NEW:
			logger.info("CMD NEW")
			room_id = data[1]
			room = room_map[room_id-1]
			if room:
				logger.info(room.status)
				if room.status == STATUS_DONE:
					room.status = STATUS_NEW
					room.temp = data[2]
					room.humit = data[3]
					room.battery = data[4]
					lcd.update_info(room)
					logger.info("change status")
					lcd.change_status(room)
				self.write_ack(self.CMD_UPDATE,room_id)
			return 0
		elif data[0] == self.CMD_PROCESS:
			logger.info("CMD PROCESS")
			return 0
		elif data[0] == self.CMD_DONE:
			logger.info("CMD DONE")
			room_id = data[1]
			room = room_map[room_id-1]
			if room:
				logger.info(room.status)
				if room.status == STATUS_PROCESS:
					room.status = STATUS_DONE
					room.temp = data[2]
					room.humit = data[3]
					room.battery = data[4]
					lcd.update_info(room)
					logger.info("change status")
					lcd.change_status(room)
				self.write_ack(self.CMD_UPDATE,room_id)
			return 0
		elif data[0] == self.CMD_ACK:
			logger.info("CMD ACK")
			if data[1] == self.CMD_PROCESS:
				room_id = data[2]
				room = room_map[room_id-1]
				if room:
					logger.info(room.status)
					if room.status == STATUS_NEW:
						room.status = CMD_PROCESS
						logger.info("change status")
						lcd.change_status(room)
			return 0

###############################################################################
class LCD_Controller:

	FIELD_TEMP = 0
	FIELD_HUMIT = 1
	FIELD_BATTERY = 2

	buff_read = bytearray([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
	def __init__(self):
		Serial.begin(9600)
		self.refesh()

	def refesh(self):
		senddata = "page 1"
		Serial.printstr(senddata)
		self.end_cmd()

	def read(self):

		temp_buff_read = self.ser.read(7)
		logger.info("receive: " + binascii.hexlify(temp_buff_read))
		self.ser.flushInput()
		if len(temp_buff_read) < 7:
			return -1
		logger.info("receive: " + binascii.hexlify(temp_buff_read))
		for index in range(len(temp_buff_read)):
			self.buff_read[index] = temp_buff_read[index]
		# self.process_data(self.buff_read)

	def update_data(self, field, index, data):
		logger.info("update info room: " + str(index + 1) + " field: " + str(field) + " data: " + str(data))
		if data > 0:
			senddata =  "t" + str(index*3 + field) + ".txt=\"" + str(data) + "\""
		else:
			senddata =  "t" + str(index*3 + field) + ".txt=\"-\""
		Serial.printstr(senddata)
		self.end_cmd()

	def update_info(self, room):
		self.update_data(self.FIELD_TEMP, room.id - 1, room.temp)
		self.update_data(self.FIELD_HUMIT, room.id - 1, room.humit)
		self.update_data(self.FIELD_BATTERY, room.id - 1, room.battery)

	def change_status(self, room):
		logger.info(room.status)
		if room.status == STATUS_DONE:
			senddata =  "vis t" + str(18 + (room.id - 1)*2) + ",0"
			logger.info(senddata)
			Serial.printstr(senddata)
			self.end_cmd()
			senddata =  "vis t" + str(18 + (room.id - 1)*2 + 1) + ",0"
			logger.info(senddata)
			Serial.printstr(senddata)
			self.end_cmd()
			senddata =  "vis n" + str(room.id - 1) + ",1"
			logger.info(senddata)
			Serial.printstr(senddata)
			self.end_cmd()
		elif room.status == STATUS_NEW:
			print("NEW")
			senddata =  "vis t" + str(18 + (room.id - 1)*2 + 1) + ",0"
			Serial.printstr(senddata)
			self.end_cmd()
			senddata =  "vis t" + str(18 + (room.id - 1)*2) + ",1"
			logger.info(senddata)
			Serial.printstr(senddata)
			self.end_cmd()
			senddata =  "vis n" + str(room.id - 1) + ",1"
			Serial.printstr(senddata)
			self.end_cmd()
		elif room.status == STATUS_PROCESS:
			print("PROCESS")
			senddata =  "vis t" + str(18 + (room.id - 1)*2) + ",0"
			logger.info(senddata)
			Serial.printstr(senddata)
			self.end_cmd()
			senddata =  "vis t" + str(18 + (room.id - 1)*2 + 1) + ",1"
			Serial.printstr(senddata)
			self.end_cmd()
			senddata =  "vis n" + str(room.id - 1) + ",1"
			Serial.printstr(senddata)
			self.end_cmd()


	def end_cmd(self):
		Serial.write(0xFF)
		Serial.write(0xFF)
		Serial.write(0xFF)	

def init_system():
	global room_map, lcd, breakevent
	room_map = [Room(1), Room(2), Room(3), Room(4), Room(5), Room(6)]
	lcd = LCD_Controller()
	lcd.refesh()
	alarm_system = AlarmSystem(breakevent)
	handler_alarm = SignalHandler(breakevent,alarm_system)
	signal.signal(signal.SIGINT, handler_alarm)
	alarm_system.start()

	lcd_process = LCD_Process(breakevent)
	handler_lcd = SignalHandler(breakevent,lcd_process)
	signal.signal(signal.SIGINT, handler_lcd)
	lcd_process.start()

###############################################################################


def main():
	"""Main function
	"""
	init_system()

	logger.info("Service Call System Start ...")
	global breakevent
	logger.info("Opening rf")
	rf_controller = RF_Controller(RF_PORT, RF_BAUDRATE, 0.2)
	logger.info("Open rf OK")
	# class Time(threading.Thread):
	# 	stopper = None
	# 	def __init__(self, stopper):
	# 		super(Time, self).__init__()
	# 		self.stopper = stopper
	# 	def run(self):
	# 		global trangthai, last_update, ping_status
	# 		while not self.stopper.is_set():
	# 			thoigian = strftime("%T",localtime())
	# 			senddata = "t9.txt=\"" + thoigian + "\""
	# 				Serial.printstr(senddata)
	# 			end_cmd()
	# 			now = time.time()
	# 			if (now - last_update) > 30:
	# 				if ping_status == 0:
	# 					cmd_py = 'python /home/pi/working/alarm_python/alarm/send_email.py --codeit 03 --codevanhanh 0 --temp 0 --humid 0 --time ' + str(strftime("%T",localtime())) + ' &'
	# 					logger.info(cmd_py)
	# 					os.system(cmd_py)
	# 				ping_status = 1
	# 			if(trangthai ==1):
	# 				senddata = "page page5"
	# 				Serial.printstr(senddata)
	# 				end_cmd()
	# 				time.sleep(0.5)
	# 				senddata = "page page0"
	# 				Serial.printstr(senddata)
	# 				end_cmd()
	# 				time.sleep(0.5)
	# 			else:
	# 				time.sleep(1)

	# t = Time(breakevent)
	# handler = SignalHandler(breakevent,t)
	# signal.signal(signal.SIGINT, handler)
	# t.start()

	status = 0
	loivanhanh = 0
	pre_loivanhanh = 0
	pre_status = 0
	last_update = time.time()
	trangthai = 0
	while 1:
		#try:
		check_data = rf_controller.read()
		#except:
			#logger.error("cannot read from rf")
			#check_data = 0
		# if(check_data == 1):
		# 	send_txt("temperature", rf_controller.data_temp)
		# if(check_data == 2):
		# 	send_txt("humid", rf_controller.data_humid)
		# if(check_data == 3):
		# 	if rf_controller.data_alarm ==2:
		# 		status = 2
		# 	elif rf_controller.data_alarm >=1:
		# 		status = 1
		# 	else:
		# 		status = 0
		# if(check_data == 4):
		# 	if pre_loivanhanh != rf_controller.data_error: 
		# 		loivanhanh = rf_controller.data_error
		# 	pre_loivanhanh = rf_controller.data_error
		# if((pre_status == 0) and (status ==1)):
		# 	trangthai = 1
		# 	bell = 1
		# elif((pre_status == 1) and (status == 0)):
		# 	trangthai = 0
		# 	bell = 0
		# if(check_data > 2):
		# 	cmd_py = 'python /home/pi/working/alarm_python/alarm/send_email.py --codeit ' + str(pre_status) + str(status) + ' --codevanhanh ' + str(loivanhanh) + ' --temp ' + str(rf_controller.data_temp) + ' --humid ' + str(rf_controller.data_humid) + ' --time ' + str(strftime("%T",localtime())) + ' &'
		# 	logger.info(cmd_py)
		# 	os.system(cmd_py)
		# 	pre_status = status
	Serial.end()
###############################################################################
# Run
###############################################################################

# GPIO.output(23, 0)
# GPIO.output(25, 0)
# GPIO.output(12, 1)
# time.sleep(1)

# GPIO.output(23, 1)
# GPIO.output(25, 1)
# GPIO.output(12, 0)

if __name__ == '__main__': main()

