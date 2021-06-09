This document describes how to setup a PWM-controlled laser or spindle
using `output_pin` and some macros.


## How does it work?
With re-purposing the printhead's fan pwm output, you can control
lasers or spindles.
This is useful if you use switchable print heads, for example
the E3D toolchanger or a DIY solution.
Usually, cam-tools such as LaserWeb can be configured to use `M3-M5`
commands, which stand for _spindle speed CW_ (`M3 S[0-255]`),
_spindle speed CCW_ (`M4 S[0-255]`) and _spindle stop_ (`M5`).


**Warning:** When driving a laser, keep all security precautions
that you can think of! Diode lasers are usually inverted.
This means, that when the MCU restarts, the laser will be
_fully on_ for the time it takes the MCU to start up again.
For good measure, it is recommended to _always_ wear appropriate
laser-goggles of the right wavelength if the laser is powered;
and to disconnect the laser when it is not needed.
Also, you should configure a safety timeout,
so that when your host or MCU encounters an error, the tool will stop.

For an example configuration, see `config/sample-pwm-tool-cfg`.

## Commands

`M3/M4 S<value>` : Set PWM duty-cycle. Values between 0 and 255.
`M5` : Stop PWM output to shutdown value.

## Laserweb Configuration

If you use Laserweb, a working configuration would be:

    GCODE START:
        M5            ; Disable Laser
        G21           ; Set units to mm
        G90           ; Absolute positioning
        G0 Z0 F7000   ; Set Non-Cutting speed

    GCODE END:
        M5            ; Disable Laser
        G91           ; relative
        G0 Z+20 F4000 ;
        G90           ; absolute

    GCODE HOMING:
        M5            ; Disable Laser
        G28           ; Home all axis

    TOOL ON:
        M3 $INTENSITY

    TOOL OFF:
        M5            ; Disable Laser

    LASER INTENSITY:
        S
