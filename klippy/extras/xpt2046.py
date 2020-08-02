# XPT2046 resisitive touch screen controller
#
# Copyright (_c) 2020 Martijn van Buul <martijn.van.buul@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import math
from . import bus

REPEAT_BACKOFF = 0.5
REPEAT_INTERVAL = 0.25
LONGCLICK_INTERVAL = 1

class XptConfigException(Exception):
    def __init__(self, value):
        super(XptConfigException, self).__init__(value)
        self.value = value

def _parse_coordinate(coordinate_string):
    components = coordinate_string.strip().split(',')

    try:
        pair = tuple(math.floor(float(p.strip())) for p in components)
    except ValueError:
        raise XptConfigException(
            "Malformed value '%s'" % (coordinate_string,))

    if len(pair) != 2:
        raise XptConfigException(
            "Malformed value '%s'" % (coordinate_string,))

    return pair

class Xpt2046MenuAction(object):
    def __init__(self, menu, function):
        self._menu = menu
        self._function = function

    def invoke(self, eventtime):
        self._menu.key_event(self._function, eventtime)

class Xpt2046GcodeAction(object):
    def __init__(self, printer, config, template_name):
        gcode_macro = printer.load_object(config, 'gcode_macro')
        self._gcode = printer.lookup_object("gcode")
        self._template = gcode_macro.load_template(config, template_name)

    def invoke(self, eventtime):
        del eventtime
        self._gcode.run_script(self._template.render())

class Xpt2046DummyAction(object):
    # pylint: disable=R0201
    def invoke(self, eventtime):
        del eventtime

def _create_action(printer_object, config, action_prefix):
    menu_function = config.get(action_prefix + '_function', None)
    if menu_function:
        menu_object = printer_object.lookup_object("menu")
        return Xpt2046MenuAction(menu_object, menu_function)
    if config.get(action_prefix + '_gcode', None):
        return Xpt2046GcodeAction(printer_object, config,
                                  action_prefix + '_gcode')
    return None

class Xpt2046Button(object):
    def __init__(self, points):
        self.points = []

        max_x = None
        points = points.split('\n')
        for point in points:
            if point:
                new_point = _parse_coordinate(point)
                if max_x is None or max_x < new_point[0]:
                    max_x = new_point[0]

                self.points.append(new_point)

        if len(self.points) < 3:
            raise XptConfigException(
                "Polygon with at least 3 vertices expected")

        self._max_ray_x = max_x + 100 # X coordinate used for ray casting

    def check_xy(self, location):
        def ccw(_a, _b, _c):
            return ((_c[1]-_a[1]) * (_b[0]-_a[0]) >
                    (_b[1]-_a[1]) * (_c[0]-_a[0]))

        def intersect(_a, _b, _c, _d):
            return (ccw(_a, _c, _d) != ccw(_b, _c, _d) and
                    ccw(_a, _b, _c) != ccw(_a, _b, _d))

        result = False
        # use a 0.1 offset (while polygon points are truncated) to ensure
        # that the casted ray can never be colinear with a polygon vertex
        outside_location = (self._max_ray_x, location[1] + 0.1)
        for i in range(len(self.points)-1):
            if intersect(self.points[i], self.points[i+1],
                         location, outside_location):
                result = not result

        if intersect(self.points[-1], self.points[0],
                     location, outside_location):
            result = not result

        return result

    # The following two methods are to be overridden by derived classes
    # pylint: disable=R0201

    # Called when a button is clicked. Can return a timestamp for an expected
    # repeat event.
    def clicked(self, eventtime):
        del eventtime
        return None

    # Called repeatedly while a button is being held. Can return a timestamp
    # for the next expected repeat event.
    def repeat(self, eventtime):
        del eventtime
        return None

class Xpt2046OneshotButton(Xpt2046Button):
    def __init__(self, points, action):
        super(Xpt2046OneshotButton, self).__init__(points)
        self._action = action

    #override
    def clicked(self, eventtime):
        self._action.invoke(eventtime)
        return None

class Xpt2046RepeatingButton(Xpt2046Button):
    def __init__(self, points, action, repeat_action):
        super(Xpt2046RepeatingButton, self).__init__(points)
        self._action = action
        self._repeat_action = repeat_action

    #override
    def clicked(self, eventtime):
        self._action.invoke(eventtime)
        return eventtime + REPEAT_BACKOFF

    #override
    def repeat(self, eventtime):
        self._repeat_action.invoke(eventtime)
        return eventtime + REPEAT_INTERVAL

class Xpt2046LongclickButton(Xpt2046Button):
    def __init__(self, points, action, longclick_action):
        super(Xpt2046LongclickButton, self).__init__(points)

        self._action = action
        self._longclick_action = longclick_action

    #override
    def clicked(self, eventtime):
        self._action.invoke(eventtime)
        return eventtime + LONGCLICK_INTERVAL

    #override
    def repeat(self, eventtime):
        self._longclick_action.invoke(eventtime)
        return None # no more callbacks required

class Xpt2046(object):
    def __init__(self, config):
        printer = config.get_printer()
        self._reactor = printer.get_reactor()
        self._gcode = printer.lookup_object("gcode")
        self._repeat_timer = self._reactor.register_timer(self._repeat_event)
        self._active_button = None
        self._spi = bus.MCU_SPI_from_config(
            config, 0, pin_option='cs_pin', default_speed=25000)

        button_pin = config.get('penirq_pin')
        buttons_object = printer.lookup_object("buttons")

        buttons_object.register_buttons([button_pin], self._penirq_callback)

        self.buttons = []

        # Discover soft buttons
        for i in range(999):
            button_prefix = 'button%d' % (i,)

            func = _create_action(printer, config, button_prefix)
            if not func:
                func = Xpt2046DummyAction()

            repeat_func = _create_action(printer, config,
                                         button_prefix + '_repeat')

            long_func = _create_action(printer, config,
                                       button_prefix + '_longpress')

            button_points = config.get(button_prefix + '_points', None)

            if not button_points or not (repeat_func or long_func or func):
                break

            try:
                if repeat_func and long_func:
                    raise XptConfigException(
                        "repeat_(function/button) and long_(function/button) "
                        "cannot be defined at the same time")
                elif repeat_func:
                    self.buttons.append(Xpt2046RepeatingButton(
                        button_points, func, repeat_func))
                elif long_func:
                    self.buttons.append(Xpt2046LongclickButton(
                        button_points, func, long_func))
                else:
                    self.buttons.append(Xpt2046OneshotButton(
                        button_points, func))

            except XptConfigException as err:
                raise config.error(
                    "Error while parsing xp2046 button %d: %s"
                    %(i, err.value))

        self._gcode.register_command(
            "XPT_DEBUG", self._cmd_debug,
            desc="Enable/disable touch panel reporting")
        self.report_enabled = False

        printer.register_event_handler("klippy:ready", self._handle_ready)

    def _penirq_callback(self, eventtime, state):
        if state:
            result = self._get_touch_xy()
            if self.report_enabled:
                self._gcode.respond_info("XPT2046 touch: (%d,%d)" % result)

            for button_candidate in self.buttons:
                if button_candidate.check_xy(result):
                    self._active_button = button_candidate
                    desired_callback = button_candidate.clicked(eventtime)
                    if desired_callback:
                        self._reactor.update_timer(self._repeat_timer,
                                                   desired_callback)
                    break
        else:
            if self.report_enabled:
                self._gcode.respond_info("XPT2046 release")

            self._active_button = None

    def _repeat_event(self, eventtime):
        desired_callback = None
        if self._active_button:
            desired_callback = self._active_button.repeat(eventtime)

        return desired_callback or self._reactor.NEVER

    def _cmd_debug(self, gcmd):
        enable = gcmd.get_int('ENABLE', None)
        if enable is not None:
            self.report_enabled = (enable != 0)
        else:
            self.report_enabled = not self.report_enabled

        gcmd.respond_info("XPT2046 debugging has been %s"
                          %("enabled" if self.report_enabled else "disabled"))

    def _handle_ready(self):
        # Ensure chip is in the correct powerdown mode.
        self._spi.spi_send([0xD0, 0x00])

    def _get_touch_xy(self):
        # poll X and Y in three times, take median

        # leave reference on, add empty byte for skewed output
        payload = [0x91, 0x00,
                   0xD1, 0x00,
                   0x91, 0x00,
                   0xD1, 0x00,
                   0x91, 0x00,
                   0xD0, 0x00, 0x00]

        result = self._spi.spi_transfer(payload)['response']

        # Output data is bytewise, but trailing by 3 clock pulses.
        def _getsample(result, start):
            return (ord(result[start+1]) >> 3) + (ord(result[start]) << 5)

        def _median3(_a, _b, _c):
            if _a > _b:
                return _a if _a < _c else (_b if _b > _c else _c)
            return _a if _a > _c else (_b if _b < _c else _c)

        _x = _median3(
            _getsample(result, 1),
            _getsample(result, 5),
            _getsample(result, 9))
        _y = _median3(
            _getsample(result, 3),
            _getsample(result, 7),
            _getsample(result, 11))

        return (_x, _y)

def load_config_prefix(config):
    return Xpt2046(config)
