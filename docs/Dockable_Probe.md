

This document is meant to describe behavior related to dockable probes.
These probes are typically microswitches mounted to a printed body that
attaches to the toolhead through some means of mechanical coupling.
This coupling is commonly done with magnets though this module can support
a variety of designs including servo and stepper actuated couplings.

# Basic Configuration

The minimum requirements for functionality are a config section where the
following options are specified. Some users may be transitioning from a macro
based set of commands and many of the options for the `[probe]` config section
are the same. The `[dockable_probe]` module is first and foremost a `[probe]`
with additional functionality added. Any options that can be specified in
for `[probe]` are valid for `[dockable_probe]` as well.

```
[dockable_probe]
pin:
z_offset:
sample_retract_dist:
approach_position:
detach_position:
check_open_attach:
dock_fixed_z:
```

Additional optional parameters are described in this guide as well as the
required parameters. Certain optional parameters are not required, but highly recommended in order to ensure desired probe behavior is observed. Additionally
the [probe calibrate guide](Probe_Calibrate.md) is recommended reading
for users unfamiliar with probe setup in Klipper.

## Attaching and Detaching Positions

```
    dock_position: 300, 295, 0
```

The first option to specify is the `dock_position`. This is simply the XYZ
coordinates where the toolhead needs to be positioned in order to attach
the probe. This parameter is X, Y and, Z separated by commas.

Many configurations have the dock attached to a moving gantry. This effectively
means that Z axis positioning is irrelevant. However, it may be necessary
to move the gantry clear of the bed or other printer components before
performing docking steps. Automatic Z hop distances are calculated based on the
probe `z_offset` + `sample_retract_dist` to ensure travel moves are
safe. If a Z axis amount is specified for this type of dock, the additional
amount will be added to the Z hop distance.

Other configurations may have the dock mounted next to the printer bed so
that the Z position _must_ be known prior to attaching the probe. If the
probe is mounted in such a way, the Z axis parameter _must_ be supplied,
and the Z axis _must_ be homed prior to attaching the probe.

```
    approach_position: 300, 250
```

The most common dock designs utilize a sort of fork or arms that extend out
from the dock. In order to attach the probe to the toolhead, the toolhead must
move into and away from the dock at a particular angle so that these arms can
capture the probe body. For magnetically coupled probes, the `approach_position`
should be defined so that it is far enough away from the probe so that the
magnets on the probe body are not attracted to the magnets on the toolhead.

```
    detach_position:  250, 295
```

Most probes that use magnets require the toolhead to move in a direction that
strips the magnets off with a sliding motion. This is to prevent the magnets
from becoming unseated from repeated pulling and thus affecting probe accuracy.
The `detach_position` is typically defined as a point that is perpendicular to
the dock so that when the toolhead moves, the probe stays docked but cleanly
detaches from the toolhead mount. For magnetically coupled probes, the
`detach_position` should be defined so that it is far enough away from the
probe so that the magnets on the probe body are not attracted to the magnets on
the toolhead.

## Dock Z location

```
    dock_fixed_z:   default false
```
There are various locations that probe docks have been mounted. It seems the
more common locations are next to a bed or on a moving gantry. If the probe
is "fixed" on the Z axis, meaning, it's position relative to XY plane of the
toolhead is always the same, this option should be set to "true".

An example where `dock_fixed_z: True` is a corexy printer with a bed that moves
up and down along the Z axis with the probe dock mounted to the frame next to a
fixed gantry. The toolhead can move to the probe dock _regardless_ of where
the bed is positioned.

Another example would be a printer with a bed that is fixed to the base of the
printer and the gantry moves along all 3 axes. The dock is mounted to a point on
this moving gantry. This as well would be `dock_fixed_z: True`

A example where `dock_fixed_z: False` would be a i3 style printer where the dock
is located on the moving bed. When the Z axis moves, the dock's position changes
relative to the toolhead.

Another example of `dock_fixed_z: False` is a cartesian or hbot cube printer
where the dock is mounted next to the moving bed on the Z axis itself.

Any printer where `dock_fixed_z: False` requires that the z axis be homed prior
to moving to the dock.

```
    safe_z_position:    0,0
```
An optional parameter may be defined for homing the Z axis using the probe.
Similar to `safe_z_home`, a set of x y coordinates may be defined to use when
homing. If this parameter is omitted, the center of the bed will be used.

## Tool Velocities

```
    attach_speed:   default is probe speed or 5mm/s
    detach_speed: default is probe speed or 5mm/s
    travel_speed:   default is 50 mm/s
```
Various optional speeds can be defined for approaching, detaching and
traveling. If these parameters are omitted, the module will use the `speed`
parameter of the probe if defined. If this option is not supplied, 5mm/s
will be used.

## Probe Attachment Verification

Given the nature of this type of probe, it is necessary to verify whether or
not it has successfully attached prior to attempting a probing move. Several
methods can be used to verify various probe attachment states.

```
    check_open_attach: default false
```
Certain probes when wired a certain way will report `OPEN` when they are
attached and `TRIGGERED` when they are detached in a non-probing state. The
`check_open_attach` option when set to `true` will check the state of the
probe pin after performing a probe attach or docking maneuver. If the probe
reports `TRIGGERED` immediately after the toolhead leaves the dock radius, an
error will be raised and any further action will be aborted.

This is intended to prevent crashing the nozzle into the bed since it is
assumed if the probe pin reads `TRIGGERED` prior to probing, the probe is
not attached.

```
    probe_sense_pin:
```
The probe may include a separate pin for attachment verification. This is a
standard pin definition similar to an endstop pin that defines how to handle the
input from the sensor. Much like the `check_open_attach` option, the check is
done immediately after the tool attaches or docks the probe. If the probe
is not attached after attempting to attach it, or it remains attached after
attempting to dock it, an error will be raised and further action will be
aborted.

```
    dock_sense_pin:
```
Certain docks may have a sensor or switch incorporated into their design in
order to report that the probe is presently located in the dock. A
`dock_sense_pin` may be provided to provide verification that the probe is
correctly positioned in the dock. This is a standard pin definition similar
to an endstop pin that defines how to handle the input from the sensor.
Prior to attempting to attach the probe, and after attempting to dock it,
this pin is checked. If the probe is not stowed, an error will be raised and
further action will be aborted.

```
    dock_retries:   0
```
A magnetic probe may require repeated attempts to attach. If `dock_retries` is
specified and the probe fails to attach or detach, the attach/detach action
will be repeated until it succeeds. If the retry limit is reached and the probe
is still not in the correct state, an error is raised and futher actions
are aborted.

```
    allow_delayed_detach: False
```
Typically, a command that requires the use of the probe will cause the probe
to be attached and then docked when it is no longer needed. In the context
of start gcode, a homing macro, or any sequence with multiple commands requiring
the use of the probe, this results in the probe repeatedly being attached and
docked between commands. If the `allow_delayed_detach` option is set to True,
the probe will wait for a short period of time before docking at the end of
a command. This can result in calibration macros executing faster as the probe
has to do less traveling. If this option is used, it is recommended to add
the manual `DETACH_PROBE` command at the end of a macro or start gcode. Often
the _next_ command will start to execute _prior_ to the probe detaching which
can result in a collision.


## Custom Actions

```
    pre_attach_gcode:
    attach_gcode:
    post_attach_gcode:
    pre_detach_gcode:
    detach_gcode:
    post_detach_gcode:
```

As universal as this module attempts to be, all use cases cannot be accounted
for. As such several "custom" gcode command templates may be supplied to be
executed at various times during probe maneuvers. These optional gcode sections
may be configured like standard gcode macro command templates with the exception
that gcode macro variables, default parameters, and rename_existing options are
excluded.

These command templates are inserted at various points of the probe execution
flow (below) so they may be used to activate a servo or move the toolhead to
a position that aligns cabling or tubes so that they do not snag on parts of
the printer.


```
    pre_attach_gcode:
```
If specified, the `pre_attach_gcode` is called prior to approaching the dock.
If a servo is needed to move the dock, this is where that command should be
issued.


```
    attach_gcode:
```
If specified, the `attach_gcode` commands are executed immediately _after_ the
toolhead reaches the `dock_position`. This gcode may be repeated if the probe
fails to attach and `dock_retries` are specified.

```
    post_attach_gcode:
```
If specified, the `post_attach_gcode` is called immediately after leaving the
dock, but only if the probe was successfully attached.


```
    pre_detach_gcode:
```
If specified, the `pre_detach_gcode` is called prior to approaching the dock.
If a servo is needed to move the dock, this is where that command should be
issued.


```
    detach_gcode:
```
If specified, the `detach_gcode` commands are executed immediately _after_ the
toolhead reaches the `dock_position`. This gcode may be repeated if the probe
fails to detach and `dock_retries` are specified.

```
    post_detach_gcode:
```
If specified, the `post_detach_gcode` is called immediately after leaving the
dock, but only if the probe was successfully docked.

## Gcode commands

There are 4 gcode commands that can be used with the probe to perform various
tasks or obtain status information.

```
    ATTACH_PROBE
```
This command will move the toolhead to the dock, attach the probe, and then
return to its previous position. If the probe is already attached, the command
will not do anything

```
    DETACH_PROBE
```
This command will move the toolhead to the dock, detach the probe, and then
return to its previous position. If the probe is already detached, the command
will not do anything

```
    GET_PROBE_STATUS
```
Responds in the gcode terminal with the current status the probe is in. Valid
states are UNKNOWN, ATTACHED, and DOCKED. This is useful during configuration
to confirm probe validation methods are working as intended.

## Typical probe execution flow

    Probing is Started:

    - A gcode command requiring the use of the probe is executed.

    - This triggers the probe to attach

    - If configured, the dock sense pin is checked to see if the probe is
      presently in the dock

    - If specified, the pre-attach gcode is executed

    - The toolhead position is compared to the dock position.

    - If the toolhead is outside of the minimum safe radius, the toolhead is
      commanded to move to the the approach vector, that is, a position that is
      the minimum safe distance from the dock in line with the dock angle

    - If the toolhead is inside of the minimum safe radius, the toolhead is
      commanded to move to the nearest point on the line of the approach vector

    - The tool is moved along the approach vector to the dock coordinates

    - If specified, the attach gcode is executed

    - The toolhead is commanded to move out of the dock back to the minimum
      safe distance in the reverse direction along the dock angle.

    - If configured, the probe is checked to see if it is attached

    - If the probe is not attached, the module retries until it is or an error
      is raised

    - If configured, the dock sense pin is checked to see if the probe is still
      present, the module retries until it not or an error is raised

    - If specified, the post-attach gcode is executed

    - The probe moves to the first probing point and beings probing

    Probing is Finished:

    - After the probe is no longer needed, the probe is triggered to detach.

    - If specified, the pre-detach gcode is executed

    - The toolhead position is compared to the dock position.

    - If the toolhead is outside of the minimum safe radius, the toolhead is
      commanded to move to the the approach vector, that is, a position that is
      the minimum safe distance from the dock in line with the dock angle

    - If the toolhead is inside of the minimum safe radius, the toolhead is
      commanded to move to the nearest point on the line of the approach vector

    - The tool is moved along the approach vector to the dock coordinates

    - If specified, the detach gcode is executed

    - The tool is commanded to move along the detach vector if supplied or a
      calculated direction based on axis parameters

    - If configured, the probe is checked to see if it is detached

    - If the probe is not detached, the module moves the tool back to the
      approach vector and retries until it detaches or an error is raised

    - If configured, the dock sense pin is checked to see if the probe is
      present in the dock. If it is not the module moves the tool back to the
      approach vector and retries until it detaches or an error is raised

    - If specified, the post-detach gcode is executed


# Use in macros

The dockable_probe module can use a delayed detach so that it does not
repeatedly dock and undock the probe from the toolhead while it is being
used in the context of a homing macro or slicer start gcode. This works
in most cases, but if a call to heat-and-wait (M109, M190) or a toolhead move
comes too soon after probing is finished, it may result in the probe staying
attached to the toolhead until after the heater is done heating or the gcode
move completes. This can be avoided by placing a call to `DETACH_PROBE`
immediately _after_ the last command requiring the probe.

example 1:

Gcode file from slicer
```
start_print b=90 e=250
```

Macro definition in Klipper
```
[gcode_macro start_print]
gcode:
    M190 S{b}           ;set bed temp and wait
    G28                 ;home all axes
    BED_MESH_CALIBRATE  ;generate a bed mesh
    G28 Z0              ;rehome z axis
    DETACH_PROBE        ;ensure probe is detached
    M109 S{e}
```

example 2:

Gcode file from slicer
```
M190 S[first_layer_bed_temperature]
M109 S[first_layer_temperature]
G28
BED_MESH_CALIBRATE
G28 Z0
DETACH_PROBE
G92 E0
G1 X0.1 Y0 F8000 ;begin priming line
G1 Z2.0 F3000
```
