This document is a reference of printer status information available
in Klipper [macros](Command_Templates.md),
[display fields](Config_Reference.md#display), and via the
[API Server](API_Server.md).

The fields in this document are subject to change - if using an
attribute be sure to review the
[Config Changes document](Config_Changes.md) when upgrading the
Klipper software.

# bed_mesh

The following information is available in the
[bed_mesh](Config_Reference.md#bed_mesh) object:
- `profile_name`, `mesh_min`, `mesh_max`, `probed_matrix`,
  `mesh_matrix`: Information on the currently active bed_mesh.

# configfile

The following information is available in the `configfile` object
(this object is always available):
- `settings.<section>.<option>`: Returns the given config file setting
  (or default value) during the last software start or restart. (Any
  settings changed at run-time will not be reflected here.)
- `config.<section>.<option>`: Returns the given raw config file
  setting as read by Klipper during the last software start or
  restart. (Any settings changed at run-time will not be reflected
  here.) All values are returned as strings.

# display_status

The following information is available in the `display_status` object
(this object is automatically available if a
[display](Config_Reference.md#display) config section is defined):
- `progress`: The progress value of the last `M73` G-Code command (or
  `virtual_sdcard.progress` if no recent `M73` received).
- `message`: The message contained in the last `M117` G-Code command.

# endstop_phase

The following information is available in the
[endstop_phase](Config_Reference.md#endstop_phase) object:
- `last_home.<stepper name>.phase`: The phase of the stepper motor at
  the end of the last home attempt.
- `last_home.<stepper name>.phases`: The total number of phases
  available on the stepper motor.
- `last_home.<stepper name>.mcu_position`: The position (as tracked by
  the micro-controller) of the stepper motor at the end of the last
  home attempt. The position is the total number of steps taken in a
  forward direction minus the total number of steps taken in the
  reverse direction since the micro-controller was last restarted.

# fan

The following information is available in
[fan](Config_Reference.md#fan),
[heater_fan some_name](Config_Reference.md#heater_fan) and
[controller_fan some_name](Config_Reference.md#controller_fan)
objects:
- `speed`: The fan speed as a float between 0.0 and 1.0.
- `rpm`: The measured fan speed in rotations per minute if the fan has
  a tachometer_pin defined.

# filament_switch_sensor

The following information is available in
[filament_switch_sensor some_name](Config_Reference.md#filament_switch_sensor)
objects:
- `enabled`: Returns True if the switch sensor is currently enabled.
- `filament_detected`: Returns True if the sensor is in a triggered
  state.

# filament_motion_sensor

The following information is available in
[filament_motion_sensor some_name](Config_Reference.md#filament_motion_sensor)
objects:
- `enabled`: Returns True if the motion sensor is currently enabled.
- `filament_detected`: Returns True if the sensor is in a triggered
  state.

# firmware_retraction

The following information is available in the
[firmware_retraction](Config_Reference.md#firmware_retraction) object:
- `retract_length`, `retract_speed`, `unretract_extra_length`,
  `unretract_speed`: The current settings for the firmware_retraction
  module. These settings may differ from the config file if a
  `SET_RETRACTION` command alters them.

# gcode_macro

The following information is available in
[gcode_macro some_name](Config_Reference.md#gcode_macro) objects:
- `<variable>`: The current value of a
  [gcode_macro variable](Command_Templates.md#variables).

# gcode_move

The following information is available in the `gcode_move` object
(this object is always available):
- `gcode_position`: The current position of the toolhead relative to
  the current G-Code origin. That is, positions that one might
  directly send to a `G1` command. It is possible to access the x, y,
  z, and e components of this position (eg, `gcode_position.x`).
- `position`: The last commanded position of the toolhead using the
  coordinate system specified in the config file. It is possible to
  access the x, y, z, and e components of this position (eg,
  `position.x`).
- `homing_origin`: The origin of the gcode coordinate system (relative
  to the coordinate system specified in the config file) to use after
  a `G28` command. The `SET_GCODE_OFFSET` command can alter this
  position. It is possible to access the x, y, and z components of
  this position (eg, `homing_origin.x`).
- `speed`: The last speed set in a `G1` command (in mm/s).
- `speed_factor`: The "speed factor override" as set by an `M220`
  command. This is a floating point value such that 1.0 means no
  override and, for example, 2.0 would double requested speed.
- `extrude_factor`: The "extrude factor override" as set by an `M221`
  command. This is a floating point value such that 1.0 means no
  override and, for example, 2.0 would double requested extrusions.
- `absolute_coordinates`: This returns True if in `G90` absolute
  coordinate mode or False if in `G91` relative mode.
- `absolute_extrude`: This returns True if in `M82` absolute extrude
  mode or False if in `M83` relative mode.

# hall_filament_width_sensor

The following information is available in the
[hall_filament_width_sensor](Config_Reference.md#hall_filament_width_sensor)
object:
- `is_active`: Returns True if the sensor is currently active.
- `Diameter`, `Raw`: The last read values from the sensor.

# heater

The following information is available for heater objects such as
[extruder](Config_Reference.md#extruder),
[heater_bed](Config_Reference.md#heater_bed), and
[heater_generic](Config_Reference.md#heater_generic):
- `temperature`: The last reported temperature (in Celsius as a float)
  for the given heater.
- `target`: The current target temperature (in Celsius as a float) for
  the given heater.
- `power`: The last setting of the PWM pin (a value between 0.0 and
  1.0) associated with the heater.
- `can_extrude`: If extruder can extrude (defined by `min_extrude_temp`),
  available only for [extruder](Config_Reference.md#extruder)

# heaters

The following information is available in the `heaters` object (this
object is available if any heater is defined):
- `available_heaters`: Returns a list of all currently available
  heaters by their full config section names, e.g. `["extruder",
  "heater_bed", "heater_generic my_custom_heater"]`.
- `available_sensors`: Returns a list of all currently available
  temperature sensors by their full config section names,
  e.g. `["extruder", "heater_bed", "heater_generic my_custom_heater",
  "temperature_sensor electronics_temp"]`.

# idle_timeout

The following information is available in the
[idle_timeout](Config_Reference.md#idle_timeout) object (this object
is always available):
- `state`: The current state of the printer as tracked by the
  idle_timeout module. It is one of the following strings: "Idle",
  "Printing", "Ready".
- `printing_time`: The amount of time (in seconds) the printer has
  been in the "Printing" state (as tracked by the idle_timeout
  module).

# mcu

The following information is available in
[mcu](Config_Reference.md#mcu) and
[mcu some_name](Config_Reference.md#mcu-my_extra_mcu) objects:
- `mcu_version`: The Klipper code version reported by the
  micro-controller.
- `mcu_build_versions`: Information on the build tools used to
  generate the micro-controller code (as reported by the
  micro-controller).
- `mcu_constants.<constant_name>`: Compile time constants reported by
  the micro-controller. The available constants may differ between
  micro-controller architectures and with each code revision.
- `last_stats.<statistics_name>`: Statistics information on the
  micro-controller connection.

# output_pin

The following information is available in
[output_pin some_name](Config_Reference.md#output_pin) objects:
- `value`: The "value" of the pin, as set by a `SET_PIN` command.

# palette2

The following information is available in the
[palette2](Config_Reference.md#palette2) object:
- `ping`: Amount of the last reported Palette 2 ping in percent.
- `remaining_load_length`: When starting a Palette 2 print, this will
  be the amount of filament to load into the extruder.
- `is_splicing`: True when the Palette 2 is splicing filament.

# pause_resume

The following information is available in the
[pause_resume](Config_Reference.md#pause_resume) object:
- `is_paused`: Returns true if a PAUSE command has been executed
  without a corresponding RESUME.

# print_stats

The following information is available in the `print_stats` object
(this object is automatically available if a
[virtual_sdcard](Config_Reference.md#virtual_sdcard) config section is
defined):
- `filename`, `total_duration`, `print_duration`, `filament_used`,
  `state`, `message`: Estimated information about the current print
  when a virtual_sdcard print is active.

# probe

The following information is available in the
[probe](Config_Reference.md#probe) object (this object is also
available if a [bltouch](Config_Reference.md#bltouch) config section
is defined):
- `last_query`: Returns True if the probe was reported as "triggered"
  during the last QUERY_PROBE command. Note, if this is used in a
  macro, due to the order of template expansion, the QUERY_PROBE
  command must be run prior to the macro containing this reference.
- `last_z_result`: Returns the Z result value of the last PROBE
  command. Note, if this is used in a macro, due to the order of
  template expansion, the PROBE (or similar) command must be run prior
  to the macro containing this reference.

# quad_gantry_level

The following information is available in the `quad_gantry_level` object
(this object is available if quad_gantry_level is defined):
- `applied`: True if the gantry leveling process has been run and completed
  successfully.

# query_endstops

The following information is available in the `query_endstops` object
(this object is available if any endstop is defined):
- `last_query["<endstop>"]`: Returns True if the given endstop was
  reported as "triggered" during the last QUERY_ENDSTOP command. Note,
  if this is used in a macro, due to the order of template expansion,
  the QUERY_ENDSTOP command must be run prior to the macro containing
  this reference.

# servo

The following information is available in
[servo some_name](Config_Reference.md#servo) objects:
- `printer["servo <config_name>"].value`: The last setting of the PWM
  pin (a value between 0.0 and 1.0) associated with the servo.

# system_stats

The following information is available in the `system_stats` object
(this object is always available):
- `sysload`, `cputime`, `memavail`: Information on the host operating
  system and process load.

# temperature sensors

The following information is available in

[bme280 config_section_name](Config_Reference.md#bmp280bme280bme680-temperature-sensor),
[htu21d config_section_name](Config_Reference.md#htu21d-sensor),
[lm75 config_section_name](Config_Reference.md#lm75-temperature-sensor),
and
[temperature_host config_section_name](Config_Reference.md#host-temperature-sensor)
objects:
- `temperature`: The last read temperature from the sensor.
- `humidity`, `pressure`, `gas`: The last read values from the sensor
  (only on bme280, htu21d, and lm75 sensors).

# temperature_fan

The following information is available in
[temperature_fan some_name](Config_Reference.md#temperature_fan)
objects:
- `temperature`: The last read temperature from the sensor.
- `target`: The target temperature for the fan.

# temperature_sensor

The following information is available in
[temperature_sensor some_name](Config_Reference.md#temperature_sensor)
objects:
- `temperature`: The last read temperature from the sensor.
- `measured_min_temp`, `measured_max_temp`: The lowest and highest
  temperature seen by the sensor since the Klipper host software was
  last restarted.

# toolhead

The following information is available in the `toolhead` object
(this object is always available):
- `position`: The last commanded position of the toolhead relative to
  the coordinate system specified in the config file. It is possible
  to access the x, y, z, and e components of this position (eg,
  `position.x`).
- `extruder`: The name of the currently active extruder. For example,
  in a macro one could use `printer[printer.toolhead.extruder].target`
  to get the target temperature of the current extruder.
- `homed_axes`: The current cartesian axes considered to be in a
  "homed" state. This is a string containing one or more of "x", "y",
  "z".
- `axis_minimum`, `axis_maximum`: The axis travel limits (mm) after
  homing.  It is possible to access the x, y, z components of this
  limit value (eg, `axis_minimum.x`, `axis_maximum.z`).
- `max_velocity`, `max_accel`, `max_accel_to_decel`,
  `square_corner_velocity`: The current printing limits that are in
  effect. This may differ from the config file settings if a
  `SET_VELOCITY_LIMIT` (or `M204`) command alters them at run-time.
- `stalls`: The total number of times (since the last restart) that
  the printer had to be paused because the toolhead moved faster than
  moves could be read from the G-Code input.

# dual_carriage

The following information is available in
[dual_carriage](Config_Reference.md#dual_carriage)
on a hybrid_corexy or hybrid_corexz robot
- `mode`: The current mode. Possible values are: "FULL_CONTROL", "DUPLICATION",
  "MIRRORED"
- `active_carriage`: The current active carriage.
Possible values are: "CARRIAGE_0", "CARRIAGE_1", "BOTH"

# virtual_sdcard

The following information is available in the
[virtual_sdcard](Config_Reference.md#virtual_sdcard) object:
- `is_active`: Returns True if a print from file is currently active.
- `progress`: An estimate of the current print progress (based of file
  size and file position).
- `file_path`: A full path to the file of currently loaded file.
- `file_position`: The current position (in bytes) of an active print.
- `file_size`: The file size (in bytes) of currently loaded file.

# webhooks

The following information is available in the `webhooks` object (this
object is always available):
- `state`: Returns a string indicating the current Klipper
  state. Possible values are: "ready", "startup", "shutdown", "error".
- `state_message`: A human readable string giving additional context
  on the current Klipper state.

# z_tilt

The following information is available in the `z_tilt` object (this
object is available if z_tilt is defined):
- `applied`: True if the z-tilt leveling process has been run and completed
  successfully.

# neopixel / dotstar
The following information is available for each `[neopixel led_name]` and
`[dotstar led_name]` defined in printer.cfg:
- `color_data`:  An array of objects, with each object containing the RGBW
  values for a led in the chain.  Note that not all configurations will contain
  a white value.  Each value is represented as a float from 0 to 1.  For
  example, the blue value of the second neopixel in a chain could be accessed
  at `printer["neopixel <config_name>"].colordata[1].B`.
