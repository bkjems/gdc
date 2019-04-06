#!/usr/bin/env python
"""Software to monitor and control garage doors via a raspberry pi."""

import time, syslog, uuid
import smtplib
import RPi.GPIO as gpio
import json
import httplib
import urllib
import subprocess
import logging
import datetime
import sys

from twisted.internet import task
from twisted.internet import reactor
from twisted.web import server
from twisted.web.static import File
from twisted.web.resource import Resource, IResource
from zope.interface import implements
from email.mime.text import MIMEText
from enum import Enum
from datetime import date
from datetime import timedelta
from twisted.cred import checkers, portal
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory

from fcache.cache import FileCache

# global
gfileCache = 'garageCache'
isDebugging = False

global CLOSED
CLOSED = 'closed'

global OPEN
OPEN = 'open'

global OPENING 
OPENING = 'opening'

global CLOSING
CLOSING = 'closing'

global STILLOPEN
STILLOPEN = 'stillopen'

global FORCECLOSE
FORCECLOSE = 'forceclose'

def getTime():
    return time.time() 

def getDateTime():
    return datetime.datetime.now() 

def elapsed_time(total_seconds):
    """Formats total seconds into a human readable format."""
    # Helper vars:
    MINUTE  = 60
    HOUR    = MINUTE * 60
    DAY     = HOUR * 24
    YEAR    = DAY * 7 * 52

    year    = int(total_seconds / YEAR)
    days    = int(total_seconds / DAY)
    hours   = int((total_seconds % DAY) / HOUR)
    minutes = int((total_seconds % HOUR) / MINUTE)
    seconds = int(total_seconds % MINUTE)

    ret = ''
    if year > 0:
        ret += str(year) + " " + (year == 1 and "yr" or "yrs" ) + ", "

    if days > 0:
        ret += str(days) + " " + (days == 1 and "day" or "days" ) + ", "

    if total_seconds < 3600:
        if total_seconds <= 60:
            ret += "%ds" % (total_seconds)
        else: 
            ret += "%dm" % (minutes)
            if seconds > 0:
                ret += " %ds" % (seconds)
    elif total_seconds < 86400:
        ret += "%d%s" % (hours, (hours == 1 and "hr" or  "hrs"))
        if minutes > 0 or seconds > 0:
            ret += " %02d:%02d" % (minutes, seconds)
    else: 
        ret += "%02d:%02d" % (hours, minutes)

    return ret

class WEEKDAYS(Enum): 
    """Enum for days of the week."""
    Mon= 0 
    Tue = 1 
    Wed = 2 
    Thu = 3 
    Fri = 4 
    Sat = 5 
    Sun = 6

class CloseAllHandler(Resource):
    """Closes all door."""

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

    def tail(self, filepath, lines=60):
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
        if door != None and door.state != CLOSING and door.state != OPENING:
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

        return elapsed_time(float(contents[0]))

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
        response = json.dumps({'timestamp': int(getTime()), 'update':update})
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

class Door(object):
    pb_iden = None

    def __init__(self, doorId, config):
        self.id = doorId
        self.name = config['id']
        self.relay_pin = config['relay_pin']
        self.state_pin = config['state_pin']
        self.test_state_pin = CLOSED 
        self.state_pin_closed_value = config['closed_value']
        self.tis = {
            CLOSED:0,
            OPEN:0,
            OPENING:0,
            CLOSING:0,
            STILLOPEN:0,
            FORCECLOSE:0 
        }
        self.setup_gpio() 

    def setup_gpio(self):
        if isDebugging:
            return

        gpio.setup(self.relay_pin, gpio.OUT)
        gpio.setup(self.state_pin, gpio.IN, pull_up_down=gpio.PUD_UP)
        gpio.output(self.relay_pin, True)

    def get_state_pin(self):
        """returns OPEN or CLOSED for a given garages door state pin"""
        self.logger = logging.getLogger(__name__)

        if isDebugging:
            return self.test_state_pin
        else:
            rv = gpio.input(self.state_pin)
            if rv == self.state_pin_closed_value:
                return CLOSED 

        return OPEN

    def toggle_relay(self):
    	"""This gets hit from the web page to open or close garage door"""

        if isDebugging:
            self.test_state_pin = CLOSED if self.test_state_pin == OPEN else OPEN 
            return

        gpio.output(self.relay_pin, False)
        time.sleep(0.2)
        gpio.output(self.relay_pin, True)


class Controller(object):
    def __init__(self, config, debugging=False):
        global isDebugging
        isDebugging = debugging 
        self.config = config

        # read args
        self.port = config['site']['port'] 
        for arg in sys.argv:
            if str(arg) == 'debug':
                # ex. python controller.py debug -v
                isDebugging = True 

            elif str(arg).startswith('port='):
                self.port = str(sys.argv[2]).split('=')[1]

        # read config
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

        # set up fcache to log last time garage door was opened
        self.fileCache = FileCache(gfileCache, flag='cs')

        # set up logging
        log_fmt = '%(asctime)s %(levelname)-8s %(message)s'
        date_fmt = '%a, %m/%d/%y %H:%M:%S' 
        log_level = logging.INFO
        self.debugMsg = "Debugging=%s" % isDebugging
        if isDebugging:
            logging.basicConfig(datefmt=date_fmt, format=log_fmt, level=log_level)
            logger = logging.getLogger(__name__)
        else:
            logging.basicConfig(datefmt=date_fmt, format=log_fmt, level=log_level, filename=self.file_name)
            gpio.setwarnings(False)
            gpio.cleanup()
            gpio.setmode(gpio.BCM)

        # Banner
        logging.info("<---Garage Controller starting (port=%s %s) --->" % (self.port, self.debugMsg))

        self.updateHandler = UpdateHandler(self)

        self.initMsg = ""

        # setup motion sensor
        if self.motion_pin != None and isDebugging != True:
            gpio.setup(self.motion_pin, gpio.IN)
            gpio.add_event_detect(self.motion_pin, gpio.RISING, callback=self.motion, bouncetime=300)
            logging.info("Motion pin = %s" % (self.motion_pin))

        # setup Doors from config file
        self.doors = [Door(x, c) for (x, c) in config['doors'].items()]
        for door in self.doors:
            door.state = door.get_state_pin()
            if door.state == OPEN:
                curr_time = getTime()
                self.setOpenState(door, curr_time) 
                door.tis[OPENING] = curr_time
            door.send_open_im = True
            door.tslo = self.getTimeSinceLastOpenFromFile(door.id) 
            self.set_initial_text_msg(door) 

        # setup alerts
        if self.alert_type == 'smtp':
            self.use_smtp = False
            smtp_params = ("smtphost", "smtpport", "smtp_tls", "username", "password", "to_email")
            self.use_smtp = ('smtp' in config['alerts']) and set(smtp_params) <= set(config['alerts']['smtp'])
        elif self.alert_type == 'pushbullet':
            self.pushbullet_access_token = config['alerts']['pushbullet']['access_token']
        elif self.alert_type == 'pushover':
            self.pushover_user_key = config['alerts']['pushover']['user_key']
        else:
            self.alert_type = None
            logging.info("No alerts configured")

        if isDebugging:
            print self.initMsg
        else:
            logging.info(self.initMsg)
            self.send_it(self.initMsg) 

    def setTimeSinceLastOpenFromFile(self, doorName):
        self.fileCache[doorName] = getTime()

    def getTimeSinceLastOpenFromFile(self, doorName):
    	"""get time since last open, if doesn't exist default to current time and return value"""

        return(self.fileCache.setdefault(doorName, getTime()))

    def getDoor(self, door_id):
        for door in self.doors:
            if (door.id == door_id):
                return door
        return None

    def motion(self, pin):
	"""motion detected, reset time_in_state to the current time for all open doors, after the "open" message IM has been send (send=False)"""

        if pin != None:
            curr_time = getTime()
            for d in self.doors:
                if d.state == OPEN and d.send_open_im == False:
                    if isDebugging:
                        logging.info("Motion detected, reset %s time" % (d.name))
                    d.tis[d.state] = curr_time
                    d.tis[STILLOPEN] = curr_time
                    d.tis[FORCECLOSE] = curr_time
                    d.send_open_im = True

    def set_initial_text_msg(self, door):
        if len(self.initMsg) == 0:
            self.initMsg = 'Initial state of '
        else: 
            self.initMsg += ', '

        self.initMsg += "%s:%s" % (door.name, door.get_state_pin())

    def getExpiredTime(self, tis, alert_time, curr_time):
        if alert_time <= 0:
            return True

        # add alert_time secs to current time
        dt_time_in_state  = datetime.datetime.fromtimestamp(tis) # convert time to datetime
        newDateTime = dt_time_in_state  + timedelta(seconds=alert_time) 
        return curr_time > time.mktime(newDateTime.timetuple()) # convert to epoch time

    def door_CLOSED(self, door, etime):
        message = ''
        curr_time = getTime()

        last_open_msg = "%s" % (elapsed_time(int(curr_time - door.tslo)))

        #self.logger.info("%s %s->%s" % (door.name, door.state, CLOSED))
        self.setTimeSinceLastOpenFromFile(door.id)
        door.tslo = self.getTimeSinceLastOpenFromFile(door.id)
        door.state = CLOSED 

        ct = curr_time - door.tis.get(OPENING) 
        etime = elapsed_time(int(ct))
        door.tis[door.state] = curr_time 

        if door.send_open_im == False:
            message = '%s is %s %s previous (%s)' % (door.name, door.state, etime, last_open_msg)
        else:
            message = '%s was opened and %s after %s previous (%s)' % (door.name, door.state, etime, last_open_msg) 
        return message

    def door_CLOSING(self, door):
        message = ''
        curr_time = getTime()        
        etime = elapsed_time(int(curr_time - door.tis.get(door.state)))
        if self.getExpiredTime(door.tis.get(door.state), self.time_to_close, curr_time):
            return self.door_CLOSED(door, etime) 
        return message

    def door_OPEN(self, door):
        message = '' 
        curr_time = getTime()
        etime = elapsed_time(int(curr_time - door.tis.get(door.state))) 

        if door.send_open_im == True and self.getExpiredTime(door.tis.get(door.state), self.time_to_report_open, curr_time):
            door.send_open_im = False
            message = '%s is %s' % (door.name, door.state)

        if self.getExpiredTime(door.tis.get(STILLOPEN), self.time_to_report_still_open, curr_time):
            door.tis[STILLOPEN] = curr_time 
            message = '%s is still %s' % (door.name, door.state)

        if self.time_to_force_close != None and self.getExpiredTime(door.tis.get(FORCECLOSE), self.time_to_force_close, curr_time):
            door.tis[FORCECLOSE] = curr_time
            message = '%s force closed %s->%s %s' % (door.name, door.state, CLOSED, etime)
            door.toggle_relay()

        return message

    def setOpenState(self, door, curr_time):
        door.tis[door.state] = curr_time
        door.tis[STILLOPEN] = curr_time
        door.tis[FORCECLOSE] = curr_time
        door.send_open_im = True

    def door_OPENING(self, door):
        curr_time = getTime()
        message = ''
        if self.getExpiredTime(door.tis.get(door.state), self.time_to_open, curr_time):
            #self.logger.info("%s %s->%s" % (door.name, door.state, OPEN))
            door.state = OPEN
            self.setOpenState(door, curr_time) 
        return message

    def check_status(self):
        for door in self.doors:
            self.check_door_status(door)

    def check_door_status(self, door):
        self.logger = logging.getLogger(__name__)
        message = '' 
        curr_time = getTime()
        pin_state = door.get_state_pin()

        if pin_state != door.state:
            if door.state != OPENING and door.state != CLOSING: 
                door.state = OPENING if door.state == CLOSED else CLOSING
                door.tis[door.state] = curr_time
                if pin_state == CLOSED:
                    pin_state = OPEN
                #self.logger.info("%s %s->%s" % (door.name, pin_state, door.state))

        if door.state == OPENING:
            message = self.door_OPENING(door)

        elif (door.state == CLOSING):
            message = self.door_CLOSING(door)

        elif door.state == OPEN:
            message = self.door_OPEN(door)

        if message != "":
            self.logger.info(message)
            self.send_it(message)

        self.updateHandler.handle_updates()

    def is_day_of_week(self, day_of_week_num):
    	"""Return the day of the week as an integer, where Monday is 0 and Sunday is 6."""

        if self.on_days_of_week == '':
            return True

        day_of_week_name = WEEKDAYS(day_of_week_num).name
        return(day_of_week_name in self.on_days_of_week.split(","))

    def is_time_between(self, curr_datetime_time):
        if self.from_time == '' and self.to_time == '' and self.on_days_of_week == '':
            return True 

        from_hr = int(self.from_time[:2])
        from_min = int(self.from_time[-2:])
        to_hr = int(self.to_time[:2])
        to_min = int(self.to_time[-2:])

        return datetime.time(from_hr, from_min) <= curr_datetime_time <= datetime.time(to_hr, to_min) 

    def can_send_alert(self):
        return self.use_alerts and self.is_day_of_week(getDateTime().weekday()) and self.is_time_between(getDateTime().time()) 

    def send_it(self, message):
        if self.can_send_alert():
            if self.alert_type == 'smtp': 
                self.send_text(message)
            elif self.alert_type == 'pushbullet':
                self.send_pushbullet('Garage', message)
            elif self.alert_type == 'pushover':
                self.send_pushover('Garage', message)

    def send_text(self, msg):
        self.logger = logging.getLogger(__name__)

        msg += time.strftime(" %b %d %H:%M", time.localtime(time.time()))
        if isDebugging:
            return

        # When restarting each morning at 4am, don't send init msg if between 3:58 - 4:05am
        raw_now = datetime.datetime.now().time()
        if datetime.time(3, 58) <= raw_now <= datetime.time(4, 5):
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
        except socket.gaierror as ge:
            self.logger.error("gaierror:%s", ge)
            return
        except socket.error as se:
            self.logger.error("socket error:%s", se)
            return
        except:
            self.logger.error("Main Exception: %s", sys.exc_info()[0])
        finally:
            try:
                server.quit()
            except smtplib.SMTPServerDisconnected as sd:
                self.logger.error("Error: .quit() failed %s", sd)
                server.close()
            except:
                self.logger.error("Exception: %s", sys.exc_info()[0])

    def send_pushbullet(self, title, message):
        config = self.config['alerts']['pushbullet']
        conn = httplib.HTTPSConnection("api.pushbullet.com:443")
        conn.request("POST", "/v2/pushes",
                     json.dumps({
                         "type": "note",
                 "title": title,
                 "body": message,
                 }), {'Authorization': 'Bearer ' + config['access_token'], 'Content-Type': 'application/json'})
        response = conn.getresponse().read()
        logging.info(response)
        #door.pb_iden = json.loads(response)['iden']

    def send_pushover(self, title, message):
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

    def close_all(self):
        self.logger = logging.getLogger(__name__)
        message = '' 
        for door in self.doors:
            print door.get_state_pin()
            if door.get_state_pin() != CLOSED:
                if door.state == CLOSING or door.state == OPENING:
                    message += door.name + " Closing or Opening, " 
                elif door.state == OPEN:
                    if message == None:
                        message = 'Close All: '
                    message += door.name
                    message += ', '
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
        reactor.listenTCP(int(self.port), site)  # @UndefinedVariable
        reactor.run()

if __name__ == '__main__':
    config_file = open('config.json')
    controller = Controller(json.load(config_file))
    config_file.close()
    controller.run()
