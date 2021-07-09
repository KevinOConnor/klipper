# Endstop accuracy improvement via stepper phase tracking
#
# Copyright (C) 2016-2021  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import math, logging
import stepper

TRINAMIC_DRIVERS = ["tmc2130", "tmc2208", "tmc2209", "tmc2660", "tmc5160"]

# Calculate the trigger phase of a stepper motor
class PhaseCalc:
    def __init__(self, printer, name, phases=None):
        self.printer = printer
        self.name = name
        self.phases = phases
        self.tmc_module = None
        # Statistics tracking for ENDSTOP_PHASE_CALIBRATE
        self.phase_history = self.last_phase = self.last_mcu_position = None
        self.is_primary = self.stats_only = False
    def lookup_tmc(self):
        for driver in TRINAMIC_DRIVERS:
            driver_name = "%s %s" % (driver, self.name)
            module = self.printer.lookup_object(driver_name, None)
            if module is not None:
                self.tmc_module = module
                if self.phases is None:
                    self.phases = module.get_microsteps() * 4
                break
        if self.phases is not None:
            self.phase_history = [0] * self.phases
    def convert_phase(self, driver_phase, driver_phases):
        phases = self.phases
        return (int(float(driver_phase) / driver_phases * phases + .5) % phases)
    def calc_phase(self, stepper, trig_mcu_pos):
        if self.tmc_module is None:
            phase = trig_mcu_pos % self.phases
        else:
            mcu_pos = stepper.get_mcu_position()
            try:
                driver_phase, driver_phases = self.tmc_module.get_phase()
            except Exception as e:
                msg = "Unable to get stepper %s phase: %s" % (self.name, str(e))
                logging.exception(msg)
                raise self.printer.command_error(msg)
            if stepper.is_dir_inverted():
                driver_phase = (driver_phases - 1) - driver_phase
            halt_phase = self.convert_phase(driver_phase, driver_phases)
            phase = (halt_phase + (trig_mcu_pos - mcu_pos)) % self.phases
        self.phase_history[phase] += 1
        self.last_phase = phase
        self.last_mcu_position = trig_mcu_pos
        return phase

# Adjusted endstop trigger positions
class EndstopPhase:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[1]
        # Obtain step_distance and microsteps from stepper config section
        sconfig = config.getsection(self.name)
        self.step_dist = stepper.parse_step_distance(sconfig)
        self.phases = sconfig.getint("microsteps", note_valid=False) * 4
        self.phase_calc = PhaseCalc(self.printer, self.name, self.phases)
        # Register event handlers
        self.printer.register_event_handler("klippy:connect",
                                            self.phase_calc.lookup_tmc)
        self.printer.register_event_handler("homing:home_rails_end",
                                            self.handle_home_rails_end)
        self.printer.load_object(config, "endstop_phase")
        # Read config
        self.endstop_phase = None
        trigger_phase = config.get('trigger_phase', None)
        if trigger_phase is not None:
            try:
                p, ps = [int(v.strip()) for v in trigger_phase.split('/')]
            except:
                raise config.error("Unable to parse trigger_phase '%s'"
                                   % (trigger_phase,))
            if p >= ps:
                raise config.error("Invalid trigger_phase '%s'"
                                   % (trigger_phase,))
            self.endstop_phase = self.phase_calc.convert_phase(p, ps)
        self.endstop_align_zero = config.getboolean('endstop_align_zero', False)
        self.endstop_accuracy = config.getfloat('endstop_accuracy', None,
                                                above=0.)
        # Determine endstop accuracy
        if self.endstop_accuracy is None:
            self.endstop_phase_accuracy = self.phases//2 - 1
        elif self.endstop_phase is not None:
            self.endstop_phase_accuracy = int(
                math.ceil(self.endstop_accuracy * .5 / self.step_dist))
        else:
            self.endstop_phase_accuracy = int(
                math.ceil(self.endstop_accuracy / self.step_dist))
        if self.endstop_phase_accuracy >= self.phases // 2:
            raise config.error("Endstop for %s is not accurate enough for"
                               " stepper phase adjustment" % (self.name,))
        if self.printer.get_start_args().get('debugoutput') is not None:
            self.endstop_phase_accuracy = self.phases
    def align_endstop(self, rail):
        if not self.endstop_align_zero or self.endstop_phase is None:
            return 0.
        # Adjust the endstop position so 0.0 is always at a full step
        microsteps = self.phases // 4
        half_microsteps = microsteps // 2
        phase_offset = (((self.endstop_phase + half_microsteps) % microsteps)
                        - half_microsteps) * self.step_dist
        full_step = microsteps * self.step_dist
        pe = rail.get_homing_info().position_endstop
        return int(pe / full_step + .5) * full_step - pe + phase_offset
    def get_homed_offset(self, stepper, trig_mcu_pos):
        phase = self.phase_calc.calc_phase(stepper, trig_mcu_pos)
        if self.endstop_phase is None:
            logging.info("Setting %s endstop phase to %d", self.name, phase)
            self.endstop_phase = phase
            return 0.
        delta = (phase - self.endstop_phase) % self.phases
        if delta >= self.phases - self.endstop_phase_accuracy:
            delta -= self.phases
        elif delta > self.endstop_phase_accuracy:
            raise self.printer.command_error(
                "Endstop %s incorrect phase (got %d vs %d)" % (
                    self.name, phase, self.endstop_phase))
        return delta * self.step_dist
    def handle_home_rails_end(self, homing_state, rails):
        for rail in rails:
            stepper = rail.get_steppers()[0]
            if stepper.get_name() == self.name:
                trig_mcu_pos = homing_state.get_trigger_position(self.name)
                align = self.align_endstop(rail)
                offset = self.get_homed_offset(stepper, trig_mcu_pos)
                homing_state.set_stepper_adjustment(self.name, align + offset)
                return

# Support for ENDSTOP_PHASE_CALIBRATE command
class EndstopPhases:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.tracking = {}
        # Register handlers
        self.printer.register_event_handler("homing:home_rails_end",
                                            self.handle_home_rails_end)
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command("ENDSTOP_PHASE_CALIBRATE",
                                    self.cmd_ENDSTOP_PHASE_CALIBRATE,
                                    desc=self.cmd_ENDSTOP_PHASE_CALIBRATE_help)
    def update_stepper(self, stepper, trig_mcu_pos, is_primary):
        stepper_name = stepper.get_name()
        phase_calc = self.tracking.get(stepper_name)
        if phase_calc is None:
            # Check if stepper has an endstop_phase config section defined
            mod_name = "endstop_phase %s" % (stepper_name,)
            m = self.printer.lookup_object(mod_name, None)
            if m is not None:
                phase_calc = m.phase_calc
            else:
                # Create new PhaseCalc tracker
                phase_calc = PhaseCalc(self.printer, stepper_name)
                phase_calc.stats_only = True
                phase_calc.lookup_tmc()
            self.tracking[stepper_name] = phase_calc
        if phase_calc.phase_history is None:
            return
        if is_primary:
            phase_calc.is_primary = True
        if phase_calc.stats_only:
            phase_calc.calc_phase(stepper, trig_mcu_pos)
    def handle_home_rails_end(self, homing_state, rails):
        for rail in rails:
            is_primary = True
            for stepper in rail.get_steppers():
                sname = stepper.get_name()
                trig_mcu_pos = homing_state.get_trigger_position(sname)
                self.update_stepper(stepper, trig_mcu_pos, is_primary)
                is_primary = False
    cmd_ENDSTOP_PHASE_CALIBRATE_help = "Calibrate stepper phase"
    def cmd_ENDSTOP_PHASE_CALIBRATE(self, gcmd):
        stepper_name = gcmd.get('STEPPER', None)
        if stepper_name is None:
            self.report_stats()
            return
        phase_calc = self.tracking.get(stepper_name)
        if phase_calc is None or phase_calc.phase_history is None:
            raise gcmd.error("Stats not available for stepper %s"
                             % (stepper_name,))
        endstop_phase, phases = self.generate_stats(stepper_name, phase_calc)
        if not phase_calc.is_primary:
            return
        configfile = self.printer.lookup_object('configfile')
        section = 'endstop_phase %s' % (stepper_name,)
        configfile.remove_section(section)
        configfile.set(section, "trigger_phase",
                       "%s/%s" % (endstop_phase, phases))
        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file with these parameters and restart the printer.")
    def generate_stats(self, stepper_name, phase_calc):
        phase_history = phase_calc.phase_history
        wph = phase_history + phase_history
        count = sum(phase_history)
        phases = len(phase_history)
        half_phases = phases // 2
        res = []
        for i in range(phases):
            phase = i + half_phases
            cost = sum([wph[j] * abs(j-phase) for j in range(i, i+phases)])
            res.append((cost, phase))
        res.sort()
        best = res[0][1]
        found = [j for j in range(best - half_phases, best + half_phases)
                 if wph[j]]
        best_phase = best % phases
        lo, hi = found[0] % phases, found[-1] % phases
        self.gcode.respond_info("%s: trigger_phase=%d/%d (range %d to %d)"
                                % (stepper_name, best_phase, phases, lo, hi))
        return best_phase, phases
    def report_stats(self):
        if not self.tracking:
            self.gcode.respond_info(
                "No steppers found. (Be sure to home at least once.)")
            return
        for stepper_name in sorted(self.tracking.keys()):
            phase_calc = self.tracking[stepper_name]
            if phase_calc is None or not phase_calc.is_primary:
                continue
            self.generate_stats(stepper_name, phase_calc)
    def get_status(self, eventtime):
        lh = { name: {'phase': pc.last_phase, 'phases': pc.phases,
                      'mcu_position': pc.last_mcu_position}
               for name, pc in self.tracking.items()
               if pc.phase_history is not None }
        return { 'last_home': lh }

def load_config_prefix(config):
    return EndstopPhase(config)

def load_config(config):
    return EndstopPhases(config)
