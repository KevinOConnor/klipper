This document describes the process of running Klipper on a Beaglebone PRU.

# Building an OS image

Start by installing the [Debian 9.9 2019-08-03 4GB SD IoT]
(https://beagleboard.org/latest-images) image. One may run the image from either
a micro-SD card or from builtin eMMC. If using the eMMC, install it to eMMC now
by following the instructions from the above link.

Then ssh into the beaglebone machine (ssh debian@beaglebone -- password is
"temppwd") and install Klipper by running the following commands:

```
git clone https://github.com/KevinOConnor/klipper
./klipper/scripts/install-beaglebone.sh
```

# Install Octoprint

One may then install Octoprint:

```
git clone https://github.com/foosel/OctoPrint.git
cd OctoPrint/
virtualenv venv
./venv/bin/python setup.py install
```

And setup OctoPrint to start at bootup:

```
sudo cp ~/OctoPrint/scripts/octoprint.init /etc/init.d/octoprint
sudo chmod +x /etc/init.d/octoprint
sudo cp ~/OctoPrint/scripts/octoprint.default /etc/default/octoprint
sudo update-rc.d octoprint defaults
```

It is necessary to modify OctoPrint's **/etc/default/octoprint** configuration
file. One must change the OCTOPRINT_USER user to "debian", change NICELEVEL to
0, uncomment the BASEDIR, CONFIGFILE, and DAEMON settings and change the
references from "/home/pi/" to "/home/debian/":

```
sudo nano /etc/default/octoprint
```

Then start the Octoprint service:

```
sudo systemctl start octoprint
```

Make sure the octoprint web server is accessible - it should be at:
<http://beaglebone:5000/>

# Building the micro-controller code

To compile the Klipper micro-controller code, start by configuring it for the
"Beaglebone PRU":

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

It is also necessary to compile and install the micro-controller code for a
Linux host process. Run "make menuconfig" a second time and configure it for a
"Linux process":

```
make menuconfig
```

Then install this micro-controller code as well:

```
sudo service klipper stop
make flash
sudo service klipper start
```

# Remaining configuration

Complete the installation by configuring Klipper and Octoprint following the
instructions in [the main installation document](Installation.md#configuring-
klipper).

# Printing on the Beaglebone

Unfortunately, the Beaglebone processor can sometimes struggle to run OctoPrint
well. Print stalls have been known to occur on complex prints (the printer may
move faster than OctoPrint can send movement commands). If this occurs, consider
using the "virtual_sdcard" feature (see [config
reference](Config_Reference.md#virtual_sdcard) for details) to print directly
from Klipper.
