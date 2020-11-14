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
import db_utils as db_Utils
import door as Doors
import requests

from datetime import timedelta
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

class GetTempHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        temp = Utils.get_temperature(Utils.temperature_pin)
        json_object = json.loads(temp)
        json_formatted_str = json.dumps(json_object, indent=2)
        return "<html><body>Garage<pre>%s</pre></body></html>" % (json_formatted_str)

class TempsHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        events = ["garage_temperature", "shed_temperature"]
        data = db_Utils.query_temperatures(events, 75)
        return "<html><body><pre>%s</pre></body></html>" % (str(data))

class LogHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def tail(self, filepath):
        data_value = ""

        try:
            with open(filepath, "rb") as f:
                loglines = f.readlines()[-60:]
        except:
            return "No log file found (%s)" % (filepath)

        # reverse order, most recent at the top
        for logline in reversed(loglines):
            data_value += logline

        return data_value

    def render(self, request):
        logs = self.tail(self.controller.file_name).replace("<", "&lt")
        return "<html><body><pre>%s</pre></body></html>" % (logs)

class ClickHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        d = request.args['id'][0]
        door = self.controller.get_door(d)
        if door != None and door.state != Utils.CLOSING and door.state != Utils.OPENING:
            door.toggle_relay()

class ClickWeatherHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        Utils.query_weather_API(requests, controller)
        weather_info = db_Utils.query_day_temperature_data() 
        json_object = json.loads(weather_info)
        json_formatted_str = json.dumps(json_object, indent=2)
        return json_formatted_str

class ClickGraphShedHandler(Resource):
    isLeaf = True
    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        events = ["shed_temperature"]
        data = db_Utils.query_temperature_data(events, controller) 
        request.setHeader('Content-Type', 'application/json')
        return json.dumps(data)

class ClickGraphHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        events = ["garage_temperature"]
        data = db_Utils.query_temperature_data(events, controller) 
        request.setHeader('Content-Type', 'application/json')
        return json.dumps(data)

class ClickMotionTestHandler(Resource):
    isLeaf = True

    def __init__ (self, controller):
        Resource.__init__(self)
        self.controller = controller

    def render(self, request):
        #self.controller.motion('testpin')
        data = db_Utils.query_garage_open_close()
        d = data.replace("<", "&lt")
        return "<html><body><pre>%s</pre></body></html>" % (d)

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
            with open( "/proc/uptime" ) as f:
                contents = f.read().split()
        except:
            return "Cannot open uptime file: /proc/uptime"

        return Utils.get_elapsed_time(float(contents[0]))

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
        response = json.dumps({'timestamp': int(Utils.get_time()), 'update':update})
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
	    #print "args "+args

        # set lastupdate if it exists
        if 'lastupdate' in args:
            request.lastupdate = float(args['lastupdate'][0])
            #print "request received " + str(request.lastupdate) + "args " + str(args)
        else:
            request.lastupdate = 0
            #print "request received " + str(request.lastupdate)

        # Can we accommodate this request now?
        updates = self.controller.get_updates(request.lastupdate)
        if updates != []:
	    #print "updates "+str(updates)
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
        Utils.temperature_pin = c['temperature_pin']

        c = self.config['config']['times']
        self.time_to_close = c['to_close_door']
        self.time_to_open = c['to_open_door']
        self.time_to_report_open = c['to_report_open']
        self.time_to_report_still_open = c['to_report_still_open']
        self.time_to_force_close = c['to_force_close']

        c = self.config['alerts']
        self.when_opened = c['when_opened']
        self.when_closed = c['when_closed']
        self.on_days_of_week = c['on_days_of_week']
        self.from_time  = c['from_time']
        self.to_time = c['to_time']
        self.alert_type = c['alert_type']

        c = self.config['mqtt']
        self.mqtt_server = c['server']
        self.mqtt_username = c['username']
        self.mqtt_password = c['password']

        c = self.config['mqtt']['topics']
        self.mqtt_topic_garage = c['garage']
        self.mqtt_topic_temperature= c['temperature']
        self.mqtt_topic_day_temperature= c['day_temperature']

        c = self.config['weatherapi']
        self.weather_url = c['url']
        self.weather_key = c['key']

        for arg in sys.argv:
            if str(arg) == 'debug':
                # ex. python controller.py debug -v
                Utils.isDebugging = True 
                self.time_to_report_open = 35 
                self.time_to_report_still_open = 100
                Utils.gfileCache += "debug"

            if str(arg).startswith('port='):
                self.port = str(sys.argv[2]).split('=')[1]
                self.port_secure = self.port

        # set up fcache to log last time garage door was opened
        self.fileCache = FileCache(Utils.gfileCache, flag='cs')

        # set up logging
        log_fmt = '%(asctime)s %(levelname)-8s %(message)s'
        date_fmt = '%a, %m/%d/%y %H:%M:%S' 
        log_level = logging.INFO

        if Utils.isDebugging:
            logging.basicConfig(datefmt=date_fmt, format=log_fmt, level=log_level)
            self.debugMsg = "Debugging=%s time_to_report_open=%d time_to_report_still_open %d gfileCache=%s" % (Utils.isDebugging, self.time_to_report_open, self.time_to_report_still_open, Utils.gfileCache)
        else:
            self.debugMsg = "Debugging=%s" % Utils.isDebugging
            logging.getLogger('mylogger').setLevel(logging.NOTSET)
            logging.basicConfig(datefmt=date_fmt, format=log_fmt, level=log_level, filename=self.file_name)
            rotatingHandler = logging.handlers.RotatingFileHandler(self.file_name, maxBytes=5000000, backupCount=3)
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
        self.doors = [Doors.Door(x, c) for (x, c) in sorted(config['doors'].items())]
        for door in self.doors:
            door.setup(gpio, self.get_time_since_last_open(door.id)) 
            self.set_initial_text_msg(door) 

        # setup alerts
        if self.alert_type == 'smtp':
            self.use_smtp = False
            smtp_params = ("smtphost", "smtpport", "smtp_tls", "username", "password", "to_email")
            self.use_smtp = ('smtp' in config['alerts']) and set(smtp_params) <= set(config['alerts']['smtp'])
        elif self.alert_type == 'pushover':
            self.pushover_user_key = config['alerts']['pushover']['user_key']
            self.pushover_api_key = config['alerts']['pushover']['api_key']
        else:
            self.alert_type = None
            logging.info("No alerts configured")

        if Utils.isDebugging:
            print self.initMsg 
        else:
            logging.info(self.initMsg)
            self.send_msg(self.initMsg) 

    def set_time_since_last_open(self, doorName):
        self.fileCache[doorName] = Utils.get_time()

    """get time since last open, if doesn't exist default to current time and return value"""
    def get_time_since_last_open(self, doorName):
        return(self.fileCache.setdefault(doorName, Utils.get_time()))

    def get_door(self, door_id):
        for door in self.doors:
            if (door.id == door_id):
                return door
        return None

    """motion detected, reset time_in_state to the current time for all open doors, after the "open" message IM has been send (send=False)"""
    def motion(self, pin):
        if pin != None:
            curr_time = Utils.get_time()
            for d in self.doors:
                if d.state == Utils.OPEN and (d.send_open_im == False or d.send_open_im_debug == False):
                    if Utils.isDebugging:
                        cur_dt = Utils.epoch_to_datetime(curr_time).strftime(Utils.TIMEFORMAT)
                        logging.info("Motion detected, reset %s (%s)" % (d.name, cur_dt))
                    d.set_open_state(curr_time)

    def set_initial_text_msg(self, door):
        if len(self.initMsg) == 0:
            self.initMsg = 'Initial state of '
        else: 
            self.initMsg += ', '

        self.initMsg += "%s:%s" % (door.name, door.get_state_pin())

    def door_CLOSED(self, door):
        message = ''
        curr_time = Utils.get_time()

        last_open_msg = "%s" % (Utils.get_elapsed_time(int(curr_time - door.tslo)))
        self.set_time_since_last_open(door.id)
        door.tslo = self.get_time_since_last_open(door.id)
        door.state = Utils.CLOSED 

        ct = curr_time - door.tis.get(Utils.OPENING) 
        etime = Utils.get_elapsed_time(int(ct))
        door.tis[door.state] = curr_time 

        cur_dt = Utils.epoch_to_datetime(curr_time).strftime(Utils.TIMEFORMAT)
        self.publish_garage_event(door, Utils.CLOSED)

        if door.send_open_im == False:
            message = '%s was %s at %s (%s) away for(%s)' % (door.name, door.state, cur_dt, etime, last_open_msg)
        else:
            message = '%s was opened & %s at %s (%s) away for(%s)' % (door.name, door.state, cur_dt, etime, last_open_msg) 
        return message

    def door_CLOSING(self, door):
        message = ''
        curr_time = Utils.get_time()        
        if Utils.is_time_expired(door.tis.get(door.state), self.time_to_close, curr_time):
            return self.door_CLOSED(door) 
        return message

    def door_OPEN(self, door):
        message = '' 
        curr_time = Utils.get_time()
        #etime = Utils.elapsed_time(int(curr_time - door.tis.get(door.state))) 
        cur_dt = Utils.epoch_to_datetime(curr_time).strftime(Utils.TIMEFORMAT)

        if door.send_open_im == True and Utils.is_time_expired(door.tis.get(door.state), self.time_to_report_open, curr_time):
            door.send_open_im = False
            message = '%s is %s at %s' % (door.name, door.state, cur_dt)

        if Utils.is_time_expired(door.tis.get(Utils.STILLOPEN), self.time_to_report_still_open, curr_time):
            door.tis[Utils.STILLOPEN] = Utils.round_up_minutes(curr_time)
            message = '%s is still %s at %s' % (door.name, door.state, cur_dt)

        #if self.time_to_force_close != None and Utils.isTimeExpired(door.tis.get(Utils.FORCECLOSE), self.time_to_force_close, curr_time):
        #    door.tis[Utils.FORCECLOSE] = curr_time
        #    message = '%s force closed %s->%s at %s (%s)' % (door.name, door.state, Utils.CLOSED, cur_dt, etime)
        #    door.toggle_relay()

        return message

    def door_OPENING(self, door):
        curr_time = Utils.get_time()
        message = ''

        self.publish_garage_event(door, Utils.OPENING)
        if Utils.is_time_expired(door.tis.get(door.state), self.time_to_open, curr_time):
            #self.logger.info("%s %s->%s" % (door.name, door.state, OPEN))
            door.state = Utils.OPEN
            door.set_open_state(curr_time) 
        return message

    def check_status(self):
        try:
            for door in self.doors:
                self.check_door_status(door)
        except Exception as e:
            self.logger.info("Error check_status %s" % e)

    def check_door_status(self, door):
        self.logger = logging.getLogger(__name__)
        message = '' 
        curr_time = Utils.get_time()
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
            self.send_msg(message)

        self.updateHandler.handle_updates()


    def publish_garage_event(self, door, msg):
        pubMsg = ""

        if msg == Utils.OPENING and door.send_open_mqtt == True:
            door.send_open_mqtt = False
            door.send_close_mqtt = True
            pubMsg += door.name+"|"+msg
        elif msg == Utils.CLOSED and door.send_close_mqtt == True:
            door.send_close_mqtt = False
            door.send_open_mqtt = True 
            pubMsg += door.name+"|"+msg

        if pubMsg != "":
            Utils.publish_MQTT(self.mqtt_server, self.mqtt_topic_garage, pubMsg, self.mqtt_username,self.mqtt_password)

    def can_send_alert(self):
        dt = Utils.get_date_time()
        if self.use_alerts:
            return Utils.is_day_of_week(self, dt.weekday()) and Utils.is_time_between(self, dt.time()) 
        return False

    def send_msg(self, message):
        if Utils.isDebugging:
            logging.info("PO - %s" % (message))
            return

        if self.can_send_alert():
            if self.alert_type == 'smtp': 
                self.send_text(message)
            elif self.alert_type == 'pushover':
                self.send_pushover(message)

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
            except:
                self.logger.error("final Exception: %s", sys.exc_info()[0])

    def send_pushover(self, message):
        self.logger = logging.getLogger(__name__)

        if Utils.is_too_early():
            return
        try:
            conn = httplib.HTTPSConnection("api.pushover.net:443")
            conn.request("POST", "/1/messages.json",
                urllib.urlencode({
                    "token": self.pushover_api_key,
                    "user": self.pushover_user_key,
                    "title": 'Garage',
                    "sound": 'pushover',
                    "message": message,
                }), { "Content-type": "application/x-www-form-urlencoded" })
            conn.getresponse()
        except socket.gaierror as e:
            self.logger.error("send_pushover Exception2: %s", e)
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

    def get_temp(self):
        msg = Utils.get_temperature(Utils.temperature_pin)
        if "error reading" in msg:
            logging.info("Error getting temperature")
        if msg != "": 
            Utils.publish_MQTT(self.mqtt_server, self.mqtt_topic_temperature, msg, self.mqtt_username, self.mqtt_password)
        return msg

    def get_weather(self):
        logging.info("calling weatherAPI")
        Utils.query_weather_API(requests, controller)

    def run(self):
        root = File('www')
        root.putChild('upd', self.updateHandler)
        root.putChild('cfg', ConfigHandler(self)) # this prints the doors on the webpage
        root.putChild('upt', UptimeHandler(self))
        root.putChild('log', LogHandler(self))
        root.putChild('temps', TempsHandler(self))
        root.putChild('gettemp', GetTempHandler(self))
        root.putChild('closeall', CloseAllHandler(self))
        root.putChild('clk', ClickHandler(self))
        root.putChild('mot', ClickMotionTestHandler(self))
        root.putChild('graph', ClickGraphHandler(self))
        root.putChild('graphshed', ClickGraphShedHandler(self))
        root.putChild('weather', ClickWeatherHandler(self))
        task.LoopingCall(self.check_status).start(1.0)
        task.LoopingCall(self.get_temp).start(1.0*60*60) # every hour
        task.LoopingCall(self.get_weather).start(1.0*60*60*12) # every 12 hours

        site = server.Site(root)

        if not self.get_config_with_default(self.config['config'], 'use_https', False):
            reactor.listenTCP(self.port, site)  # @UndefinedVariable
        else:
            sslContext = ssl.DefaultOpenSSLContextFactory(self.config['site']['ssl_key'], self.config['site']['ssl_cert'])
            reactor.listenSSL(self.port_secure, site, sslContext)  # @UndefinedVariable

        reactor.run()  # @UndefinedVariable

if __name__ == '__main__':
    config_file = open('/home/pi/gdc/config.json')
    controller = Controller(json.load(config_file))
    config_file.close()
    controller.run()
