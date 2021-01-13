# Support for ST7789V (240x320 graphics) LCD displays
#
# Copyright (C) 2020  Martijn van Buul <martijn.van.buul@gmail.com>
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import math
from . import font8x14
from .. import bus

BACKGROUND_PRIORITY_CLOCK = 0x7fffffff00000000

# Recovery time after reset
ST7789_RESET_DELAY = 0.200 # min. 150 ms according to manual
ST7789_MINIMAL_DELAY = 0.100 # min. 5 ms according to manual

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

class BitmapWriterHelper(object):
    def __init__(self, display, fgcolor, bgcolor):
        self.oid = display.oid
        self.bitmap_cmd = display.bitmap_cmd
        self.fgcolor = fgcolor
        self.bgcolor = bgcolor
        self.max_bytes_in_request = 60
        self.buffer = None
        self.use_continuation = False
        self.reset()

    def reset(self):
        self.buffer = bytearray(0)
        self.use_continuation = False

    def flush(self):
        if self.buffer:
            self.bitmap_cmd.send([self.oid, self.use_continuation,
                                  self.fgcolor, self.bgcolor, self.buffer])
            self.reset()

    def write(self, data):
        self.buffer.extend(data)
        if len(self.buffer) >= self.max_bytes_in_request:
            self.bitmap_cmd.send([self.oid, self.use_continuation,
                                  self.fgcolor, self.bgcolor,
                                  self.buffer[0:self.max_bytes_in_request]])
            self.buffer = self.buffer[self.max_bytes_in_request:]
            self.use_continuation = True

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
        caset_sent = False
        last_row = None
        writer = BitmapWriterHelper(
            self.display, self.fgcolor, self.bgcolor)

        for row in range(self.size_y):
            old_row = self.old_framebuffer[row]
            new_row = self.framebuffer[row]
            if old_row is None or old_row != new_row:
                if not caset_sent:
                    # CASET 0-319
                    caset_cmd = [[0x2A,
                                  self.origin_x >> 8, self.origin_x & 0xff,
                                  self.end_x >> 8, self.end_x & 0xff]]
                    self.display.send(caset_cmd)
                    caset_sent = True

                if last_row is None or last_row != row + 1:
                    # Flush existing data, send RASET
                    writer.flush()
                    raset_cmd = [[0x2B,
                                  0, row + self.origin_y, 0x0,
                                  row + self.origin_y + 1]]
                    self.display.send(raset_cmd)

                last_row = row
                writer.write(new_row)

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

        self.__framebuffer = Framebuffer(display,
                                         left, top,
                                         width + 1, height + 1,
                                         fgcolor, bgcolor)

        glyph_x = (width - glyph_width) // 2
        glyph_y = (height - glyph_height) // 2

        self.__framebuffer.write_bitmap(glyph_x, glyph_y, glyph)

    def flush(self):
        self.__framebuffer.flush()

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
            "st7789v_send_cmd oid=%c cmds=%*s", cq=self.cmd_queue)
        self.bitmap_cmd = self.mcu.lookup_command(
            "st7789v_bitmap oid=%c cont=%c fg=%hu bg=%hu data=%*s",
            cq=self.cmd_queue)

    def send(self, cmds):
        for cmd in cmds:
            self.send_cmd.send([self.oid, cmd],
                               reqclock=BACKGROUND_PRIORITY_CLOCK)

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
