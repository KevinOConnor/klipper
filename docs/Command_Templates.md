This document provides information on implementing G-Code command
sequences in gcode_macro (and similar) config sections.

### G-Code Macro Naming

Case is not important for the G-Code macro name - MY_MACRO and
my_macro will evaluate the same and may be called in either upper or
lower case. If any numbers are used in the macro name then they must
all be at the end of the name (eg, TEST_MACRO25 is valid, but
MACRO25_TEST3 is not).

### Formatting of G-Code in the config

Indentation is important when defining a macro in the config file. To
specify a multi-line G-Code sequence it is important for each line to
have proper indentation. For example:

```
[gcode_macro blink_led]
gcode:
  SET_PIN PIN=my_led VALUE=1
  G4 P2000
  SET_PIN PIN=my_led VALUE=0
```

Note how the `gcode:` config option always starts at the beginning of
the line and subsequent lines in the G-Code macro never start at the
beginning.

### Save/Restore state for G-Code moves

Unfortunately, the G-Code command language can be challenging to use.
The standard mechanism to move the toolhead is via the `G1` command
(the `G0` command is an alias for `G1` and it can be used
interchangeably with it). However, this command relies on the "G-Code
parsing state" setup by `M82`, `M83`, `G90`, `G91`, `G92`, and
previous `G1` commands.  When creating a G-Code macro it is a good
idea to always explicitly set the G-Code parsing state prior to
issuing a `G1` command. (Otherwise, there is a risk the `G1` command
will make an undesirable request.)

A common way to accomplish that is to wrap the `G1` moves in
`SAVE_GCODE_STATE`, `G91`, and `RESTORE_GCODE_STATE`. For example:

```
[gcode_macro MOVE_UP]
gcode:
  SAVE_GCODE_STATE NAME=my_move_up_state
  G91
  G1 Z10 F300
  RESTORE_GCODE_STATE NAME=my_move_up_state
```

The `G91` command places the G-Code parsing state into "relative move
mode" and the `RESTORE_GCODE_STATE` command restores the state to what
it was prior to entering the macro. Be sure to specify an explicit
speed (via the `F` parameter) on the first `G1` command.

### Template expansion
<!-- {% raw %} -->

The gcode_macro `gcode:` config section is evaluated using the Jinja2
template language. One can evaluate expressions at run-time by
wrapping them in `{ }` characters or use conditional statements
wrapped in `{% %}`. See the
[Jinja2 documentation](http://jinja.pocoo.org/docs/2.10/templates/)
for further information on the syntax.

This is most often used to inspect parameters passed to the macro when
it is called. These parameters are available via the `params`
pseudo-variable. For example, if the macro:

```
[gcode_macro SET_PERCENT]
gcode:
  M117 Now at { params.VALUE|float * 100 }%
```

were invoked as `SET_PERCENT VALUE=.2` it would evaluate to `M117 Now
at 20%`. Note that parameter names are always in upper-case when
evaluated in the macro and are always passed as strings. If performing
math then they must be explicitly converted to integers or floats.

An example of a complex macro:
```
[gcode_macro clean_nozzle]
gcode:
  SAVE_GCODE_STATE NAME=clean_nozzle_state
  G90
  G0 Z15 F300
  {% for wipe in range(8) %}
    {% for coordinate in [(275,4),(235,4)] %}
      G0 X{coordinate[0]} Y{coordinate[1] + 0.25 * wipe} Z9.7 F12000
    {% endfor %}
  {% endfor %}
  RESTORE_GCODE_STATE NAME=clean_nozzle_state
```
<!-- {% endraw %} -->

#### The "printer" Variable

It is possible to inspect (and alter) the current state of the printer
via the `printer` pseudo-variable. For example:

```
[gcode_macro slow_fan]
gcode:
  M106 S{ printer.fan.speed * 0.9 * 255}
```

Important! Macros are first evaluated in entirety and only then are
the resulting commands executed. If a macro issues a command that
alters the state of the printer, the results of that state change will
not be visible during the evaluation of the macro. This can also
result in subtle behavior when a macro generates commands that call
other macros, as the called macro is evaluated when it is invoked
(which is after the entire evaluation of the calling macro).

By convention, the name immediately following `printer` is the name of
a config section. So, for example, `printer.fan` refers to the fan
object created by the `[fan]` config section. There are some
exceptions to this rule - notably the `gcode_move` and `toolhead`
objects. If the config section contains spaces in it, then one can
access it via the `[ ]` accessor - for example:
`printer["generic_heater my_chamber_heater"].temperature`.

The following are common printer attributes:
- `printer.fan.speed`: The fan speed as a float between 0.0 and 1.0.
  This is also available on "heater_fan", "fan_generic", and
  "controller_fan" config sections (eg,
  `printer["fan_generic my_fan"].speed`).
- `printer.fan.rpm`: The measured fan speed in rotations per minute if
  the fan has a tachometer_pin defined.  This is also available on
  "heater_fan", "fan_generic", and "controller_fan" config sections
  (eg, `printer["fan_generic my_fan"].rpm`).
- `printer.gcode_move.gcode_position`: The current position of the
  toolhead relative to the current G-Code origin. That is, positions
  that one might directly send to a `G1` command. It is possible to
  access the x, y, z, and e components of this position (eg,
  `printer.gcode_move.gcode_position.x`).
- `printer.gcode_move.position`: The last commanded position of the
  toolhead using the coordinate system specified in the config
  file. It is possible to access the x, y, z, and e components of this
  position (eg, `printer.gcode_move.position.x`).
- `printer.gcode_move.homing_origin`: The origin of the gcode
  coordinate system (relative to the coordinate system specified in
  the config file) to use after a `G28` command. The
  `SET_GCODE_OFFSET` command can alter this position. It is possible
  to access the x, y, and z components of this position (eg,
  `printer.gcode_move.homing_origin.x`).
- `printer.gcode_move.speed`: The last speed set in a `G1` command (in
  mm/s).
- `printer.gcode_move.speed_factor`: The "speed factor override" as
  set by an `M220` command. This is a floating point value such
  that 1.0 means no override and, for example, 2.0 would double
  requested speed.
- `printer.gcode_move.extrude_factor`: The "extrude factor override"
  as set by an `M221` command. This is a floating point value such
  that 1.0 means no override and, for example, 2.0 would double
  requested extrusions.
- `printer.gcode_move.absolute_coordinates`: This returns True if in
  `G90` absolute coordinate mode or False if in `G91` relative mode.
- `printer.gcode_move.absolute_extrude`: This returns True if in `M82`
  absolute extrude mode or False if in `M83` relative mode.
- `printer["gcode_macro <macro_name>"].<variable>`: The current value
  of a gcode_macro variable.
- `printer.<heater>.temperature`: The last reported temperature (in
  Celsius as a float) for the given heater. Example heaters are:
  `extruder`, `extruder1`, `heater_bed`, `heater_generic
  <config_name>`.
- `printer.<heater>.target`: The current target temperature (in
  Celsius as a float) for the given heater.
- `printer.<heater>.power`: The last setting of the PWM pin (a value
  between 0.0 and 1.0) associated with the heater.
- `printer.idle_timeout.state`: The current state of the printer as
  tracked by the idle_timeout module. It is one of the following
  strings: "Idle", "Printing", "Ready".
- `printer.idle_timeout.printing_time`: The amount of time (in
  seconds) the printer has been in the "Printing" state (as tracked by
  the idle_timeout module).
- `printer.pause_resume.is_paused`: Returns true if a PAUSE command
  has been executed without a corresponding RESUME.
- `printer.toolhead.position`: The last commanded position of the
  toolhead relative to the coordinate system specified in the config
  file. It is possible to access the x, y, z, and e components of this
  position (eg, `printer.toolhead.position.x`).
- `printer.toolhead.extruder`: The name of the currently active
  extruder. For example, one could use
  `printer[printer.toolhead.extruder].target` to get the target
  temperature of the current extruder.
- `printer.toolhead.homed_axes`: The current cartesian axes considered
  to be in a "homed" state. This is a string containing one or more of
  "x", "y", "z".
- `printer.toolhead.axis_minimum`,
  `printer.toolhead.axis_maximum`: The axis travel limits (mm) after homing.
  It is possible to access the x, y, z components of this
  limit value (eg, `printer.toolhead.axis_minimum.x`,
  `printer.toolhead.axis_maximum.z`).
- `printer.toolhead.max_velocity`, `printer.toolhead.max_accel`,
  `printer.toolhead.max_accel_to_decel`,
  `printer.toolhead.square_corner_velocity`: The current printing
  limits that are in effect. This may differ from the config file
  settings if a `SET_VELOCITY_LIMIT` (or `M204`) command alters them
  at run-time.
- `printer.heaters.available_heaters`: Returns a list of all currently
  available heaters by their full config section names,
  e.g. `["extruder", "heater_bed", "heater_generic my_custom_heater"]`.
- `printer.heaters.available_sensors`: Returns a list of all currently
  available temperature sensors by their full config section names,
  e.g. `["extruder", "heater_bed", "heater_generic my_custom_heater",
  "temperature_sensor electronics_temp"]`.
- `printer.query_endstops.last_query["<endstop>"]`: Returns True if
  the given endstop was reported as "triggered" during the last
  QUERY_ENDSTOP command. Note, due to the order of template expansion
  (see above), the QUERY_ENDSTOP command must be run prior to the
  macro containing this reference.
- `printer.probe.last_query`: Returns True if the probe was reported
  as "triggered" during the last QUERY_PROBE command. Note, due to the
  order of template expansion (see above), the QUERY_PROBE command
  must be run prior to the macro containing this reference.
- `printer.probe.last_z_result`: Returns the Z result value of the last
  PROBE command.
- `printer.configfile.settings.<section>.<option>`: Returns the given
  config file setting (or default value) during the last software
  start or restart. (Any settings changed at run-time will not be
  reflected here.)
- `printer.configfile.config.<section>.<option>`: Returns the given
  raw config file setting as read by Klipper during the last software
  start or restart. (Any settings changed at run-time will not be
  reflected here.) All values are returned as strings.
- `printer["gcode_macro <macro_name>"].<variable>`: The current value
  of a [gcode_macro variable](#variables).
- `printer.webhooks.state`: Returns a string indicating the current
  Klipper state. Possible values are: "ready", "startup", "shutdown",
  "error".
- `printer.webhooks.state_message`: A human readable string giving
  additional context on the current Klipper state.
- `printer.display_status.progress`: The progress value of the last
  `M73` G-Code command (or `printer.virtual_sdcard.progress` if no
  recent `M73` received).
- `printer.display_status.message`: The message contained in the last
  `M117` G-Code command.
- `printer["filament_switch_sensor <config_name>"].enabled`: Returns
  True if the switch sensor is currently enabled.
- `printer["filament_switch_sensor <config_name>"].filament_detected`:
  Returns True if the sensor is in a triggered state.
- `printer.virtual_sdcard.is_active`: Returns True if a print from
  file is currently active.
- `printer.virtual_sdcard.progress`: An estimate of the current print
  progress (based of file size and file position).
- `printer.virtual_sdcard.file_position`: The current position (in
  bytes) of an active print.
- `printer.print_stats.filename`,
  `printer.print_stats.total_duration`,
  `printer.print_stats.print_duration`,
  `printer.print_stats.filament_used`, `printer.print_stats.state`,
  `printer.print_stats.message`: Estimated information about the
  current print when a virtual_sdcard print is active.
- `printer.firmware_retraction.retract_length`,
  `printer.firmware_retraction.retract_speed`,
  `printer.firmware_retraction.unretract_extra_length`,
  `printer.firmware_retraction.unretract_speed`: The current settings
  for the firmware_retraction module. These settings may differ from
  the config file if a `SET_RETRACTION` command alters them.
- `printer["bme280 <sensor_name>"].temperature`,
  `printer["bme280 <sensor_name>"].humidity`,
  `printer["bme280 <sensor_name>"].pressure`: The last read values
  from the sensor.
- `printer["htu21d <sensor_name>"].temperature`,
  `printer["htu21d <sensor_name>"].humidity`: The last read values
  from the sensor.
- `printer["lm75 <sensor_name>"].temperature`: The last read
  temperature from the sensor.
- `printer["temperature_host <sensor_name>"].temperature`: The last read
  temperature from the sensor.
- `printer["temperature_sensor <config_name>"].temperature`: The last read
  temperature from the sensor.
- `printer["temperature_sensor <config_name>"].measured_min_temp`,
  `printer["temperature_sensor <config_name>"].measured_max_temp`: The
  lowest and highest temperature seen by the sensor since the Klipper
  host software was last restarted.
- `printer["temperature_fan <config_name>"].temperature`: The last read
  temperature from the sensor.
- `printer["temperature_fan <config_name>"].target`: The target
  temperature for the fan.
- `printer["output_pin <config_name>"].value`: The "value" of the pin,
  as set by a `SET_PIN` command.
- `printer["servo <config_name>"].value`: The last setting of the PWM
  pin (a value between 0.0 and 1.0) associated with the servo.
- `printer.bed_mesh.profile_name`, `printer.bed_mesh.mesh_min`,
  `printer.bed_mesh.mesh_max`, `printer.bed_mesh.probed_matrix`,
  `printer.bed_mesh.mesh_matrix`: Information on the currently active
  bed_mesh.
- `printer.hall_filament_width_sensor.is_active`: Returns True if the
  sensor is currently active.
- `printer.hall_filament_width_sensor.Diameter`,
  `printer.hall_filament_width_sensor.Raw`: The last read values from
  the sensor.
- `printer.mcu.mcu_version`: The Klipper code version reported by the
  micro-controller.
- `printer.mcu.mcu_build_versions`: Information on the build tools
  used to generate the micro-controller code (as reported by the
  micro-controller).
- `printer.mcu.mcu_constants.<constant_name>`: Compile time constants
  reported by the micro-controller. The available constants may differ
  between micro-controller architectures and with each code revision.
- `printer.mcu.last_stats.<statistics_name>`: Statistics information
  on the micro-controller connection.

The above list is subject to change - if using an attribute be sure to
review the [Config Changes document](Config_Changes.md) when upgrading
the Klipper software. The above list is not exhaustive.  Other
attributes may be available (via `get_status()` methods defined in the
software). However, undocumented attributes may change without notice
in future Klipper releases.

### Actions

There are some commands available that can alter the state of the
printer. For example, `{ action_emergency_stop() }` would cause the
printer to go into a shutdown state. Note that these actions are taken
at the time that the macro is evaluated, which may be a significant
amount of time before the generated g-code commands are executed.

Available "action" commands:
- `action_respond_info(msg)`: Write the given `msg` to the
  /tmp/printer pseudo-terminal. Each line of `msg` will be sent with a
  "// " prefix.
- `action_raise_error(msg)`: Abort the current macro (and any calling
  macros) and write the given `msg` to the /tmp/printer
  pseudo-terminal. The first line of `msg` will be sent with a "!! "
  prefix and subsequent lines will have a "// " prefix.
- `action_emergency_stop(msg)`: Transition the printer to a shutdown
  state. The `msg` parameter is optional, it may be useful to describe
  the reason for the shutdown.
- `action_call_remote_method(method_name)`: Calls a method registered
  by a remote client.  If the method takes parameters they should
  be provided via keyword arguments, ie:
  `action_call_remote_method("print_stuff", my_arg="hello_world")`

### Variables

The SET_GCODE_VARIABLE command may be useful for saving state between
macro calls. Variable names may not contain any upper case characters.
For example:

```
[gcode_macro start_probe]
variable_bed_temp: 0
gcode:
  # Save target temperature to bed_temp variable
  SET_GCODE_VARIABLE MACRO=start_probe VARIABLE=bed_temp VALUE={printer.heater_bed.target}
  # Disable bed heater
  M140
  # Perform probe
  PROBE
  # Call finish_probe macro at completion of probe
  finish_probe

[gcode_macro finish_probe]
gcode:
  # Restore temperature
  M140 S{printer["gcode_macro start_probe"].bed_temp}
```

Be sure to take the timing of macro evaluation and command execution
into account when using SET_GCODE_VARIABLE.

### Delayed Gcodes

The [delayed_gcode] configuration option can be used to execute a delayed
gcode sequence:

```
[delayed_gcode clear_display]
gcode:
  M117

[gcode_macro load_filament]
gcode:
 G91
 G1 E50
 G90
 M400
 M117 Load Complete!
 UPDATE_DELAYED_GCODE ID=clear_display DURATION=10
```

When the `load_filament` macro above executes, it will display a
"Load Complete!" message after the extrusion is finished.  The
last line of gcode enables the "clear_display" delayed_gcode, set
to execute in 10 seconds.

The `initial_duration` config option can be set to execute the
delayed_gcode on printer startup.  The countdown begins when the
printer enters the "ready" state.  For example, the below delayed_gcode
will execute 5 seconds after the printer is ready, initializing
the display with a "Welcome!" message:

```
[delayed_gcode welcome]
initial_duration: 5.
gcode:
  M117 Welcome!
```

Its possible for a delayed gcode to repeat by updating itself in
the gcode option:

```
[delayed_gcode report_temp]
initial_duration: 2.
gcode:
  {action_respond_info("Extruder Temp: %.1f" % (printer.extruder0.temperature))}
  UPDATE_DELAYED_GCODE ID=report_temp DURATION=2
```

The above delayed_gcode will send "// Extruder Temp: [ex0_temp]" to
Octoprint every 2 seconds.  This can be canceled with the following
gcode:


```
UPDATE_DELAYED_GCODE ID=report_temp DURATION=0
```

### Save Variables to disk
<!-- {% raw %} -->

If a
[save_variables config section](Config_Reference.md#save_variables)
has been enabled, `SAVE_VARIABLE VARIABLE=<name> VALUE=<value>` can be
used to save the variable to disk so that it can be used across
restarts. All stored variables are loaded into the
`printer.save_variables.variables` dict at startup and can be used in
gcode macros. to avoid overly long lines you can add the following at
the top of the macro:
```
{% set svv = printer.save_variables.variables %}
```

As an example, it could be used to save the state of 2-in-1-out hotend
and when starting a print ensure that the active extruder is used,
instead of T0:

```
[gcode_macro T1]
gcode:
  ACTIVATE_EXTRUDER extruder=extruder1
  SAVE_VARIABLE VARIABLE=currentextruder VALUE='"extruder1"'

[gcode_macro T0]
gcode:
  ACTIVATE_EXTRUDER extruder=extruder
  SAVE_VARIABLE VARIABLE=currentextruder VALUE='"extruder"'

[gcode_macro START_GCODE]
gcode:
  {% set svv = printer.save_variables.variables %}
  ACTIVATE_EXTRUDER extruder={svv.currentextruder}
```
<!-- {% endraw %} -->
