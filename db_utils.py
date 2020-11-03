#!/usr/bin/env python
"""Utility methods to monitor and control garage doors via a raspberry pi."""
import sys
import time
import json
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
    #print "calling publishMQTT "+msg
    publish.single(topic, str(msg), hostname=server, auth={'username':username, 'password':password})

def get_temperature(gpio):
    try:
        h, t = dht.read_retry(dht.DHT22, gpio)
        if t is not None:
            t = t * (9/5.0) + 32 # convert to fahrenheit
        if h is not None and t is not None:
            return "Temp={0:0.1f}F Humidity={1:0.1f}%".format(t,h)
    except:
        return "error reading temperature :"

    return ""

def query_temperatures():
    conn = sqlite3.connect('/home/pi/db/gdc')
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM gdc_data WHERE event=\'garage_temperature\' ORDER BY id DESC LIMIT 30')
    
        rows = c.fetchall()
    
        data = ""
        for row in rows:
	    if row[3] == None:
	        continue
	    
            data += str(row[1] + " " +row[3] + "\n")

    except:
        return ("ERROR: query_temperatures: %s", sys.exc_info()[0])

    return data

def query_day_temperature_data():
    conn = sqlite3.connect('/home/pi/db/gdc')
    c = conn.cursor()
    c.execute('SELECT * FROM gdc_data WHERE event=\'day_temperature\' ORDER BY _time')

    rows = c.fetchall()
    data = "" 
    weather_info ={}
    weather_info["weather_temps"] = []

    try:
        for row in rows:
	    weather_temps = weather_info["weather_temps"]
	    if row[3] == "":
	        day = {"date":row[1], "avgtemp_f":row[4]}
	        weather_temps.append(day)
	    else:
	        d = json.loads(row[3])
	        day = {"date":d["date"], "avghumidity":d['avghumidity'], "avgtemp_f":d['avgtemp_f'], "mintemp_f":d['mintemp_f'], "maxtemp_f": d['maxtemp_f']}
	        weather_temps.append(day)
    except:
	return("query_day_temperature_date failed")

    return json.dumps(weather_info)

    
def query_day_temp_data():
    conn = sqlite3.connect('/home/pi/db/gdc')
    c = conn.cursor()
    c.execute('SELECT * FROM gdc_data WHERE event=\'day_temperature\' ORDER BY _time')

    rows = c.fetchall()

    avg_temp = {}
    for row in rows:
        dt = row[1].split(" ")[0]

	# handle different ways the day temps are stored
	if row[3] == "":
    	    avg_temp_value = row[4] 	
	else:
	    d = json.loads(row[3])
    	    avg_temp_value = d['avgtemp_f'] 	

    	avg_temp[dt] = avg_temp_value

    #print avg_temp
    return avg_temp

	
def query_temperatures_data():
    conn = sqlite3.connect('/home/pi/db/gdc')
    c = conn.cursor()
    c.execute('SELECT * FROM gdc_data WHERE event=\'garage_temperature\' ORDER BY _time')

    rows = c.fetchall()

    avg_temp = query_day_temp_data() 

    high_low = {}
    for row in rows:
        hl_dt = row[1].split(" ")[0]
	
        if hl_dt not in high_low.keys(): 
           high_low[hl_dt] = [0,0]

        low_temp = float(high_low[hl_dt][0])	
        high_temp = float(high_low[hl_dt][1])	
        temperature = float(row[4])

	if temperature < low_temp or low_temp == 0:
            high_low[hl_dt][0] = temperature
	if temperature > high_temp or high_temp == 0:
            high_low[hl_dt][1] = temperature

    data = []
    for i in sorted(high_low.keys()):
	dparts = i.split("-")

	avg_temp_value = ""
	if i in avg_temp.keys():
	   avg_temp_value = avg_temp[i]

 	data.append({"y":high_low[i], "avg_temp":avg_temp_value, "yy":dparts[0], "m":int(dparts[1]), "d":dparts[2]})
        	
    return data 

#
# Query db base on sql statement and return all rows found. If an error occurs log it and return None
#
def query_db(sql):
    try:
	if sql == None:
	    sql = ""
        conn = sqlite3.connect('/home/pi/db/gdc')
        c = conn.cursor()
        c.execute(sql)
        return(c.fetchall())
    except Exception as e:
        logging.info("query_db exception: %s", e)
	return None


#
# Query for the number of times the garage was opened and closed based on the 
# database entries. Calculate how long the door was left open
# return a string 
#
def query_garageOpenClose():
    rows = query_db('SELECT * FROM gdc_data WHERE event=\'2 Car\' ORDER BY id DESC LIMIT 30')
    if rows == None:
	return None

    data = ""
    label = {}
    open_time = ""
    time_diff = ""
    for row in reversed(rows):
	time_diff = ""
        if row[3] == "closed" and open_time != "":
            dt1 = datetime.datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S")
            dt2 = datetime.datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
            tot_sec  = (dt2-dt1).total_seconds()
            time_diff = " (%s)" % (Utils.elapsed_time(int(tot_sec)))

        open_time = ""
        if row[3] == "opening":
            open_time = row[1] 

        data += str(row[1] + " " +row[3] + time_diff) + "\n"

    return (data)

#
# query the weather api for historic day temperatures.  Can only go back 7 days 
#
def weatherAPI(requests,controller):
    weather_info ={}
    weather_info["weather_temps"] = []
    try:
        for i in range(7):
            weather_temps= weather_info["weather_temps"]

            date = Utils.getDateTime() - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')

            url = 'http://api.weatherapi.com/v1/history.json?key=d7fff8a3981e42e2b9c132711201810&q=Riverton&dt=' + date_str
            data = requests.get(url)
            json_data = data.json()
            y = json_data["forecast"]["forecastday"][0]["day"]
            day = { "date":date_str, "avghumidity":y["avghumidity"], "avgtemp_f":y["avgtemp_f"], "mintemp_f":y["mintemp_f"], "maxtemp_f":y["maxtemp_f"] }
            weather_temps.append(day)
	    #print "-->"+str(day)

            # save historic temp in sqlite3 gdc
	    try:
                Utils.publishMQTT(controller.mqtt_server, controller.mqtt_topic_day_temperature, str(day), controller.mqtt_username, controller.mqtt_password)
	    except Exception as e:
                return("MQTT exception: %s", e)
    except:
        return("Weather check error: %s", sys.exc_info()[0])

    return weather_info

