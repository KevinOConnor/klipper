# Regression test helper script
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import sys, os, optparse, logging, subprocess

TEMP_GCODE_FILE = "_test_.gcode"
TEMP_LOG_FILE = "_test_.log"
TEMP_OUTPUT_FILE = "_test_output"


######################################################################
# Test cases
######################################################################

class error(Exception):
    pass

class TestCase:
    def __init__(self, fname, dictdir, tempdir, verbose, keepfiles):
        self.fname = fname
        self.dictdir = dictdir
        self.tempdir = tempdir
        self.verbose = verbose
        self.keepfiles = keepfiles
    def relpath(self, fname, rel='test'):
        if rel == 'dict':
            reldir = self.dictdir
        elif rel == 'temp':
            reldir = self.tempdir
        else:
            reldir = os.path.dirname(self.fname)
        return os.path.join(reldir, fname)
    def parse_test(self):
        # Parse file into test cases
        config_fname = gcode_fname = dict_fnames = None
        should_fail = multi_tests = False
        gcode = []
        f = open(self.fname, 'r')
        for line in f:
            cpos = line.find('#')
            if cpos >= 0:
                line = line[:cpos]
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == "CONFIG":
                if config_fname is not None:
                    # Multiple tests in same file
                    if not multi_tests:
                        multi_tests = True
                        self.launch_test(config_fname, dict_fnames,
                                         gcode_fname, gcode, should_fail)
                config_fname = self.relpath(parts[1])
                if multi_tests:
                    self.launch_test(config_fname, dict_fnames,
                                     gcode_fname, gcode, should_fail)
            elif parts[0] == "DICTIONARY":
                dict_fnames = [self.relpath(parts[1], 'dict')]
                for mcu_dict in parts[2:]:
                    mcu, fname = mcu_dict.split('=', 1)
                    dict_fnames.append('%s=%s' % (
                        mcu.strip(), self.relpath(fname.strip(), 'dict')))
            elif parts[0] == "GCODE":
                gcode_fname = self.relpath(parts[1])
            elif parts[0] == "SHOULD_FAIL":
                should_fail = True
            else:
                gcode.append(line.strip())
        f.close()
        if not multi_tests:
            self.launch_test(config_fname, dict_fnames,
                             gcode_fname, gcode, should_fail)
    def launch_test(self, config_fname, dict_fnames, gcode_fname, gcode,
                    should_fail):
        gcode_is_temp = False
        if gcode_fname is None:
            gcode_fname = self.relpath(TEMP_GCODE_FILE, 'temp')
            gcode_is_temp = True
            f = open(gcode_fname, 'w')
            f.write('\n'.join(gcode + ['']))
            f.close()
        elif gcode:
            raise error("Can't specify both a gcode file and gcode commands")
        if config_fname is None:
            raise error("config file not specified")
        if dict_fnames is None:
            raise error("data dictionary file not specified")
        # Call klippy
        sys.stderr.write("    Starting %s (%s)\n" % (
            self.fname, os.path.basename(config_fname)))
        args = [ sys.executable, './klippy/klippy.py', config_fname,
                 '-i', gcode_fname, '-o', TEMP_OUTPUT_FILE, '-v' ]
        for df in dict_fnames:
            args += ['-d', df]
        if not self.verbose:
            args += ['-l', TEMP_LOG_FILE]
        res = subprocess.call(args)
        is_fail = (should_fail and not res) or (not should_fail and res)
        if is_fail:
            if not self.verbose:
                self.show_log()
            if should_fail:
                raise error("Test failed to raise an error")
            raise error("Error during test")
        # Do cleanup
        if self.keepfiles:
            return
        for fname in os.listdir(self.tempdir):
            if fname.startswith(TEMP_OUTPUT_FILE):
                os.unlink(fname)
        if not self.verbose:
            os.unlink(TEMP_LOG_FILE)
        else:
            sys.stderr.write('\n')
        if gcode_is_temp:
            os.unlink(gcode_fname)
    def run(self):
        try:
            self.parse_test()
        except error as e:
            return str(e)
        except Exception:
            logging.exception("Unhandled exception during test run")
            return "internal error"
        return "success"
    def show_log(self):
        f = open(TEMP_LOG_FILE, 'r')
        data = f.read()
        f.close()
        sys.stdout.write(data)


######################################################################
# Startup
######################################################################

def main():
    # Parse args
    usage = "%prog [options] <test cases>"
    opts = optparse.OptionParser(usage)
    opts.add_option("-d", "--dictdir", dest="dictdir", default=".",
                    help="directory for dictionary files")
    opts.add_option("-t", "--tempdir", dest="tempdir", default=".",
                    help="directory for temporary files")
    opts.add_option("-k", action="store_true", dest="keepfiles",
                    help="do not remove temporary files")
    opts.add_option("-v", action="store_true", dest="verbose",
                    help="show all output from tests")
    options, args = opts.parse_args()
    if len(args) < 1:
        opts.error("Incorrect number of arguments")
    logging.basicConfig(level=logging.DEBUG)

    # Run each test
    for fname in args:
        tc = TestCase(fname, options.dictdir, options.tempdir, options.verbose,
                      options.keepfiles)
        res = tc.run()
        if res != 'success':
            sys.stderr.write("\n\nTest case %s FAILED (%s)!\n\n" % (fname, res))
            sys.exit(-1)

    sys.stderr.write("\n    All %d test cases passed\n" % (len(args),))

if __name__ == '__main__':
    main()
