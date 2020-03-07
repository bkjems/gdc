#!/usr/bin/env python
"""Software to monitor and control garage doors via a raspberry pi."""
import datetime
import httplib
import json
import logging
import logging.handlers
import time
import smtplib
import sys
import urllib

import RPi.GPIO as gpio
import utils as Utils
import door as Doors

from email.mime.text import MIMEText
from fcache.cache import FileCache
from twisted.cred import portal
from twisted.internet import reactor
from twisted.internet import ssl
from twisted.internet import task
from twisted.web import server
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory
from twisted.web.static import File
from twisted.web.resource import Resource, IResource
from zope.interface import implements

class CloseAllHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        if self.controller.close_all():
            return ''
        else:
            return 'All doors are closed.'

class LogHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def tail(self, filepath):
        data_value = ""
        with open(filepath, "rb") as f:
            loglines = f.readlines()[-60:]
        f.close()

        # reverse order, most recent at the top
        for logline in reversed(loglines):
            data_value += logline

        return data_value

    def render(self, request):
        data = self.tail(self.controller.file_name)
        return "<html><body><pre>%s</pre></body></html>" % (data,)

class ClickHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        d = request.args['id'][0]
        door = self.controller.getDoor(d)
        if door != None and door.state != Utils.CLOSING and door.state != Utils.OPENING:
            door.toggle_relay()

class ClickMotionTestHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        self.controller.motion('testpin')

class ConfigHandler(Resource):
    isLeaf = True
    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        request.setHeader('Content-Type', 'application/json')
        return json.dumps([(d.id, d.name, d.state, d.tis.get(d.state))
                           for d in self.controller.doors])

class UptimeHandler(Resource):
    isLeaf = True
    def __init__ (self, controller):
        Resource.__init__(self)

    def uptime(self):
        try:
            f = open( "/proc/uptime" )
            contents = f.read().split()
            f.close()
        except:
            return "Cannot open uptime file: /proc/uptime"

        return Utils.elapsed_time(float(contents[0]))

    def render(self, request):
        request.setHeader('Content-Type', 'application/json')
        return json.dumps("Uptime: " + self.uptime())

class UpdateHandler(Resource):
    isLeaf = True
    def __init__(self, controller):
        Resource.__init__(self)
        self.delayed_requests = []
        self.controller = controller

    def handle_updates(self):
        for request in self.delayed_requests:
            updates = self.controller.get_updates(request.lastupdate)
            if updates != []:
                self.send_updates(request, updates)
                self.delayed_requests.remove(request)

    def format_updates(self, request, update):
        response = json.dumps({'timestamp': int(Utils.getTime()), 'update':update})
        if hasattr(request, 'jsonpcallback'):
            return request.jsonpcallback +'('+response+')'
        else:
            return response

    def send_updates(self, request, updates):
        request.write(self.format_updates(request, updates))
        request.finish()

    def render(self, request):
        # set the request content type
        request.setHeader('Content-Type', 'application/json')

        # set args
        args = request.args

        # set jsonp callback handler name if it exists
        if 'callback' in args:
            request.jsonpcallback =  args['callback'][0]

        # set lastupdate if it exists
        if 'lastupdate' in args:
            request.lastupdate = float(args['lastupdate'][0])
            #print "request received " + str(request.lastupdate)
        else:
            request.lastupdate = 0
            print "request received " + str(request.lastupdate)

        # Can we accommodate this request now?
        updates = self.controller.get_updates(request.lastupdate)
        if updates != []:
            return self.format_updates(request, updates)

        request.notifyFinish().addErrback(lambda x: self.delayed_requests.remove(request))
        self.delayed_requests.append(request)

        # tell the client we're not done yet
        return server.NOT_DONE_YET

class Controller(object):
    def __init__(self, config, debugging=False):
        Utils.isDebugging = debugging 
        self.config = config

        # read config
        c = self.config['site']
	self.port = c['port']
	self.port_secure = c['port_secure']

        c = self.config['config']
        self.use_https = c['use_https']
        self.use_auth = c['use_auth']
        self.use_alerts = c['use_alerts']
        self.motion_pin = c['motion_pin']
        self.file_name = c['logfile']

        c = self.config['config']['times']
        self.time_to_close = c['to_close_door']
        self.time_to_open = c['to_open_door']
        self.time_to_report_open = c['to_report_open']
        self.time_to_report_still_open = c['to_report_still_open']
        self.time_to_force_close = c['to_force_close']

        c = self.config['alerts']
        self.when_opened = c['when_opened']
        self.when_closed = c['when_closed']
        self.from_time  = c['from_time']
        self.to_time = c['to_time']
        self.on_days_of_week = c['on_days_of_week']
        self.alert_type = c['alert_type']

        for arg in sys.argv:
            if str(arg) == 'debug':
                # ex. python controller.py debug -v
                Utils.isDebugging = True 

            if str(arg).startswith('port='):
                self.port = str(sys.argv[2]).split('=')[1]
                self.port_secure = self.port

        # set up fcache to log last time garage door was opened
        self.fileCache = FileCache(Utils.gfileCache, flag='cs')

        # set up logging
        log_fmt = '%(asctime)s %(levelname)-8s %(message)s'
        date_fmt = '%a, %m/%d/%y %H:%M:%S' 
        log_level = logging.INFO
        self.debugMsg = "Debugging=%s" % Utils.isDebugging

        if Utils.isDebugging:
            logging.basicConfig(datefmt=date_fmt, format=log_fmt, level=log_level)
        else:
	    logging.getLogger('mylogger').setLevel(logging.NOTSET)
            logging.basicConfig(datefmt=date_fmt, format=log_fmt, level=log_level, filename=self.file_name)
	    rotatingHandler = logging.handlers.RotatingFileHandler(self.file_name, maxBytes=500000, backupCount=5)
	    rotatingHandler.setLevel(log_level)
	    rotatingHandler.setFormatter(logging.Formatter(log_fmt))
	    logging.getLogger('mylogger').addHandler(rotatingHandler)

            gpio.setwarnings(False)
            gpio.cleanup()
            gpio.setmode(gpio.BCM)

        # Banner
        logging.info("<---Garage Controller starting (port=%s %s) --->" % (self.port_secure, self.debugMsg))

        self.updateHandler = UpdateHandler(self)

        self.initMsg = ""

        # setup motion sensor
        if self.motion_pin != None and Utils.isDebugging != True:
            gpio.setup(self.motion_pin, gpio.IN)
            gpio.add_event_detect(self.motion_pin, gpio.RISING, callback=self.motion, bouncetime=300)
            logging.info("Motion pin = %s" % (self.motion_pin))

        # setup Doors from config file
        self.doors = [Doors.Door(x, c) for (x, c) in config['doors'].items()]
        for door in self.doors:
	    door.setup_gpio(gpio)
            door.state = door.get_state_pin()
            if door.state == Utils.OPEN:
                curr_time = Utils.getTime()
                self.setOpenState(door, curr_time) 
                door.tis[Utils.OPENING] = curr_time
            door.send_open_im = True
            door.tslo = self.getTimeSinceLastOpenFromFile(door.id) 
            self.set_initial_text_msg(door) 

        # setup alerts
        if self.alert_type == 'smtp':
            self.use_smtp = False
            smtp_params = ("smtphost", "smtpport", "smtp_tls", "username", "password", "to_email")
            self.use_smtp = ('smtp' in config['alerts']) and set(smtp_params) <= set(config['alerts']['smtp'])
        elif self.alert_type == 'pushover':
            self.pushover_user_key = config['alerts']['pushover']['user_key']
        else:
            self.alert_type = None
            logging.info("No alerts configured")

        if Utils.isDebugging:
            print self.initMsg
        else:
            logging.info(self.initMsg)
            self.send_it(self.initMsg) 

    def setTimeSinceLastOpenFromFile(self, doorName):
        self.fileCache[doorName] = Utils.getTime()

    """get time since last open, if doesn't exist default to current time and return value"""
    def getTimeSinceLastOpenFromFile(self, doorName):
        return(self.fileCache.setdefault(doorName, Utils.getTime()))

    def getDoor(self, door_id):
        for door in self.doors:
            if (door.id == door_id):
                return door
        return None

    """motion detected, reset time_in_state to the current time for all open doors, after the "open" message IM has been send (send=False)"""
    def motion(self, pin):
        if pin != None:
            curr_time = Utils.getTime()
            for d in self.doors:
                if d.state == Utils.OPEN and (d.send_open_im == False or d.send_open_im_debug == False):
                    if Utils.isDebugging:
        		cur_dt = time.strftime("%m/%d/%y %H:%M:%S", time.localtime(curr_time))
                        logging.info("Motion detected, reset %s (%s)" % (d.name, cur_dt))
                    d.tis[d.state] = curr_time
                    d.tis[Utils.STILLOPEN] = curr_time
                    d.tis[Utils.FORCECLOSE] = curr_time
                    d.send_open_im = True

    def set_initial_text_msg(self, door):
        if len(self.initMsg) == 0:
            self.initMsg = 'Initial state of '
        else: 
            self.initMsg += ', '

        self.initMsg += "%s:%s" % (door.name, door.get_state_pin())

    def door_CLOSED(self, door):
        message = ''
        curr_time = Utils.getTime()

        last_open_msg = "%s" % (Utils.elapsed_time(int(curr_time - door.tslo)))

        #self.logger.info("%s %s->%s" % (door.name, door.state, CLOSED))
        self.setTimeSinceLastOpenFromFile(door.id)
        door.tslo = self.getTimeSinceLastOpenFromFile(door.id)
        door.state = Utils.CLOSED 

        ct = curr_time - door.tis.get(Utils.OPENING) 
        etime = Utils.elapsed_time(int(ct))
        door.tis[door.state] = curr_time 

        cur_dt = time.strftime("%H:%M:%S", time.localtime(time.time()))
        if door.send_open_im == False:
            message = '%s was %s at %s (%s) away for(%s)' % (door.name, door.state, cur_dt, etime, last_open_msg)
        else:
            message = '%s was opened and %s at %s (%s) away for(%s)' % (door.name, door.state, cur_dt, etime, last_open_msg) 
        return message

    def door_CLOSING(self, door):
        message = ''
        curr_time = Utils.getTime()        
        if Utils.getExpiredTime(door.tis.get(door.state), self.time_to_close, curr_time):
            return self.door_CLOSED(door) 
        return message

    def door_OPEN(self, door):
        message = '' 
        curr_time = Utils.getTime()
        etime = Utils.elapsed_time(int(curr_time - door.tis.get(door.state))) 
        cur_dt = time.strftime("%H:%M:%S", time.localtime(time.time()))

        if door.send_open_im == True and Utils.getExpiredTime(door.tis.get(door.state), self.time_to_report_open, curr_time):
            door.send_open_im = False
            message = '%s is %s at %s' % (door.name, door.state, cur_dt)

        if Utils.getExpiredTime(door.tis.get(Utils.STILLOPEN), self.time_to_report_still_open, curr_time):
            door.tis[Utils.STILLOPEN] = curr_time 
            message = '%s is still %s at %s' % (door.name, door.state, cur_dt)

        if self.time_to_force_close != None and Utils.getExpiredTime(door.tis.get(Utils.FORCECLOSE), self.time_to_force_close, curr_time):
            door.tis[Utils.FORCECLOSE] = curr_time
            message = '%s force closed %s->%s at %s (%s)' % (door.name, door.state, Utils.CLOSED, cur_dt, etime)
            door.toggle_relay()

        return message

    def setOpenState(self, door, curr_time):
        door.tis[door.state] = curr_time
        door.tis[Utils.STILLOPEN] = curr_time
        door.tis[Utils.FORCECLOSE] = curr_time
        door.send_open_im = True
        door.send_open_im_debug = True

    def door_OPENING(self, door):
        curr_time = Utils.getTime()
        message = ''
        if Utils.getExpiredTime(door.tis.get(door.state), self.time_to_open, curr_time):
            #self.logger.info("%s %s->%s" % (door.name, door.state, OPEN))
            door.state = Utils.OPEN
            self.setOpenState(door, curr_time) 
        return message

    def check_status(self):
        for door in self.doors:
            self.check_door_status(door)

    def check_door_status(self, door):
        self.logger = logging.getLogger(__name__)
        message = '' 
        curr_time = Utils.getTime()
        pin_state = door.get_state_pin()

        if pin_state != door.state:
            if door.state != Utils.OPENING and door.state != Utils.CLOSING: 
                door.state = Utils.OPENING if door.state == Utils.CLOSED else Utils.CLOSING
                door.tis[door.state] = curr_time
        	if Utils.isDebugging:
                    self.logger.info("%s %s(%s)" % (door.name, door.state, pin_state))

        if door.state == Utils.OPENING:
            message = self.door_OPENING(door)

        elif (door.state == Utils.CLOSING):
            message = self.door_CLOSING(door)

        elif door.state == Utils.OPEN:
            if door.send_open_im_debug == True and Utils.isDebugging: 
                self.logger.info("%s %s(%s)" % (door.name, door.state, pin_state))
        	door.send_open_im_debug = False
            message = self.door_OPEN(door)

        if message != "":
            self.logger.info(message)
            self.send_it(message)

        self.updateHandler.handle_updates()

    def can_send_alert(self):
        return self.use_alerts and Utils.is_day_of_week(self, Utils.getDateTime().weekday()) and Utils.is_time_between(self, Utils.getDateTime().time()) 

    def send_it(self, message):
        if self.can_send_alert():
	    doorname = "Garage"
            if self.alert_type == 'smtp': 
                self.send_text(message)
            elif self.alert_type == 'pushover':
                self.send_pushover(doorname, message)

    def send_text(self, msg):
        self.logger = logging.getLogger(__name__)
	if Utils.is_too_early():
            return

        #logging.info("SM - %s" % (msg))
        try:
            if self.use_smtp:
                config = self.config['alerts']['smtp']
                server = smtplib.SMTP(config["smtphost"], config["smtpport"])
                if (config["smtp_tls"] == True) :
                    server.starttls()
                    server.login(config["username"], config["password"])
                    mg = MIMEText(msg)
                    server.sendmail('from', config["to_email"], mg.as_string())
        except smtplib.SMTPException as e:
            self.logger.error("Error: unable to send gmail text %s", e)
        except:
            self.logger.error("Main Exception: %s", sys.exc_info()[0])
        finally:
            try:
                server.quit()
            except smtplib.SMTPServerDisconnected as sd:
                self.logger.error("sd Error: .quit() failed %s", sd)
                server.close()
            except smtplib.SMTPException as se1:
                self.logger.error("se1 Exception Error: .quit() failed %s", se1)
            except smtplib.SMTPResponseException as se2:
                self.logger.error("se2 smtp Exception Error: .quit() failed %s", se2)
            except:
                self.logger.error("final Exception: %s", sys.exc_info()[0])

    def send_pushover(self, title, message):
        self.logger = logging.getLogger(__name__)

	if Utils.is_too_early():
            return

        try:
            config = self.config['alerts']['pushover']
            conn = httplib.HTTPSConnection("api.pushover.net:443")
            conn.request("POST", "/1/messages.json",
                urllib.urlencode({
                    "token": config['api_key'],
                    "user": config['user_key'],
                    "title": title,
                    "message": message,
                }), { "Content-type": "application/x-www-form-urlencoded" })
            conn.getresponse()
        except:
            self.logger.error("send_pushover Exception: %s", sys.exc_info()[0])

    def close_all(self):
        self.logger = logging.getLogger(__name__)
        message = '' 
        for door in self.doors:
            if door.get_state_pin() != Utils.CLOSED:
                if door.state == Utils.CLOSING or door.state == Utils.OPENING:
                    message += door.name + " Closing or Opening, " 
                elif door.state == Utils.OPEN:
                    if message == None:
                        message = 'Close All: '
                    message += door.name +'('+ door.state +')'
                    door.toggle_relay()
                    time.sleep(0.2) 

        if message != '':
            self.logger.info(message)
            return True
        else:
            return False

    def get_updates(self, lastupdate):
        updates = []
        for d in self.doors:
            timeinstate = d.tis.get(d.state)
            if timeinstate  >= lastupdate:
                updates.append((d.id, d.state, timeinstate))
        return updates

    def get_config_with_default(self, config, param, default):
        if not config:
            return default
        if not param in config:
            return default
        return config[param]

    def run(self):
        root = File('www')
        root.putChild('upd', self.updateHandler)
        root.putChild('cfg', ConfigHandler(self)) # this prints the doors on the webpage
        root.putChild('upt', UptimeHandler(self))
        root.putChild('log', LogHandler(self))
        root.putChild('closeall', CloseAllHandler(self))
        root.putChild('clk', ClickHandler(self))
        root.putChild('mot', ClickMotionTestHandler(self))
        task.LoopingCall(self.check_status).start(1.0)

        site = server.Site(root)

        if not self.get_config_with_default(self.config['config'], 'use_https', False):
            reactor.listenTCP(self.port, site)  # @UndefinedVariable
        else:
            sslContext = ssl.DefaultOpenSSLContextFactory(self.config['site']['ssl_key'], self.config['site']['ssl_cert'])
            reactor.listenSSL(self.port_secure, site, sslContext)  # @UndefinedVariable

        reactor.run()  # @UndefinedVariable
if __name__ == '__main__':
    config_file = open('config.json')
    controller = Controller(json.load(config_file))
    config_file.close()
    controller.run()
