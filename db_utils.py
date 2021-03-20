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


def build_sql(eventNames, limit, orderby, desc_asc):
    sql = ("SELECT * FROM gdc_data WHERE event=")
    cnt = 0
    for event in eventNames:
        if cnt != 0:
            sql += " or event="
        cnt += 1
        sql += "\'" + event + "\'"

    sql += " ORDER BY " + orderby + " "

    if desc_asc != "":
        sql += desc_asc

    if limit > 0:
        sql += " LIMIT %d" % (limit)

    return sql


def query_db(sql):
    conn = sqlite3.connect('/home/pi/db/gdc')
    try:
        c = conn.cursor()
        c.execute(sql)
        return(c.fetchall())
    except:
        return ("ERROR: query_db: sql:%s -- %s", sql, sys.exc_info()[0])

    return None


def query_temperatures(eventNames, limit):
    sql = build_sql(eventNames, limit, "_time", "desc")
    rows = query_db(sql)
    try:
        data = ""
        for row in rows:
            data += '{} {:>20}: {:>5.1f}\n'.format(
                row[1], row[2], float(row[4]))
    except:
        return ("ERROR: query_temperatures: %s", sys.exc_info()[0])

    return data


def query_day_temperature_data():
    sql = build_sql(["day_temperature"], 20, "_time", "desc")
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
    sql = build_sql(["day_temperature"], 0, "_time", "")
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
    sql = build_sql(eventName, 0, "_time", "")
    rows = query_db(sql)

    curr_date = Utils.get_date_time().strftime('%Y-%m-%d')
    avg_temp = query_day_temp_data()

    high_low = {}
    for row in rows:
        hl_date = row[1].split(" ")[0]

        if hl_date not in high_low.keys():
            high_low[hl_date] = [0, 0]
        try:
            low_temp = float(high_low[hl_date][0])
            high_temp = float(high_low[hl_date][1])
            temperature = float(row[4])

            if temperature < low_temp or low_temp == 0:
                high_low[hl_date][0] = temperature
            if temperature > high_temp or high_temp == 0:
                high_low[hl_date][1] = temperature
        except:
            continue

    # add todays avg temperature to db
    Utils.query_weather_API_by_date(requests, controller, curr_date)

    # create json
    json_data = []
    for hl_temps in sorted(high_low.keys()):
        hl_date = datetime.datetime.strptime(hl_temps, "%Y-%m-%d")
        avg_temp_value = ""

        if hl_temps in avg_temp.keys():
            avg_temp_value = avg_temp[hl_temps]
            json_data.append({ "y": high_low[hl_temps], "avg_temp": avg_temp_value, "m": hl_date.month, "d": hl_date.day, 
                "yy": hl_date.year })
    return json_data



def query_garage_open_close():
    sql = build_sql(["2 Car"], 30, "id", "desc")
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
