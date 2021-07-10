This file describes the support for the Mechaduino (and "Smart
Stepper", and their clones).

THIS SUPPORT IS EXPERIMENTAL - PROCEED WITH CAUTION!

With this support, the Klipper micro-controller code runs directly on
the Mechaduino and all communication is done via USB.

# Compiling

Compile the firmware for the SAMD21 mcu. Build with support for an
8KiB bootloader and enable USB.

It should be possible to flash the bootloader with something like:
```
make flash FLASH_DEVICE=/dev/ttyACM0
```
See the
[bootloaders document](Bootloaders.md#samd21-micro-controllers-arduino-zero)
for information on entering the bootloader.

After Klipper is flashed to the Mechaduino, it is also possible to
enter the bootloader by running the above "make flash" command. (Run
the command to enter the bootloader and then run the command a second
time to flash the chip.)

# Configuration

Copy one of the snippets from
[config/sample-mechaduino.cfg](../config/sample-mechaduino.cfg) to the
printer.cfg.

# Calibration

The Mechaduino needs to be calibrated before first use. Disconnect the
stepper motor from all load and run a command like the following:
```
SERVO_CALIBRATE SERVO=stepper_x
```

The above should take about a minute to complete. After it completes
it will be necessary to save the results to the config file:
```
SAVE_CONFIG
```

# Modes

Currently only "open loop" and "constant torque" mode are supported.
The "open loop" mode is the default.

To use "constant torque" mode, run something like the following:
```
SET_TORQUE_MODE SERVO=stepper_x EXCITE=64 CURRENT=0.750
```
The CURRENT parameter (specified in Amps) controls how much torque the
stepper should apply (it may not exceed the current parameter
specified in the printer config file). To go in a reverse direction
use `EXCITE=448`. To turn off the stepper motor use `CURRENT=0`.
