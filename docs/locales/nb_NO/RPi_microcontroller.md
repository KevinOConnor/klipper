This document describes the process of running Klipper on a RPi and use the same
RPi as secondary mcu.

# Why use RPi as a secondary MCU?

Often the MCUs dedicated to controlling 3D printers have a limited and pre-
configured number of exposed pins to manage the main printing functions (thermal
resistors, extruders, steppers ...). Using the RPi where Klipper is installed as
a secondary MCU gives the possibility to directly use the GPIOs and the buses
(i2c, spi) of the RPi inside klipper without using Octoprint plugins (if used)
or external programs giving the ability to control everything within the print
GCODE.

**Warning**: If your platform is a *Beaglebone* and you have correctly followed
the installation steps, the linux mcu is already installed and configured for
your system.

# Install the rc script

If you want to use the host as a secondary MCU the klipper_mcu process must run
before the klippy process.

After installing Klipper, install the script. run:

```
cd ~/klipper/
sudo cp "./scripts/klipper-mcu-start.sh" /etc/init.d/klipper_mcu
sudo update-rc.d klipper_mcu defaults
```

# Building the micro-controller code

To compile the Klipper micro-controller code, start by configuring it for the
"Linux process":

```
cd ~/klipper/
make menuconfig
```

To build and install the new micro-controller code, run:

```
sudo service klipper stop
make flash
sudo service klipper start
```

If klippy.log reports a "Permission denied" error when attempting to connect
to `/tmp/klipper_host_mcu` then you need to add your user to the tty group. The
following command will add the "pi" user to the tty group:

```
sudo usermod -a -G tty pi
```

# Remaining configuration

Complete the installation by configuring Klipper secondary MCU following the
instructions in [RaspberryPi sample config](../config/sample-raspberry-pi.cfg)
and [Multi MCU sample config](../config/sample-multi-mcu.cfg).

# Optional: Identify the correct gpiochip

On Rasperry and on many clones the pins exposed on the GPIO belong to the first
gpiochip. They can therefore be used on klipper simply by referring them with
the name `gpio0..n`. However, there are cases in which the exposed pins belong
to gpiochips other than the first. For example in the case of some OrangePi
models or if a Port Expander is used. In these cases it is useful to use the
commands to access the *Linux GPIO character device* to verify the configuration.

To install the *Linux GPIO character device - binary* on a debian based distro
like octopi run:

```
sudo apt-get install gpiod
```

To check available gpiochip run:

```
gpiodetect
```

To check the pin number and the pin availability tun:

```
gpioinfo
```

The chosen pin can thus be used within the configuration as
`gpiochip<n>/gpio<o>` where **n** is the chip number as seen by the
`gpiodetect` command and **o** is the line number seen by the` gpioinfo`
command.

***Warning:*** only gpio marked as `unused` can be used. It is not possible for
a *line* to be used by multiple processes simultaneously.

For example on a RPi 3B+ where klipper use the GPIO20 for a switch:

```
$ gpiodetect
gpiochip0 [pinctrl-bcm2835] (54 lines)
gpiochip1 [raspberrypi-exp-gpio] (8 lines)

$ gpioinfo
gpiochip0 - 54 lines:
        line   0:      unnamed       unused   input  active-high
        line   1:      unnamed       unused   input  active-high
        line   2:      unnamed       unused   input  active-high
        line   3:      unnamed       unused   input  active-high
        line   4:      unnamed       unused   input  active-high
        line   5:      unnamed       unused   input  active-high
        line   6:      unnamed       unused   input  active-high
        line   7:      unnamed       unused   input  active-high
        line   8:      unnamed       unused   input  active-high
        line   9:      unnamed       unused   input  active-high
        line  10:      unnamed       unused   input  active-high
        line  11:      unnamed       unused   input  active-high
        line  12:      unnamed       unused   input  active-high
        line  13:      unnamed       unused   input  active-high
        line  14:      unnamed       unused   input  active-high
        line  15:      unnamed       unused   input  active-high
        line  16:      unnamed       unused   input  active-high
        line  17:      unnamed       unused   input  active-high
        line  18:      unnamed       unused   input  active-high
        line  19:      unnamed       unused   input  active-high
        line  20:      unnamed    "klipper"  output  active-high [used]
        line  21:      unnamed       unused   input  active-high
        line  22:      unnamed       unused   input  active-high
        line  23:      unnamed       unused   input  active-high
        line  24:      unnamed       unused   input  active-high
        line  25:      unnamed       unused   input  active-high
        line  26:      unnamed       unused   input  active-high
        line  27:      unnamed       unused   input  active-high
        line  28:      unnamed       unused   input  active-high
        line  29:      unnamed       "led0"  output  active-high [used]
        line  30:      unnamed       unused   input  active-high
        line  31:      unnamed       unused   input  active-high
        line  32:      unnamed       unused   input  active-high
        line  33:      unnamed       unused   input  active-high
        line  34:      unnamed       unused   input  active-high
        line  35:      unnamed       unused   input  active-high
        line  36:      unnamed       unused   input  active-high
        line  37:      unnamed       unused   input  active-high
        line  38:      unnamed       unused   input  active-high
        line  39:      unnamed       unused   input  active-high
        line  40:      unnamed       unused   input  active-high
        line  41:      unnamed       unused   input  active-high
        line  42:      unnamed       unused   input  active-high
        line  43:      unnamed       unused   input  active-high
        line  44:      unnamed       unused   input  active-high
        line  45:      unnamed       unused   input  active-high
        line  46:      unnamed       unused   input  active-high
        line  47:      unnamed       unused   input  active-high
        line  48:      unnamed       unused   input  active-high
        line  49:      unnamed       unused   input  active-high
        line  50:      unnamed       unused   input  active-high
        line  51:      unnamed       unused   input  active-high
        line  52:      unnamed       unused   input  active-high
        line  53:      unnamed       unused   input  active-high
gpiochip1 - 8 lines:
        line   0:      unnamed       unused   input  active-high
        line   1:      unnamed       unused   input  active-high
        line   2:      unnamed       "led1"  output   active-low [used]
        line   3:      unnamed       unused   input  active-high
        line   4:      unnamed       unused   input  active-high
        line   5:      unnamed       unused   input  active-high
        line   6:      unnamed       unused   input  active-high
        line   7:      unnamed       unused   input  active-high
```
