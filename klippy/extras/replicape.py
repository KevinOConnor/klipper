# Code to configure miscellaneous chips
#
# Copyright (C) 2017-2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, os
import pins, mcu
from . import bus

REPLICAPE_MAX_CURRENT = 3.84
REPLICAPE_PCA9685_BUS = 2
REPLICAPE_PCA9685_ADDRESS = 0x70
REPLICAPE_PCA9685_CYCLE_TIME = .001
PIN_MIN_TIME = 0.100

class pca9685_pwm:
    def __init__(self, replicape, channel, pin_type, pin_params):
        self._replicape = replicape
        self._channel = channel
        if pin_type not in ['digital_out', 'pwm']:
            raise pins.error("Pin type not supported on replicape")
        self._mcu = replicape.host_mcu
        self._mcu.register_config_callback(self._build_config)
        self._bus = REPLICAPE_PCA9685_BUS
        self._address = REPLICAPE_PCA9685_ADDRESS
        self._cycle_time = REPLICAPE_PCA9685_CYCLE_TIME
        self._max_duration = 2.
        self._oid = None
        self._invert = pin_params['invert']
        self._start_value = self._shutdown_value = float(self._invert)
        self._is_static = False
        self._last_clock = 0
        self._pwm_max = 0.
        self._set_cmd = None
    def get_mcu(self):
        return self._mcu
    def setup_max_duration(self, max_duration):
        self._max_duration = max_duration
    def setup_cycle_time(self, cycle_time, hardware_pwm=False):
        if hardware_pwm:
            raise pins.error("pca9685 does not support hardware_pwm parameter")
        if cycle_time != self._cycle_time:
            logging.info("Ignoring pca9685 cycle time of %.6f (using %.6f)",
                         cycle_time, self._cycle_time)
    def setup_start_value(self, start_value, shutdown_value, is_static=False):
        if is_static and start_value != shutdown_value:
            raise pins.error("Static pin can not have shutdown value")
        if self._invert:
            start_value = 1. - start_value
            shutdown_value = 1. - shutdown_value
        self._start_value = max(0., min(1., start_value))
        self._shutdown_value = max(0., min(1., shutdown_value))
        self._is_static = is_static
        self._replicape.note_pwm_start_value(
            self._channel, self._start_value, self._shutdown_value)
    def _build_config(self):
        self._pwm_max = self._mcu.get_constant_float("PCA9685_MAX")
        cycle_ticks = self._mcu.seconds_to_clock(self._cycle_time)
        if self._is_static:
            self._mcu.add_config_cmd(
                "set_pca9685_out bus=%d addr=%d channel=%d"
                " cycle_ticks=%d value=%d" % (
                    self._bus, self._address, self._channel,
                    cycle_ticks, self._start_value * self._pwm_max))
            return
        self._mcu.request_move_queue_slot()
        self._oid = self._mcu.create_oid()
        self._mcu.add_config_cmd(
            "config_pca9685 oid=%d bus=%d addr=%d channel=%d cycle_ticks=%d"
            " value=%d default_value=%d max_duration=%d" % (
                self._oid, self._bus, self._address, self._channel, cycle_ticks,
                self._start_value * self._pwm_max,
                self._shutdown_value * self._pwm_max,
                self._mcu.seconds_to_clock(self._max_duration)))
        cmd_queue = self._mcu.alloc_command_queue()
        self._set_cmd = self._mcu.lookup_command(
            "queue_pca9685_out oid=%c clock=%u value=%hu", cq=cmd_queue)
    def set_pwm(self, print_time, value, cycle_time=None):
        clock = self._mcu.print_time_to_clock(print_time)
        if self._invert:
            value = 1. - value
        value = int(max(0., min(1., value)) * self._pwm_max + 0.5)
        self._replicape.note_pwm_enable(print_time, self._channel, value)
        self._set_cmd.send([self._oid, clock, value],
                           minclock=self._last_clock, reqclock=clock)
        self._last_clock = clock
    def set_digital(self, print_time, value):
        if value:
            self.set_pwm(print_time, 1.)
        else:
            self.set_pwm(print_time, 0.)

class ReplicapeDACEnable:
    def __init__(self, replicape, channel, pin_type, pin_params):
        if pin_type != 'digital_out':
            raise pins.error("Replicape virtual enable pin must be digital_out")
        if pin_params['invert']:
            raise pins.error("Replicape virtual enable pin can not be inverted")
        self.mcu = replicape.host_mcu
        self.value = replicape.stepper_dacs[channel]
        self.pwm = pca9685_pwm(replicape, channel, pin_type, pin_params)
    def get_mcu(self):
        return self.mcu
    def setup_max_duration(self, max_duration):
        self.pwm.setup_max_duration(max_duration)
    def set_digital(self, print_time, value):
        if value:
            self.pwm.set_pwm(print_time, self.value)
        else:
            self.pwm.set_pwm(print_time, 0.)

SERVO_PINS = {
    "servo0": ("/pwm0", "gpio0_30", "gpio1_18"), # P9_11, P9_14
    "servo1": ("/pwm1", "gpio3_17", "gpio1_19"), # P9_28, P9_16
}

class servo_pwm:
    def __init__(self, replicape, pin_params):
        config_name = pin_params['pin']
        pwmchip = 'pwmchip0'
        if not replicape.host_mcu.is_fileoutput():
            try:
                # Determine the pwmchip number for the servo channels
                # /sys/devices/platform/ocp/48302000.epwmss/48302200.pwm/pwm
                # should be stable on the beagle bone black.
                # It contains only a "pwmchipX" directory. The entry in
                # /sys/class/pwm/ used by the Linux MCU should be a symlink
                # to this directory.
                pwmdev = os.listdir(
                '/sys/devices/platform/ocp/48302000.epwmss/48302200.pwm/pwm/')
                pwmchip = [pc for pc in pwmdev if pc.startswith('pwmchip')][0]
            except:
                raise pins.error("Replicape unable to determine pwmchip")
        pwm_pin, resv1, resv2 = SERVO_PINS[config_name]
        pin_params = dict(pin_params)
        pin_params['pin'] = pwmchip + pwm_pin
        # Setup actual pwm pin using linux hardware pwm on host
        self.mcu_pwm = replicape.host_mcu.setup_pin("pwm", pin_params)
        self.get_mcu = self.mcu_pwm.get_mcu
        self.setup_max_duration = self.mcu_pwm.setup_max_duration
        self.setup_start_value = self.mcu_pwm.setup_start_value
        self.set_pwm = self.mcu_pwm.set_pwm
        # Reserve pins to warn user of conflicts
        pru_mcu = replicape.mcu_pwm_enable.get_mcu()
        printer = pru_mcu.get_printer()
        ppins = printer.lookup_object('pins')
        pin_resolver = ppins.get_pin_resolver(pru_mcu.get_name())
        pin_resolver.reserve_pin(resv1, config_name)
        pin_resolver.reserve_pin(resv2, config_name)
    def setup_cycle_time(self, cycle_time, hardware_pwm=False):
        self.mcu_pwm.setup_cycle_time(cycle_time, True);

ReplicapeStepConfig = {
    'disable': None,
    '1': (1<<7)|(1<<5), '2': (1<<7)|(1<<5)|(1<<6), 'spread2': (1<<5),
    '4': (1<<7)|(1<<5)|(1<<4), '16': (1<<7)|(1<<5)|(1<<6)|(1<<4),
    'spread4': (1<<5)|(1<<4), 'spread16': (1<<7), 'stealth4': (1<<7)|(1<<6),
    'stealth16': 0
}

class Replicape:
    def __init__(self, config):
        printer = config.get_printer()
        ppins = printer.lookup_object('pins')
        ppins.register_chip('replicape', self)
        revisions = {'B3': 'B3'}
        config.getchoice('revision', revisions)
        self.host_mcu = mcu.get_printer_mcu(printer, config.get('host_mcu'))
        # Setup enable pin
        enable_pin = config.get('enable_pin', '!gpio0_20')
        self.mcu_pwm_enable = ppins.setup_pin('digital_out', enable_pin)
        self.mcu_pwm_enable.setup_max_duration(0.)
        self.mcu_pwm_start_value = self.mcu_pwm_shutdown_value = False
        # Setup power pins
        self.pins = {
            "power_e": (pca9685_pwm, 5), "power_h": (pca9685_pwm, 3),
            "power_hotbed": (pca9685_pwm, 4),
            "power_fan0": (pca9685_pwm, 7), "power_fan1": (pca9685_pwm, 8),
            "power_fan2": (pca9685_pwm, 9), "power_fan3": (pca9685_pwm, 10) }
        self.servo_pins = {
            "servo0": 3, "servo1": 2 }
        # Setup stepper config
        self.last_stepper_time = 0.
        self.stepper_dacs = {}
        shift_registers = [1, 0, 0, 1, 1]
        for port, name in enumerate('xyzeh'):
            prefix = 'stepper_%s_' % (name,)
            sc = config.getchoice(
                prefix + 'microstep_mode', ReplicapeStepConfig, 'disable')
            if sc is None:
                continue
            sc |= shift_registers[port]
            if config.getboolean(prefix + 'chopper_off_time_high', False):
                sc |= 1<<3
            if config.getboolean(prefix + 'chopper_hysteresis_high', False):
                sc |= 1<<2
            if config.getboolean(prefix + 'chopper_blank_time_high', True):
                sc |= 1<<1
            shift_registers[port] = sc
            channel = port + 11
            cur = config.getfloat(
                prefix + 'current', above=0., maxval=REPLICAPE_MAX_CURRENT)
            self.stepper_dacs[channel] = cur / REPLICAPE_MAX_CURRENT
            self.pins[prefix + 'enable'] = (ReplicapeDACEnable, channel)
        self.enabled_channels = {ch: False for cl, ch in self.pins.values()}
        self.sr_disabled = list(reversed(shift_registers))
        if [i for i in [0, 1, 2] if 11+i in self.stepper_dacs]:
            # Enable xyz steppers
            shift_registers[0] &= ~1
        if [i for i in [3, 4] if 11+i in self.stepper_dacs]:
            # Enable eh steppers
            shift_registers[3] &= ~1
        if (config.getboolean('standstill_power_down', False)
            and self.stepper_dacs):
            shift_registers[4] &= ~1
        self.sr_enabled = list(reversed(shift_registers))
        sr_spi_bus = "spidev1.1"
        if not self.host_mcu.is_fileoutput() and os.path.exists(
                '/sys/devices/platform/ocp/481a0000.spi/spi_master/spi2'):
            sr_spi_bus = "spidev2.1"
        self.sr_spi = bus.MCU_SPI(self.host_mcu, sr_spi_bus, None, 0, 50000000)
        self.sr_spi.setup_shutdown_msg(self.sr_disabled)
        self.sr_spi.spi_send(self.sr_disabled)
    def note_pwm_start_value(self, channel, start_value, shutdown_value):
        self.mcu_pwm_start_value |= not not start_value
        self.mcu_pwm_shutdown_value |= not not shutdown_value
        self.mcu_pwm_enable.setup_start_value(
            self.mcu_pwm_start_value, self.mcu_pwm_shutdown_value)
        self.enabled_channels[channel] = not not start_value
    def note_pwm_enable(self, print_time, channel, value):
        is_enable = not not value
        if self.enabled_channels[channel] == is_enable:
            # Nothing to do
            return
        self.enabled_channels[channel] = is_enable
        # Check if need to set the pca9685 enable pin
        on_channels = [1 for c, e in self.enabled_channels.items() if e]
        if not on_channels:
            self.mcu_pwm_enable.set_digital(print_time, 0)
        elif is_enable and len(on_channels) == 1:
            self.mcu_pwm_enable.set_digital(print_time, 1)
        # Check if need to set the stepper enable lines
        if channel not in self.stepper_dacs:
            return
        on_dacs = [1 for c in self.stepper_dacs.keys()
                   if self.enabled_channels[c]]
        if not on_dacs:
            sr = self.sr_disabled
        elif is_enable and len(on_dacs) == 1:
            sr = self.sr_enabled
        else:
            return
        print_time = max(print_time, self.last_stepper_time + PIN_MIN_TIME)
        clock = self.host_mcu.print_time_to_clock(print_time)
        self.sr_spi.spi_send(sr, minclock=clock, reqclock=clock)
    def setup_pin(self, pin_type, pin_params):
        pin = pin_params['pin']
        if pin in self.pins:
            pclass, channel = self.pins[pin]
            return pclass(self, channel, pin_type, pin_params)
        elif pin in self.servo_pins:
            # enable servo pins via shift registers
            index = self.servo_pins[pin]
            self.sr_enabled[index] |= 1
            self.sr_disabled[index] |= 1
            self.sr_spi.spi_send(self.sr_disabled)
            return servo_pwm(self, pin_params)
        raise pins.error("Unknown replicape pin %s" % (pin,))

def load_config(config):
    return Replicape(config)
