# Support for ST7789V (240x320 graphics) LCD displays
#
# Copyright (C) 2021  Matthew Lloyd <github@matthewlloyd.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import sys
import numpy
import time
from PIL import Image, ImageChops, ImageDraw
from .. import bus
from . import font8x14, logo

BACKGROUND_PRIORITY_CLOCK = 0x7fffffff00000000
MAX_FLUSH_DURATION_S = 0.050
MAX_FLUSH_BYTES = 16384

# Screen size
ST7789V_ROWS = 320
ST7789V_COLS = 240
ST7789V_FONT_WIDTH   =  8
ST7789V_FONT_HEIGHT  = 16

# Commands
ST7789V_CMD_SLPIN     = 0x10
ST7789V_CMD_SLPOUT    = 0x11
ST7789V_CMD_INVOFF    = 0x20  # Display Inversion Off
ST7789V_CMD_INVON     = 0x21  # Display Inversion On
ST7789V_CMD_GAMMA_SET = 0x26  # gamma set (see ST7789V_GAMMA_CURVE*)
ST7789V_CMD_DISPOFF   = 0x28
ST7789V_CMD_DISPON    = 0x29
ST7789V_CMD_CASET     = 0x2A
ST7789V_CMD_RASET     = 0x2B
ST7789V_CMD_RAMWR     = 0x2C
ST7789V_CMD_RAMRD     = 0x2E
ST7789V_CMD_MADCTL    = 0x36
ST7789V_CMD_IDMOFF    = 0x37  # Idle Mode Off
ST7789V_CMD_IDMON     = 0x38  # Idle Mode On
ST7789V_CMD_COLMOD    = 0x3A
ST7789V_CMD_RAMWRC    = 0x3C
ST7789V_CMD_WRDISBV   = 0x51  # Write Display Brightness
ST7789V_CMD_RDDISBV   = 0x52  # Read Display Brightness Value
ST7789V_CMD_WRCTRLD   = 0x53  # Write CTRL Display (see ST7789V_MASK_CTRLD_*)
ST7789V_CMD_RDCTRLD   = 0x54  # Read CTRL Value Display

ST7789V_GAMMA_CURVE0 = 0x01
ST7789V_GAMMA_CURVE1 = 0x02
ST7789V_GAMMA_CURVE2 = 0x04
ST7789V_GAMMA_CURVE3 = 0x08

# ST7789V CTRL Display
ST7789V_MASK_CTRLD_BCTRL = 1 << 5  # Brightness Control Block
ST7789V_MASK_CTRLD_DD    = 1 << 3  # Display Dimming
ST7789V_MASK_CTRLD_BL    = 1 << 2  # Backlight Control

TextGlyphs = { 'right_arrow': '\x1a', 'degrees': '\xf8' }

class DisplayBase:
    def __init__(self, send):
        self.send = send
        self.logo = None
        # Our notion of what's currently in the remote VRAM.
        self.remote_vram = Image.new('RGB', (ST7789V_COLS, ST7789V_ROWS),
                                     color=(255, 255, 255))
        # Our local framebuffer, set to a different color so we know it
        # needs to be transmitted.
        self.vram = Image.new('RGB', (ST7789V_COLS, ST7789V_ROWS),
                              color=(0, 0, 0))
        # The bounding box of VRAM that needs flushing (writing to the LCD).
        self.invalidated_bbox = [0, 0, ST7789V_COLS, ST7789V_ROWS]
        # Draw the Klipper logo, and arrange the regular Klipper UI below
        # with a small border.
        x1, y1, x2, y2 = self.render_logo()
        self.ui_width_chars = (
            ST7789V_COLS - 2 * ST7789V_FONT_WIDTH) // ST7789V_FONT_WIDTH
        self.ui_height_chars = (
            ST7789V_ROWS - y2 - 2 * ST7789V_FONT_HEIGHT) // ST7789V_FONT_HEIGHT
        ui_border_x = (
            ST7789V_COLS - self.ui_width_chars * ST7789V_FONT_WIDTH) / 2
        self.ui_top_left = (
            ui_border_x,
            ST7789V_ROWS - (self.ui_height_chars + 1) * ST7789V_FONT_HEIGHT)
        self.ui_bottom_right = (
            self.ui_top_left[0] + self.ui_width_chars * ST7789V_FONT_WIDTH,
            self.ui_top_left[1] + self.ui_height_chars * ST7789V_FONT_HEIGHT)
        self.ui_size = (
            self.ui_bottom_right[0] - self.ui_top_left[0],
            self.ui_bottom_right[1] - self.ui_top_left[1])
        self.font = [self._rowmajor_bitmap_to_image(b)
                     for b in font8x14.VGA_FONT]
        self.icons = {}
    def x_y_to_offset(self, x, y):
        return y * ST7789V_COLS + x
    def offset_to_x_y(self, offset):
        return offset % ST7789V_COLS, offset // ST7789V_COLS
    def ui_c_r_to_x_y(self, c, r):
        return (self.ui_top_left[0] + c * ST7789V_FONT_WIDTH,
                self.ui_top_left[1] + r * ST7789V_FONT_HEIGHT)
    def _rowmajor_bitmap_to_image(self, b, width=8):
        return Image.frombytes('1', (width, len(b) / (width / 8)), b)
    def rgb_to_565(self, rgb):
        r = rgb[0] >> 3 & 0x1f
        g = rgb[1] >> 2 & 0x3f
        b = rgb[2] >> 3 & 0x1f
        return (r << 11) + (g << 5) + b
    def flush(self):
        start_time = time.time()
        if self.invalidated_bbox is None:
            return
        total_bytes_sent = 0
        # Find all changes in the "vram" and send them to the chip.
        # First perform a fast short-circuit equality check.
        equal = self.remote_vram.tobytes() == self.vram.tobytes()
        if equal:
            self.invalidated_bbox = None
            return
        # Examine strips of rows matching the font height.
        strip_height = ST7789V_FONT_HEIGHT
        start_x = self.invalidated_bbox[0]
        start_y = (self.invalidated_bbox[1] // strip_height) * strip_height
        end_x = self.invalidated_bbox[2]
        end_y = ((self.invalidated_bbox[3] // strip_height) + 1) * strip_height
        # ImageChops.difference is expensive, so only compare invalidated parts.
        diff = ImageChops.difference(
            self.remote_vram.crop((start_x, start_y, end_x, end_y)),
            self.vram.crop((start_x, start_y, end_x, end_y)))
        for row in range(start_y, end_y, strip_height):
            # Crop down the diff to just the strip.
            strip_diff = diff.crop(
                (0,
                 row - start_y,
                 end_x - start_x,
                 row - start_y + strip_height))

            # Fast short-circuit equality check.
            equal = not any(strip_diff.tobytes())
            if equal:
                continue

            # Convert to an RGB NumPy array for speed.
            arr = numpy.fromstring(strip_diff.tobytes(), dtype=numpy.uint8)
            arr = arr.reshape((strip_diff.size[1], strip_diff.size[0], 3))

            # Find indices of columns that have changed within this strip.
            changed_cols = arr.any(axis=2).any(axis=0)
            cols = numpy.nonzero(changed_cols)[0]
            if len(cols) == 0:
                continue

            # Determine ranges of columns to transmit, joining sections
            # to avoid unnecessary RASET/CASET instructions, but skipping
            # large gaps that have not changed.
            max_gap_to_join = 4
            first_col = last_col = cols[0]
            i = 1
            while i == 1 or i <= len(cols):
                if i < len(cols) and cols[i] - last_col <= max_gap_to_join:
                    last_col = cols[i]
                    i += 1
                    continue

                # Transmit the strip from first_col to last_col.
                strip = self.vram.crop((
                    start_x + first_col, row,
                    start_x + last_col + 1, row + strip_height))

                # Convert the image to an array of bytes.
                data = numpy.fromstring(strip.tobytes(), dtype=numpy.uint8)
                # Convert from RGB888 (24-bit) to RGB565 (16-bit).
                data565 = numpy.zeros((data.shape[0] / 3,), dtype=numpy.uint16)
                data565[:] += \
                    ((data[0::3] >> 3) & 0x1f).astype(numpy.uint16) << 11
                data565[:] += \
                    ((data[1::3] >> 2) & 0x3f).astype(numpy.uint16) << 5
                data565[:] += \
                    ((data[2::3] >> 3) & 0x1f).astype(numpy.uint16)
                # Convert to big endian format if needed.
                if sys.byteorder == 'little':
                    data565[:] = (data565[:] >> 8) + ((data565[:] & 0xff) << 8)
                out = map(ord, data565.tobytes())

                # Set the write window, then send the actual data.
                self.cmd_raset(row, row + strip_height - 1)
                self.cmd_caset(start_x + first_col, start_x + last_col)
                self.cmd(ST7789V_CMD_RAMWR)
                self.write_data(out)
                total_bytes_sent += len(out)

                # Update our image of the remote VRAM to reflect what we
                # transmitted.
                self.remote_vram.paste(strip, (start_x + first_col, row))

                if i < len(cols):
                    first_col = last_col = cols[i]
                i += 1

            # Take a break at least every 50ms or 16KB transmitted to
            # prevent display updates choking and stalling the MCU.
            if (time.time() > start_time + MAX_FLUSH_DURATION_S
                    or total_bytes_sent > MAX_FLUSH_BYTES):
                # Reduce invalidated portion so we don't waste time.
                flushed_through_y = row + strip_height
                if flushed_through_y >= self.invalidated_bbox[3]:
                    # The bbox is now empty.
                    self.invalidated_bbox = None
                elif flushed_through_y >= self.invalidated_bbox[1]:
                    self.invalidated_bbox[1] = flushed_through_y
                # Return false to signal the flush is not complete.
                return self.invalidated_bbox is None

        # Flush is complete.
        self.invalidated_bbox = None
        return True
    def _invalidate(self, xy, size):
        if self.invalidated_bbox is None:
            self.invalidated_bbox = [
                xy[0], xy[1], xy[0] + size[0], xy[1] + size[1]]
        else:
            self.invalidated_bbox = [
                min(self.invalidated_bbox[0], xy[0]),
                min(self.invalidated_bbox[1], xy[1]),
                max(self.invalidated_bbox[2], xy[0] + size[0]),
                max(self.invalidated_bbox[3], xy[1] + size[1])]
    def write_text(self, x, y, data):
        width = self.get_dimensions()[0]
        if x + len(data) > width:
            data = data[:width - min(x, width)]
        for i, char in enumerate(data):
            self.vram.paste(self.font[ord(char)], self.ui_c_r_to_x_y(x + i, y))
        self._invalidate(
            self.ui_c_r_to_x_y(x, y),
            (len(data) * ST7789V_FONT_WIDTH, ST7789V_FONT_HEIGHT))
    def write_graphics(self, x, y, data):
        im = self._rowmajor_bitmap_to_image(
            numpy.array(data, dtype=numpy.uint8), 8)
        xy = self.ui_c_r_to_x_y(x, y)
        self.vram.paste(im, xy)
        self._invalidate(xy, im.size)
    def set_glyphs(self, glyphs):
        for glyph_name, glyph_data in glyphs.items():
            # icon[0] contains MSBs, icon[1] contains LSBs
            icon = glyph_data.get('icon16x16')
            if icon is not None:
                arr = numpy.zeros( (len(icon[0]),), dtype=numpy.uint16)
                if sys.byteorder == 'little':
                    arr += numpy.array(icon[0], dtype=numpy.uint16)
                    arr += numpy.array(icon[1], dtype=numpy.uint16) << 8
                else:
                    arr += numpy.array(icon[0], dtype=numpy.uint16) << 8
                    arr += numpy.array(icon[1], dtype=numpy.uint16)
                self.icons[glyph_name] = self._rowmajor_bitmap_to_image(
                    arr.tobytes(), width=16)
    def write_glyph(self, x, y, glyph_name):
        icon = self.icons.get(glyph_name)
        xy = self.ui_c_r_to_x_y(x, y)
        if icon is not None and x < self.get_dimensions()[0] - 2:
            # Draw icon in graphics mode.
            self.vram.paste(icon, box=xy)
            self._invalidate(xy, icon.size)
            return 2
        char = TextGlyphs.get(glyph_name)
        if char is not None:
            # Draw character.
            self.vram.paste(self.font[ord(char)], box=xy)
            self._invalidate(xy, (ST7789V_FONT_WIDTH, ST7789V_FONT_HEIGHT))
            return 1
        return 0
    def clear(self):
        # Fill with black, avoiding the static logo.
        draw = ImageDraw.Draw(self.vram)
        draw.rectangle((self.ui_top_left, self.ui_bottom_right), fill=(0, 0, 0))
        self._invalidate(self.ui_top_left, self.ui_size)
    def get_dimensions(self):
        return self.ui_width_chars, self.ui_height_chars
    def render_logo(self):
        logo_width = ST7789V_COLS / 2
        if self.logo is None:
            self.logo = logo.make_logo(logo_width)
        x_pos = (ST7789V_COLS - logo_width) / 2
        y_pos = 0
        self.vram.paste(self.logo, box=(x_pos, y_pos), mask=self.logo)
        self._invalidate((x_pos, y_pos), self.logo.size)
        return x_pos, y_pos, x_pos + self.logo.width, y_pos + self.logo.height


class ST7789V(DisplayBase):
    def __init__(self, config):
        # We retain direct control of the "CS pin", since the chip uses it to
        # signal command vs data.
        self.spi = bus.MCU_SPI_from_config(
            config, 0, default_speed=3000000, use_cs_pin=False)
        self.cs_pin = bus.MCU_bus_digital_out(
            self.spi.get_mcu(), config.get('cs_pin'),
            self.spi.get_command_queue())
        self.cs_pin_state = None
        self.rs_pin = bus.MCU_bus_digital_out(
            self.spi.get_mcu(), config.get('rs_pin'),
            self.spi.get_command_queue())
        self.rs_pin_state = None
        self.mcu_reset = bus.MCU_bus_digital_out(
            self.spi.get_mcu(), config.get("rst_pin"),
            self.spi.get_command_queue())
        DisplayBase.__init__(self, None)
    def set_cs(self, val):
        if val is None:
            return
        if self.cs_pin_state != val:
            self.cs_pin_state = val
            self.cs_pin.update_digital_out(
                val, reqclock=BACKGROUND_PRIORITY_CLOCK)
    def set_rs(self, val):
        if val is None:
            return
        if self.rs_pin_state != val:
            self.rs_pin_state = val
            self.rs_pin.update_digital_out(
                val, reqclock=BACKGROUND_PRIORITY_CLOCK)
    def cmd(self, cmd, data=None):
        old_cs = self.cs_pin_state
        self.set_cs(0)
        self.set_rs(0)
        self.spi.spi_send([cmd], reqclock=BACKGROUND_PRIORITY_CLOCK)
        if data is not None:
            self.set_rs(1)
            self.spi.spi_send(data, reqclock=BACKGROUND_PRIORITY_CLOCK)
        self.set_cs(old_cs)
    def write_data(self, data):
        if data is None or len(data) == 0:
            return
        old_cs = self.cs_pin_state
        self.set_cs(0)
        self.set_rs(1)
        # Up to 56 bytes works here, 58 does not. The MCU command will include
        # a 3 byte command prefix, a 3 byte header, and a 2 byte trailer.
        # 56 + 3 + 3 + 2 = 64 bytes. The MCU's USB code accepts only up to 64.
        max_length = 56
        while len(data) > 0:
            datapart = data[:max_length]
            self.spi.spi_send(datapart, reqclock=BACKGROUND_PRIORITY_CLOCK)
            data = data[max_length:]
        self.set_cs(old_cs)
    def cmd_caset(self, x, cx):
        self.cmd(ST7789V_CMD_CASET, [x >> 8, x & 0xff, cx >> 8, cx & 0xff])
    def cmd_raset(self, y, cy):
        self.cmd(ST7789V_CMD_RASET, [y >> 8, y & 0xff, cy >> 8, cy & 0xff])
    def init(self):
        mcu = self.mcu_reset.get_mcu()
        curtime = mcu.get_printer().get_reactor().monotonic()
        print_time = mcu.estimated_print_time(curtime)
        self.set_cs(1)
        self.set_rs(1)
        # Toggle the reset line. Start with a 5ms high prelude.
        self.mcu_reset.update_digital_out(
            1, minclock=mcu.print_time_to_clock(print_time))
        print_time += 0.005
        # 15ms reset (low) pulse.
        self.mcu_reset.update_digital_out(
            0, minclock=mcu.print_time_to_clock(print_time))
        print_time += 0.015
        self.mcu_reset.update_digital_out(
            1, minclock=mcu.print_time_to_clock(print_time))
        # 10ms wait to allow the controller time to reset.
        print_time += 0.010
        self.mcu_reset.update_digital_out(
            1, minclock=mcu.print_time_to_clock(print_time))
        # Wake the controller up and wait 10ms.
        self.cmd(ST7789V_CMD_SLPOUT)
        print_time += 0.010
        self.mcu_reset.update_digital_out(
            1, minclock=mcu.print_time_to_clock(print_time))
        # Set control registers.
        # Memory data access control (mirror XY).
        self.cmd(ST7789V_CMD_MADCTL, [0xC0])
        # Interface pixel format (5-6-5, hi-color).
        self.cmd(ST7789V_CMD_COLMOD, [0x05])
        # Turn on the display and wait 10ms.
        self.cmd(ST7789V_CMD_DISPON)
        print_time += 0.010
        self.mcu_reset.update_digital_out(
            1, minclock=mcu.print_time_to_clock(print_time))
