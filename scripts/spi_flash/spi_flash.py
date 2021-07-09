#!/usr/bin/env python2
# Module supporting uploads Klipper firmware to an SD Card via SPI
#
# Copyright (C) 2021 Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import sys
import argparse
import os
import zlib
import hashlib
import logging
import collections
import time
import traceback
import json
import board_defs
import fatfs_lib
import reactor
import serialhdl
import clocksync
import mcu

###########################################################
#
# Helper methods
#
###########################################################

def output_line(msg):
    sys.stdout.write("%s\n" % (msg,))
    sys.stdout.flush()

def output(msg):
    sys.stdout.write("%s" % (msg,))
    sys.stdout.flush()

def calc_crc7(data):
    # G(x) = x^7 + x^3 + 1
    # Shift left as we are only calculating a 7 bit CRC
    poly = 0b10001001 << 1
    crc = 0
    for b in data:
        crc ^= b & 0xFF
        for i in range(8):
            crc = (crc << 1) ^ poly if crc & 0x80 else crc << 1
    # The sdcard protocol likes the crc left justfied with a
    # padded bit
    return crc | 1

def calc_crc16(data):
    poly = 0b10001000000100001
    crc = 0
    for b in data:
        crc ^= (b & 0xFF) << 8
        for i in range(8):
            crc = (crc << 1) ^ poly if crc & 0x8000 else crc << 1
    return crc & 0xFFFF

# Translate a serial device name to a stable serial name in
# /dev/serial/by-path/
# Borrowed from  klipper/scripts/flash_usb.py
def translate_serial_to_tty(device):
    ttyname = os.path.realpath(device)
    if os.path.exists('/dev/serial/by-path/'):
        for fname in os.listdir('/dev/serial/by-path/'):
            fname = '/dev/serial/by-path/' + fname
            if os.path.realpath(fname) == ttyname:
                return ttyname, fname
    return ttyname, ttyname

def check_need_convert(board_name, config):
    if board_name.lower().startswith('mks-robin-e3'):
        # we need to convert this file
        robin_util = os.path.join(
            fatfs_lib.KLIPPER_DIR, "scripts/update_mks_robin.py")
        klipper_bin = config['klipper_bin_path']
        robin_bin = os.path.join(
            os.path.dirname(klipper_bin),
            os.path.basename(config['firmware_path']))
        cmd = "%s %s %s %s" % (sys.executable, robin_util, klipper_bin,
                               robin_bin)
        output("Converting Klipper binary to MKS Robin format...")
        os.system(cmd)
        output_line("Done")
        config['klipper_bin_path'] = robin_bin


###########################################################
#
# SPI FLash Implementation
#
###########################################################

SPI_OID = 0
SPI_MODE = 0
SD_SPI_SPEED = 4000000
# MCU Command Constants
RESET_CMD = "reset"
GET_CFG_CMD = "get_config"
GET_CFG_RESPONSE = "config is_config=%c crc=%u move_count=%hu is_shutdown=%c"
ALLOC_OIDS_CMD = "allocate_oids count=%d"
SPI_CFG_CMD = "config_spi oid=%d pin=%s"
SPI_BUS_CMD = "spi_set_bus oid=%d spi_bus=%s mode=%d rate=%d"
SW_SPI_BUS_CMD = "spi_set_software_bus oid=%d " \
    "miso_pin=%s mosi_pin=%s sclk_pin=%s mode=%d rate=%d"
SPI_SEND_CMD = "spi_send oid=%c data=%*s"
SPI_XFER_CMD = "spi_transfer oid=%c data=%*s"
SPI_XFER_RESPONSE = "spi_transfer_response oid=%c response=%*s"
FINALIZE_CFG_CMD = "finalize_config crc=%d"

class SPIFlashError(Exception):
    pass

class SPIDirect:
    def __init__(self, ser):
        self.oid = SPI_OID
        self._spi_send_cmd = mcu.CommandWrapper(ser, SPI_SEND_CMD)
        self._spi_transfer_cmd = mcu.CommandQueryWrapper(
            ser, SPI_XFER_CMD, SPI_XFER_RESPONSE, self.oid)

    def spi_send(self, data):
        self._spi_send_cmd.send([self.oid, data])

    def spi_transfer(self, data):
        return self._spi_transfer_cmd.send([self.oid, data])


# FatFs Constants. Enums are implemented as lists. The item's index is its value
DRESULT = ['RES_OK', 'RES_ERROR', 'RES_WRPRT', 'RES_NOTRDY', 'RES_PARERR']
FRESULT = [
    'FR_OK', 'FR_DISK_ERR', 'FR_INT_ERR', 'FR_NOT_READY', 'FR_NO_FILE',
    'FR_NO_PATH', 'FR_INVALID_NAME', 'FR_DENIED', 'FR_EXIST',
    'FR_INVALID_OBJECT', 'FR_WRITE_PROTECTED', 'FR_INVALID_DRIVE',
    'FR_NOT_ENABLED', 'FR_NO_FILESYSTEM', 'FR_MKFS_ABORTED', 'FR_TIMEOUT',
    'FR_LOCKED', 'FR_NOT_ENOUGH_CORE', 'FR_TOO_MANY_OPEN_FILES',
    'FR_INVALID_PARAMETER'
]
FS_TYPES = {1: "FAT12", 2: "FAT16", 3: "FAT32", 4: "EXFAT"}
STA_NO_INIT = 1 << 0
STA_NO_DISK = 1 << 1
STA_WRITE_PROTECT = 1 << 2
SECTOR_SIZE = 512

# FAT16/32 File System Support
class FatFS:
    def __init__(self, ser):
        self.sdcard = SDCardSPI(ser)
        self.disk_status = STA_NO_INIT | STA_NO_DISK
        self.ffi_callbacks = []
        self.ffi_main, self.ffi_lib = fatfs_lib.get_fatfs_ffi()
        self._register_callbacks()

    def _register_callbacks(self):
        status_cb = self.ffi_main.callback(
            "uint8_t(void)", self._fatfs_cb_status)
        init_cb = self.ffi_main.callback(
            "uint8_t(void)", self._fatfs_cb_initialize)
        read_cb = self.ffi_main.callback(
            "uint8_t(uint8_t*, uint32_t, unsigned int)",
            self._fatfs_cb_disk_read)
        write_cb = self.ffi_main.callback(
            "uint8_t(const uint8_t*, uint32_t, unsigned int)",
            self._fatfs_cb_disk_write)
        ioctl_cb = self.ffi_main.callback(
            "uint8_t(uint8_t, void*)", self._fatfs_cb_disk_ioctl)
        ftime_cb = self.ffi_main.callback(
            "uint32_t(void)", self._fatfs_cb_get_fattime)
        # Keep a reference to the callbacks so they don't get gc'ed
        self.ffi_callbacks = [status_cb, init_cb, read_cb, write_cb,
                              ioctl_cb, ftime_cb]
        self.ffi_lib.fatfs_set_callbacks(
            status_cb, init_cb, read_cb, write_cb, ioctl_cb, ftime_cb)

    def clear_callbacks(self):
        self.ffi_lib.fatfs_clear_callbacks()
        self.ffi_callbacks = []

    def _fatfs_cb_status(self):
        return self.disk_status

    def _fatfs_cb_initialize(self):
        try:
            self.sdcard.init_sd()
        except Exception:
            logging.exception("flash_sdcard: error initializing sdcard")
            self.disk_status = STA_NO_INIT
        else:
            self.disk_status = 0
            if self.sdcard.write_protected:
                self.disk_status |= STA_WRITE_PROTECT
        return self.disk_status

    def _fatfs_cb_disk_read(self, readbuf, sector, count):
        start = 0
        end = SECTOR_SIZE
        for sec in range(sector, sector + count, 1):
            tries = 3
            buf = None
            while True:
                try:
                    buf = self.sdcard.read_sector(sec)
                except Exception:
                    tries -= 1
                    if not tries:
                        logging.exception("SD Card Read Error")
                        break
                else:
                    break
            if buf is None:
                return DRESULT.index("RES_ERROR")
            readbuf[start:end] = list(buf)
            start = end
            end += SECTOR_SIZE
        return 0

    def _fatfs_cb_disk_write(self, writebuf, sector, count):
        start = 0
        end = SECTOR_SIZE
        for sec in range(sector, sector + count, 1):
            tries = 3
            while True:
                try:
                    self.sdcard.write_sector(sec, writebuf[start:end])
                except Exception:
                    tries -= 1
                    if not tries:
                        logging.exception("SD Card Write Error")
                        return DRESULT.index("RES_ERROR")
                else:
                    break
            start = end
            end += SECTOR_SIZE
        return 0

    def _fatfs_cb_disk_ioctl(self, cmd, buff):
        # The Current FatFS configuration does not require
        # this module to take any actions for incoming IOCTL
        # commands.
        ioctl_cmds = [
            'CTRL_SYNC', 'GET_SECTOR_COUNT', 'GET_SECTOR_SIZE',
            'GET_BLOCK_SIZE', 'CTRL_TRIM']
        logging.debug("flash_sdcard: Received IOCTL command %s"
                      % (ioctl_cmds[cmd]))
        return 0

    def _fatfs_cb_get_fattime(self):
        tobj = time.localtime()
        year = tobj[0] - 1980
        sec = min(tobj[5], 59) // 2
        return (year << 25) | (tobj[1] << 21) | (tobj[2] << 16) \
            | (tobj[3] << 11) | (tobj[4] << 5) | sec

    def mount(self, print_func=logging.info):
        ret = self.ffi_lib.fatfs_mount()
        if ret == 0:
            self.sdcard.print_card_info(print_func)
            dinfo = self.get_disk_info()
            for key, val in sorted(dinfo.items(), key=lambda x: x[0]):
                print_func("%s: %s" % (key, val))
        else:
            raise OSError("flash_sdcard: failed to mount SD Card, returned %s"
                          % (FRESULT[ret]))

    def unmount(self):
        self.ffi_lib.fatfs_unmount()
        self.sdcard.deinit()
        self.disk_status = STA_NO_INIT | STA_NO_DISK

    def open_file(self, sd_path, mode="r"):
        sdf = SDCardFile(self.ffi_main, self.ffi_lib, sd_path, mode)
        sdf.open()
        return sdf

    def remove_item(self, sd_path):
        # Can be path to directory or file
        ret = self.ffi_lib.fatfs_remove(sd_path)
        if ret != 0:
            raise OSError("flash_sdcard: Error deleting item at path '%s',"
                          " result: %s"
                          % (sd_path, FRESULT[ret]))

    def get_file_info(self, sd_file_path):
        finfo = self.ffi_main.new("struct ff_file_info *")
        ret = self.ffi_lib.fatfs_get_fstats(finfo, sd_file_path)
        if ret != 0:
            raise OSError(
                "flash_sdcard: Failed to retreive file info for path '%s',"
                " result: %s"
                % (sd_file_path, FRESULT[ret],))
        return self._parse_ff_info(finfo)

    def list_sd_directory(self, sd_dir_path):
        flist = self.ffi_main.new("struct ff_file_info[128]")
        ret = self.ffi_lib.fatfs_list_dir(flist, 128, sd_dir_path)
        if ret != 0:
            raise OSError("flash_sdcard: Failed to retreive file list at path"
                          " '%s', result: %s"
                          % (sd_dir_path, FRESULT[ret],))
        convlist = []
        for f in flist:
            if f.size == 0 and f.modified_date == 0 and f.modified_time == 0:
                # Empty record indicates end of list
                break
            convlist.append(self._parse_ff_info(f))
        return convlist

    def _parse_ff_info(self, finfo):
        fdate = finfo.modified_date
        ftime = finfo.modified_time
        dstr = "%d-%d-%d %d:%d:%d" % (
            (fdate >> 5) & 0xF, fdate & 0x1F, ((fdate >> 9) & 0x7F) + 1980,
            (ftime >> 11) & 0x1F, (ftime >> 5) & 0x3F, ftime & 0x1F)
        return {
            'name': self.ffi_main.string(finfo.name, 13),
            'size': finfo.size,
            'modified': dstr,
            'is_dir': bool(finfo.attrs & 0x10),
            'is_read_only': bool(finfo.attrs & 0x01),
            'is_hidden': bool(finfo.attrs & 0x02),
            'is_system': bool(finfo.attrs & 0x04)
        }

    def get_disk_info(self):
        disk_info = self.ffi_main.new("struct ff_disk_info *")
        ret = self.ffi_lib.fatfs_get_disk_info(disk_info)
        if ret != 0:
            logging.info("flash_sdcard: Failed to retreive disk info: %s"
                         % (FRESULT[ret],))
            return {}
        return {
            'volume_label': self.ffi_main.string(disk_info.label, 12),
            'volume_serial': disk_info.serial_number,
            'fs_type': FS_TYPES.get(disk_info.fs_type, "UNKNOWN")
        }


SD_FILE_MODES = {
    'w+x': 0x01 | 0x02 | 0x04, 'wx': 0x02 | 0x04,
    'r+': 0x01 | 0x02, 'w+': 0x01 | 0x02 | 0x08,
    'a+': 0x01 | 0x02 | 0x30, 'r': 0x01,
    'w': 0x02 | 0x08, 'a': 0x02 | 0x30}

class SDCardFile:
    def __init__(self, ffi_main, ffi_lib, sd_path, mode="r"):
        self.ffi_main = ffi_main
        self.ffi_lib = ffi_lib
        self.path = sd_path
        mode = mode.lower()
        if mode[-1] == 'b':
            mode = mode[:-1]
        self.mode = SD_FILE_MODES.get(mode, 0)
        self.fhdl = None
        self.eof = False

    def open(self):
        if self.fhdl is not None:
            # already open
            return
        self.fhdl = self.ffi_lib.fatfs_open(self.path, self.mode)
        self.eof = False
        if self.fhdl == self.ffi_main.NULL:
            self.fhdl = None
            raise OSError("flash_sdcard: Could not open file '%s':"
                          % (self.path))

    def read(self, length=None):
        if self.fhdl is None:
            raise OSError("flash_sdcard: File '%s' not open" % (self.path))
        if self.eof:
            return b""
        ret_buf = b""
        full_read = False
        if length is None:
            # read until eof
            full_read = True
            length = 4096
        cdata_buf = self.ffi_main.new("uint8_t[]", length)
        byte_buf = self.ffi_main.buffer(cdata_buf)
        while True:
            bytes_read = self.ffi_lib.fatfs_read(self.fhdl, cdata_buf, length)
            if bytes_read < 0:
                raise OSError("flash_sdcard: Error Reading file '%s'"
                              % (self.path))
            self.eof = (bytes_read < length)
            ret_buf += byte_buf[0:bytes_read]
            if self.eof or not full_read:
                break
        return ret_buf

    def write(self, buf):
        if self.fhdl is None:
            raise OSError("flash_sdcard: File '%s' not open" % (self.path))
        if not buf:
            return 0
        cbuf = self.ffi_main.from_buffer(buf)
        bytes_written = self.ffi_lib.fatfs_write(self.fhdl, cbuf, len(cbuf))
        if bytes_written < 0:
            # Disk Full or some other error
            raise OSError("flash_sdcard: Error writing file '%s'" % (self.path))
        return bytes_written

    def close(self):
        if self.fhdl is not None:
            ret = self.ffi_lib.fatfs_close(self.fhdl)
            self.fhdl = None
            if ret != 0:
                logging.info("flash_sdcard: Error closing sd file '%s', "
                             "returned %d"
                             % (self.path, FRESULT[ret]))

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        self.close()


SD_COMMANDS = {
    'GO_IDLE_STATE': 0,
    'SEND_IF_COND': 8,
    'SEND_CSD': 9,
    'SEND_CID': 10,
    'SD_SEND_OP_COND': 41,
    'SEND_STATUS': 13,
    'SET_BLOCKLEN': 16,
    'READ_SINGLE_BLOCK': 17,
    'WRITE_BLOCK': 24,
    'APP_CMD': 55,
    'READ_OCR': 58,
    'CRC_ON_OFF': 59,
}

class SDCardSPI:
    def __init__(self, ser):
        self.spi = SPIDirect(ser)
        self.reactor = ser.get_reactor()
        self.enable_crc = True
        self.mutex = self.reactor.mutex()
        self.initialized = False
        self.sd_version = 0
        self.high_capacity = False
        self.write_protected = False
        self.total_sectors = 0
        self.card_info = collections.OrderedDict()

    def init_sd(self):
        with self.mutex:
            if self.initialized:
                return
            # Send reset command (CMD0)
            if not self._check_command(1, 'GO_IDLE_STATE', 0):
                raise OSError(
                    "flash_sdcard: failed to reset SD Card\n"
                    "Note that older (Version 1.0) SD cards can not be\n"
                    "hot swapped.  Execute FIRMWARE_RESTART with the card\n"
                    "inserted for successful initialization.")
            # Check Voltage Range (CMD8). Only Cards meeting the v2.0 spec
            # support this. V1.0 cards (and MMC) will return illegal command.
            check_pattern = 0b1010
            resp = self._send_command_with_response(
                'SEND_IF_COND', (1 << 8) | check_pattern)
            resp = resp.strip(b'\xFF')
            if resp and resp[0] & (1 << 2):
                # CMD8 is illegal, this is a version 1.0 card
                self.sd_version = 1
            elif len(resp) == 5:
                if resp[0] == 1:
                    self.sd_version = 2
                    if not (resp[-2] == 1 and resp[-1] == check_pattern):
                        raise OSError("flash_sdcard: SD Card not running in a "
                                      "compatible voltage range")
                else:
                    raise OSError("flash_sdcard: CMD8 Error 0x%X" % (resp[0],))
            else:
                raise OSError("flash_sdcard: Invalid CMD8 response: %s"
                              % (repr(resp)))
            if self.enable_crc:
                # Enable SD crc checks (CMD59)
                if not self._check_command(1, 'CRC_ON_OFF', 1):
                    logging.info("flash_sdcard: failed to enable CRC checks")
            if self.sd_version == 2:
                # Init card and come out of idle (ACMD41)
                # Version 2 Cards may init before checking the OCR
                if not self._check_command(0, 'SD_SEND_OP_COND', 1 << 30,
                                           is_app_cmd=True):
                    raise OSError("flash_sdcard: SD Card did not come"
                                  " out of IDLE after reset")
            # Read OCR Register (CMD58)
            resp = self._send_command_with_response('READ_OCR', 0)
            resp = resp.strip(b'\xFF')
            # If 'READ_OCR' is illegal then this is likely MMC.
            # At this time MMC is not supported
            if len(resp) == 5:
                if self.sd_version == 1 and resp[0] == 1:
                    # Check acceptable volatage range for V1 cards
                    if resp[2] != 0xFF:
                        raise OSError("flash_sdcard: card does not support"
                                      " 3.3v range")
                elif self.sd_version == 2 and resp[0] == 0:
                    # Determine if this is a high capacity sdcard
                    if resp[1] & 0x40:
                        self.high_capacity = True
                else:
                    raise OSError("flash_sdcard: READ_OCR Error 0x%X"
                                  % (resp[0],))
            else:
                raise OSError("flash_sdcard: Invalid OCR Response")
            if self.sd_version == 1:
                # Init card and come out of idle (ACMD41)
                # Version 1 Cards do this after checking the OCR
                if not self._check_command(0, 'SD_SEND_OP_COND', 0,
                                           is_app_cmd=True):
                    raise OSError("flash_sdcard: SD Card did not come"
                                  " out of IDLE after reset")

            # Set block size to 512 (CMD16)
            if self._check_command(0, 'SET_BLOCKLEN', SECTOR_SIZE, tries=5):
                self.initialized = True
            else:
                raise OSError("flash_sdcard: failed to set block size")
            # Read out CSD and CID information registers
            self._process_cid_reg()
            self._process_csd_reg()

    def deinit(self):
        with self.mutex:
            if self.initialized:
                # Reset the SD Card
                try:
                    if not self._check_command(1, 'GO_IDLE_STATE', 0):
                        logging.info("flash_sdcard: failed to reset SD Card")
                    # Disable CRC Checks
                    if not self._check_command(1, 'CRC_ON_OFF', 0):
                        logging.info("flash_sdcard: failed to disable CRC")
                except Exception:
                    logging.exception("Error resetting SD Card")
            self.initialized = False
            self.sd_version = 0
            self.high_capacity = False
            self.total_sectors = 0
            self.card_info.clear()

    def _check_command(self, expected, cmd, args, is_app_cmd=False, tries=15):
        func = self._send_app_cmd_with_response if is_app_cmd else \
            self._send_command_with_response
        while True:
            resp, rt = func(cmd, args, get_rt=True)
            # logging.info("flash_sdcard: Check cmd %s, response: %s"
            #              % (cmd, repr(resp)))
            resp = resp.strip(b'\xFF')
            if resp and expected == resp[0]:
                return True
            tries -= 1
            if tries < 1:
                return False
            self.reactor.pause(rt + .1)

    def _send_command(self, cmd, args):
        command = SD_COMMANDS[cmd] | 0x40
        request = [command]
        if isinstance(args, int):
            for i in range(3, -1, -1):
                request.append((args >> (8*i)) & 0xFF)
        elif isinstance(args, list) and len(args) == 4:
            request += args
        else:
            raise OSError("flash_sdcard: Invalid SD Card Command argument")
        crc = calc_crc7(request)
        request.append(crc)
        self.spi.spi_send(request)

    def _send_command_with_response(self, cmd, args, get_rt=False):
        self._send_command(cmd, args)
        params = self.spi.spi_transfer([0xFF]*8)
        if get_rt:
            return bytearray(params['response']), params['#receive_time']
        else:
            return bytearray(params['response'])

    def _send_app_cmd_with_response(self, cmd, args, get_rt=False):
        # CMD55 tells the SD Card that the next command is an
        # Application Specific Command.
        self._send_command_with_response('APP_CMD', 0)
        return self._send_command_with_response(cmd, args, get_rt)

    def _find_sd_token(self, token, tries=10):
        while tries:
            params = self.spi.spi_transfer([0xFF])
            resp = bytearray(params['response'])
            if resp[0] == token:
                return True
            tries -= 1
        return False

    def _find_sd_response(self, tries=10):
        while tries:
            params = self.spi.spi_transfer([0xFF])
            resp = bytearray(params['response'])
            if resp[0] != 0xFF:
                return resp[0]
            tries -= 1
        return 0xFF

    def _process_cid_reg(self):
        self._send_command('SEND_CID', 0)
        reg = self._do_block_read(size=16)
        if reg is None:
            raise OSError("flash_sdcard: Error reading CID register")
        cid = collections.OrderedDict()
        cid['manufacturer_id'] = reg[0]
        cid['oem_id'] = reg[1:3].decode(encoding='ascii', errors='ignore')
        cid['product_name'] = reg[3:8].decode(
            encoding='ascii', errors='ignore')
        cid['product_revision'] = str(reg[8] >> 4 & 0xFF) + "." \
            + str(reg[8] & 0xFF)
        cid['serial_number'] = "".join(["%02X" % (c,) for c in reg[9:13]])
        mfg_year = (((reg[13] & 0xF) << 4) | ((reg[14] >> 4) & 0xF)) + 2000
        mfg_month = reg[14] & 0xF
        cid['manufacturing_date'] = "%d/%d" % (mfg_month, mfg_year)
        crc = calc_crc7(reg[:15])
        if crc != reg[15]:
            raise OSError("flash_sdcard: CID crc mismatch: 0x%02X, recd: 0x%02X"
                          % (crc, reg[15]))
        self.card_info.update(cid)

    def _process_csd_reg(self):
        self._send_command('SEND_CSD', 0)
        reg = self._do_block_read(size=16)
        if reg is None:
            raise OSError("flash_sdcard: Error reading CSD register")
        str_capacity = "Invalid"
        max_capacity = 0
        csd_type = (reg[0] >> 6) & 0x3
        if csd_type == 0:
            # Standard Capacity (CSD Version 1.0)
            max_block_len = 2**(reg[5] & 0xF)
            c_size = ((reg[6] & 0x3) << 10) | (reg[7] << 2) | \
                ((reg[8] >> 6) & 0x3)
            c_mult = 2**((((reg[9] & 0x3) << 1) | (reg[10] >> 7)) + 2)
            max_capacity = (c_size + 1) * c_mult * max_block_len
            str_capacity = "%.1f MiB" % (max_capacity / (1024.0**2))
        elif csd_type == 1:
            # High Capacity (CSD Version 2.0)
            c_size = ((reg[7] & 0x3F) << 16) | (reg[8] << 8) | reg[9]
            max_capacity = (c_size + 1) * 512 * 1024
            str_capacity = "%.1f GiB" % (max_capacity / (1024.0**3))
        else:
            logging.info("sdcard: Unsupported csd type: %d" % (csd_type))
        self.write_protected = (reg[14] & 0x30) != 0
        crc = calc_crc7(reg[:15])
        if crc != reg[15]:
            raise OSError("flash_sdcard: CSD crc mismatch: 0x%02X, recd: 0x%02X"
                          % (crc, reg[15]))
        self.card_info['capacity'] = str_capacity
        self.total_sectors = max_capacity // SECTOR_SIZE

    def print_card_info(self, print_func=logging.info):
        print_func("\nSD Card Information:")
        print_func("Version: %.1f" % (self.sd_version))
        print_func("SDHC/SDXC: %s" % (self.high_capacity))
        print_func("Write Protected: %s" % (self.write_protected))
        print_func("Sectors: %d" % (self.total_sectors,))
        for name, val in self.card_info.items():
            print_func("%s: %s" % (name, val))

    def read_sector(self, sector):
        buf = None
        err_msg = "flash_sdcard: read error, sector %d" % (sector,)
        with self.mutex:
            if not 0 <= sector < self.total_sectors:
                err_msg += " out of range"
            elif not self.initialized:
                err_msg += ", SD Card not initialized"
            else:
                offset = sector
                if not self.high_capacity:
                    offset = sector * SECTOR_SIZE
                self._send_command('READ_SINGLE_BLOCK', offset)
                buf = self._do_block_read()
            if buf is None:
                raise OSError(err_msg)
            return buf

    def _do_block_read(self, size=SECTOR_SIZE):
        valid_response = True
        sd_resp = self._find_sd_response()
        if sd_resp != 0:
            logging.info("flash_sdcard: invalid read block response: 0x%02X"
                         % (sd_resp))
            valid_response = False
        if not self._find_sd_token(0xFE):
            logging.info("flash_sdcard: read error, unable to find "
                         "start token")
            valid_response = False
        if not valid_response:
            # In the event of an invalid response we will still
            # send 514 bytes to be sure that the sdcard's output
            # buffer is clear
            bcount = size + 2
            while bcount:
                sent = min(32, bcount)
                self.spi.spi_send([0xFF]*sent)
                bcount -= sent
            self._find_sd_token(0xFF)
            return None
        buf = bytearray()
        while len(buf) < size:
            count = min(32, size - len(buf))
            params = self.spi.spi_transfer([0xFF]*count)
            buf += bytearray(params['response'])
        # Get the CRC
        params = self.spi.spi_transfer([0xFF, 0xFF])
        # Make sure we leave the busy state
        self._find_sd_token(0xFF)
        crc = bytearray(params['response'])
        crc_int = (crc[0] << 8) | crc[1]
        calculated_crc = calc_crc16(buf)
        if calculated_crc != crc_int:
            logging.info(
                "flash_sdcard: CRC Mismatch, Received: %04X, Calculated: %04X"
                % (crc_int, calculated_crc))
            return None
        return buf

    def write_sector(self, sector, data):
        with self.mutex:
            if not 0 <= sector < self.total_sectors:
                raise OSError(
                    "flash_sdcard: write error, sector number %d invalid"
                    % (sector))
            if not self.initialized:
                raise OSError("flash_sdcard: write error, SD Card not"
                              " initialized")
            outbuf = bytearray(data)
            if len(outbuf) > SECTOR_SIZE:
                raise OSError("sd_card: Cannot write sector larger"
                              " than %d bytes"
                              % (SECTOR_SIZE))
            elif len(outbuf) < SECTOR_SIZE:
                outbuf += bytearray([0] * (SECTOR_SIZE - len(outbuf)))
            offset = sector
            if not self.high_capacity:
                offset = sector * SECTOR_SIZE
            if not self._check_command(0, 'WRITE_BLOCK', offset, tries=2):
                raise OSError("flash_sdcard: Error writing to sector %d"
                              % (sector,))
            crc = calc_crc16(outbuf)
            outbuf.insert(0, 0xFE)
            outbuf.append((crc >> 8) & 0xFF)
            outbuf.append(crc & 0xFF)
            while outbuf:
                self.spi.spi_send(outbuf[:32])
                outbuf = outbuf[32:]
            resp = self._find_sd_response()
            err_msgs = []
            if (resp & 0x1f) != 5:
                err_msgs.append("flash_sdcard: write error 0x%02X" % (resp,))
            # wait until the card leaves the busy state
            if not self._find_sd_token(0xFF, tries=128):
                err_msgs.append("flash_sdcard: could not leave busy"
                                " state after write")
            else:
                status = self._send_command_with_response('SEND_STATUS', 0)
                status = status.strip(b'\xFF')
                if len(status) == 2:
                    if status[1] != 0:
                        err_msgs.append(
                            "flash_sdcard:  write error 0x%02X"
                            % (status[1],))
                else:
                    err_msgs.append("flash_sdcard: Invalid status response"
                                    " after write: %s" % (repr(status),))
            if err_msgs:
                raise OSError("\n".join(err_msgs))

class MCUConnection:
    def __init__(self, k_reactor, device, baud, board_cfg):
        self.reactor = k_reactor
        self.serial_device = device
        self.baud = baud
        # TODO: a change in baudrate will cause an issue, come up
        # with a method for handling it gracefully
        self._serial = serialhdl.SerialReader(self.reactor)
        self.clocksync = clocksync.ClockSync(self.reactor)
        self.board_config = board_cfg
        self.fatfs = None
        self.connect_completion = None
        self.connected = False
        self.enumerations = {}
        self.raw_dictionary = None

    def connect(self):
        output("Connecting to MCU..")
        self.connect_completion = self.reactor.completion()
        self.connected = False
        self.reactor.register_callback(self._do_serial_connect)
        curtime = self.reactor.monotonic()
        while True:
            curtime = self.reactor.pause(curtime + 1.)
            output(".")
            if self.connect_completion.test():
                self.connected = self.connect_completion.wait()
                break
        self.connect_completion = None
        if not self.connected:
            output("\n")
            raise SPIFlashError("Unable to connect to MCU")
        output_line("Connected")
        msgparser = self._serial.get_msgparser()
        mcu_type = msgparser.get_constant('MCU')
        build_mcu_type = self.board_config['mcu']
        if mcu_type != build_mcu_type:
            raise SPIFlashError(
                "MCU Type mismatch: Build MCU = %s, Connected MCU = %s"
                % (build_mcu_type, mcu_type))
        self.enumerations = msgparser.get_enumerations()
        self.raw_dictionary = msgparser.get_raw_data_dictionary()

    def _do_serial_connect(self, eventtime):
        endtime = eventtime + 60.
        while True:
            try:
                self._serial.connect_uart(self.serial_device, self.baud)
                self.clocksync.connect(self._serial)
            except Exception:
                curtime = self.reactor.monotonic()
                if curtime > endtime:
                    self.connect_completion.complete(False)
                    return
                output("Connection Error, retrying..")
                self._serial.disconnect()
                self.reactor.pause(curtime + 2.)
            else:
                break
        self.connect_completion.complete(True)

    def reset(self):
        output("Attempting MCU Reset...")
        if self.fatfs is not None:
            self.fatfs.unmount()
            self.fatfs.clear_callbacks()
        # XXX: do we need to support other reset methods?
        self._serial.send(RESET_CMD)
        self.reactor.pause(self.reactor.monotonic() + 0.015)
        self.reactor.end()
        output_line("Done")

    def disconnect(self):
        if not self.connected:
            return
        self._serial.disconnect()
        self.connected = False

    def check_need_restart(self):
        output("Checking Current MCU Configuration...")
        get_cfg_cmd = mcu.CommandQueryWrapper(
            self._serial, GET_CFG_CMD, GET_CFG_RESPONSE)
        params = get_cfg_cmd.send()
        output_line("Done")
        if params['is_config'] or params['is_shutdown']:
            output_line("MCU needs restart: is_config=%d, is_shutdown=%d"
                        % (params['is_config'], params['is_shutdown']))
            return True
        return False

    def configure_mcu(self, printfunc=logging.info):
        # TODO: add commands for buttons?  Or perhaps an endstop?  We
        # just need to be able to query the status of the detect pin
        cs_pin = self.board_config['cs_pin'].upper()
        bus = self.board_config['spi_bus']
        bus_enums = self.enumerations.get(
            'spi_bus', self.enumerations.get('bus'))
        pin_enums = self.enumerations.get('pin')
        if bus == "swspi":
            cfgpins = self.board_config['spi_pins']
            pins = [p.strip().upper() for p in cfgpins.split(',') if p.strip()]
            pin_err_msg = "Invalid Software SPI Pins: %s" % (cfgpins,)
            if len(pins) != 3:
                raise SPIFlashError(pin_err_msg)
            for p in pins:
                if p not in pin_enums:
                    raise SPIFlashError(pin_err_msg)
            bus_cmd = SW_SPI_BUS_CMD % (SPI_OID, pins[0], pins[1], pins[2],
                                        SPI_MODE, SD_SPI_SPEED)
        else:
            if bus not in bus_enums:
                raise SPIFlashError("Invalid SPI Bus: %s" % (bus,))
            bus_cmd = SPI_BUS_CMD % (SPI_OID, bus, SPI_MODE, SD_SPI_SPEED)
        if cs_pin not in pin_enums:
            raise SPIFlashError("Invalid CS Pin: %s" % (cs_pin,))
        cfg_cmds = [
            ALLOC_OIDS_CMD % (1),
            SPI_CFG_CMD % (SPI_OID, cs_pin),
            bus_cmd,
        ]
        config_crc = zlib.crc32('\n'.join(cfg_cmds)) & 0xffffffff
        cfg_cmds.append(FINALIZE_CFG_CMD % (config_crc,))
        for cmd in cfg_cmds:
            self._serial.send(cmd)
        self.fatfs = FatFS(self._serial)
        self.reactor.pause(self.reactor.monotonic() + .5)
        printfunc("Initializing SD Card and Mounting file system...")
        try:
            self.fatfs.mount(printfunc)
        except OSError:
            logging.exception("SD Card Mount Failure")
            raise SPIFlashError(
                "Failed to Initialize SD Card. Is it inserted?")

    def sdcard_upload(self):
        output("Uploading Klipper Firmware to SD Card...")
        input_sha = hashlib.sha1()
        sd_sha = hashlib.sha1()
        klipper_bin_path = self.board_config['klipper_bin_path']
        fw_path = self.board_config.get('firmware_path', "firmware.bin")
        try:
            with open(klipper_bin_path, 'rb') as local_f:
                with self.fatfs.open_file(fw_path, "wb") as sd_f:
                    while True:
                        buf = local_f.read(4096)
                        if not buf:
                            break
                        input_sha.update(buf)
                        sd_f.write(buf)
        except Exception:
            logging.exception("SD Card Upload Error")
            raise SPIFlashError("Error Uploading Firmware")
        output_line("Done")
        output("Validating Upload...")
        try:
            finfo = self.fatfs.get_file_info(fw_path)
            with self.fatfs.open_file(fw_path, 'r') as sd_f:
                while True:
                    buf = sd_f.read(4096)
                    if not buf:
                        break
                    sd_sha.update(buf)
        except Exception:
            logging.exception("SD Card Download Error")
            raise SPIFlashError("Error reading %s from SD" % (fw_path))
        sd_size = finfo.get('size', -1)
        input_chksm = input_sha.hexdigest().upper()
        sd_chksm = sd_sha.hexdigest().upper()
        if input_chksm != sd_chksm:
            raise SPIFlashError("Checksum Mismatch: Got '%s', expected '%s'"
                                % (sd_chksm, input_chksm))
        output_line("Done")
        output_line(
            "Firmware Upload Complete: %s, Size: %d, Checksum (SHA1): %s"
            % (fw_path, sd_size, sd_chksm))
        return sd_chksm

    def verify_flash(self, req_chksm, old_dictionary, req_dictionary):
        output("Verifying Flash...")
        validation_passed = False
        msgparser = self._serial.get_msgparser()
        cur_dictionary = msgparser.get_raw_data_dictionary()
        # If we have a dictionary, check that it matches.
        if req_dictionary:
            if cur_dictionary != req_dictionary:
                raise SPIFlashError("Version Mismatch: Got '%s...', "
                                    "expected '%s...'"
                                    % (msgparser.get_version_info()[0],
                                       json.loads(req_dictionary)['version']))
            output("Version matched...")
            validation_passed = True
        # Otherwise check that the MCU dictionary changed
        elif cur_dictionary != old_dictionary:
            output("Version updated...")
            validation_passed = True
        else:
            output("Version unchanged...")
        # If the version didn't change, look for current firmware to checksum
        cur_fw_sha = None
        if not validation_passed:
            cur_fw_path = self.board_config.get('current_firmware_path',
                                                "FIRMWARE.CUR")
            try:
                with self.fatfs.open_file(cur_fw_path, 'r') as sd_f:
                    cur_fw_sha = hashlib.sha1()
                    while True:
                        buf = sd_f.read(4096)
                        if not buf:
                            break
                        cur_fw_sha.update(buf)
            except Exception:
                msg = "Failed to read file %s" % (cur_fw_path,)
                logging.debug(msg)
                output("Checksum skipped...")
            if cur_fw_sha is not None:
                cur_fw_chksm = cur_fw_sha.hexdigest().upper()
                if req_chksm == cur_fw_chksm:
                    validation_passed = True
                    output("Checksum matched...")
                else:
                    raise SPIFlashError("Checksum Mismatch: Got '%s', "
                                        "expected '%s'"
                                        % (cur_fw_chksm, req_chksm))
        if not validation_passed:
            raise SPIFlashError("Validation failure.")
        output_line("Done")
        # Remove firmware file if MCU bootloader failed to rename.
        if cur_fw_sha is None:
            try:
                fw_path = self.board_config.get('firmware_path', "firmware.bin")
                self.fatfs.remove_item(fw_path)
                output_line("Found and deleted %s after reset" % (fw_path,))
            except Exception:
                pass
        output_line("Firmware Flash Successful")
        output_line("Current Firmware: %s" % (msgparser.get_version_info()[0],))

class SPIFlash:
    def __init__(self, args):
        self.board_config = args
        if not os.path.exists(args['device']):
            raise SPIFlashError("No device found at '%s'" % (args['device'],))
        if not os.path.isfile(args['klipper_bin_path']):
            raise SPIFlashError("Unable to locate klipper binary at '%s'"
                                % (args['klipper_bin_path'],))
        tty_name, dev_by_path = translate_serial_to_tty(args['device'])
        self.device_path = dev_by_path
        self.baud_rate = args['baud']
        self.mcu_conn = None
        self.firmware_checksum = None
        self.task_complete = False
        self.need_upload = True
        self.old_dictionary = None
        self.new_dictionary = None
        if args['klipper_dict_path'] is not None:
            try:
                with open(args['klipper_dict_path'], 'rb') as dict_f:
                    self.new_dictionary = dict_f.read(32*1024)
            except Exception:
                raise SPIFlashError("Missing or invalid dictionary at '%s'"
                                    % (args['klipper_dict_path'],))

    def _wait_for_reconnect(self):
        output("Waiting for device to reconnect...")
        time.sleep(1.)
        if os.path.exists(self.device_path):
            # device is already available, this could be a UART
            time.sleep(2.)
        else:
            wait_left = 30
            while wait_left:
                time.sleep(1.)
                output(".")
                if os.path.exists(self.device_path):
                    break
                wait_left -= 1
            else:
                output_line("Error")
                raise SPIFlashError("Unable to reconnect")
        output_line("Done")

    def run_reset(self, eventtime):
        # Reset MCU to default state if necessary
        self.mcu_conn.connect()
        if self.mcu_conn.check_need_restart():
            self.mcu_conn.reset()
            self.task_complete = True
        else:
            self.need_upload = False
            self.run_sdcard_upload(eventtime)

    def run_sdcard_upload(self, eventtime):
        # Reconnect and upload
        if not self.mcu_conn.connected:
            self.mcu_conn.connect()
        self.old_dictionary = self.mcu_conn.raw_dictionary
        self.mcu_conn.configure_mcu(printfunc=output_line)
        self.firmware_checksum = self.mcu_conn.sdcard_upload()
        self.mcu_conn.reset()
        self.task_complete = True

    def run_verify(self, eventtime):
        # Reconnect and verify
        self.mcu_conn.connect()
        self.mcu_conn.configure_mcu()
        self.mcu_conn.verify_flash(self.firmware_checksum, self.old_dictionary,
                                   self.new_dictionary)
        self.mcu_conn.reset()
        self.task_complete = True

    def run_reactor_task(self, run_cb):
        self.task_complete = False
        k_reactor = reactor.Reactor()
        self.mcu_conn = MCUConnection(k_reactor, self.device_path,
                                      self.baud_rate, self.board_config)
        k_reactor.register_callback(run_cb)
        try:
            k_reactor.run()
        except SPIFlashError:
            raise
        except Exception:
            # ignore exceptions that occur after a task is complete
            if not self.task_complete:
                raise
        finally:
            self.mcu_conn.disconnect()
            k_reactor.finalize()
            self.mcu_conn = k_reactor = None

    def run(self):
        self.run_reactor_task(self.run_reset)
        self._wait_for_reconnect()
        if self.need_upload:
            self.run_reactor_task(self.run_sdcard_upload)
            self._wait_for_reconnect()
        self.run_reactor_task(self.run_verify)

def main():
    parser = argparse.ArgumentParser(
        description="SD Card Firmware Upload Utility")
    parser.add_argument(
        "-l", "--list", action="store_true",
        help="List Supported Boards")
    args = parser.parse_known_args()
    if args[0].list:
        blist = board_defs.list_boards()
        output_line("Available Boards:")
        for board in blist:
            output_line(board)
        return
    parser.add_argument(
        "-b", "--baud", metavar="<baud rate>", type=int,
        default=250000, help="Serial Baud Rate")
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose output")
    parser.add_argument(
        "-d", "--dict_path", metavar="<klipper.dict>", type=str,
        default=None, help="Klipper firmware dictionary")
    parser.add_argument(
        "device", metavar="<device>", help="Device Serial Port")
    parser.add_argument(
        "board", metavar="<board>", help="Board Type")
    parser.add_argument(
        "klipper_bin_path", metavar="<klipper.bin>",
        help="Klipper firmware binary")
    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.CRITICAL
    logging.basicConfig(level=log_level)
    flash_args = board_defs.lookup_board(args.board)
    if flash_args is None:
        output_line("Unable to find defintion for board: %s" % (args.board,))
        sys.exit(-1)
    flash_args['device'] = args.device
    flash_args['baud'] = args.baud
    flash_args['klipper_bin_path'] = args.klipper_bin_path
    flash_args['klipper_dict_path'] = args.dict_path
    check_need_convert(args.board, flash_args)
    fatfs_lib.check_fatfs_build(output)
    try:
        spiflash = SPIFlash(flash_args)
        spiflash.run()
    except Exception as e:
        output_line("\nSD Card Flash Error: %s" % (str(e),))
        traceback.print_exc(file=sys.stdout)
        sys.exit(-1)
    output_line("SD Card Flash Complete")


if __name__ == "__main__":
    main()
