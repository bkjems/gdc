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
import db_utils as db_Utils

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
WEEK = 'wk'

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


class WEEK_DAYS(Enum):
    # Enum for days of the week.
    Mon = 0
    Tue = 1
    Wed = 2
    Thu = 3
    Fri = 4
    Sat = 5
    Sun = 6


def get_time():
    return time.time()


def get_date_time():
    return datetime.datetime.now()


def get_elapsed_time(total_seconds):
    if total_seconds == 0:
        return 'inf'
    save_total_seconds = total_seconds
    parts = []
    _min = 0
    sec = 0
    for unit, div in TIME_DURATION_UNITS:
        amount, total_seconds = divmod(int(total_seconds), div)
        if amount > 0:
            if unit == MIN:
                _min = amount
            elif unit == SEC:
                sec = amount
            else:
                parts.append('{} {}{}'.format(
                    amount, unit, "" if amount == 1 else "s"))
    if _min > 0 or sec > 0:
        if save_total_seconds <= 60 or (_min <= 0 and sec > 0):
            parts.append('{}s'.format("60" if sec == 0 else str(sec).zfill(2)))
        else:
            parts.append('{}:{}'.format("00" if _min == 0 else str(
                _min).zfill(2), "00" if sec == 0 else str(sec).zfill(2)))
    return ', '.join(parts)


def is_day_of_week(self, day_of_week_num):
    """Return the day of the week as an integer, where Monday is 0 and Sunday is 6."""
    if self.on_days_of_week == '':
        return True

    day_of_week_name = WEEK_DAYS(day_of_week_num).name
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
    return is_too_early_with_time(Utils.get_date_time().time())


def is_too_early_with_time(time_now):
    # When restarting each morning at 4am, don't send init msg if between 3:58 - 4:05am
    if time_now == None:
        return False

    return(datetime.time(3, 58) <= time_now <= datetime.time(4, 5))


def is_time_expired(tis, alert_time, curr_time):
    if alert_time <= 0:
        return True

    # add alert_time secs to current time
    dt_time_in_state = epoch_to_datetime(tis)
    newDateTime = dt_time_in_state + timedelta(seconds=alert_time)
    return curr_time > datetime_to_epoch(newDateTime)


def datetime_to_epoch(dt):
    if dt == None:
        return None

    return time.mktime(dt.timetuple())  # convert to epoch time


def epoch_to_datetime(epoch):
    if epoch == None:
        return None

    # convert time_seconds to datetime
    return datetime.datetime.fromtimestamp(epoch)


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


def round_up_string(td_string):
    dt = None
    if td_string != "":
        dt = datetime.datetime.strptime(td_string, Utils.DATEFORMAT)

    return round_up_datetime(dt)


def round_up_minutes(dt_seconds):
    if dt_seconds == None:
        return None

    dt = epoch_to_datetime(dt_seconds)
    return datetime_to_epoch(round_up_datetime(dt))


def round_up_datetime(dt):
    if dt == None:
        return None

    nm, hr = modby(dt.minute)
    ft = timedelta(hours=+hr, minutes=+(nm-dt.minute-1),
                   seconds=+(60-dt.second))

    return dt + ft


def publish_MQTT(server, topic, msg, username, password):
    if isDebugging:
        print "calling MQTT - topic: {}, msg: {}, server: {}, username: {}".format(
            topic, str(msg), server, username)
    publish.single(topic, str(msg), hostname=server, auth={'username': username, 'password': password})


def get_temperature(gpio):
    try:
        h, t = dht.read_retry(dht.DHT22, gpio)
        if t is not None:
            t = t * (9/5.0) + 32  # convert to fahrenheit
        if h is not None and t is not None:
            return "Temp={0:0.1f}F Humidity={1:0.1f}%".format(t, h)
    except:
        return "error reading temperature :"

    return ""

def query_weather_API_by_date(requests, controller, date_value):
    if date_value == None or date_value == "":
        return "invalid date"

    try:
        url = 'http://api.weatherapi.com/v1/history.json?key=d7fff8a3981e42e2b9c132711201810&q=Riverton&dt=' + date_value
        data = requests.get(url)
        json_data = data.json()
        y = json_data["forecast"]["forecastday"][0]["day"]
        day = {"date": date_value, "avghumidity": y["avghumidity"], "avgtemp_f": y["avgtemp_f"],
                "mintemp_f": y["mintemp_f"], "maxtemp_f": y["maxtemp_f"]}

        # save historic temp in sqlite3 gdc
        try:
            Utils.publish_MQTT(controller.mqtt_server, controller.mqtt_topic_day_temperature, str(day), controller.mqtt_username, controller.mqtt_password)
        except Exception as e:
            return("MQTT exception: %s", e)

        return day
    except:
        return("Error query_weather_API_by_date: %s", sys.exc_info()[0])

#
# query the weather api for historic day temperatures.  Can only go back 7 days
#
def query_weather_API(requests, controller):
    weather_info = {}
    weather_info["weather_temps"] = []
    try:
        for i in range(7):
            date = Utils.get_date_time() - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            day = query_weather_API_by_date(requests, controller, date_str)

            weather_temps = weather_info["weather_temps"]
            weather_temps.append(day)
    except:
        return("Error query_weather_API: %s", sys.exc_info()[0])
    return weather_info
