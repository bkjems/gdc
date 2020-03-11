import utils as Utils
import controller as Controller

class Door(object):
    def __init__(self, doorId, config):
	self.gpio = None
        self.id = doorId
        self.name = config['id']
        self.relay_pin = config['relay_pin']
        self.state_pin = config['state_pin']
        self.test_state_pin = Utils.CLOSED
        self.state_pin_closed_value = config['closed_value']
        self.tis = {
            Utils.CLOSED:0,
            Utils.OPEN:0,
            Utils.OPENING:0,
            Utils.CLOSING:0,
            Utils.STILLOPEN:0,
            Utils.FORCECLOSE:0
        }

    def setup_gpio(self, gpio):
        if Utils.isDebugging:
            return

	self.gpio = gpio
        self.gpio.setup(self.relay_pin, gpio.OUT)
        self.gpio.setup(self.state_pin, gpio.IN, pull_up_down=gpio.PUD_UP)
        self.gpio.output(self.relay_pin, True)

    """returns OPEN or CLOSED for a given garages door state pin"""
    def get_state_pin(self):
        if Utils.isDebugging:
            return self.test_state_pin
        else:
            rv = self.gpio.input(self.state_pin)
            if rv == self.state_pin_closed_value:
                return Utils.CLOSED

        return Utils.OPEN

    """This gets hit from the web page to open or close garage door"""
    def toggle_relay(self):
        if Utils.isDebugging:
            self.test_state_pin = Utils.CLOSED if self.test_state_pin == Utils.OPEN else Utils.OPEN
            return

        self.gpio.output(self.relay_pin, False)
        time.sleep(0.2)
        self.gpio.output(self.relay_pin, True)
