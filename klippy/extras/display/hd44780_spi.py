# Support for HD44780 (20x4 text) LCD displays
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2018  Eric Callahan <arksine.code@gmail.com>
# Copyright (C) 2021  Marc-Andre Denis <marcadenis@msn.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
from .. import bus

LINE_LENGTH_DEFAULT="20"
LINE_LENGTH_OPTIONS={"16":16, "20":20}

TextGlyphs = { 'right_arrow': '\x7e' }



class hd44780_spi:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.hd44780_protocol_init = config.getboolean('hd44780_protocol_init',
            True)
        # spi config
        self.spi = bus.MCU_SPI_from_config(
            config, 0x00, pin_option="latch_pin")
        self.mcu = self.spi.get_mcu()
        #self.spi.spi_send([0x01,0xa0])
        self.data_mask = (1<<1)
        self.command_mask = 0
        self.enable_mask = (1<<3)

        self.icons = {}
        self.line_length = config.getchoice('line_length', LINE_LENGTH_OPTIONS,
            LINE_LENGTH_DEFAULT)

        # framebuffers
        self.text_framebuffers = [bytearray(' '*2*self.line_length),
                                  bytearray(' '*2*self.line_length)]
        self.glyph_framebuffer = bytearray(64)
        self.all_framebuffers = [
            # Text framebuffers
            (self.text_framebuffers[0], bytearray('~'*2*self.line_length),
              0x80),
            (self.text_framebuffers[1], bytearray('~'*2*self.line_length),
              0xc0),
            # Glyph framebuffer
            (self.glyph_framebuffer, bytearray('~'*64), 0x40) ]
    def send_4_bits(self, cmd, is_data, minclock):
        if is_data:
            mask = self.data_mask
        else:
            mask = self.command_mask
        self.spi.spi_send([(cmd & 0xF0) | mask], minclock)
        self.spi.spi_send([(cmd & 0xF0) | mask | self.enable_mask], minclock)
        self.spi.spi_send([(cmd & 0xF0) | mask], minclock)
    def send(self, cmds, is_data=False, minclock=0):
        for data in cmds:
            self.send_4_bits(data,is_data,minclock)
            self.send_4_bits(data<<4,is_data,minclock)
    def flush(self):
        # Find all differences in the framebuffers and send them to the chip
        for new_data, old_data, fb_id in self.all_framebuffers:
            if new_data == old_data:
                continue
            # Find the position of all changed bytes in this framebuffer
            diffs = [[i, 1] for i, (n, o) in enumerate(zip(new_data, old_data))
                     if n != o]
            # Batch together changes that are close to each other
            for i in range(len(diffs)-2, -1, -1):
                pos, count = diffs[i]
                nextpos, nextcount = diffs[i+1]
                if pos + 4 >= nextpos and nextcount < 16:
                    diffs[i][1] = nextcount + (nextpos - pos)
                    del diffs[i+1]
            # Transmit changes
            for pos, count in diffs:
                chip_pos = pos
                self.send([fb_id + chip_pos])
                self.send(new_data[pos:pos+count], is_data=True)
            old_data[:] = new_data
        return True
    def init(self):
        curtime = self.printer.get_reactor().monotonic()
        print_time = self.mcu.estimated_print_time(curtime)
        # Program 4bit / 2-line mode and then issue 0x02 "Home" command
        if self.hd44780_protocol_init:
            init = [[0x33], [0x33], [0x32], [0x28, 0x28, 0x02]]
        else:
            init = [[0x02]]
        # Reset (set positive direction ; enable display and hide cursor)
        init.append([0x06, 0x0c])
        for i, cmds in enumerate(init):
            minclock = self.mcu.print_time_to_clock(print_time + i * .100)
            self.send(cmds, minclock=minclock)
        self.flush()
    def write_text(self, x, y, data):
        if x + len(data) > self.line_length:
            data = data[:self.line_length - min(x, self.line_length)]
        pos = x + ((y & 0x02) >> 1) * self.line_length
        self.text_framebuffers[y & 1][pos:pos+len(data)] = data
    def set_glyphs(self, glyphs):
        for glyph_name, glyph_data in glyphs.items():
            data = glyph_data.get('icon5x8')
            if data is not None:
                self.icons[glyph_name] = data
    def write_glyph(self, x, y, glyph_name):
        data = self.icons.get(glyph_name)
        if data is not None:
            slot, bits = data
            self.write_text(x, y, [slot])
            self.glyph_framebuffer[slot * 8:(slot + 1) * 8] = bits
            return 1
        char = TextGlyphs.get(glyph_name)
        if char is not None:
            # Draw character
            self.write_text(x, y, char)
            return 1
        return 0
    def write_graphics(self, x, y, data):
        pass
    def clear(self):
        spaces = ' ' * 2*self.line_length
        self.text_framebuffers[0][:] = spaces
        self.text_framebuffers[1][:] = spaces
    def get_dimensions(self):
        return (self.line_length, 4)
