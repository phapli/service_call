import subprocess
import smtplib
import socket
from email.mime.text import MIMEText
import datetime
import logging
import os.path
import re
import time
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



# Change to your own account information
to = 'phapli1991@gmail.com'
to1 = 'service.calling.system@gmail.com'
gmail_user = 'service.calling.system@gmail.com'
gmail_password = 'giaothoa1234'

tries = 0
while True:
    if (tries > 60):
        exit()
    try:
        smtpserver = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        smtpserver.ehlo()
        smtpserver.starttls()
        smtpserver.ehlo
        smtpserver.login(gmail_user, gmail_password)
        today = datetime.date.today()
        # Very Linux Specific
        arg='ip route list'
        p=subprocess.Popen(arg,shell=True,stdout=subprocess.PIPE)
        data = p.communicate()
        split_data = data[0].split()
        ipaddr = split_data[split_data.index('src')+1]
        my_ip = 'Service Calling System started up on ip: %s' %  ipaddr
        logger.info(my_ip)
        msg = MIMEText(my_ip)
        msg['Subject'] = 'IP For Service Calling System'
        msg['From'] = gmail_user
        msg['To'] = to
        smtpserver.sendmail(gmail_user, [to], msg.as_string())

        msg1 = MIMEText(my_ip)
        msg1['Subject'] = 'IP For Service Calling System'
        msg1['From'] = gmail_user
        msg1['To'] = to1
        smtpserver.sendmail(gmail_user, [to1], msg1.as_string())
        smtpserver.quit()
        break
    except Exception as e:
        logger.error("ERROR to send ip")
        tries = tries + 1
        time.sleep(5)