# Pin name to pin number definitions
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import re

class error(Exception):
    pass


######################################################################
# Arduino mappings
######################################################################

Arduino_standard = [
    "PD0", "PD1", "PD2", "PD3", "PD4", "PD5", "PD6", "PD7", "PB0", "PB1",
    "PB2", "PB3", "PB4", "PB5", "PC0", "PC1", "PC2", "PC3", "PC4", "PC5",
]
Arduino_analog_standard = [
    "PC0", "PC1", "PC2", "PC3", "PC4", "PC5", "PE0", "PE1",
]

Arduino_mega = [
    "PE0", "PE1", "PE4", "PE5", "PG5", "PE3", "PH3", "PH4", "PH5", "PH6",
    "PB4", "PB5", "PB6", "PB7", "PJ1", "PJ0", "PH1", "PH0", "PD3", "PD2",
    "PD1", "PD0", "PA0", "PA1", "PA2", "PA3", "PA4", "PA5", "PA6", "PA7",
    "PC7", "PC6", "PC5", "PC4", "PC3", "PC2", "PC1", "PC0", "PD7", "PG2",
    "PG1", "PG0", "PL7", "PL6", "PL5", "PL4", "PL3", "PL2", "PL1", "PL0",
    "PB3", "PB2", "PB1", "PB0", "PF0", "PF1", "PF2", "PF3", "PF4", "PF5",
    "PF6", "PF7", "PK0", "PK1", "PK2", "PK3", "PK4", "PK5", "PK6", "PK7",
]
Arduino_analog_mega = [
    "PF0", "PF1", "PF2", "PF3", "PF4", "PF5",
    "PF6", "PF7", "PK0", "PK1", "PK2", "PK3", "PK4", "PK5", "PK6", "PK7",
]

Sanguino = [
    "PB0", "PB1", "PB2", "PB3", "PB4", "PB5", "PB6", "PB7", "PD0", "PD1",
    "PD2", "PD3", "PD4", "PD5", "PD6", "PD7", "PC0", "PC1", "PC2", "PC3",
    "PC4", "PC5", "PC6", "PC7", "PA0", "PA1", "PA2", "PA3", "PA4", "PA5",
    "PA6", "PA7"
]
Sanguino_analog = [
    "PA0", "PA1", "PA2", "PA3", "PA4", "PA5", "PA6", "PA7"
]

Arduino_Due = [
    "PA8", "PA9", "PB25", "PC28", "PA29", "PC25", "PC24", "PC23", "PC22","PC21",
    "PA28", "PD7", "PD8", "PB27", "PD4", "PD5", "PA13", "PA12", "PA11", "PA10",
    "PB12", "PB13", "PB26", "PA14", "PA15", "PD0", "PD1", "PD2", "PD3", "PD6",
    "PD9", "PA7", "PD10", "PC1", "PC2", "PC3", "PC4", "PC5", "PC6", "PC7",
    "PC8", "PC9", "PA19", "PA20", "PC19", "PC18", "PC17", "PC16", "PC15","PC14",
    "PC13", "PC12", "PB21", "PB14", "PA16", "PA24", "PA23", "PA22", "PA6","PA4",
    "PA3", "PA2", "PB17", "PB18", "PB19", "PB20", "PB15", "PB16", "PA1", "PA0",
    "PA17", "PA18", "PC30", "PA21", "PA25", "PA26", "PA27", "PA28", "PB23"
]
Arduino_Due_analog = [
    "PA16", "PA24", "PA23", "PA22", "PA6", "PA4", "PA3", "PA2", "PB17", "PB18",
    "PB19", "PB20"
]

Adafruit_GrandCentral = [
    "PB25", "PB24", "PC18", "PC19", "PC20",
    "PC21", "PD20", "PD21", "PB18", "PB2",
    "PB22", "PB23", "PB0", "PB1", "PB16",
    "PB17", "PC22", "PC23", "PB12", "PB13",
    "PB20", "PB21", "PD12", "PA15", "PC17",
    "PC16", "PA12", "PA13", "PA14", "PB19",
    "PA23", "PA22", "PA21", "PA20", "PA19",
    "PA18", "PA17", "PA16", "PB15", "PB14",
    "PC13", "PC12", "PC15", "PC14", "PC11",
    "PC10", "PC6", "PC7", "PC4", "PC5",
    "PD11", "PD8", "PD9", "PD10", "PA2",
    "PA5", "PB3", "PC0", "PC1", "PC2",
    "PC3", "PB4", "PB5", "PB6", "PB7",
    "PB8", "PB9", "PA4", "PA6", "PA7"
]
Adafruit_GrandCentral_analog = [
    "PA2", "PA5", "PB3", "PC0", "PC1", "PC2", "PC3", "PB4", "PB5", "PB6", "PB7",
    "PB8", "PB9", "PA4", "PA6", "PA7"
]


Arduino_from_mcu = {
    "atmega168": (Arduino_standard, Arduino_analog_standard),
    "atmega328": (Arduino_standard, Arduino_analog_standard),
    "atmega328p": (Arduino_standard, Arduino_analog_standard),
    "atmega644p": (Sanguino, Sanguino_analog),
    "atmega1280": (Arduino_mega, Arduino_analog_mega),
    "atmega2560": (Arduino_mega, Arduino_analog_mega),
    "sam3x8e": (Arduino_Due, Arduino_Due_analog),
    "samd51p20a": (Adafruit_GrandCentral, Adafruit_GrandCentral_analog),
}

def get_aliases_arduino(mcu):
    if mcu not in Arduino_from_mcu:
        raise error("Arduino aliases not supported on mcu '%s'" % (mcu,))
    dpins, apins = Arduino_from_mcu[mcu]
    aliases = {}
    for i in range(len(dpins)):
        aliases['ar' + str(i)] = dpins[i]
    for i in range(len(apins)):
        aliases['analog%d' % (i,)] = apins[i]
    return aliases


######################################################################
# Beaglebone mappings
######################################################################

beagleboneblack_mappings = {
    'P8_3': 'gpio1_6', 'P8_4': 'gpio1_7', 'P8_5': 'gpio1_2',
    'P8_6': 'gpio1_3', 'P8_7': 'gpio2_2', 'P8_8': 'gpio2_3',
    'P8_9': 'gpio2_5', 'P8_10': 'gpio2_4', 'P8_11': 'gpio1_13',
    'P8_12': 'gpio1_12', 'P8_13': 'gpio0_23', 'P8_14': 'gpio0_26',
    'P8_15': 'gpio1_15', 'P8_16': 'gpio1_14', 'P8_17': 'gpio0_27',
    'P8_18': 'gpio2_1', 'P8_19': 'gpio0_22', 'P8_20': 'gpio1_31',
    'P8_21': 'gpio1_30', 'P8_22': 'gpio1_5', 'P8_23': 'gpio1_4',
    'P8_24': 'gpio1_1', 'P8_25': 'gpio1_0', 'P8_26': 'gpio1_29',
    'P8_27': 'gpio2_22', 'P8_28': 'gpio2_24', 'P8_29': 'gpio2_23',
    'P8_30': 'gpio2_25', 'P8_31': 'gpio0_10', 'P8_32': 'gpio0_11',
    'P8_33': 'gpio0_9', 'P8_34': 'gpio2_17', 'P8_35': 'gpio0_8',
    'P8_36': 'gpio2_16', 'P8_37': 'gpio2_14', 'P8_38': 'gpio2_15',
    'P8_39': 'gpio2_12', 'P8_40': 'gpio2_13', 'P8_41': 'gpio2_10',
    'P8_42': 'gpio2_11', 'P8_43': 'gpio2_8', 'P8_44': 'gpio2_9',
    'P8_45': 'gpio2_6', 'P8_46': 'gpio2_7', 'P9_11': 'gpio0_30',
    'P9_12': 'gpio1_28', 'P9_13': 'gpio0_31', 'P9_14': 'gpio1_18',
    'P9_15': 'gpio1_16', 'P9_16': 'gpio1_19', 'P9_17': 'gpio0_5',
    'P9_18': 'gpio0_4', 'P9_19': 'gpio0_13', 'P9_20': 'gpio0_12',
    'P9_21': 'gpio0_3', 'P9_22': 'gpio0_2', 'P9_23': 'gpio1_17',
    'P9_24': 'gpio0_15', 'P9_25': 'gpio3_21', 'P9_26': 'gpio0_14',
    'P9_27': 'gpio3_19', 'P9_28': 'gpio3_17', 'P9_29': 'gpio3_15',
    'P9_30': 'gpio3_16', 'P9_31': 'gpio3_14', 'P9_41': 'gpio0_20',
    'P9_42': 'gpio3_20', 'P9_43': 'gpio0_7', 'P9_44': 'gpio3_18',

    'P9_33': 'AIN4', 'P9_35': 'AIN6', 'P9_36': 'AIN5', 'P9_37': 'AIN2',
    'P9_38': 'AIN3', 'P9_39': 'AIN0', 'P9_40': 'AIN1',
}

def get_aliases_beaglebone(mcu):
    if mcu != 'pru':
        raise error("Beaglebone aliases not supported on mcu '%s'" % (mcu,))
    return beagleboneblack_mappings


######################################################################
# Command translation
######################################################################

re_pin = re.compile(r'(?P<prefix>[ _]pin=)(?P<name>[^ ]*)')

class PinResolver:
    def __init__(self, validate_aliases=True):
        self.validate_aliases = validate_aliases
        self.reserved = {}
        self.aliases = {}
        self.active_pins = {}
    def reserve_pin(self, pin, reserve_name):
        if pin in self.reserved and self.reserved[pin] != reserve_name:
            raise error("Pin %s reserved for %s - can't reserve for %s" % (
                pin, self.reserved[pin], reserve_name))
        self.reserved[pin] = reserve_name
    def alias_pin(self, alias, pin):
        if alias in self.aliases and self.aliases[alias] != pin:
            raise error("Alias %s mapped to %s - can't alias to %s" % (
                alias, self.aliases[alias], pin))
        if pin in self.aliases:
            pin = self.aliases[pin]
        self.aliases[alias] = pin
        for existing_alias, existing_pin in self.aliases.items():
            if existing_pin == alias:
                self.aliases[existing_alias] = pin
    def add_pin_mapping(self, mcu_type, mapping_name):
        if mapping_name == 'arduino':
            pin_mapping = get_aliases_arduino(mcu_type)
        elif mapping_name == 'beaglebone':
            pin_mapping = get_aliases_beaglebone(mcu_type)
        else:
            raise error("Unknown pin alias mapping '%s'" % (mapping_name,))
        for alias, pin in pin_mapping.items():
            self.alias_pin(alias, pin)
    def update_command(self, cmd):
        def pin_fixup(m):
            name = m.group('name')
            pin_id = self.aliases.get(name, name)
            if (name != self.active_pins.setdefault(pin_id, name)
                and self.validate_aliases):
                raise error("pin %s is an alias for %s" % (
                    name, self.active_pins[pin_id]))
            if pin_id in self.reserved:
                raise error("pin %s is reserved for %s" % (
                    name, self.reserved[pin_id]))
            return m.group('prefix') + str(pin_id)
        return re_pin.sub(pin_fixup, cmd)


######################################################################
# Pin to chip mapping
######################################################################

class PrinterPins:
    error = error
    def __init__(self):
        self.chips = {}
        self.active_pins = {}
        self.pin_resolvers = {}
        self.allow_multi_use_pins = {}
    def parse_pin(self, pin_desc, can_invert=False, can_pullup=False):
        desc = pin_desc.strip()
        pullup = invert = 0
        if can_pullup and (desc.startswith('^') or desc.startswith('~')):
            pullup = 1
            if desc.startswith('~'):
                pullup = -1
            desc = desc[1:].strip()
        if can_invert and desc.startswith('!'):
            invert = 1
            desc = desc[1:].strip()
        if ':' not in desc:
            chip_name, pin = 'mcu', desc
        else:
            chip_name, pin = [s.strip() for s in desc.split(':', 1)]
        if chip_name not in self.chips:
            raise error("Unknown pin chip name '%s'" % (chip_name,))
        if [c for c in '^~!: ' if c in pin]:
            format = ""
            if can_pullup:
                format += "[^~] "
            if can_invert:
                format += "[!] "
            raise error("Invalid pin description '%s'\n"
                        "Format is: %s[chip_name:] pin_name" % (
                            pin_desc, format))
        pin_params = {'chip': self.chips[chip_name], 'chip_name': chip_name,
                      'pin': pin, 'invert': invert, 'pullup': pullup}
        return pin_params
    def lookup_pin(self, pin_desc, can_invert=False, can_pullup=False,
                   share_type=None):
        pin_params = self.parse_pin(pin_desc, can_invert, can_pullup)
        pin = pin_params['pin']
        share_name = "%s:%s" % (pin_params['chip_name'], pin)
        if share_name in self.active_pins:
            share_params = self.active_pins[share_name]
            if share_name in self.allow_multi_use_pins:
                pass
            elif share_type is None or share_type != share_params['share_type']:
                raise error("pin %s used multiple times in config" % (pin,))
            elif (pin_params['invert'] != share_params['invert']
                  or pin_params['pullup'] != share_params['pullup']):
                raise error("Shared pin %s must have same polarity" % (pin,))
            return share_params
        pin_params['share_type'] = share_type
        self.active_pins[share_name] = pin_params
        return pin_params
    def setup_pin(self, pin_type, pin_desc, share_type=None):
        can_invert = pin_type in ['endstop', 'digital_out', 'pwm']
        can_pullup = pin_type in ['endstop']
        pin_params = self.lookup_pin(
            pin_desc, can_invert, can_pullup, share_type)
        return pin_params['chip'].setup_pin(pin_type, pin_params)
    def reset_pin_sharing(self, pin_params):
        share_name = "%s:%s" % (pin_params['chip_name'], pin_params['pin'])
        del self.active_pins[share_name]
    def get_pin_resolver(self, chip_name):
        if chip_name not in self.pin_resolvers:
            raise error("Unknown chip name '%s'" % (chip_name,))
        return self.pin_resolvers[chip_name]
    def register_chip(self, chip_name, chip):
        chip_name = chip_name.strip()
        if chip_name in self.chips:
            raise error("Duplicate chip name '%s'" % (chip_name,))
        self.chips[chip_name] = chip
        self.pin_resolvers[chip_name] = PinResolver()
    def allow_multi_use_pin(self, pin_desc):
        pin_params = self.parse_pin(pin_desc)
        share_name = "%s:%s" % (pin_params['chip_name'], pin_params['pin'])
        self.allow_multi_use_pins[share_name] = True

def add_printer_objects(config):
    config.get_printer().add_object('pins', PrinterPins())
