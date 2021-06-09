# -*- coding: utf-8 -*-
# Basic LCD menu support
#
# Copyright (C) 2020  Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, logging, ast, re
from string import Template
from . import menu_keys


class sentinel:
    pass


class error(Exception):
    pass


# Scriptable menu element abstract baseclass
class MenuElement(object):
    def __init__(self, manager, config, **kwargs):
        if type(self) is MenuElement:
            raise error(
                'Abstract MenuElement cannot be instantiated directly')
        self._manager = manager
        self._cursor = '>'
        # set class defaults and attributes from arguments
        self._index = kwargs.get('index', None)
        self._enable = kwargs.get('enable', True)
        self._name = kwargs.get('name', None)
        self._enable_tpl = self._name_tpl = None
        if config is not None:
            # overwrite class attributes from config
            self._index = config.getint('index', self._index)
            self._name_tpl = manager.gcode_macro.load_template(
                config, 'name', self._name)
            try:
                self._enable = config.getboolean('enable', self._enable)
            except config.error:
                self._enable_tpl = manager.gcode_macro.load_template(
                    config, 'enable')
            # item namespace - used in relative paths
            self._ns = str(" ".join(config.get_name().split(' ')[1:])).strip()
        else:
            # ns - item namespace key, used in item relative paths
            # $__id - generated id text variable
            __id = '__menu_' + hex(id(self)).lstrip("0x").rstrip("L")
            self._ns = Template(
                'menu ' + kwargs.get('ns', __id)).safe_substitute(__id=__id)
        self._last_heartbeat = None
        self.__scroll_pos = None
        self.__scroll_request_pending = False
        self.__scroll_next = 0
        # menu scripts
        self._scripts = {}
        # init
        self.init()

    # override
    def init(self):
        pass

    def _render_name(self):
        if self._name_tpl is not None:
            context = self.get_context()
            return self.manager.asflat(self._name_tpl.render(context))
        return self.manager.asflat(self._name)

    def _load_script(self, config, name, option=None):
        """Load script template from config or callback from dict"""
        if name in self._scripts:
            logging.info(
                "Declaration of '%s' hides "
                "previous script declaration" % (name,))
        option = option or name
        if isinstance(config, dict):
            self._scripts[name] = config.get(option, None)
        else:
            self._scripts[name] = self.manager.gcode_macro.load_template(
                config, option, '')

    # override
    def is_editing(self):
        return False

    # override
    def is_scrollable(self):
        return True

    # override
    def is_enabled(self):
        context = self.get_context()
        return self.eval_enable(context)

    # override
    def start_editing(self):
        pass

    # override
    def stop_editing(self):
        pass

    # override
    def get_context(self, cxt=None):
        # get default menu context
        context = self.manager.get_context(cxt)
        context['menu'].update({
            'ns': self.get_ns()
        })
        return context

    def eval_enable(self, context):
        if self._enable_tpl is not None:
            return bool(ast.literal_eval(self._enable_tpl.render(context)))
        return bool(self._enable)

    # Called when a item is selected
    def select(self):
        self.__reset_scroller()

    def heartbeat(self, eventtime):
        self._last_heartbeat = eventtime
        if eventtime >= self.__scroll_next:
            self.__scroll_next = eventtime + 0.5
            if not self.is_editing():
                self.__update_scroller()

    def __update_scroller(self):
        if self.__scroll_pos is None and self.__scroll_request_pending is True:
            self.__scroll_pos = 0
        elif self.__scroll_request_pending is True:
            self.__scroll_pos += 1
            self.__scroll_request_pending = False
        elif self.__scroll_request_pending is False:
            pass  # hold scroll position
        elif self.__scroll_request_pending is None:
            self.__reset_scroller()

    def __reset_scroller(self):
        self.__scroll_pos = None
        self.__scroll_request_pending = False

    def need_scroller(self, value):
        """
        Allows to control the scroller
        Parameters:
            value (bool, None): True  - inc. scroll pos. on next update
                                False - hold scroll pos.
                                None  - reset the scroller
        """
        self.__scroll_request_pending = value

    def __slice_name(self, name, index):
        chunks = []
        for i, text in enumerate(re.split(r'(\~.*?\~)', name)):
            if i & 1 == 0:  # text
                chunks += text
            else:  # glyph placeholder
                chunks.append(text)
        return "".join(chunks[index:])

    def render_name(self, selected=False):
        name = str(self._render_name())
        if selected and self.__scroll_pos is not None:
            name = self.__slice_name(name, self.__scroll_pos)
        else:
            self.__reset_scroller()
        return name

    def get_ns(self, name='.'):
        name = str(name).strip()
        if name.startswith('..'):
            name = ' '.join(
                [(' '.join(str(self._ns).split(' ')[:-1])), name[2:]])
        elif name.startswith('.'):
            name = ' '.join([str(self._ns), name[1:]])
        return name.strip()

    def send_event(self, event, *args):
        return self.manager.send_event(
            "%s:%s" % (self.get_ns(), str(event)), *args)

    def get_script(self, name):
        if name in self._scripts:
            return self._scripts[name]
        return None

    def _run_script(self, name, context):
        _render = getattr(self._scripts[name], 'render', None)
        # check template
        if _render is not None and callable(_render):
            return _render(context)
        # check callback
        elif callable(self._scripts[name]):
            return self._scripts[name](self, context)
        # check static string
        elif isinstance(self._scripts[name], str):
            return self._scripts[name]

    def run_script(self, name, **kwargs):
        event = kwargs.get('event', None)
        context = kwargs.get('context', None)
        render_only = kwargs.get('render_only', False)
        result = ""
        # init context
        if name in self._scripts:
            context = self.get_context(context)
            context['menu'].update({
                'event': event or name
            })
            result = self._run_script(name, context)
        if not render_only:
            # run result as gcode
            self.manager.queue_gcode(result)
            # default behaviour
            _handle = getattr(self, "handle_script_" + name, None)
            if callable(_handle):
                _handle()
        return result

    @property
    def cursor(self):
        return str(self._cursor)[:1]

    @property
    def manager(self):
        return self._manager

    @property
    def index(self):
        return self._index


class MenuContainer(MenuElement):
    """Menu container abstract class"""
    def __init__(self, manager, config, **kwargs):
        if type(self) is MenuContainer:
            raise error(
                'Abstract MenuContainer cannot be instantiated directly')
        super(MenuContainer, self).__init__(manager, config, **kwargs)
        self._populate_cb = kwargs.get('populate', None)
        self._cursor = '>'
        self.__selected = None
        self._allitems = []
        self._names = []
        self._items = []

    def init(self):
        super(MenuContainer, self).init()
        # recursive guard
        self._parents = []

    # overload
    def _names_aslist(self):
        return []

    # overload
    def is_accepted(self, item):
        return isinstance(item, MenuElement)

    def is_editing(self):
        return any([item.is_editing() for item in self._items])

    def stop_editing(self):
        for item in self._items:
            if item.is_editing():
                item.stop_editing()

    def lookup_item(self, item):
        if isinstance(item, str):
            name = item.strip()
            ns = self.get_ns(name)
            return (self.manager.lookup_menuitem(ns), name)
        elif isinstance(item, MenuElement):
            return (item, item.get_ns())
        return (None, item)

    # overload
    def _lookup_item(self, item):
        return self.lookup_item(item)

    def _index_of(self, item):
        try:
            index = None
            if isinstance(item, str):
                s = item.strip()
                index = self._names.index(s)
            elif isinstance(item, MenuElement):
                index = self._items.index(item)
            return index
        except ValueError:
            return None

    def index_of(self, item, look_inside=False):
        index = self._index_of(item)
        if index is None and look_inside is True:
            for con in self:
                if isinstance(con, MenuContainer) and con._index_of(item):
                    index = self._index_of(con)
        return index

    def add_parents(self, parents):
        if isinstance(parents, list):
            self._parents.extend(parents)
        else:
            self._parents.append(parents)

    def assert_recursive_relation(self, parents=None):
        assert self not in (parents or self._parents), \
            "Recursive relation of '%s' container" % (self.get_ns(),)

    def insert_item(self, s, index=None):
        self._insert_item(s, index)

    def _insert_item(self, s, index=None):
        item, name = self._lookup_item(s)
        if item is not None:
            if not self.is_accepted(item):
                raise error("Menu item '%s'is not accepted!" % str(type(item)))
            if isinstance(item, (MenuElement)):
                item.init()
            if isinstance(item, (MenuContainer)):
                item.add_parents(self._parents)
                item.add_parents(self)
                item.assert_recursive_relation()
            if index is None:
                self._allitems.append((item, name))
            else:
                self._allitems.insert(index, (item, name))

    # overload
    def _populate(self):
        pass

    def populate(self):
        self._allitems = []  # empty list
        for name in self._names_aslist():
            self._insert_item(name)
        # populate successor items
        self._populate()
        # run populate callback
        if self._populate_cb is not None and callable(self._populate_cb):
            self._populate_cb(self)
        # send populate event
        self.send_event('populate', self)

    def update_items(self):
        _a = [(item, name) for item, name in self._allitems
              if item.is_enabled()]
        self._items, self._names = zip(*_a) or ([], [])

    # select methods
    def init_selection(self):
        self.select_at(0)

    def select_at(self, index):
        self.__selected = index
        # select element
        item = self.selected_item()
        if isinstance(item, MenuElement):
            item.select()
        return item

    def select_item(self, needle):
        if isinstance(needle, MenuElement):
            if self.selected_item() is not needle:
                index = self.index_of(needle)
                if index is not None:
                    self.select_at(index)
        else:
            logging.error("Cannot select non menuitem")
        return self.selected

    def selected_item(self):
        if isinstance(self.selected, int) and 0 <= self.selected < len(self):
            return self[self.selected]
        else:
            return None

    def select_next(self):
        if not isinstance(self.selected, int):
            index = 0 if len(self) else None
        elif 0 <= self.selected < len(self) - 1:
            index = self.selected + 1
        else:
            index = self.selected
        return self.select_at(index)

    def select_prev(self):
        if not isinstance(self.selected, int):
            index = 0 if len(self) else None
        elif 0 < self.selected < len(self):
            index = self.selected - 1
        else:
            index = self.selected
        return self.select_at(index)

    # override
    def draw_container(self, nrows, eventtime):
        pass

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, key):
        return self._items[key]

    @property
    def selected(self):
        return self.__selected


class MenuDisabled(MenuElement):
    def __init__(self, manager, config, **kwargs):
        super(MenuDisabled, self).__init__(manager, config, name='')

    def is_enabled(self):
        return False


class MenuCommand(MenuElement):
    def __init__(self, manager, config, **kwargs):
        super(MenuCommand, self).__init__(manager, config, **kwargs)
        self._load_script(config or kwargs, 'gcode')


class MenuInput(MenuCommand):
    def __init__(self, manager, config, **kwargs):
        super(MenuInput, self).__init__(manager, config, **kwargs)
        # set class defaults and attributes from arguments
        self._input = kwargs.get('input', None)
        self._input_min = kwargs.get('input_min', -999999.0)
        self._input_max = kwargs.get('input_max', 999999.0)
        self._input_step = kwargs.get('input_step', 1.0)
        self._realtime = kwargs.get('realtime', False)
        self._input_tpl = self._input_min_tpl = self._input_max_tpl = None
        if config is not None:
            # overwrite class attributes from config
            self._realtime = config.getboolean('realtime', self._realtime)
            self._input_tpl = manager.gcode_macro.load_template(
                config, 'input')
            self._input_min_tpl = manager.gcode_macro.load_template(
                config, 'input_min', str(self._input_min))
            self._input_max_tpl = manager.gcode_macro.load_template(
                config, 'input_max', str(self._input_max))
            self._input_step = config.getfloat(
                'input_step', self._input_step, above=0.)

    def init(self):
        super(MenuInput, self).init()
        self._is_dirty = False
        self.__last_change = None
        self._input_value = None

    def is_scrollable(self):
        return False

    def is_editing(self):
        return self._input_value is not None

    def stop_editing(self):
        if not self.is_editing():
            return
        self._reset_value()

    def start_editing(self):
        if self.is_editing():
            return
        self._init_value()

    def heartbeat(self, eventtime):
        super(MenuInput, self).heartbeat(eventtime)
        if (self._is_dirty is True
                and self.__last_change is not None
                and self._input_value is not None
                and (eventtime - self.__last_change) > 0.250):
            if self._realtime is True:
                self.run_script('gcode', event='change')
                self.run_script('change')
            self._is_dirty = False

    def get_context(self, cxt=None):
        context = super(MenuInput, self).get_context(cxt)
        value = (self._eval_value(context) if self._input_value is None
                 else self._input_value)
        context['menu'].update({
            'input': value
        })
        return context

    def is_enabled(self):
        context = super(MenuInput, self).get_context()
        return self.eval_enable(context)

    def _eval_min(self, context):
        try:
            if self._input_min_tpl is not None:
                return float(ast.literal_eval(
                    self._input_min_tpl.render(context)))
            return float(self._input_min)
        except ValueError:
            logging.exception("Input min value evaluation error")

    def _eval_max(self, context):
        try:
            if self._input_max_tpl is not None:
                return float(ast.literal_eval(
                    self._input_max_tpl.render(context)))
            return float(self._input_max)
        except ValueError:
            logging.exception("Input max value evaluation error")

    def _eval_value(self, context):
        try:
            if self._input_tpl is not None:
                return float(ast.literal_eval(
                    self._input_tpl.render(context)))
            return float(self._input)
        except ValueError:
            logging.exception("Input value evaluation error")

    def _value_changed(self):
        self.__last_change = self._last_heartbeat
        self._is_dirty = True

    def _init_value(self):
        context = super(MenuInput, self).get_context()
        self._input_value = None
        self._input_min = self._eval_min(context)
        self._input_max = self._eval_max(context)
        self._input_value = min(self._input_max, max(
            self._input_min, self._eval_value(context)))
        self._value_changed()

    def _reset_value(self):
        self._input_value = None

    def _get_input_step(self, fast_rate=False):
        return ((10.0 * self._input_step) if fast_rate and (
                (self._input_max - self._input_min) / self._input_step > 100.0)
                else self._input_step)

    def inc_value(self, fast_rate=False):
        last_value = self._input_value
        if self._input_value is None:
            return

        input_step = self._get_input_step(fast_rate)
        self._input_value += abs(input_step)
        self._input_value = min(self._input_max, max(
            self._input_min, self._input_value))

        if last_value != self._input_value:
            self._value_changed()

    def dec_value(self, fast_rate=False):
        last_value = self._input_value
        if self._input_value is None:
            return

        input_step = self._get_input_step(fast_rate)
        self._input_value -= abs(input_step)
        self._input_value = min(self._input_max, max(
            self._input_min, self._input_value))

        if last_value != self._input_value:
            self._value_changed()

    # default behaviour on click
    def handle_script_click(self):
        if not self.is_editing():
            self.start_editing()
        elif self.is_editing():
            self.stop_editing()


class MenuList(MenuContainer):
    def __init__(self, manager, config, **kwargs):
        super(MenuList, self).__init__(manager, config, **kwargs)
        self._viewport_top = 0

        def _cb(el, context):
            el.manager.back()
        # create back item
        self._itemBack = self.manager.menuitem_from(
            'command', name='..', gcode=_cb)

    def _names_aslist(self):
        return self.manager.lookup_children(self.get_ns())

    def _populate(self):
        super(MenuList, self)._populate()
        self._viewport_top = 0
        #  add back as first item
        self.insert_item(self._itemBack, 0)

    def draw_container(self, nrows, eventtime):
        display = self.manager.display
        selected_row = self.selected
        # adjust viewport
        if selected_row is not None:
            if selected_row >= (self._viewport_top + nrows):
                self._viewport_top = (selected_row - nrows) + 1
            if selected_row < self._viewport_top:
                self._viewport_top = selected_row
        else:
            self._viewport_top = 0
        # clamps viewport
        self._viewport_top = max(0, min(self._viewport_top, len(self) - nrows))
        try:
            y = 0
            for row in range(self._viewport_top, self._viewport_top + nrows):
                text = ""
                prefix = ""
                suffix = ""
                if row < len(self):
                    current = self[row]
                    selected = (row == selected_row)
                    if selected:
                        current.heartbeat(eventtime)
                    text = current.render_name(selected)
                    # add prefix (selection indicator)
                    if selected and not current.is_editing():
                        prefix = current.cursor
                    elif selected and current.is_editing():
                        prefix = '*'
                    else:
                        prefix = ' '
                    # add suffix (folder indicator)
                    if isinstance(current, MenuList):
                        suffix += '>'
                # draw to display
                plen = len(prefix)
                slen = len(suffix)
                width = self.manager.cols - plen - slen
                # draw item prefix (cursor)
                ppos = display.draw_text(y, 0, prefix, eventtime)
                # draw item name
                tpos = display.draw_text(y, ppos, text.ljust(width), eventtime)
                # check scroller
                if (selected and tpos > self.manager.cols
                        and current.is_scrollable()):
                    # scroll next
                    current.need_scroller(True)
                else:
                    # reset scroller
                    current.need_scroller(None)
                # draw item suffix
                if suffix:
                    display.draw_text(
                        y, self.manager.cols - slen, suffix, eventtime)
                # next display row
                y += 1
        except Exception:
            logging.exception('List drawing error')


class MenuVSDList(MenuList):
    def __init__(self, manager, config, **kwargs):
        super(MenuVSDList, self).__init__(manager, config, **kwargs)

    def _populate(self):
        super(MenuVSDList, self)._populate()
        sdcard = self.manager.printer.lookup_object('virtual_sdcard', None)
        if sdcard is not None:
            files = sdcard.get_file_list()
            for fname, fsize in files:
                self.insert_item(self.manager.menuitem_from(
                    'command', name=repr(fname), gcode='M23 /%s' % str(fname)))


menu_items = {
    'disabled': MenuDisabled,
    'command': MenuCommand,
    'input': MenuInput,
    'list': MenuList,
    'vsdlist': MenuVSDList
}


TIMER_DELAY = 1.0


class MenuManager:
    def __init__(self, config, display):
        self.running = False
        self.menuitems = {}
        self.menustack = []
        self.children = {}
        self.display = display
        self.printer = config.get_printer()
        self.pconfig = self.printer.lookup_object('configfile')
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode_queue = []
        self.context = {}
        self.root = None
        self.root_long_click = None
        self._root = config.get('menu_root', '__main')
        self._root_long_click = config.get('menu_root_long_click', self._root)
        self.cols, self.rows = self.display.get_dimensions()
        self.timeout = config.getint('menu_timeout', 0)
        self.timer = 0
        # reverse container navigation
        self._reverse_navigation = config.getboolean(
            'menu_reverse_navigation', False)
        # load printer objects
        self.gcode_macro = self.printer.load_object(config, 'gcode_macro')
        # register itself for printer callbacks
        self.printer.add_object('menu', self)
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        # register gcode
        self.gcode.register_command("MENU_SHOW", self.cmd_MENU_SHOW,
                                    desc=self.cmd_MENU_SHOW_help)
        # register for key events
        menu_keys.MenuKeys(config, self.key_event)
        # Load local config file in same directory as current module
        self.load_config(os.path.dirname(__file__), 'menu.cfg')
        # Load items from main config
        self.load_menuitems(config)
        # Load menu root
        self.root = self.lookup_menuitem(self._root)
        # Load long click menu
        if self._root_long_click != self._root:
            self.root_long_click = self.lookup_menuitem(self._root_long_click)
        # send init event
        self.send_event('init', self)

    def handle_ready(self):
        # start timer
        reactor = self.printer.get_reactor()
        reactor.register_timer(self.timer_event, reactor.NOW)

    def timer_event(self, eventtime):
        self.timeout_check(eventtime)
        return eventtime + TIMER_DELAY

    def timeout_check(self, eventtime):
        if (self.is_running() and self.timeout > 0
                and isinstance(self.root, MenuContainer)):
            if self.timer >= self.timeout:
                self.exit()
            else:
                self.timer += 1
        else:
            self.timer = 0

    def send_event(self, event, *args):
        return self.printer.send_event("menu:" + str(event), *args)

    cmd_MENU_SHOW_help = "Show menu on a screen"
    def cmd_MENU_SHOW(self, gcmd):
        menuitem = self.lookup_menuitem(gcmd.get('ITEM'))

        if self.is_running() and not gcmd.get_int('ROOT', 0):
            self.stack_push(menuitem)
        else:
            curtime = self.printer.get_reactor().monotonic()
            self.stack_root(menuitem, curtime)

    def is_running(self):
        return self.running

    def begin(self, eventtime, event):
        if event == 'long_click' and self.root_long_click != None:
            self.stack_root(self.root_long_click, eventtime)
        else:
            self.stack_root(self.root, eventtime)

    def get_status(self, eventtime):
        return {
            'timeout': self.timeout,
            'running': self.running,
            'rows': self.rows,
            'cols': self.cols
        }

    def _action_back(self, force=False, update=True):
        self.back(force, update)
        return ""

    def _action_exit(self, force=False):
        self.exit(force)
        return ""

    def get_context(self, cxt=None):
        context = dict(self.context)
        if isinstance(cxt, dict):
            context.update(cxt)
        return context

    def update_context(self, eventtime):
        # menu default jinja2 context
        self.context = self.gcode_macro.create_template_context(eventtime)
        self.context['menu'] = {
            'eventtime': eventtime,
            'back': self._action_back,
            'exit': self._action_exit
        }

    def stack_root(self, container, eventtime):
        top = self.stack_peek()
        if top is not None:
            if isinstance(top, MenuList):
                top.run_script('leave')

        self.menustack = []

        if isinstance(container, MenuContainer):
            # send begin event
            self.send_event('begin', self)
            self.update_context(eventtime)
            if isinstance(container, MenuContainer):
                container.init_selection()
            self.stack_push(container)
            self.running = True
            return
        elif self.root is not None:
            logging.error("Invalid root, menu stopped!")
        self.running = False

    def stack_push(self, container):
        if not isinstance(container, MenuContainer):
            raise error("Wrong type, expected MenuContainer")
        container.populate()
        top = self.stack_peek()
        if top is not None:
            if isinstance(top, MenuList):
                top.run_script('leave')
        if isinstance(container, MenuList):
            container.run_script('enter')
        if not container.is_editing():
            container.update_items()
            container.init_selection()
        self.timer = 0
        self.menustack.append(container)

    def stack_pop(self, update=True):
        container = None
        if self.stack_size() > 0:
            container = self.menustack.pop()
            if not isinstance(container, MenuContainer):
                raise error("Wrong type, expected MenuContainer")
            top = self.stack_peek()
            if top is not None:
                if not isinstance(container, MenuContainer):
                    raise error("Wrong type, expected MenuContainer")
                if not top.is_editing() and update is True:
                    top.update_items()
                    top.init_selection()
                if isinstance(container, MenuList):
                    container.run_script('leave')
                if isinstance(top, MenuList):
                    top.run_script('enter')
            else:
                if isinstance(container, MenuList):
                    container.run_script('leave')
        return container

    def stack_size(self):
        return len(self.menustack)

    def stack_peek(self, lvl=0):
        container = None
        if self.stack_size() > lvl:
            container = self.menustack[self.stack_size() - lvl - 1]
        return container

    def screen_update_event(self, eventtime):
        # screen update
        if not self.is_running():
            return False
        # draw menu
        self.update_context(eventtime)
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            container.heartbeat(eventtime)
            container.draw_container(self.rows, eventtime)
        return True

    def up(self, fast_rate=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if isinstance(current, MenuInput) and current.is_editing():
                current.dec_value(fast_rate)
            else:
                if self._reverse_navigation is True:
                    container.select_next()  # reverse
                else:
                    container.select_prev()  # normal

    def down(self, fast_rate=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if isinstance(current, MenuInput) and current.is_editing():
                current.inc_value(fast_rate)
            else:
                if self._reverse_navigation is True:
                    container.select_prev()  # reverse
                else:
                    container.select_next()  # normal

    def back(self, force=False, update=True):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if isinstance(current, MenuInput) and current.is_editing():
                if force is True:
                    current.stop_editing()
                else:
                    return
            parent = self.stack_peek(1)
            if isinstance(parent, MenuContainer):
                self.stack_pop(update)
                index = parent.index_of(container, True)
                if index is not None:
                    parent.select_at(index)
                elif parent.selected_item() is None:
                    parent.init_selection()

            else:
                self.stack_pop()
                self.running = False

    def exit(self, force=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if (not force and isinstance(current, MenuInput)
                    and current.is_editing()):
                return
            if isinstance(container, MenuList):
                container.run_script('leave')
            self.send_event('exit', self)
            self.running = False

    def push_container(self, menu):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            if (isinstance(menu, MenuContainer)
                    and not container.is_editing()
                    and menu is not container):
                self.stack_push(menu)
                return True
        return False

    def press(self, event='click'):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if isinstance(current, MenuContainer):
                self.stack_push(current)
            elif isinstance(current, MenuInput):
                if current.is_editing():
                    current.run_script('gcode', event=event)
                current.run_script(event)
            elif isinstance(current, MenuCommand):
                current.run_script('gcode', event=event)
                current.run_script(event)
            else:
                # current is None, no selection. passthru to container
                container.run_script(event)

    def queue_gcode(self, script):
        if not script:
            return
        if not self.gcode_queue:
            reactor = self.printer.get_reactor()
            reactor.register_callback(self.dispatch_gcode)
        self.gcode_queue.append(script)

    def dispatch_gcode(self, eventtime):
        while self.gcode_queue:
            script = self.gcode_queue[0]
            try:
                self.gcode.run_script(script)
            except Exception:
                logging.exception("Script running error")
            self.gcode_queue.pop(0)

    def menuitem_from(self, type, **kwargs):
        if type not in menu_items:
            raise error("Choice '%s' for option '%s'"
                        " is not a valid choice" % (type, menu_items))
        return menu_items[type](self, None, **kwargs)

    def add_menuitem(self, name, item):
        existing_item = False
        if name in self.menuitems:
            existing_item = True
            logging.info(
                "Declaration of '%s' hides "
                "previous menuitem declaration" % (name,))
        self.menuitems[name] = item
        if isinstance(item, MenuElement):
            parent = item.get_ns('..')
            if parent and not existing_item:
                if item.index is not None:
                    self.children.setdefault(parent, []).insert(
                        item.index, item.get_ns())
                else:
                    self.children.setdefault(parent, []).append(
                        item.get_ns())

    def lookup_menuitem(self, name, default=sentinel):
        if name is None:
            return None
        if name in self.menuitems:
            return self.menuitems[name]
        if default is sentinel:
            raise self.printer.config_error(
                "Unknown menuitem '%s'" % (name,))
        return default

    def lookup_children(self, ns):
        if ns in self.children:
            return list(self.children[ns])
        return list()

    def load_config(self, *args):
        cfg = None
        filename = os.path.join(*args)
        try:
            cfg = self.pconfig.read_config(filename)
        except Exception:
            raise self.printer.config_error(
                "Cannot load config '%s'" % (filename,))
        if cfg:
            self.load_menuitems(cfg)
        return cfg

    def load_menuitems(self, config):
        for cfg in config.get_prefix_sections('menu '):
            type = cfg.get('type')
            if type not in menu_items:
                raise error("Choice '%s' for option '%s'"
                            " is not a valid choice" % (type, menu_items))
            item = menu_items[type](self, cfg)
            self.add_menuitem(item.get_ns(), item)

    def _click_callback(self, eventtime, event):
        if self.is_running():
            self.press(event)
        else:
            # lets start and populate the menu items
            self.begin(eventtime, event)

    def key_event(self, key, eventtime):
        if key == 'click':
            self._click_callback(eventtime, key)
        elif key == 'long_click':
            self._click_callback(eventtime, key)
        elif key == 'up':
            self.up(False)
        elif key == 'fast_up':
            self.up(True)
        elif key == 'down':
            self.down(False)
        elif key == 'fast_down':
            self.down(True)
        elif key == 'back':
            self.back()
        self.display.request_redraw()

    # Collection of manager class helper methods

    @classmethod
    def stripliterals(cls, s):
        """Literals are beginning or ending by the double or single quotes"""
        s = str(s)
        if (s.startswith('"') and s.endswith('"')) or \
                (s.startswith("'") and s.endswith("'")):
            s = s[1:-1]
        return s

    @classmethod
    def aslatin(cls, s):
        if isinstance(s, str):
            return s
        elif isinstance(s, unicode):
            return unicode(s).encode('latin-1', 'ignore')
        else:
            return str(s)

    @classmethod
    def asflat(cls, s):
        return cls.stripliterals(''.join(cls.aslatin(s).splitlines()))
