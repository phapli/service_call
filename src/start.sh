#!/bin/sh
sudo ps -ef | grep "8080" | awk '{print $2}' |sudo xargs kill -9
sudo python ./main.py 8080