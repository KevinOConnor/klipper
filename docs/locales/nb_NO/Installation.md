These instructions assume the software will run on a Raspberry Pi computer in
conjunction with OctoPrint. It is recommended that a Raspberry Pi 2, 3, or 4
computer be used as the host machine (see the [FAQ](FAQ.md#can-i-run-klipper-on-
something-other-than-a-raspberry-pi-3) for other machines).

Klipper currently supports a number of Atmel ATmega based micro-controllers,
[ARM based micro-controllers](Features.md#step-benchmarks), and [Beaglebone
PRU](beaglebone.md) based printers.

# Prepping an OS image

Start by installing [OctoPi](https://github.com/guysoft/OctoPi) on the Raspberry
Pi computer. Use OctoPi v0.17.0 or later - see the [octopi
releases](https://github.com/guysoft/OctoPi/releases) for release information.
One should verify that OctoPi boots and that the OctoPrint web server works.
After connecting to the OctoPrint web page, follow the prompt to upgrade
OctoPrint to v1.4.2 or later.

After installing OctoPi and upgrading OctoPrint, it will be necessary to ssh
into the target machine to run a handful of system commands. If using a Linux or
MacOS desktop, then the "ssh" software should already be installed on the
desktop. There are free ssh clients available for other desktops (eg,
[PuTTY](https://www.chiark.greenend.org.uk/~sgtatham/putty/)). Use the ssh
utility to connect to the Raspberry Pi (ssh pi@octopi -- password is
"raspberry") and run the following commands:

```
git clone https://github.com/KevinOConnor/klipper
./klipper/scripts/install-octopi.sh
```

The above will download Klipper, install some system dependencies, setup Klipper
to run at system startup, and start the Klipper host software. It will require
an internet connection and it may take a few minutes to complete.

# Building and flashing the micro-controller

To compile the micro-controller code, start by running these commands on the
Raspberry Pi:

```
cd ~/klipper/
make menuconfig
```

Select the appropriate micro-controller and review any other options provided.
Once configured, run:

```
make
```

It is necessary to determine the serial port connected to the micro-controller.
For micro-controllers that connect via USB, run the following:

```
ls /dev/serial/by-id/*
```

It should report something similar to the following:

```
/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0
```

It's common for each printer to have its own unique serial port name. This
unique name will be used when flashing the micro-controller. It's possible there
may be multiple lines in the above output - if so, choose the line corresponding
to the micro-controller (see the [FAQ](FAQ.md#wheres-my-serial-port) for more
information).

For common micro-controllers, the code can be flashed with something similar to:

```
sudo service klipper stop
make flash FLASH_DEVICE=/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0
sudo service klipper start
```

Be sure to update the FLASH_DEVICE with the printer's unique serial port name.

When flashing for the first time, make sure that OctoPrint is not connected
directly to the printer (from the OctoPrint web page, under the "Connection"
section, click "Disconnect").

# Configuring OctoPrint to use Klipper

The OctoPrint web server needs to be configured to communicate with the Klipper
host software. Using a web browser, login to the OctoPrint web page and then
configure the following items:

Navigate to the Settings tab (the wrench icon at the top of the page). Under
"Serial Connection" in "Additional serial ports" add "/tmp/printer". Then
click "Save".

Enter the Settings tab again and under "Serial Connection" change the "Serial
Port" setting to "/tmp/printer".

In the Settings tab, navigate to the "Behavior" sub-tab and select the
"Cancel any ongoing prints but stay connected to the printer" option. Click
"Save".

From the main page, under the "Connection" section (at the top left of the
page) make sure the "Serial Port" is set to "/tmp/printer" and click
"Connect". (If "/tmp/printer" is not an available selection then try
reloading the page.)

Once connected, navigate to the "Terminal" tab and type "status" (without
the quotes) into the command entry box and click "Send". The terminal window
will likely report there is an error opening the config file - that means
OctoPrint is successfully communicating with Klipper. Proceed to the next
section.

# Configuring Klipper

The Klipper configuration is stored in a text file on the Raspberry Pi. Take a
look at the example config files in the [config directory](../config/). The
[config reference](Config_Reference.md) contains documentation on config
parameters.

Arguably the easiest way to update the Klipper configuration file is to use a
desktop editor that supports editing files over the "scp" and/or "sftp"
protocols. There are freely available tools that support this (eg, Notepad++,
WinSCP, and Cyberduck). Use one of the example config files as a starting point
and save it as a file named "printer.cfg" in the home directory of the pi user
(ie, /home/pi/printer.cfg).

Alternatively, one can also copy and edit the file directly on the Raspberry Pi
via ssh - for example:

```
cp ~/klipper/config/example-cartesian.cfg ~/printer.cfg
nano ~/printer.cfg
```

Make sure to review and update each setting that is appropriate for the
hardware.

It's common for each printer to have its own unique name for the micro-
controller. The name may change after flashing Klipper, so rerun the
`ls /dev/serial/by-id/*` command and then update the config file with the unique
name. For example, update the `[mcu]` section to look something similar to:

```
[mcu]
serial: /dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0
```

After creating and editing the file it will be necessary to issue a "restart"
command in the OctoPrint web terminal to load the config. A "status" command
will report the printer is ready if the Klipper config file is successfully read
and the micro-controller is successfully found and configured. It is not unusual
to have configuration errors during the initial setup - update the printer
config file and issue "restart" until "status" reports the printer is ready.

Klipper reports error messages via the OctoPrint terminal tab. The "status"
command can be used to re-report error messages. The default Klipper startup
script also places a log in **/tmp/klippy.log** which provides more detailed
information.

In addition to common g-code commands, Klipper supports a few extended commands
- "status" and "restart" are examples of these commands. Use the "help"
command to get a list of other extended commands.

After Klipper reports that the printer is ready go on to the [config check
document](Config_checks.md) to perform some basic checks on the pin definitions
in the config file.

# Contacting the developers

Be sure to see the [FAQ](FAQ.md) for answers to some common questions. See the
[contact page](Contact.md) to report a bug or to contact the developers.
