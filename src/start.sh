#!/bin/sh
sudo ps -ef | grep "8080" | awk '{print $2}' |sudo xargs kill -9
sudo python /home/pi/service_call/src/main.py 8080
