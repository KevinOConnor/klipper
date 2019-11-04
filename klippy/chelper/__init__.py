# Wrapper around C helper code
#
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, logging
import cffi, sys


######################################################################
# _chelper.so compiling
######################################################################

COMPILE_CMD = ("gcc -Wall -g -O2 -shared -fPIC"
               " -flto -fwhole-program -fno-use-linker-plugin"
               " -o %s %s")
SOURCE_FILES = [
    'pyhelper.c', 'serialqueue.c', 'stepcompress.c', 'itersolve.c',
    'kin_cartesian.c', 'kin_corexy.c', 'kin_delta.c', 'kin_polar.c',
    'kin_winch.c', 'kin_extruder.c'
]
if hasattr(sys, 'gettotalrefcount'):
    DEST_LIB = "_chelper_d.so"
else:
    DEST_LIB = "_chelper.so"
OTHER_FILES = [
    'list.h', 'serialqueue.h', 'stepcompress.h', 'itersolve.h', 'pyhelper.h',
    'kinematics.h', '__init__.py'
]

defs_stepcompress = """
    struct stepcompress *stepcompress_alloc(uint32_t oid);
    void stepcompress_fill(struct stepcompress *sc, uint32_t max_error
        , uint32_t invert_sdir, uint32_t queue_step_msgid
        , uint32_t set_next_step_dir_msgid);
    void stepcompress_free(struct stepcompress *sc);
    int stepcompress_reset(struct stepcompress *sc, uint64_t last_step_clock);
    int stepcompress_queue_msg(struct stepcompress *sc
        , uint32_t *data, int len);

    struct steppersync *steppersync_alloc(struct serialqueue *sq
        , struct stepcompress **sc_list, int sc_num, int move_num);
    void steppersync_free(struct steppersync *ss);
    void steppersync_set_time(struct steppersync *ss
        , double time_offset, double mcu_freq);
    int steppersync_flush(struct steppersync *ss, uint64_t move_clock);
"""

defs_itersolve = """
    struct move *move_alloc(void);
    void move_fill(struct move *m, double print_time
        , double accel_t, double cruise_t, double decel_t
        , double start_pos_x, double start_pos_y, double start_pos_z
        , double axes_d_x, double axes_d_y, double axes_d_z
        , double start_v, double cruise_v, double accel);
    int32_t itersolve_gen_steps(struct stepper_kinematics *sk, struct move *m);
    void itersolve_set_stepcompress(struct stepper_kinematics *sk
        , struct stepcompress *sc, double step_dist);
    double itersolve_calc_position_from_coord(struct stepper_kinematics *sk
        , double x, double y, double z);
    void itersolve_set_commanded_pos(struct stepper_kinematics *sk, double pos);
    double itersolve_get_commanded_pos(struct stepper_kinematics *sk);
"""

defs_kin_cartesian = """
    struct stepper_kinematics *cartesian_stepper_alloc(char axis);
"""

defs_kin_corexy = """
    struct stepper_kinematics *corexy_stepper_alloc(char type);
"""

defs_kin_delta = """
    struct stepper_kinematics *delta_stepper_alloc(double arm2
        , double tower_x, double tower_y);
"""

defs_kin_polar = """
    struct stepper_kinematics *polar_stepper_alloc(char type);
"""

defs_kin_winch = """
    struct stepper_kinematics *winch_stepper_alloc(double anchor_x
        , double anchor_y, double anchor_z);
"""

defs_kin_extruder = """
    struct stepper_kinematics *extruder_stepper_alloc(void);
    void extruder_move_fill(struct move *m, double print_time
        , double accel_t, double cruise_t, double decel_t, double start_pos
        , double start_v, double cruise_v, double accel
        , double extra_accel_v, double extra_decel_v);
"""

defs_serialqueue = """
    #define MESSAGE_MAX 64
    struct pull_queue_message {
        uint8_t msg[MESSAGE_MAX];
        int len;
        double sent_time, receive_time;
    };

    struct serialqueue *serialqueue_alloc(int serial_fd, int write_only);
    void serialqueue_exit(struct serialqueue *sq);
    void serialqueue_free(struct serialqueue *sq);
    struct command_queue *serialqueue_alloc_commandqueue(void);
    void serialqueue_free_commandqueue(struct command_queue *cq);
    void serialqueue_send(struct serialqueue *sq, struct command_queue *cq
        , uint8_t *msg, int len, uint64_t min_clock, uint64_t req_clock);
    void serialqueue_pull(struct serialqueue *sq
        , struct pull_queue_message *pqm);
    void serialqueue_set_baud_adjust(struct serialqueue *sq
        , double baud_adjust);
    void serialqueue_set_receive_window(struct serialqueue *sq
        , int receive_window);
    void serialqueue_set_clock_est(struct serialqueue *sq, double est_freq
        , double last_clock_time, uint64_t last_clock);
    void serialqueue_get_stats(struct serialqueue *sq, char *buf, int len);
    int serialqueue_extract_old(struct serialqueue *sq, int sentq
        , struct pull_queue_message *q, int max);
"""

defs_pyhelper = """
    extern "Python+C" void python_logging_callback(const char* msg);
    double get_monotonic(void);
"""

defs_std = """
    void free(void*);
"""

defs_all = [
    defs_pyhelper, defs_serialqueue, defs_std,
    defs_stepcompress, defs_itersolve,
    defs_kin_cartesian, defs_kin_corexy, defs_kin_delta, defs_kin_polar,
    defs_kin_winch, defs_kin_extruder
]

ffi_source = """
#include "stepcompress.h"
#include "itersolve.h"
#include "kinematics.h"
#include "serialqueue.h"
#include "pyhelper.h"
"""

# Return the list of file modification times
def get_mtimes(srcdir, filelist):
    out = []
    for filename in filelist:
        pathname = os.path.join(srcdir, filename)
        try:
            t = os.path.getmtime(pathname)
        except os.error:
            continue
        out.append(t)
    return out

# Check if the code needs to be compiled
def check_build_code(srcdir, target, sources, builder, other_files=[]):
    src_times = get_mtimes(srcdir, sources + other_files)
    obj_times = get_mtimes(srcdir, [target])
    if not obj_times or max(src_times) > min(obj_times):
        logging.info("Building C code module %s", target)
        builder(srcdir, target, sources)

FFI_main = None
FFI_lib = None

def build_extension(srcdir, target, sources):
    ffi = cffi.FFI()
    for d in defs_all:
        ffi.cdef(d)
    libdir = os.path.dirname(os.path.abspath(__file__))
    ffi.set_source("_chelper", ffi_source, sources = SOURCE_FILES
                   , extra_compile_args = [ "-Werror" ])
    ffi.compile(tmpdir = libdir)

# Return the Foreign Function Interface api to the caller
def get_ffi():
    global FFI_main, FFI_lib
    if FFI_lib is None:
        srcdir = os.path.dirname(os.path.realpath(__file__))
        check_build_code(srcdir, DEST_LIB, SOURCE_FILES, build_extension
                         , OTHER_FILES)
        from _chelper import ffi, lib
        FFI_main = ffi
        FFI_lib = lib
        #FFI_lib = FFI_main.dlopen(os.path.join(srcdir, DEST_LIB))

        # Setup error logging
        @ffi.def_extern()
        def python_logging_callback(msg):
            logging.error(FFI_main.string(msg))
    return FFI_main, FFI_lib


######################################################################
# hub-ctrl hub power controller
######################################################################

HC_COMPILE_CMD = "gcc -Wall -g -O2 -o %s %s -lusb"
HC_SOURCE_FILES = ['hub-ctrl.c']
HC_SOURCE_DIR = '../../lib/hub-ctrl'
HC_TARGET = "hub-ctrl"
HC_CMD = "sudo %s/hub-ctrl -h 0 -P 2 -p %d"

def build_hub_ctrl(srcdir, target, sources):
    srcfiles = [os.path.join(srcdir, fname) for fname in sources]
    destlib = os.path.join(srcdir, target)
    os.system(HC_COMPILE_CMD % (destlib, ' '.join(srcfiles)))

def run_hub_ctrl(enable_power):
    srcdir = os.path.dirname(os.path.realpath(__file__))
    hubdir = os.path.join(srcdir, HC_SOURCE_DIR)
    check_build_code(hubdir, HC_TARGET, HC_SOURCE_FILES, build_hub_ctrl)
    os.system(HC_CMD % (hubdir, enable_power))

if __name__ == '__main__':
    get_ffi()
