# -*- coding: utf-8 -*-
# Support for menu button press tracking
#
# Copyright (C) 2018  Janar Sööt <janar.soot@gmail.com>
# Copyright (C) 2020  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

LONG_PRESS_DURATION = 0.800
TIMER_DELAY = .200

class MenuKeys:
    def __init__(self, config, callback):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.callback = callback
        buttons = self.printer.load_object(config, "buttons")
        # Register rotary encoder
        encoder_pins = config.get('encoder_pins', None)
        self.encoder_steps_per_detent = config.getchoice(
            'encoder_steps_per_detent', {'2': 2, '4': 4}, '2')
        if encoder_pins is not None:
            try:
                pin1, pin2 = encoder_pins.split(',')
            except:
                raise config.error("Unable to parse encoder_pins")
            buttons.register_rotary_encoder(pin1.strip(), pin2.strip(),
                                            self.encoder_cw_callback,
                                            self.encoder_ccw_callback,
                                            self.encoder_steps_per_detent)
        self.encoder_fast_rate = config.getfloat('encoder_fast_rate',
                                                 .030, above=0.)
        self.last_encoder_cw_eventtime = 0
        self.last_encoder_ccw_eventtime = 0
        # Register click button
        self.is_short_click = False
        self.click_timer = self.reactor.register_timer(self.long_click_event)
        self.register_button(config, 'click_pin', self.click_callback, False)
        # Register other buttons
        self.register_button(config, 'back_pin', self.back_callback)
        self.register_button(config, 'up_pin', self.up_callback)
        self.register_button(config, 'down_pin', self.down_callback)
        self.register_button(config, 'kill_pin', self.kill_callback)

    def register_button(self, config, name, callback, push_only=True):
        pin = config.get(name, None)
        if pin is None:
            return
        buttons = self.printer.lookup_object("buttons")
        analog_range = config.get('analog_range_' + name, None)
        if analog_range is None:
            if push_only:
                buttons.register_button_push(pin, callback)
            else:
                buttons.register_buttons([pin], callback)
            return
        try:
            amin, amax = map(float, analog_range.split(','))
        except:
            raise config.error("Unable to parse analog_range_" + name)
        pullup = config.getfloat('analog_pullup_resistor', 4700., above=0.)
        if push_only:
            buttons.register_adc_button_push(pin, amin, amax, pullup, callback)
        else:
            buttons.register_adc_button(pin, amin, amax, pullup, callback)

    # Rotary encoder callbacks
    def encoder_cw_callback(self, eventtime):
        fast_rate = ((eventtime - self.last_encoder_cw_eventtime)
                     <= self.encoder_fast_rate)
        self.last_encoder_cw_eventtime = eventtime
        if fast_rate:
            self.callback('fast_up', eventtime)
        else:
            self.callback('up', eventtime)

    def encoder_ccw_callback(self, eventtime):
        fast_rate = ((eventtime - self.last_encoder_ccw_eventtime)
                     <= self.encoder_fast_rate)
        self.last_encoder_ccw_eventtime = eventtime
        if fast_rate:
            self.callback('fast_down', eventtime)
        else:
            self.callback('down', eventtime)

    # Click handling
    def long_click_event(self, eventtime):
        self.is_short_click = False
        self.callback('long_click', eventtime)
        return self.reactor.NEVER

    def click_callback(self, eventtime, state):
        if state:
            self.is_short_click = True
            self.reactor.update_timer(self.click_timer,
                                      eventtime + LONG_PRESS_DURATION)
        elif self.is_short_click:
            self.reactor.update_timer(self.click_timer, self.reactor.NEVER)
            self.callback('click', eventtime)

    # Other button callbacks
    def back_callback(self, eventtime):
        self.callback('back', eventtime)

    def up_callback(self, eventtime):
        self.callback('up', eventtime)

    def down_callback(self, eventtime):
        self.callback('down', eventtime)

    def kill_callback(self, eventtime):
        self.printer.invoke_shutdown("Shutdown due to kill button!")
