#!/usr/bin/env python
"""Utility methods to monitor and control garage doors via a raspberry pi."""
import sys
import time
import json
import datetime
import utils as Utils
import sqlite3
from enum import Enum
from datetime import timedelta
from time import gmtime
import requests


def query_temperatures(eventName, limit):
    sql = ('SELECT * FROM gdc_data WHERE event=\'%s\' ORDER BY _time desc LIMIT %d') % (eventName, limit)
    rows = query_db(sql)
    try:
        data = ""
        for row in rows:
            if row[3] == None:
                continue
            data += str(row[1] + " " + row[2] + " " + row[3] + "\n")
    except:
        return ("ERROR: query_temperatures: %s", sys.exc_info()[0])

    return data


def query_day_temperature_data():
    sql = ('SELECT * FROM gdc_data WHERE event=\'%s\' ORDER BY _time') % ("day_temperature")
    rows = query_db(sql)

    weather_info = {}
    weather_info["weather_temps"] = []
    try:
        for row in rows:
            if row[3] == "":
                day = {"date": row[1], "avgtemp_f": row[4]}
            else:
                day = json.loads(row[3])

            weather_temps = weather_info["weather_temps"]
            weather_temps.append(day)
    except:
        return("query_day_temperature_date failed")

    return json.dumps(weather_info)


def query_day_temp_data():
    sql = ('SELECT * FROM gdc_data WHERE event=\'%s\' ORDER BY _time') % ("day_temperature")
    rows = query_db(sql)

    avg_temp = {}
    for row in rows:
        date_value = row[1].split(" ")[0]

        # handle different ways the day temps are stored
        if row[3] == "":
            avg_temp_value = row[4]
        else:
            json_data = json.loads(row[3])
            avg_temp_value = json_data['avgtemp_f']

        avg_temp[date_value] = avg_temp_value

    return avg_temp


def query_temperature_data(eventName, controller):
    sql = ('SELECT * FROM gdc_data WHERE event=\'%s\' ORDER BY _time') % (eventName)
    rows = query_db(sql)

    curr_date = Utils.get_date_time().strftime('%Y-%m-%d')
    avg_temp = query_day_temp_data()

    high_low = {}
    for row in rows:
        hl_dt = row[1].split(" ")[0]

        if hl_dt not in high_low.keys():
            high_low[hl_dt] = [0, 0]
        try:
            low_temp = float(high_low[hl_dt][0])
            high_temp = float(high_low[hl_dt][1])
            temperature = float(row[4])
        except:
            continue

        if temperature < low_temp or low_temp == 0:
            high_low[hl_dt][0] = temperature
        if temperature > high_temp or high_temp == 0:
            high_low[hl_dt][1] = temperature

    Utils.query_weather_API_by_date(requests, controller, curr_date)

    data = []
    for temp in sorted(high_low.keys()):
        data_parts = temp.split("-")
        avg_temp_value = ""

        if temp in avg_temp.keys():
            avg_temp_value = avg_temp[temp]
            data.append({"y": high_low[temp], "avg_temp": avg_temp_value, "yy": data_parts[0], "m": int(
                data_parts[1]), "d": data_parts[2]})             
    return data


def query_garage_open_close():
    sql = ('SELECT * FROM gdc_data WHERE event=\'%s\' ORDER BY id DESC LIMIT 30') % ('2 Car')
    rows = query_db(sql)

    data = ""
    open_time = ""
    time_diff = ""
    
    for row in reversed(rows):
        time_diff = ""
        if row[3] == "closed" and open_time != "":
            dt1 = datetime.datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S")
            dt2 = datetime.datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
            tot_sec = (dt2-dt1).total_seconds()
            time_diff = " (%s)" % (Utils.get_elapsed_time(int(tot_sec)))

        open_time = ""
        if row[3] == "opening":
            open_time = row[1]

        data += "%s %s%s\n" % (str(row[1]), str(row[3]), time_diff)
    return (data)


def query_db(sql):
    conn = sqlite3.connect('/home/pi/db/gdc')
    try:
        c = conn.cursor()
        c.execute(sql)

        return(c.fetchall())
    except:
        return ("ERROR: query_temperatures: %s", sys.exc_info()[0])

    return None
