# Support for logging periodic statistics
#
# Copyright (C) 2018-2020  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, time, logging

def get_os_stats(eventtime):
    # Get core usage stats
    msg = "sysload=%.2f cputime=%.3f" % (os.getloadavg()[0],
                                         time.process_time())
    # Get available system memory
    try:
        f = open("/proc/meminfo", "rb")
        data = f.read()
        f.close()
        for line in data.split('\n'):
            if line.startswith("MemAvailable:"):
                msg = "%s memavail=%s" % (msg, line.split()[1])
                break
    except:
        pass
    return (False, msg)

class PrinterStats:
    def __init__(self, config):
        self.printer = config.get_printer()
        reactor = self.printer.get_reactor()
        self.stats_timer = reactor.register_timer(self.generate_stats)
        self.stats_cb = []
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
    def handle_ready(self):
        self.stats_cb = [o.stats for n, o in self.printer.lookup_objects()
                         if hasattr(o, 'stats')]
        if self.printer.get_start_args().get('debugoutput') is None:
            reactor = self.printer.get_reactor()
            reactor.update_timer(self.stats_timer, reactor.NOW)
    def generate_stats(self, eventtime):
        stats = [cb(eventtime) for cb in self.stats_cb]
        if max([s[0] for s in stats]):
            stats.append(get_os_stats(eventtime))
            logging.info("Stats %.1f: %s", eventtime,
                         ' '.join([s[1] for s in stats]))
        return eventtime + 1.

def load_config(config):
    return PrinterStats(config)
