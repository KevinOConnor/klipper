# Wrapper around C helper code
#
# Copyright (C) 2016-2021  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, logging
import cffi


######################################################################
# c_helper.so compiling
######################################################################

GCC_CMD = "gcc"
COMPILE_ARGS = ("-Wall -g -O2 -shared -fPIC"
                " -flto -fwhole-program -fno-use-linker-plugin"
                " -o %s %s")
SSE_FLAGS = "-mfpmath=sse -msse2"
SOURCE_FILES = [
    'pyhelper.c', 'serialqueue.c', 'stepcompress.c', 'itersolve.c', 'trapq.c',
    'kin_cartesian.c', 'kin_corexy.c', 'kin_corexz.c', 'kin_delta.c',
    'kin_polar.c', 'kin_rotary_delta.c', 'kin_winch.c', 'kin_extruder.c',
    'kin_shaper.c',
]
DEST_LIB = "c_helper.so"
OTHER_FILES = [
    'list.h', 'serialqueue.h', 'stepcompress.h', 'itersolve.h', 'pyhelper.h',
    'trapq.h',
]

defs_stepcompress = """
    struct stepcompress *stepcompress_alloc(uint32_t oid);
    void stepcompress_fill(struct stepcompress *sc, uint32_t max_error
        , uint32_t invert_sdir, int32_t queue_step_msgtag
        , int32_t set_next_step_dir_msgtag);
    void stepcompress_free(struct stepcompress *sc);
    int stepcompress_reset(struct stepcompress *sc, uint64_t last_step_clock);
    int stepcompress_set_last_position(struct stepcompress *sc
        , int64_t last_position);
    int64_t stepcompress_find_past_position(struct stepcompress *sc
        , uint64_t clock);
    int stepcompress_queue_msg(struct stepcompress *sc
        , uint32_t *data, int len);
    struct steppersync *steppersync_alloc(struct serialqueue *sq
        , struct stepcompress **sc_list, int sc_num
        , struct sync_channel **pc_list, int pc_num, int move_num);
    void steppersync_free(struct steppersync *ss);
    void steppersync_set_time(struct steppersync *ss
        , double time_offset, double mcu_freq);
    int steppersync_flush(struct steppersync *ss, uint64_t move_clock);
"""

defs_sync_channel = """
    struct sync_channel *sync_channel_alloc(uint32_t oid);
    void sync_channel_free(struct sync_channel *pc);
    int sync_channel_queue_msg(struct sync_channel *pc
        , uint32_t *data, int len, uint64_t req_clock);
"""

defs_itersolve = """
    int32_t itersolve_generate_steps(struct stepper_kinematics *sk
        , double flush_time);
    double itersolve_check_active(struct stepper_kinematics *sk
        , double flush_time);
    int32_t itersolve_is_active_axis(struct stepper_kinematics *sk, char axis);
    void itersolve_set_trapq(struct stepper_kinematics *sk, struct trapq *tq);
    void itersolve_set_stepcompress(struct stepper_kinematics *sk
        , struct stepcompress *sc, double step_dist);
    double itersolve_calc_position_from_coord(struct stepper_kinematics *sk
        , double x, double y, double z);
    void itersolve_set_position(struct stepper_kinematics *sk
        , double x, double y, double z);
    double itersolve_get_commanded_pos(struct stepper_kinematics *sk);
"""

defs_trapq = """
    void trapq_append(struct trapq *tq, double print_time
        , double accel_t, double cruise_t, double decel_t
        , double start_pos_x, double start_pos_y, double start_pos_z
        , double axes_r_x, double axes_r_y, double axes_r_z
        , double start_v, double cruise_v, double accel);
    struct trapq *trapq_alloc(void);
    void trapq_free(struct trapq *tq);
    void trapq_free_moves(struct trapq *tq, double print_time);
"""

defs_kin_cartesian = """
    struct stepper_kinematics *cartesian_stepper_alloc(char axis);
"""

defs_kin_corexy = """
    struct stepper_kinematics *corexy_stepper_alloc(char type);
"""

defs_kin_corexz = """
    struct stepper_kinematics *corexz_stepper_alloc(char type);
"""

defs_kin_delta = """
    struct stepper_kinematics *delta_stepper_alloc(double arm2
        , double tower_x, double tower_y);
"""

defs_kin_polar = """
    struct stepper_kinematics *polar_stepper_alloc(char type);
"""

defs_kin_rotary_delta = """
    struct stepper_kinematics *rotary_delta_stepper_alloc(
        double shoulder_radius, double shoulder_height
        , double angle, double upper_arm, double lower_arm);
"""

defs_kin_winch = """
    struct stepper_kinematics *winch_stepper_alloc(double anchor_x
        , double anchor_y, double anchor_z);
"""

defs_kin_extruder = """
    struct stepper_kinematics *extruder_stepper_alloc(void);
    void extruder_set_smooth_time(struct stepper_kinematics *sk
        , double smooth_time);
"""

defs_kin_shaper = """
    enum INPUT_SHAPER_TYPE {
        INPUT_SHAPER_ZV = 0,
        INPUT_SHAPER_ZVD = 1,
        INPUT_SHAPER_MZV = 2,
        INPUT_SHAPER_EI = 3,
        INPUT_SHAPER_2HUMP_EI = 4,
        INPUT_SHAPER_3HUMP_EI = 5,
    };

    double input_shaper_get_step_generation_window(int shaper_type
        , double shaper_freq, double damping_ratio);
    int input_shaper_set_shaper_params(struct stepper_kinematics *sk
        , int shaper_type_x, int shaper_type_y
        , double shaper_freq_x, double shaper_freq_y
        , double damping_ratio_x, double damping_ratio_y);
    int input_shaper_set_sk(struct stepper_kinematics *sk
        , struct stepper_kinematics *orig_sk);
    struct stepper_kinematics * input_shaper_alloc(void);
"""

defs_serialqueue = """
    #define MESSAGE_MAX 64
    struct pull_queue_message {
        uint8_t msg[MESSAGE_MAX];
        int len;
        double sent_time, receive_time;
        uint64_t notify_id;
    };

    struct serialqueue *serialqueue_alloc(int serial_fd, char serial_fd_type
        , int client_id);
    void serialqueue_exit(struct serialqueue *sq);
    void serialqueue_free(struct serialqueue *sq);
    struct command_queue *serialqueue_alloc_commandqueue(void);
    void serialqueue_free_commandqueue(struct command_queue *cq);
    void serialqueue_send(struct serialqueue *sq, struct command_queue *cq
        , uint8_t *msg, int len, uint64_t min_clock, uint64_t req_clock
        , uint64_t notify_id);
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
    void set_python_logging_callback(void (*func)(const char *));
    double get_monotonic(void);
"""

defs_std = """
    void free(void*);
"""

defs_all = [
    defs_pyhelper, defs_serialqueue, defs_std, defs_stepcompress,
    defs_sync_channel, defs_itersolve, defs_trapq, defs_kin_cartesian,
    defs_kin_corexy, defs_kin_corexz, defs_kin_delta, defs_kin_polar,
    defs_kin_rotary_delta, defs_kin_winch, defs_kin_extruder, defs_kin_shaper,
]

# Update filenames to an absolute path
def get_abs_files(srcdir, filelist):
    return [os.path.join(srcdir, fname) for fname in filelist]

# Return the list of file modification times
def get_mtimes(filelist):
    out = []
    for filename in filelist:
        try:
            t = os.path.getmtime(filename)
        except os.error:
            continue
        out.append(t)
    return out

# Check if the code needs to be compiled
def check_build_code(sources, target):
    src_times = get_mtimes(sources)
    obj_times = get_mtimes([target])
    return not obj_times or max(src_times) > min(obj_times)

# Check if the current gcc version supports a particular command-line option
def check_gcc_option(option):
    cmd = "%s %s -S -o /dev/null -xc /dev/null > /dev/null 2>&1" % (
        GCC_CMD, option)
    res = os.system(cmd)
    return res == 0

# Check if the current gcc version supports a particular command-line option
def do_build_code(cmd):
    res = os.system(cmd)
    if res:
        msg = "Unable to build C code module (error=%s)" % (res,)
        logging.error(msg)
        raise Exception(msg)

FFI_main = None
FFI_lib = None
pyhelper_logging_callback = None

# Hepler invoked from C errorf() code to log errors
def logging_callback(msg):
    logging.error(FFI_main.string(msg))

# Return the Foreign Function Interface api to the caller
def get_ffi():
    global FFI_main, FFI_lib, pyhelper_logging_callback
    if FFI_lib is None:
        srcdir = os.path.dirname(os.path.realpath(__file__))
        srcfiles = get_abs_files(srcdir, SOURCE_FILES)
        ofiles = get_abs_files(srcdir, OTHER_FILES)
        destlib = get_abs_files(srcdir, [DEST_LIB])[0]
        if check_build_code(srcfiles+ofiles+[__file__], destlib):
            if check_gcc_option(SSE_FLAGS):
                cmd = "%s %s %s" % (GCC_CMD, SSE_FLAGS, COMPILE_ARGS)
            else:
                cmd = "%s %s" % (GCC_CMD, COMPILE_ARGS)
            logging.info("Building C code module %s", DEST_LIB)
            do_build_code(cmd % (destlib, ' '.join(srcfiles)))
        FFI_main = cffi.FFI()
        for d in defs_all:
            FFI_main.cdef(d)
        FFI_lib = FFI_main.dlopen(destlib)
        # Setup error logging
        pyhelper_logging_callback = FFI_main.callback("void func(const char *)",
                                                      logging_callback)
        FFI_lib.set_python_logging_callback(pyhelper_logging_callback)
    return FFI_main, FFI_lib


######################################################################
# hub-ctrl hub power controller
######################################################################

HC_COMPILE_CMD = "gcc -Wall -g -O2 -o %s %s -lusb"
HC_SOURCE_FILES = ['hub-ctrl.c']
HC_SOURCE_DIR = '../../lib/hub-ctrl'
HC_TARGET = "hub-ctrl"
HC_CMD = "sudo %s/hub-ctrl -h 0 -P 2 -p %d"

def run_hub_ctrl(enable_power):
    srcdir = os.path.dirname(os.path.realpath(__file__))
    hubdir = os.path.join(srcdir, HC_SOURCE_DIR)
    srcfiles = get_abs_files(hubdir, HC_SOURCE_FILES)
    destlib = get_abs_files(hubdir, [HC_TARGET])[0]
    if check_build_code(srcfiles, destlib):
        logging.info("Building C code module %s", HC_TARGET)
        do_build_code(HC_COMPILE_CMD % (destlib, ' '.join(srcfiles)))
    os.system(HC_CMD % (hubdir, enable_power))


if __name__ == '__main__':
    get_ffi()
