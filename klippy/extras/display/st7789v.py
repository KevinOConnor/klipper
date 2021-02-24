# Support for ST7789V (240x320 graphics) LCD displays
#
# Copyright (C) 2020  Martijn van Buul <martijn.van.buul@gmail.com>
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import math
from . import font8x14
from .. import bus
import logging

BACKGROUND_PRIORITY_CLOCK = 0x7fffffff00000000

# Recovery time after reset
ST7789_RESET_DELAY = 0.200 # min. 150 ms according to manual
ST7789_MINIMAL_DELAY = 0.100 # min. 5 ms according to manual

MAX_BYTES_IN_REQUEST = 48      # max payload to encode in a single request.
MAX_BYTES_TO_KEEP_PENDING = 45 # max payload to keep pending.

MAX_ROW = 240
MAX_COLUMN = 320

TEXTGLYPHS = {
    'right_arrow': '\x1a',
    'degrees': '\xf8',
    'left_arrow' : '\x1b'}

class ST7789vParseException(Exception):
    def __init__(self, value):
        super(ST7789vParseException, self).__init__(value)
        self.value = value

def _parse_rect(rect_string):
    components = rect_string.split(',')

    try:
        elements = tuple(int(math.floor(float(p.strip()))) for p in components)
    except ValueError:
        raise ST7789vParseException("Malformed rectangle '%s'"
                                    % (rect_string,))

    if len(elements) != 4:
        raise ST7789vParseException("Malformed rectangle '%s'"
                                    % (rect_string,))
    for i in range(0, len(elements) - 1):
        if (elements[i] < 0 or
           ( (i%1 == 1) and elements[i] > MAX_ROW) or
           ( (i%1 == 0) and elements[i] > MAX_COLUMN)):
            raise ST7789vParseException("Rectangle '%s' outside display"
                                        % (rect_string,))

    return {
        'left': elements[0],
        'top' : elements[1],
        'right' : elements[2],
        'bottom' : elements[3]}

def _parse_color(color_string):
    components = color_string.split(',')

    try:
        elements = tuple(max(0, min(255, math.floor(float(p.strip()))))
                         for p in components)
    except ValueError:
        raise ST7789vParseException("Malformed color '%s'" % (color_string,))

    if len(elements) != 3:
        raise ST7789vParseException("Malformed color '%s'" % (color_string,))

    # convert to RGB565
    _r = int(elements[0])
    _g = int(elements[1])
    _b = int(elements[2])

    color = ((_r // 8) << 11) | ((_g // 4) << 5) | (_b // 8)
    return color

def _parse_glyph(data):
    glyph_data = []
    width = None
    height = 0

    for line in data.split('\n'):
        line = line.strip().replace('.', '0').replace('*', '1')
        if not line:
            continue
        height = height + 1
        if width is None:
            width = len(line)
        elif len(line) != width or line.replace('0', '').replace('1', ''):
            raise ST7789vParseException("Invalid glyph line %d" % (height,))

        linedata = bytearray((width+7) // 8)
        index = 0
        while line:
            this_chunk = line[0:8]
            line = line[8:]

            # pad chunk if less than 8 pixels wide
            chunk_length = len(this_chunk)
            if chunk_length != 8:
                this_chunk += '0' * (8 - chunk_length)

            linedata[index] = int(this_chunk, 2)
            index += 1

        glyph_data.append(linedata)

    return glyph_data, width, height

class ResetHelper(object):
    def __init__(self, disp, resx_pin, csx_pin, rdx_pin, mcu, cmd_queue):
        self.mcu_csx = None
        self.mcu_rdx = None
        self.display = disp

        self.mcu = mcu
        self.cmd_queue = cmd_queue

        self.mcu_resx = bus.MCU_bus_digital_out(
            self.mcu,
            resx_pin,
            self.cmd_queue)

        if csx_pin is not None:
            self.mcu_csx = bus.MCU_bus_digital_out(
                self.mcu,
                csx_pin,
                self.cmd_queue)

        if rdx_pin is not None:
            self.mcu_rdx = bus.MCU_bus_digital_out(
                self.mcu,
                rdx_pin,
                self.cmd_queue)

    def init(self):
        curtime = self.mcu.get_printer().get_reactor().monotonic()

        print_time = self.mcu.estimated_print_time(curtime)
        print_time += ST7789_MINIMAL_DELAY

        minclock = self.mcu.print_time_to_clock(print_time)
        self.mcu_resx.update_digital_out(0, minclock=minclock)

        if self.mcu_rdx is not None or self.mcu_csx is not None:
            print_time = print_time + ST7789_MINIMAL_DELAY
            minclock = self.mcu.print_time_to_clock(print_time)
            if self.mcu_rdx is not None:
                self.mcu_rdx.update_digital_out(1, minclock=minclock)
                self.mcu_csx.update_digital_out(0, minclock=minclock)

        print_time = print_time + ST7789_MINIMAL_DELAY
        minclock = self.mcu.print_time_to_clock(print_time)
        self.mcu_resx.update_digital_out(1, minclock=minclock)

        # Force a delay on the command queue before transmitting
        # the sleep out command
        print_time = print_time + ST7789_RESET_DELAY
        minclock = self.mcu.print_time_to_clock(print_time)
        self.mcu_resx.update_digital_out(1, minclock=minclock)

        self.display.send([[0x11]]) # Sleep out

        # Force a delay on the command queue before transmitting
        # any subsequent commands.
        print_time = print_time + ST7789_MINIMAL_DELAY
        minclock = self.mcu.print_time_to_clock(print_time)
        self.mcu_resx.update_digital_out(1, minclock=minclock)

class PixelRunIterator(object):
    def __init__(self, pixeldata, width):
        self.data = pixeldata
        self.current_bit = 0x80
        self.next_index = 1
        self.current_byte = self.data[0]
        self.remaining = width

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining == 0:
            raise StopIteration

        thisbit = self.peekbit()
        count = 1

        while self.advance():
            if self.peekbit() != thisbit:
                break
            count = count + 1

        return thisbit, count
    def next(self): # python 2 compatibility
        return self.__next__()

    def peekbit(self):
        return ((self.current_byte & self.current_bit) != 0)

    def advance(self):
        self.remaining -= 1

        if self.remaining == 0:
            return False

        self.current_bit >>= 1
        if self.current_bit == 0:
            self.current_bit = 0x80
            if self.next_index >= len(self.data):
                self.current_byte = 0
            else:
                self.current_byte = self.data[self.next_index]
            self.next_index += 1
        return True

class PackBitsStream(object):
    LITERAL=-1
    LITERAL_DCX=-2
    def __init__(self, oid, send_cmd):
        self.oid = oid
        self.send_cmd = send_cmd
        self.buffer = bytearray()

    def add_command(self, data):
        self._extend_buffer(PackBitsStream.LITERAL_DCX, data)

    def add_literal_data(self, data):
        data_len = len(data)
        for write_pos in range(0, data_len, 64):
            nr_bytes = min(64, data_len - write_pos)
            self._extend_buffer(PackBitsStream.LITERAL,
                                data[write_pos: write_pos + nr_bytes])

    def add_repeating_data(self, runlength, data):
        while runlength > 0:
            section = min(129, runlength)
            runlength -= section
            self._extend_buffer(section, data)

    def _extend_buffer(self, header, data):
        if not data:
            return
        remaining = MAX_BYTES_IN_REQUEST - len(self.buffer) - 1

        if len(data) > remaining:
            # data will not fit
            if header == PackBitsStream.LITERAL:
                self._extend_buffer(PackBitsStream.LITERAL,
                                    data[:remaining])
                self._extend_buffer(PackBitsStream.LITERAL, data[remaining:])
            elif header == PackBitsStream.LITERAL_DCX:
                # Assert DCX on first write
                self._extend_buffer(PackBitsStream.LITERAL_DCX,
                                    data[:remaining])
                self._extend_buffer(PackBitsStream.LITERAL, data[remaining:])
            else:
                # flush and try again
                self.flush()
                self._extend_buffer(header, data)
        else:
            if header == PackBitsStream.LITERAL:
                self.buffer.append(len(data) + 63)
            elif header == PackBitsStream.LITERAL_DCX:
                self.buffer.append(len(data) - 1)
            else:
                self.buffer.append(header + 126) # repeat
            self.buffer.extend(data)

            if len(self.buffer) >= MAX_BYTES_TO_KEEP_PENDING:
                self.flush()

    def flush(self):
        if self.buffer:
            self.send_cmd.send([self.oid, self.buffer],
                            reqclock=BACKGROUND_PRIORITY_CLOCK)
            self.buffer = bytearray()

class BitmapWriterHelper(object):
    def __init__(self, display, fgcolor, bgcolor, start_x, end_x, end_y):
        self.stream = PackBitsStream(display.oid, display.send_cmd)
        self.fgcolor = fgcolor
        self.bgcolor = bgcolor

        self.last_row = None
        self.start_x = start_x
        self.end_x = end_x - 1 # CASET end column is included!
        self.end_y = end_y - 1 # RASET end row is included!
        self.width = end_x - start_x
        self.literal_buffer = None

        self.caset_sent = False

    def flush(self):
        if self.caset_sent:
            self._flush_literal_buffer()
            self.stream.flush()

    def _flush_literal_buffer(self):
        if not self.literal_buffer:
            return

        self.stream.add_literal_data(self.literal_buffer)

        self.literal_buffer = None

    def write(self, row, data):
        if not self.last_row or self.last_row+1 != row:
            # Do not continue previous row
            self._flush_literal_buffer()
            if not self.caset_sent:
                self.stream.add_command([0x2A, # CASET
                                         self.start_x >>8, self.start_x & 0xff,
                                         self.end_x >> 8, self.end_x & 0xff])
                self.caset_sent = True

            self.stream.add_command([0x2b, # RASET
                                     0, row, 0, self.end_y])
            self.stream.add_command([0x2c]) # data, no continuation

        self.last_row = row

        for is_foreground, runlength in PixelRunIterator(data, self.width):
            value = self.fgcolor if is_foreground else self.bgcolor

            hi = value >> 8
            lo = value & 0xff

            if runlength < 2:
                if not self.literal_buffer:
                    self.literal_buffer = bytearray([hi, lo])
                else:
                    self.literal_buffer.extend([hi, lo])
            else:
                self._flush_literal_buffer()
                self.stream.add_repeating_data(runlength, [hi, lo])
class Framebuffer(object):
    def __init__(self, display, origin_x, origin_y,
                 size_x, size_y, fgcolor, bgcolor):
        self.size_x = size_x
        self.display = display
        self.size_y = size_y
        self.origin_x = origin_x
        self.end_x = origin_x + size_x
        self.origin_y = origin_y
        self.fgcolor = fgcolor
        self.bgcolor = bgcolor
        self.icons = {}

        self.framebuffer = self.__makebuffer()
        self.old_framebuffer = [None for _i in range(self.size_y)]

        self.nr_columns = size_x // 8
        self.nr_rows = size_y // 16

    def __makebuffer(self):
        return [bytearray((self.size_x+7)//8) for _i in range(self.size_y)]

    def flush(self):
        writer = BitmapWriterHelper(
            self.display, self.fgcolor, self.bgcolor,
            self.origin_x, self.end_x, self.size_y + self.origin_y)

        for row in range(self.size_y):
            old_row = self.old_framebuffer[row]
            new_row = self.framebuffer[row]
            if old_row is None or old_row != new_row:
                writer.write(row + self.origin_y, new_row)

        writer.flush()
        self.old_framebuffer[:] = self.framebuffer

    def write_glyph(self, _x, _y, glyph_name):
        icon = self.icons.get(glyph_name)
        if icon is not None and _x < self.nr_columns - 1:
            # Draw icon in graphics mode
            for icondata in icon:
                self.write_graphics(_x, _y, icondata)
                _x += 1

            return 2
        char = TEXTGLYPHS.get(glyph_name)
        if char is not None:
            # Draw character
            self.write_text(_x, _y, char)
            return 1
        return 0

    def clear(self):
        self.framebuffer = self.__makebuffer()

    def set_glyphs(self, glyphs):
        for glyph_name, glyph_data in glyphs.items():
            icon = glyph_data.get('icon16x16')
            if icon is not None:
                self.icons[glyph_name] = icon

    def write_text(self, _x, _y, data):
        if _x + len(data) > self.nr_columns:
            data = data[:self.nr_columns - min(_x, self.nr_columns)]

        top_row = 16 * _y

        for char in data:
            font_char = font8x14.VGA_FONT[ord(char)]
            for row in range(14):
                self.framebuffer[top_row + row][_x] = font_char[row]
            _x += 1

    def write_graphics(self, _x, _y, data):
        top_row = _y * 16

        for row, content in enumerate(data):
            self.framebuffer[top_row + row][_x] = content

    def write_bitmap(self, _x, _y, bitmap):
        if not bitmap:
            return

        shift_bits = _x & 7
        carry_bits = 8 - shift_bits

        start_column = _x // 8

        for row, row_data in enumerate(bitmap):
            output_row = self.framebuffer[_y+row]
            carry = output_row[start_column] & (0xff << carry_bits)
            nr_columns = min(len(row_data), self.size_x - start_column)

            for col in range(nr_columns):
                output_row[start_column + col] = (
                    carry | (row_data[col] >> shift_bits))
                carry = (row_data[col] << carry_bits) & 0xff

            if shift_bits > 0:
                # Write out carry, but avoid writing beyond the end of the row.
                end_column = nr_columns + start_column
                if end_column < self.size_x:
                    output_row[end_column] = (
                        (output_row[end_column] & (0xff >> shift_bits)) | carry)

    def get_dimensions(self):
        return (self.nr_columns, self.nr_rows)

class ST7789VButton(object):
    def __init__(self, display, config):
        if config['rect'] is None:
            raise ST7789vParseException("Missing rect")

        if config['fgcolor'] is None:
            raise ST7789vParseException("Missing fgcolor")

        if config['bgcolor'] is None:
            raise ST7789vParseException("Missing bgcolor")

        if config['glyph'] is None:
            raise ST7789vParseException("Missing glyph")

        rect = _parse_rect(config['rect'])
        fgcolor = _parse_color(config['fgcolor'])
        bgcolor = _parse_color(config['bgcolor'])

        glyph, glyph_width, glyph_height = _parse_glyph(config['glyph'])

        top = rect['top']
        left = rect['left']
        width = rect['right'] - left
        height = rect['bottom'] - top

        self._framebuffer = Framebuffer(display,
                                        left, top,
                                        width, height,
                                        fgcolor, bgcolor)

        glyph_x = (width - glyph_width) // 2
        glyph_y = (height - glyph_height) // 2

        self._framebuffer.write_bitmap(glyph_x, glyph_y, glyph)

    def flush(self):
        self._framebuffer.flush()

class ST7789V(object):
    def __init__(self, config):
        printer = config.get_printer()

        try:
            self.fgcolor = _parse_color(config.get("fgcolor", "255,255,255"))
        except ST7789vParseException as err:
            raise config.error(("Error while parsing st7789v fgcolor: %s")
                               %(err.value,))

        try:
            self.bgcolor = _parse_color(config.get("bgcolor", "0,0,0"))
        except ST7789vParseException as err:
            raise config.error(("Error while parsing st7789v bgcolor: %s")
                               %(err.value,))


        # pin config
        ppins = printer.lookup_object('pins')

        # mandatory pins
        pins = {name:ppins.lookup_pin(config.get(name + '_pin'))
                for name in ['dcx', 'wrx', 'd8', 'd9', 'd10',
                             'd11', 'd12', 'd13', 'd14', 'd15']}

        mcu = None
        for pin_params in pins.values():
            if mcu is not None and pin_params['chip'] != mcu:
                raise ppins.error("st7789 all pins must be on same mcu")
            mcu = pin_params['chip']
        self.pins = {
            name:pin_params['pin'] for name, pin_params in pins.iteritems()
        }
        self.mcu = mcu
        self.oid = self.mcu.create_oid()
        self.mcu.register_config_callback(self.build_config)
        self.cmd_queue = self.mcu.alloc_command_queue()
        self.send_cmd = None
        self.bitmap_cmd = None

        self.reset = ResetHelper(
            self,
            config.get('resx_pin', None),
            config.get('csx_pin', None),
            config.get('rdx_pin', None),
            mcu,
            self.cmd_queue)

        try:
            menu_rect = _parse_rect(config.get('rect'))
        except ST7789vParseException as err:
            raise config.error(("Error while parsing st7789v rect: %s")
                               %(err.value,))

        self.menu_framebuffer = Framebuffer(self,
                                            menu_rect['left'],
                                            menu_rect['top'],
                                            menu_rect['right'],
                                            menu_rect['bottom'],
                                            self.fgcolor, self.bgcolor)

        # discover soft buttons
        self.__soft_buttons = []

        for i in range(999):
            button_config = {
                'rect' : config.get('button%d_rect' %(i,), None),
                'fgcolor' : config.get('button%d_fgcolor'%(i,), None),
                'bgcolor' : config.get('button%d_bgcolor'%(i,), None),
                'glyph' : config.get('button%d_glyph'%(i,), None)
            }

            if None not in button_config.values():
                try:
                    self.__soft_buttons.append(
                        ST7789VButton(self, button_config))
                except ST7789vParseException as err:
                    raise config.error(
                        "Error while parsing st7789v button %d: %s"
                        %(i, err.value))
            else:
                break

    def build_config(self):
        self.mcu.add_config_cmd(
            "config_st7789v oid=%u dcx_pin=%s wrx_pin=%s d8_pin=%s"
            " d9_pin=%s d10_pin=%s d11_pin=%s d12_pin=%s d13_pin=%s"
            " d14_pin=%s d15_pin=%s" % (
                self.oid, self.pins['dcx'], self.pins['wrx'], self.pins['d8'],
                self.pins['d9'], self.pins['d10'], self.pins['d11'],
                self.pins['d12'], self.pins['d13'], self.pins['d14'],
                self.pins['d15']
                )
            )

        self.send_cmd = self.mcu.lookup_command(
            "st7789v_send_cmd oid=%c data=%*s", cq=self.cmd_queue)

    def send(self, cmds):
        stream = PackBitsStream(self.oid, self.send_cmd)

        for cmd in cmds:
            stream.add_command(cmd)

        stream.flush()

    def flush(self):
        self.menu_framebuffer.flush()

    def init(self):
        self.reset.init()

        # Initialisation sequence from marlin
        # Lines idicated with an asterisk (*) indicate where registers are
        # written with reset defaults according to the manual.
        init_cmds = [[0xB2, 0x0c, 0x00, 0x33, 0x33], # Porch control  (*)
                     [0xB7, 0x35], # Gate control                     (*)
                     [0xBB, 0x1f], # Voltage compensation, 0.875V
                     [0xC0, 0x2c], # LCM CTRL                         (*)
                     #[0xC2, 0x01, 0xC3], # VDVVRHEN, marlin setting illegal?
                     [0xC4, 0x20], # VDV set, 0V                      (*)
                     [0xC6, 0x0f], # FRCTL2, 60 Hz                    (*)
                     [0xD0, 0xA4, 0xA1], # PCTRL1, nonstandard?
                     [0x36, 0xA0], # MADCTL, depends on orientation,
                                   # RGB, MV MX
                     [0x3A, 0x55], # COLMOD, 16 bpp
                     [0x13]] # Normal display mode

        self.send(init_cmds)

        # Fill screen in black
        intermediate_buffer = Framebuffer(self, 0, 0, 320, 240, 0, 0)
        intermediate_buffer.flush()

        self.menu_framebuffer.flush()

        for button in self.__soft_buttons:
            button.flush()

        self.send([[0x29]]) # display on

    def set_glyphs(self, glyphs):
        self.menu_framebuffer.set_glyphs(glyphs)

    def write_text(self, _x, _y, data):
        self.menu_framebuffer.write_text(_x, _y, data)

    def write_graphics(self, _x, _y, data):
        self.menu_framebuffer.write_graphics(_x, _y, data)

    def write_glyph(self, _x, _y, glyph_name):
        return self.menu_framebuffer.write_glyph(_x, _y, glyph_name)

    def clear(self):
        self.menu_framebuffer.clear()

    def get_dimensions(self):
        return self.menu_framebuffer.get_dimensions()
