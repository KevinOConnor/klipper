# Tool for compiling and updating micro-controller code
#
# Copyright (C) 2021  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import sys, os, subprocess, logging, errno, tempfile, shutil
import util, mcu

class PrinterFlashMCU:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        mcu_names = [n.strip() for n in config.get('mcu', 'mcu').split(',')]
        self.mcus = [mcu.get_printer_mcu(self.printer, m) for m in mcu_names]
        self.kconfig = config.get('kconfig')
        fc = {c: c for c in self._get_flash_choices(["-T"])}
        self.flash_method = config.getchoice('flash_method', fc)
        pf = self.printer.load_object(config, "flash_mcu")
        pf.register_mcu(self.name, self)
    def _get_flash_choices(self, cmdargs):
        srcdir = os.path.dirname(os.path.realpath(__file__))
        flash_helper = os.path.join(srcdir, '..', '..', 'scripts',
                                    'flash_helper.py')
        args = [sys.executable, flash_helper] + cmdargs
        try:
            data = subprocess.check_output(args)
        except:
            logging.exception("Error in flash_helper execution")
            raise self.printer.command_error(
                "Unable to run flash_helper script")
        return [line.split()[0] for line in data.split('\n') if line.split()]
    def handle_get_devices(self, web_request):
        devs = self._get_flash_choices(["-t", self.flash_method, "-D"])
        web_request.send(devs)
    def _make_kconfig(self, kconfig_filename):
        out = "# Automatically generated file from flash_mcu\n" + self.kconfig
        try:
            f = open(kconfig_filename, 'wb')
            f.write(out)
            f.close()
        except:
            logging.exception("Failed to write kconfig file")
            raise error("Error writing kconfig file")
    def _read_data(self, data, fd):
        try:
            while 1:
                newdata = os.read(fd, 4096)
                if not newdata:
                    break
                data.append(newdata)
        except os.error, e:
            if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                logging.exception("Error on read() of command")
                raise error("Error running command")
    def _dump_data(self, data):
        logging.info("======= Command failed ======\n"
                     "%s\n"
                     "======= End ======" % ("".join(data),))
    def _run_command(self, cmdargs):
        reactor = self.printer.reactor
        start_time = reactor.monotonic()
        error = self.printer.command_error
        data = []
        try:
            p = subprocess.Popen(cmdargs, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
            fd = p.stdout.fileno()
            util.set_nonblock(fd)
            while 1:
                ret = p.poll()
                if ret is not None:
                    break
                self._read_data(data, fd)
                curtime = reactor.monotonic()
                if curtime > start_time + 300.:
                    p.kill()
                    self._dump_data(data)
                    raise error("Flash process did not end.")
                reactor.pause(curtime + 0.100)
            self._read_data(data, fd)
            ret = p.wait()
            if ret != 0:
                self._dump_data(data)
                raise error("Flash reported error (see log for details)")
        except OSError, e:
            logging.exception("Failed to run command")
            raise error("Error running flash command")
    def handle_flash(self, web_request):
        devname = web_request.get_str("device") # XXX - must verify
        srcdir = os.path.dirname(os.path.realpath(__file__))
        makedir = os.path.join(srcdir, '..', '..')
        temp_dirname = tempfile.mkdtemp()
        kconfig_filename = os.path.join(temp_dirname, "config")
        build_dirname = os.path.join(temp_dirname, "build")
        self._make_kconfig(kconfig_filename)
        make_args = ['make', '-C', makedir, 'OUT=%s/' % (build_dirname,),
                     'KCONFIG_CONFIG=%s' % (kconfig_filename,)]
        self._run_command(make_args + ['olddefconfig'])
        self._run_command(make_args)
        srcdir = os.path.dirname(os.path.realpath(__file__))
        flash_helper = os.path.join(srcdir, '..', '..', 'scripts',
                                    'flash_helper.py')
        flash_args = [sys.executable, flash_helper, '-t', self.flash_method,
                      '-d', devname, '-k', kconfig_filename,
                      '-o', build_dirname]
        def flash_cb():
            try:
                self._run_command(flash_args)
                shutil.rmtree(temp_dirname)
            except:
                logging.exception("Unhandled exception during flash")
        gcode = self.printer.lookup_object('gcode')
        with gcode.get_mutex():
            self.printer.register_event_handler('klippy:disconnect', flash_cb)
            gcode.request_restart('restart')

class PrinterFlash:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.handlers = {}
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint("flash_mcu/get_devices",
                                   self._handle_get_devices)
        webhooks.register_endpoint("flash_mcu/flash", self._handle_flash)
    def register_mcu(self, name, obj):
        self.handlers[name] = obj
    def _get_name(self, web_request):
        name = web_request.get_str("name")
        obj = self.handlers.get(name)
        if obj is None:
            raise web_request.error("Invalid name")
        return obj
    def _handle_get_devices(self, web_request):
        self._get_name(web_request).handle_get_devices(web_request)
    def _handle_flash(self, web_request):
        self._get_name(web_request).handle_flash(web_request)

def load_config(config):
    return PrinterFlash(config)

def load_config_prefix(config):
    return PrinterFlashMCU(config)
