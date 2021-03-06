import fileinput
import serial
import binascii
import time

RF_PORT = "/dev/ttyUSB0"
RF_BAUDRATE = 9600

class RF_Controller:
	ser = serial.Serial()
	buff_read = bytearray([0x00, 0x00, 0x00, 0x00, 0x00])

	CMD_UPDATE = 0x01
	CMD_NEW = 0x02
	CMD_PROCESS = 0x03
	CMD_DONE = 0x03
	CMD_ACK = 0x04

	def __init__(self, port, baudrate, timeout):
		self.ser.port = port
		self.ser.baudrate = baudrate
		self.ser.timeout = timeout
		self.ser.open()
		print self.ser.is_open
	def read(self):
		temp_buff_read = self.ser.read(5)
		self.ser.flushInput()
		if len(temp_buff_read) < 5:
			return -1
		logger.info("receive: " + binascii.hexlify(temp_buff_read))
		for index in range(len(temp_buff_read)):
			self.buff_read[index] = temp_buff_read[index]
		self.process_data(temp_buff_read)

	def write(self, data):
		print ("send " + binascii.hexlify(data))
		for index in range(len(data)):
			time.sleep(0.03)
			self.ser.write(bytearray([data[index]]))

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
			room_id = data[1]
			room = room_map[room_id]
			if room:
				room.temp = data[2]
				room.humit = data[3]
				room.battery = data[4]
				lcd.update_info(room)
				return 0
		elif data[0] == self.CMD_NEW:
			return 0
		elif data[0] == self.CMD_PROCESS:
			return 0
		elif data[0] == self.CMD_DONE:
			return 0
		elif data[0] == self.CMD_ACK:
			return 0


rf_controller = RF_Controller(RF_PORT, RF_BAUDRATE, 0.2)

while 1:
	line = "55aa77665544332211ffff"
	rf_controller.write(binascii.unhexlify(line.strip()))
	 # if line == "1\n":
	# 	data = bytearray([0x01, 0x01, 0x15, 0x3d, 0x2f])
	# 	rf_controller.write(data)
	# elif line == "2\n"
	# 	data = bytearray([0x01, 0x01, 0x15, 0x3d, 0x2f])
	# 	rf_controller.write(data)
	time.sleep(2)