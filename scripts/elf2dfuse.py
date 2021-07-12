#! /usr/bin/env python2
from __future__ import with_statement

#
# Please read: http://rc.fdr.hu/UM0391.pdf for a description of the
# dfuse file format.
#
# usage: elf2dfuse.py infile outfile

import os
import subprocess
import tempfile
import sys
import struct
import subprocess
import zlib


def mk_uint8(x):
    return struct.pack("<B", x)


def mk_uint16(x):
    return struct.pack("<H", x)


def mk_uint32(x):
    return struct.pack("<I", x)


def compute_crc(data):
    return 0xFFFFFFFF & -zlib.crc32(data) - 1


def read_file(file):
    with open(file) as f:
        return f.read()


def write_file(file, content):
    with open(file, "w") as f:
        f.write(content)


def try_delete_file(file):
    try:
        os.remove(file)
    except OSError, e:
        if e.errno != 2:
            raise


def check(val):
    if not val:
        raise Exception("Check failed!")


def elf_to_binary_data(infile):
    binfile = tempfile.mkstemp(prefix=os.path.basename(infile),
                               suffix=".bin")[1]
    try:
        check(subprocess.call(['arm-none-eabi-objcopy',
                               '-Obinary',
                               infile,
                               binfile]) == 0)
        return read_file(binfile)
    finally:
        try_delete_file(binfile)


infile = sys.argv[1]
outfile = sys.argv[2]

# Get the input file's data
image_data = elf_to_binary_data(infile)

# Get the start address
image_addr = -1
proc = subprocess.Popen(['arm-none-eabi-nm', infile], stdout=subprocess.PIPE)
for l in proc.stdout:
    tokens = l.split()
    if len(tokens) == 3 and tokens[2] == 'VectorTable':
        image_addr = int(tokens[0], 16)
check(image_addr != -1)

# Generate the .dfuse file. Only tested with dfu-util. Annoying fields
# are not filled out.

# DFU Prefix
out = "DfuSe"       # szSignature:  Magic
out += mk_uint8(1)   # bVersion:     Version
out += mk_uint32(0)  # DFUImageSize: Total file size. Not Used.
out += mk_uint8(1)   # bTargets:     Number of targets that follow

# Single DFU Image
# Target prefix
# szSignature:                 Magic
# bAlternateSetting:           Alternate setting to program on
# bTargetNamed + szTargetName: No name for this target
# dwTargetSize:                Size of the image for this target
# dwNbElements:                Number of elements that make up the image
out += "Target"
out += mk_uint8(0)
out += 259 * mk_uint8(0)
out += mk_uint32(len(image_data))
out += mk_uint32(1)

# Single Image Element
# dwElementAddress: Address at which to load this element
# dwElementSize:    Size of the element to load
# Data:             The actual data to write
out += mk_uint32(image_addr)
out += mk_uint32(len(image_data))
out += image_data

# DFU Suffix
out += mk_uint16(0xFFFF)    # bcdDevice
out += mk_uint16(0xFFFF)    # idProduct
out += mk_uint16(0xFFFF)    # idVendor
out += mk_uint16(0x011a)    # bcdDFU: DFU version
out += "UFD"                # ucDFUSignature
out += mk_uint8(16)         # bLength: Length of suffix
out += mk_uint32(compute_crc(out))   # dwCRC:

# Erase temporary files at shutdown
with open(outfile, "wb") as f:
    f.write(out)
    try_delete_file(outfile)
print('DFuse file: {}'.format(outfile))
