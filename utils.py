#!/usr/bin/env python
"""Utility methods to monitor and control garage doors via a raspberry pi."""
import time
import datetime
import utils as Utils 
import paho.mqtt.publish as publish
import Adafruit_DHT as dht
import sqlite3
from enum import Enum
from datetime import timedelta
from time import gmtime


"""global"""
gfileCache = 'garageCache'
isDebugging = False
temperature_pin = ""

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

global DATEFORMAT
DATEFORMAT = '%m-%d-%Y %H:%M:%S'

global TIMEFORMAT
TIMEFORMAT = '%H:%M:%S'

global YEAR 
YEAR = 'yr'

global WEEK
WEEK= 'wk'

global DAY 
DAY = 'day'

global HOUR
HOUR = 'hr'

global MIN
MIN = 'm'

global SEC
SEC = 's'

TIME_DURATION_UNITS = (
    (YEAR, 60*60*24*365),
    (WEEK, 60*60*24*7),
    (DAY,  60*60*24),
    (HOUR, 60*60),
    (MIN,  60),
    (SEC,  1) 
)

class WEEKDAYS(Enum):
    # Enum for days of the week.
    Mon = 0
    Tue = 1
    Wed = 2
    Thu = 3
    Fri = 4
    Sat = 5
    Sun = 6

def getTime():
    return time.time()

def getDateTime():
    return datetime.datetime.now()

def elapsed_time(total_seconds):
    if total_seconds == 0:
        return 'inf'
    save_total_seconds = total_seconds
    parts = []
    _min = 0
    sec  = 0 
    for unit, div in TIME_DURATION_UNITS:
        amount, total_seconds = divmod(int(total_seconds), div)
        if amount > 0:
	    if unit == MIN:
	        _min= amount
	    elif unit == SEC:
	        sec = amount
	    else:
	        parts.append('{} {}{}'.format(amount, unit, "" if amount == 1 else "s")) 
    if _min  > 0 or sec > 0:
	if save_total_seconds <= 60 or (_min <= 0 and sec > 0):
            parts.append('{}s'.format("60" if sec == 0 else str(sec).zfill(2)))
	else:
            parts.append('{}:{}'.format("00" if _min == 0 else str(_min).zfill(2), "00" if sec == 0 else str(sec).zfill(2)))

    return ', '.join(parts)

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

def is_too_early():
    return is_too_early_withTime(Utils.getDateTime().time())

def is_too_early_withTime(time_now):
    # When restarting each morning at 4am, don't send init msg if between 3:58 - 4:05am
    if time_now == None:
        return False

    return(datetime.time(3, 58) <= time_now <= datetime.time(4, 5))

def isTimeExpired(tis, alert_time, curr_time):
    if alert_time <= 0:
        return True

    # add alert_time secs to current time
    dt_time_in_state  = epochToDatetime(tis) 
    newDateTime = dt_time_in_state  + timedelta(seconds=alert_time) 
    return curr_time > datetimeToEpoch(newDateTime)

def datetimeToEpoch(dt):
    if dt == None:
        return None

    return time.mktime(dt.timetuple()) # convert to epoch time

def epochToDatetime(epoch):
    if epoch == None:
        return None

    return datetime.datetime.fromtimestamp(epoch) # convert time_seconds to datetime

def modby(mins):
    by = 5
    hr = 0
    r = (mins % by)

    if r != 0:
        mins += (by - r)

    if mins % 60 == 0:
	mins = 0
        hr = 1

    return mins, hr

def roundUp_string(td_string):
    dt = None
    if td_string != "":
        dt = datetime.datetime.strptime(td_string, Utils.DATEFORMAT) 

    return roundUpDateTime(dt)

def roundUpMins(dt_seconds):
    if dt_seconds == None: 
        return None

    dt = epochToDatetime(dt_seconds) 
    return datetimeToEpoch(roundUpDateTime(dt))

def roundUpDateTime(dt):
    if dt == None: 
        return None

    nm, hr = modby(dt.minute)
    ft = timedelta(hours=+hr, minutes=+(nm-dt.minute-1), seconds=+(60-dt.second))

    return dt + ft

def publishMQTT(server, topic, msg, username, password):
    publish.single(topic, msg, hostname=server, auth={'username':username, 'password':password})

def get_temperature(gpio):
        try:
            h, t = dht.read_retry(dht.DHT22, gpio)
            if t is not None:
                t = t * (9/5.0) + 32 # convert to fahrenheit
            if h is not None and t is not None:
                return "Temp={0:0.1f}F Humidity={1:0.1f}%".format(t,h)
        except:
            print "error reading read_temperature"
        return ""

def query_temperatures():
    conn = sqlite3.connect('/home/pi/db/gdc')
    c = conn.cursor()
    c.execute('SELECT * FROM gdc_data WHERE event=\'garage_temperature\' ORDER BY id DESC LIMIT 30')

    rows = c.fetchall()

    data = ""
    label = {}
    for row in rows:
        data += str(row[1] + " " +row[3])
        data += "\n"

    return data
