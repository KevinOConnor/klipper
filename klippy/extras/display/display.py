# Basic LCD display support
#
# Copyright (C) 2018-2020  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2018  Aleph Objects, Inc <marcio@alephobjects.com>
# Copyright (C) 2018  Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, os, ast
from . import hd44780, st7920, uc1701, menu

# Normal time between each screen redraw
REDRAW_TIME = 0.500
# Minimum time between screen redraws
REDRAW_MIN_TIME = 0.100

LCD_chips = {
    'st7920': st7920.ST7920, 'hd44780': hd44780.HD44780,
    'uc1701': uc1701.UC1701, 'ssd1306': uc1701.SSD1306, 'sh1106': uc1701.SH1106,
}

# Storage of [display_template my_template] config sections
class DisplayTemplate:
    def __init__(self, config):
        self.printer = config.get_printer()
        name_parts = config.get_name().split()
        if len(name_parts) != 2:
            raise config.error("Section name '%s' is not valid"
                               % (config.get_name(),))
        self.name = name_parts[1]
        self.params = {}
        for option in config.get_prefix_options('param_'):
            try:
                self.params[option] = ast.literal_eval(config.get(option))
            except ValueError as e:
                raise config.error(
                    "Option '%s' in section '%s' is not a valid literal" % (
                        option, config.get_name()))
        gcode_macro = self.printer.load_object(config, 'gcode_macro')
        self.template = gcode_macro.load_template(config, 'text')
    def render(self, context, **kwargs):
        params = dict(self.params)
        params.update(**kwargs)
        if len(params) != len(self.params):
            raise self.printer.command_error(
                "Invalid parameter to display_template %s" % (self.name,))
        context = dict(context)
        context.update(params)
        return self.template.render(context)

# Store [display_data my_group my_item] sections (one instance per group name)
class DisplayGroup:
    def __init__(self, config, name, data_configs):
        # Load and parse the position of display_data items
        items = []
        for c in data_configs:
            pos = c.get('position')
            try:
                row, col = [int(v.strip()) for v in pos.split(',')]
            except:
                raise config.error("Unable to parse 'position' in section '%s'"
                                   % (c.get_name(),))
            items.append((row, col, c.get_name()))
        # Load all templates and store sorted by display position
        configs_by_name = {c.get_name(): c for c in data_configs}
        printer = config.get_printer()
        gcode_macro = printer.load_object(config, 'gcode_macro')
        self.data_items = []
        for row, col, name in sorted(items):
            c = configs_by_name[name]
            if c.get('text'):
                template = gcode_macro.load_template(c, 'text')
                self.data_items.append((row, col, template))
    def show(self, display, templates, eventtime):
        context = self.data_items[0][2].create_template_context(eventtime)
        context['draw_progress_bar'] = display.draw_progress_bar
        def render(name, **kwargs):
            return templates[name].render(context, **kwargs)
        context['render'] = render
        for row, col, template in self.data_items:
            text = template.render(context)
            display.draw_text(row, col, text.replace('\n', ''), eventtime)
        context.clear() # Remove circular references for better gc

class PrinterLCD:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        # Load low-level lcd handler
        self.lcd_chip = config.getchoice('lcd_type', LCD_chips)(config)
        # Load menu and display_status
        self.menu = None
        name = config.get_name()
        if name == 'display':
            # only load menu for primary display
            self.menu = menu.MenuManager(config, self)
        self.printer.load_object(config, "display_status")
        # Configurable display
        self.display_templates = {}
        self.display_data_groups = {}
        self.load_config(config)
        dgroup = "_default_16x4"
        if self.lcd_chip.get_dimensions()[0] == 20:
            dgroup = "_default_20x4"
        dgroup = config.get('display_group', dgroup)
        self.show_data_group = self.display_data_groups.get(dgroup)
        if self.show_data_group is None:
            raise config.error("Unknown display_data group '%s'" % (dgroup,))
        # Screen updating
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.screen_update_timer = self.reactor.register_timer(
            self.screen_update_event)
        self.redraw_request_pending = False
        self.redraw_time = 0.
        # Register g-code commands
        gcode = self.printer.lookup_object("gcode")
        gcode.register_mux_command('SET_DISPLAY_GROUP', 'DISPLAY', name,
                                   self.cmd_SET_DISPLAY_GROUP,
                                   desc=self.cmd_SET_DISPLAY_GROUP_help)
        if name == 'display':
            gcode.register_mux_command('SET_DISPLAY_GROUP', 'DISPLAY', None,
                                       self.cmd_SET_DISPLAY_GROUP)
    def get_dimensions(self):
        return self.lcd_chip.get_dimensions()
    # Configurable display
    def _parse_glyph(self, config, glyph_name, data, width, height):
        glyph_data = []
        for line in data.split('\n'):
            line = line.strip().replace('.', '0').replace('*', '1')
            if not line:
                continue
            if len(line) != width or line.replace('0', '').replace('1', ''):
                raise config.error("Invalid glyph line in %s" % (glyph_name,))
            glyph_data.append(int(line, 2))
        if len(glyph_data) != height:
            raise config.error("Glyph %s incorrect lines" % (glyph_name,))
        return glyph_data
    def load_config(self, config):
        # Load default display config file
        pconfig = self.printer.lookup_object('configfile')
        filename = os.path.join(os.path.dirname(__file__), 'display.cfg')
        try:
            dconfig = pconfig.read_config(filename)
        except Exception:
            raise self.printer.config_error("Cannot load config '%s'"
                                            % (filename,))
        # Load display_template sections
        dt_main = config.get_prefix_sections('display_template ')
        dt_main_names = { c.get_name(): 1 for c in dt_main }
        dt_def = [c for c in dconfig.get_prefix_sections('display_template ')
                  if c.get_name() not in dt_main_names]
        for c in dt_main + dt_def:
            dt = DisplayTemplate(c)
            self.display_templates[dt.name] = dt
        # Load display_data sections
        dd_main = config.get_prefix_sections('display_data ')
        dd_main_names = { c.get_name(): 1 for c in dd_main }
        dd_def = [c for c in dconfig.get_prefix_sections('display_data ')
                  if c.get_name() not in dd_main_names]
        groups = {}
        for c in dd_main + dd_def:
            name_parts = c.get_name().split()
            if len(name_parts) != 3:
                raise config.error("Section name '%s' is not valid"
                                   % (c.get_name(),))
            groups.setdefault(name_parts[1], []).append(c)
        for group_name, data_configs in groups.items():
            dg = DisplayGroup(config, group_name, data_configs)
            self.display_data_groups[group_name] = dg
        # Load display glyphs
        dg_prefix = 'display_glyph '
        icons = {}
        dg_main = config.get_prefix_sections(dg_prefix)
        dg_main_names = {c.get_name(): 1 for c in dg_main}
        dg_def = [c for c in dconfig.get_prefix_sections(dg_prefix)
                  if c.get_name() not in dg_main_names]
        for dg in dg_main + dg_def:
            glyph_name = dg.get_name()[len(dg_prefix):]
            data = dg.get('data', None)
            if data is not None:
                idata = self._parse_glyph(config, glyph_name, data, 16, 16)
                icon1 = [(bits >> 8) & 0xff for bits in idata]
                icon2 = [bits & 0xff for bits in idata]
                icons.setdefault(glyph_name, {})['icon16x16'] = (icon1, icon2)
            data = dg.get('hd44780_data', None)
            if data is not None:
                slot = dg.getint('hd44780_slot', minval=0, maxval=7)
                idata = self._parse_glyph(config, glyph_name, data, 5, 8)
                icons.setdefault(glyph_name, {})['icon5x8'] = (slot, idata)
        self.lcd_chip.set_glyphs(icons)
    # Initialization
    def handle_ready(self):
        self.lcd_chip.init()
        # Start screen update timer
        self.reactor.update_timer(self.screen_update_timer, self.reactor.NOW)
    # Screen updating
    def screen_update_event(self, eventtime):
        if self.redraw_request_pending:
            self.redraw_request_pending = False
            self.redraw_time = eventtime + REDRAW_MIN_TIME
        self.lcd_chip.clear()
        # update menu component
        if self.menu is not None:
            ret = self.menu.screen_update_event(eventtime)
            if ret:
                self.lcd_chip.flush()
                return eventtime + REDRAW_TIME
        # Update normal display
        try:
            self.show_data_group.show(self, self.display_templates, eventtime)
        except:
            logging.exception("Error during display screen update")
        self.lcd_chip.flush()
        return eventtime + REDRAW_TIME
    def request_redraw(self):
        if self.redraw_request_pending:
            return
        self.redraw_request_pending = True
        self.reactor.update_timer(self.screen_update_timer, self.redraw_time)
    def draw_text(self, row, col, mixed_text, eventtime):
        pos = col
        for i, text in enumerate(mixed_text.split('~')):
            if i & 1 == 0:
                # write text
                self.lcd_chip.write_text(pos, row, text.encode())
                pos += len(text)
            else:
                # write glyph
                pos += self.lcd_chip.write_glyph(pos, row, text)
    def draw_progress_bar(self, row, col, width, value):
        pixels = -1 << int(width * 8 * (1. - value) + .5)
        pixels |= (1 << (width * 8 - 1)) | 1
        for i in range(width):
            data = [0xff] + [(pixels >> (i * 8)) & 0xff] * 14 + [0xff]
            self.lcd_chip.write_graphics(col + width - 1 - i, row, data)
        return ""
    cmd_SET_DISPLAY_GROUP_help = "Set the active display group"
    def cmd_SET_DISPLAY_GROUP(self, gcmd):
        group = gcmd.get('GROUP')
        new_dg = self.display_data_groups.get(group)
        if new_dg is None:
            raise gcmd.error("Unknown display_data group '%s'" % (group,))
        self.show_data_group = new_dg

def load_config(config):
    return PrinterLCD(config)
