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

    def testelapsedTimeSeconds(self):
	rv = Utils.elapsed_time(60)
        self.assertEqual('60s', rv)

    def testelapsedTimeMinutes(self):
	rv = Utils.elapsed_time(160)
        self.assertEqual('2m 40s', rv)

    def testelapsedTimeHours(self):
	rv = Utils.elapsed_time(4560)
        self.assertEqual('1hr 16:00', rv)

    def testelapsedTimeDays(self):
	rv = Utils.elapsed_time(144560)
        self.assertEqual('1 day, 16:09', rv)

#
# sudo python controller_test.py -v"
#
if __name__ == '__main__':
    # begin the unittest.main()
    unittest.main()

