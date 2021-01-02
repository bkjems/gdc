# gdc
Garage Door Controller (gdc)
======================
Control and monitor garage doors using a Raspberry PI

Overview:
---------

This project allows you to monitor and control your garage doors remotely (via the web). The software is written in Python and runs on a Raspberry Pi:

* Shows the state of the garage doors (open, closed, opening, or closing)
* Notification of changes via email or texts
* Remote control of the garage doors (webpage)
* Timestamp state changes for each garage door
* Logging of all garage door activity including last time the garage was opened
* Ability to reset notification with motion detection

Launch at startup
* sudo service gdc stop
* sudo service gdc start
