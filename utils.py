#!/usr/bin/env python
"""Utility methods to monitor and control garage doors via a raspberry pi."""
import time
import datetime
from time import strftime
from datetime import date
from enum import Enum
from datetime import timedelta

"""global"""
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
    # When restarting each morning at 4am, don't send init msg if between 3:58 - 4:05am
    raw_now = datetime.datetime.now().time()
    return(datetime.time(3, 58) <= raw_now <= datetime.time(4, 5))


def getExpiredTime(tis, alert_time, curr_time):
    if alert_time <= 0:
        return True

    # add alert_time secs to current time
    dt_time_in_state  = datetime.datetime.fromtimestamp(tis) # convert time to datetime
    newDateTime = dt_time_in_state  + timedelta(seconds=alert_time)
    return curr_time > time.mktime(newDateTime.timetuple()) # convert to epoch time
