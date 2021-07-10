#!/usr/bin/env python2
# Tool for writing micro-controller code
#
# Copyright (C) 2021  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import sys, os, optparse

def get_flash_types():
    # XXX - should auto-detect types from flash_usb and flash-sdcard
    return ["makeflash", "sdcard,btt-skr-mini-e3-v2",
            "sdcard,btt-skr-mini-mz"]

def list_flash_types():
    for t in get_flash_types():
        sys.stdout.write('%s\n' % (t,))

def list_devices(flash_type):
    # XXX - list applicable devices somehow?
    dummy_devices = ["/dev/ttyUSB0", "/dev/ttyAMA0", "/dev/ttyACM0"]
    for d in dummy_devices:
        sys.stdout.write('%s\n' % (d,))


######################################################################
# Flashing code
######################################################################

def do_makeflash(device, kconfig, out):
    # XXX - this is dummy code - we should call avrdude / flash_usb directly
    srcdir = os.path.dirname(os.path.realpath(__file__))
    makedir = os.path.join(srcdir, '..')
    os.system("make -C '%s' OUT='%s' KCONFIG_CONFIG='%s' FLASH_DEVICE='%s'"
              " flash" % (makedir, out, kconfig, device))

def do_sdcard(sdcard_method, device, out):
    # XXX - this is just dummy testing code - should import spi_flash code
    srcdir = os.path.dirname(os.path.realpath(__file__))
    kbin = os.path.join(out, "klipper.bin")
    os.system("%s/flash-sdcard.sh -f %s %s %s"
              % (srcdir, kbin, device, sdcard_method))

def do_flash(flash_type, device, kconfig, out):
    # XXX - this is just dummy testing targets
    if flash_type == "makeflash":
        do_makeflash(device, kconfig, out)
    elif flash_type.startswith('sdcard,'):
        do_sdcard(flash_type[7:], device, out)


######################################################################
# Startup
######################################################################

def main():
    usage = "%prog [options]"
    opts = optparse.OptionParser(usage)
    opts.add_option("-T", "--listtype", action="store_true",
                    help="list available flash types")
    opts.add_option("-D", "--listdevice", action="store_true",
                    help="list available target devices")
    opts.add_option("-t", "--type", type="string", dest="flash_type",
                    help="flash method to attempt")
    opts.add_option("-d", "--device", type="string", dest="device",
                    help="device to flash")
    opts.add_option("-k", "--kconfig", type="string", dest="kconfig",
                    help="kconfig file of build")
    opts.add_option("-o", "--out", type="string", dest="out",
                    help="build directory")
    options, args = opts.parse_args()
    if len(args) != 0:
        opts.error("Incorrect number of arguments")
    if options.listtype:
        list_flash_types()
        return
    if options.flash_type not in get_flash_types():
        opts.error("Must specify a valid flash type")
    if options.listdevice:
        list_devices(options.flash_type)
        return
    if not options.device or not options.kconfig or not options.out:
        opts.error("Must specify device, kconfig, and out options")
    do_flash(options.flash_type, options.device, options.kconfig, options.out)

if __name__ == '__main__':
    main()
