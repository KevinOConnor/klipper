This document provides some hints and tips on tuning some popular
configuration settings. The goal is to provide a high-level overview
of these parameters and to provide some intuition for tuning. This
document is not intended to be an authoritative reference.

See the
[example.cfg](https://github.com/KevinOConnor/klipper/tree/master/config/example.cfg)
file for the full documentation of the settings discussed here.

Tuning for faster prints
========================

A common goal is to tune for higher print speeds while still
maintaining reasonable print quality. A useful tool is Klipper's
["batch processing mode"](Debugging.md#translating-gcode-files-to-micro-controller-commands). It
allows one to determine the print time of a gcode file without having
to actually print it. Follow the steps in the link above to setup
Klipper in this mode, then ssh into the host machine, and run a
command like the following:

```
~/klippy-env/bin/python ./klippy/klippy.py ~/printer.cfg -d out/klipper.dict -o /dev/null -i ~/.octoprint/uploads/my_print.gcode
```

The above command may take anywhere from a few seconds to a few
minutes to complete depending on the gcode file used. When it does
complete, it should report a line like `INFO:root:Exiting (print
time 5107.300s)`. This value is the total time (in seconds) that it
would take to print the given gcode file with the given printer.cfg
file. When tuning config parameters to reduce print time, it is
recommended to run a print simulation to determine the time impact of
each change.

The following are common settings that one would tune to reduce print
times (greatest impact first):

- `Print layer height (slicer setting)`: Increasing layer height can
  significantly reduce overall print times. However, increased layer
  height may result in decreased surface quality due to bowing of
  individual layers. A very high layer height may adversely impact
  layer adhesion. A typical "rule of thumb" is to avoid layer heights
  greater than ~75% of the nozzle diameter.

  Depending on the printer, one may also wish to use a layer height
  that is a multiple of a full step distance on the Z stepper motor to
  avoid "Z banding" artifacts.

- `Print velocity (slicer setting)`: A higher print velocity will
  result in lower print times. The maximum speed is typically limited
  by the maximum flow rate of the extruder. A too high print velocity
  may result in under extrusion (often first seen as print blemishes
  on straight walls of prints).

  Although velocity is set in the slicer, the M220 command can be used
  during tuning tests. To find the maximum acceptable velocity (for a
  given layer height), make sure the max_velocity setting in the
  config file is sufficiently high, and consider printing the
  [docs/prints/square_tower.stl](prints/square_tower.stl) with:
  `TUNING_TOWER COMMAND=M220 PARAMETER=S START=80 FACTOR=5`

  Many slicers offer a variety of print speed configurations for
  various extrusion moves. It's useful to use a slower speed for the
  first layer (to improve bed adhesion) and it's useful to use a
  slower speed for external perimeters (to improve surface quality).
  Consider using the measured maximum velocity for the remaining
  speeds (including "travel moves").

- `max_accel`: A higher acceleration value results in lower print
  times. The maximum acceleration is typically limited by the impact
  of vibrations to print quality. A very high acceleration may also
  result in "skipped steps" due to insufficient stepper torque.

  See the [Resonance Compensation document](Resonance_Compensation.md)
  for info on testing acceleration, tuning input_shaper, and selecting
  a maximum acceleration with it.

Tuning for extrusion quality
============================

A common goal is to tune the printer for improved print extrusion
quality. The primary method of improving quality is to "go slower"
(see the previous section). However, Klipper has several settings that
may improve quality without increasing print time.

- `pressure_advance`: Enabling and tuning Pressure Advance may reduce
  "extruder ooze", reduce blobbing during corners, and reduce surface
  defects. See the [Pressure Advance document](Pressure_Advance.md)
  for further information.

- `pressure_advance_smooth_time`: This setting is available if
  pressure_advance is enabled, though it rarely requires tuning. The
  setting controls the time window that Klipper uses to smooth
  extruder movement. A too small value can cause excessive extruder
  noise and result in "skipped steps". Larger values result in
  smoother extruder motion, but can cause subtle print blemishes
  leading up to corners.

  If testing is desired, consider printing the
  [docs/prints/square_tower.stl](prints/square_tower.stl) with:
  `TUNING_TOWER COMMAND=SET_PRESSURE_ADVANCE PARAMETER=SMOOTH_TIME
  START=0.101 FACTOR=-.002`

- `square_corner_velocity`: This setting balances a quality trade-off
  between extruder flow rate and toolhead cornering speed. A higher
  value may improve surface quality on curves and corners due to fewer
  changes in extruder flow rate, but a too high value may cause print
  defects due to toolhead vibrations. A very high value may result in
  "skipped steps". A too low value may result in increased print times
  and poor surface quality on curves and corners.

  Before tuning square_corner_velocity it is recommend to first tune
  Pressure Advance. The Pressure Advance system may mitigate the
  impact of changes to extruder flow rate without the impact of
  increasing cornering speeds.

  Increasing square_corner_velocity may reduce overall print times,
  but doing so generally offers diminishing returns. That is, a
  significant increase to square_corner_velocity is likely to
  introduce print defects while only reducing total print time by a
  small amount.

  If testing is desired, consider printing the
  [docs/prints/square_tower.stl](prints/square_tower.stl) with:
  `TUNING_TOWER COMMAND=SET_VELOCITY_LIMIT
  PARAMETER=SQUARE_CORNER_VELOCITY START=0 FACTOR=.5`

Other Parameters
================

- `max_accel_to_decel`: This setting is intended to reduce printer
  vibrations caused by small zigzag moves. Some slicers will emit
  these types of moves for "gap fills". A lower value can reduce
  printer vibrations, but a too small value may unnecessarily increase
  print times. If you find a print that causes significant printer
  vibration then consider tuning this value with that print.

- `max_extrude_only_velocity` and `max_extrude_only_accel`: These
  settings limit how fast retraction moves occur. Klipper uses
  conservative values for these settings by default. If one uses very
  high retraction settings, then one may need to increase these values
  to avoid pauses during retraction. However, it is generally
  preferable to tune Pressure Advance, use small retraction settings,
  and leave these settings at their default.

- `instantaneous_corner_velocity`: This setting limits the speed of
  cornering moves with large changes in extrusion rates. These moves
  are rare and tuning this setting is not thought to be necessary.

- `pid_Kp`, `pid_Ki`, `pid_Kd`: These settings control the heater PID
  algorithm. See the description of `PID_CALIBRATE` in the
  [Config Checks document](Config_checks.md#calibrate-pid-settings)
  for using the automated PID calibration tool. It may also be
  possible to manually tune the PID - do a web search for "pid tuning"
  to find further information.
