import unittest
import json
import time
import datetime
import utils as Utils
import door as Doors

# This is the class we want to test. So, we need to import it
import controller as ControllerClass 

class Test(unittest.TestCase):

    def setup(self):
        config_file = open('config.json')
        c = ControllerClass.Controller(json.load(config_file), True) 
        config_file.close()
	c.from_time = ""
        c.to_time = ""
        c.on_days_of_week = ""
 	c.time_to_open = 0	
	return c

    def testDoorNameIsNamedRight(self):
	c = self.setup() 
	door = c.getDoor("right")
        assert door is not None
        self.assertTrue(door.id == "right")

    def testDoorOpenAtStartup(self):
	c = self.setup() 
	door = c.getDoor("right")
	door.test_state_pin = Utils.OPEN
	door.state = Utils.OPEN
	door.toggle_relay()
        #self.assertEquals(door.test_state_pin, "open")

    def testDoorOpenLongerThanTTW(self):
	c = self.setup() 
	door = c.getDoor("right")
	c.time_to_report_open= 1
	c.time_to_close = 0
	door.toggle_relay()
	c.check_status() 
	time.sleep(4)
	c.check_status() 
        self.assertFalse(door.send_open_im)

    def testOpenNoApproxTimeInOpen(self):
	c = self.setup() 
	door = c.getDoor("right")
	c.time_to_open = 0
	door.toggle_relay()
	time.sleep(2)
	c.check_status()
        self.assertEquals(door.test_state_pin, "open")

    def testOpenCloseNoApproxTimeInClose(self):
	c = self.setup() 
	door = c.getDoor("right")
	c.time_to_close= 0
	c.time_to_open = 0

	door.toggle_relay()
	c.check_status()
        self.assertEquals(door.test_state_pin, "open")

	door.toggle_relay()
	c.check_status()
        self.assertEquals(door.test_state_pin, "closed")

    def testOpeningWithApproxTimeToOpen(self):
	c = self.setup() 
	d = c.getDoor("right")
	d.state = "closed" 
	c.time_to_open=5
	d.toggle_relay()
	c.check_door_status(d)
        self.assertEquals(d.state, "opening")
 
    def testClosingWithApproxTimeToClose(self):
	c = self.setup() 
	door = c.getDoor("right")
	door.state = "open"
	door.test_state_pin= "open"
	door.time_to_close= 5
	door.toggle_relay()
	c.check_door_status(door)
        self.assertEquals(door.state, "closing")

    def testIsDayOfWeekInvalid(self):
        c = self.setup()
        c.on_days_of_week="Mon,Tue,Wed,Thu,Fri,Sun"
        dow = datetime.date(2018, 11, 17).weekday()
        rv = Utils.is_day_of_week(c,dow)
        self.assertFalse(rv)

    def testIsTooEarly(self):
        self.setup() 
        dt = datetime.datetime.strptime('03:55', '%H:%M').time()
        self.assertFalse(Utils.is_too_early_withTime(dt))
        dt = datetime.datetime.strptime('04:00', '%H:%M').time()
        self.assertTrue(Utils.is_too_early_withTime(dt)) 
        self.assertFalse(Utils.is_too_early_withTime(Utils.getDateTime().time()))
        self.assertFalse(Utils.is_too_early_withTime(None))
        self.assertFalse(Utils.is_too_early())

    def testIsDayOfWeekValid(self):
        c = self.setup()
        c.on_days_of_week="Mon,Tue,Wed,Thu,Fri,Sat,Sun"
        dow = datetime.date(2018, 11, 17).weekday()
        rv = Utils.is_day_of_week(c,dow)
        self.assertTrue(rv)

    def testIsDayOfWeekEmpty(self):
        c = self.setup()
        c.on_days_of_week=""
        dow = datetime.date(2018, 11, 17).weekday()
        rv = Utils.is_day_of_week(c,dow)
        self.assertTrue(rv)

    def testIsTimeBetweenParamsEmpty(self):
        c = self.setup()
        c.from_time = ""
        c.to_time = ""
        c.on_days_of_week = ""
        rv = Utils.is_time_between(c,datetime.time(5, 0))
        self.assertTrue(rv)

    def testIsTimeBetweenInvalid(self):
        c = self.setup()
        c.from_time = '00:01'
        c.to_time = '02:00'
        rv = Utils.is_time_between(c,datetime.time(2, 2))
        self.assertFalse(rv)

    def testIsTimeBetween0000_2359Valid(self):
        c = self.setup()
        c.from_time = '00:01'
        c.to_time = '23:59'
        rv = Utils.is_time_between(c,datetime.time(3,1))
        self.assertTrue(rv)

    def testelapsedTimes(self):
        self.assertEqual('43s', Utils.elapsed_time(43))
        self.assertEqual('60s', Utils.elapsed_time(60))
        self.assertEqual('01:05', Utils.elapsed_time(65))
        self.assertEqual('1 hr', Utils.elapsed_time(3600))
        self.assertEqual('1 hr, 16:03', Utils.elapsed_time(4563))
        self.assertEqual('1 day', Utils.elapsed_time(86400))
        self.assertEqual('1 day, 05s', Utils.elapsed_time(86405))
        self.assertEqual('2 days, 7 hrs, 12:00', Utils.elapsed_time(198720))
        self.assertEqual('1 wk, 1 day, 1 hr, 04s', Utils.elapsed_time(694804))
        self.assertEqual('1 wk, 1 day, 1 hr, 01:01', Utils.elapsed_time(694861))
        self.assertEqual('3 wks, 3 days, 19 hrs, 42:40', Utils.elapsed_time(2144560))
        self.assertEqual('1 yr, 1 wk, 1 day, 1 hr, 02:40', Utils.elapsed_time(32230960))

    def testIsTimeExpired(self):
        self.setup()
        tis = Utils.datetimeToEpoch(datetime.datetime.strptime("06-14-2020 11:00:00", Utils.DATEFORMAT))
        alert_time =  1200 # 20 mins
        curr_time = Utils.datetimeToEpoch(datetime.datetime.strptime("06-14-2020 11:10:00", Utils.DATEFORMAT))
        self.assertFalse(Utils.isTimeExpired(tis, alert_time, curr_time))       

        curr_time = Utils.datetimeToEpoch(datetime.datetime.strptime("06-14-2020 11:20:01", Utils.DATEFORMAT))
        self.assertTrue(Utils.isTimeExpired(tis, alert_time, curr_time))

        alert_time =  0 
        self.assertTrue(Utils.isTimeExpired(tis, alert_time, curr_time))

    def testStillOpen_mktime(self):
        c = self.setup()
        door = c.getDoor("right")
        door.tis[Utils.STILLOPEN] = Utils.roundUpMins(Utils.getTime())
        curr_time = datetime.datetime.strptime("06-14-2020 13:11:05", Utils.DATEFORMAT)
        door.tis[Utils.STILLOPEN] = Utils.roundUpMins(Utils.datetimeToEpoch(curr_time))
        self.assertEqual(1592162100.0, door.tis[Utils.STILLOPEN])

    def testRoundUp(self):
        self.assertEqual(Utils.roundUp_string("07-01-2020 14:09:00"), 
	    datetime.datetime.strptime("07-01-2020 14:10:00", Utils.DATEFORMAT))
        self.assertEqual(Utils.roundUp_string("12-31-2020 23:59:10"), 
	    datetime.datetime.strptime("01-01-2021 00:00:00", Utils.DATEFORMAT))
        self.assertEqual(Utils.roundUp_string("12-11-2020 23:59:10"), 
	    datetime.datetime.strptime("12-12-2020 00:00:00", Utils.DATEFORMAT))
        self.assertEqual(Utils.roundUp_string("12-13-2020 11:59:10"), 
	    datetime.datetime.strptime("12-13-2020 12:00:00", Utils.DATEFORMAT))
        self.assertEqual(Utils.roundUp_string("10-31-2020 23:59:10"), 
	    datetime.datetime.strptime("11-01-2020 00:00:00", Utils.DATEFORMAT))
        self.assertEqual(Utils.roundUp_string("01-02-2020 14:50:10"), 
	    datetime.datetime.strptime("01-02-2020 14:50:00", Utils.DATEFORMAT))

    def testDiffBetween2Dates(self):
        dt1 = datetime.datetime.strptime("10-10-2020 17:31:57", "%m-%d-%Y %H:%M:%S")
        dt2 = datetime.datetime.strptime("10-10-2020 17:34:58", "%m-%d-%Y %H:%M:%S")
        total_secs = (dt2-dt1).total_seconds()
        time_diff = "%s" % (Utils.elapsed_time(int(total_secs)))
        self.assertEqual("03:01", time_diff) 


#
# sudo python controller_test.py -v"
#
if __name__ == '__main__':
    # begin the unittest.main()
    unittest.main()

