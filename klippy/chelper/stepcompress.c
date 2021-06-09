// Stepper pulse schedule compression
//
// Copyright (C) 2016-2021  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

// The goal of this code is to take a series of scheduled stepper
// pulse times and compress them into a handful of commands that can
// be efficiently transmitted and executed on a microcontroller (mcu).
// The mcu accepts step pulse commands that take interval, count, and
// add parameters such that 'count' pulses occur, with each step event
// calculating the next step event time using:
//  next_wake_time = last_wake_time + interval; interval += add
// This code is written in C (instead of python) for processing
// efficiency - the repetitive integer math is vastly faster in C.

#include <math.h> // sqrt
#include <stddef.h> // offsetof
#include <stdint.h> // uint32_t
#include <stdio.h> // fprintf
#include <stdlib.h> // malloc
#include <string.h> // memset
#include "compiler.h" // DIV_ROUND_UP
#include "pyhelper.h" // errorf
#include "serialqueue.h" // struct queue_message
#include "stepcompress.h" // stepcompress_alloc

#define CHECK_LINES 1
#define QUEUE_START_SIZE 1024

struct stepcompress {
    // Buffer management
    uint32_t *queue, *queue_end, *queue_pos, *queue_next;
    // Internal tracking
    uint32_t max_error;
    double mcu_time_offset, mcu_freq, last_step_print_time;
    // Message generation
    uint64_t last_step_clock;
    struct list_head msg_queue;
    uint32_t oid;
    int32_t queue_step_msgtag, set_next_step_dir_msgtag;
    int sdir, invert_sdir;
    // Step+dir+step filter
    uint64_t next_step_clock;
    int next_step_dir;
    // History tracking
    int64_t last_position;
    struct list_head history_list;
};

struct sync_channel {
    // Buffer management
    uint32_t *queue, *queue_end, *queue_pos, *queue_next;

    // Message generation
    struct list_head msg_queue;
    uint32_t oid;
};

struct step_move {
    uint32_t interval;
    uint16_t count;
    int16_t add;
};

#define HISTORY_EXPIRE (30.0)

struct history_move {
    struct list_node node;
    uint64_t first_clock, last_clock;
    int64_t start_position;
    int step_count;
    struct step_move sm;
};


/****************************************************************
 * Step compression
 ****************************************************************/

static inline int32_t
idiv_up(int32_t n, int32_t d)
{
    return (n>=0) ? DIV_ROUND_UP(n,d) : (n/d);
}

static inline int32_t
idiv_down(int32_t n, int32_t d)
{
    return (n>=0) ? (n/d) : (n - d + 1) / d;
}

struct points {
    int32_t minp, maxp;
};

// Given a requested step time, return the minimum and maximum
// acceptable times
static inline struct points
minmax_point(struct stepcompress *sc, uint32_t *pos)
{
    uint32_t lsc = sc->last_step_clock, point = *pos - lsc;
    uint32_t prevpoint = pos > sc->queue_pos ? *(pos-1) - lsc : 0;
    uint32_t max_error = (point - prevpoint) / 2;
    if (max_error > sc->max_error)
        max_error = sc->max_error;
    return (struct points){ point - max_error, point };
}

// The maximum add delta between two valid quadratic sequences of the
// form "add*count*(count-1)/2 + interval*count" is "(6 + 4*sqrt(2)) *
// maxerror / (count*count)".  The "6 + 4*sqrt(2)" is 11.65685, but
// using 11 works well in practice.
#define QUADRATIC_DEV 11

// Find a 'step_move' that covers a series of step times
static struct step_move
compress_bisect_add(struct stepcompress *sc)
{
    uint32_t *qlast = sc->queue_next;
    if (qlast > sc->queue_pos + 65535)
        qlast = sc->queue_pos + 65535;
    struct points point = minmax_point(sc, sc->queue_pos);
    int32_t outer_mininterval = point.minp, outer_maxinterval = point.maxp;
    int32_t add = 0, minadd = -0x8000, maxadd = 0x7fff;
    int32_t bestinterval = 0, bestcount = 1, bestadd = 1, bestreach = INT32_MIN;
    int32_t zerointerval = 0, zerocount = 0;

    for (;;) {
        // Find longest valid sequence with the given 'add'
        struct points nextpoint;
        int32_t nextmininterval = outer_mininterval;
        int32_t nextmaxinterval = outer_maxinterval, interval = nextmaxinterval;
        int32_t nextcount = 1;
        for (;;) {
            nextcount++;
            if (&sc->queue_pos[nextcount-1] >= qlast) {
                int32_t count = nextcount - 1;
                return (struct step_move){ interval, count, add };
            }
            nextpoint = minmax_point(sc, sc->queue_pos + nextcount - 1);
            int32_t nextaddfactor = nextcount*(nextcount-1)/2;
            int32_t c = add*nextaddfactor;
            if (nextmininterval*nextcount < nextpoint.minp - c)
                nextmininterval = idiv_up(nextpoint.minp - c, nextcount);
            if (nextmaxinterval*nextcount > nextpoint.maxp - c)
                nextmaxinterval = idiv_down(nextpoint.maxp - c, nextcount);
            if (nextmininterval > nextmaxinterval)
                break;
            interval = nextmaxinterval;
        }

        // Check if this is the best sequence found so far
        int32_t count = nextcount - 1, addfactor = count*(count-1)/2;
        int32_t reach = add*addfactor + interval*count;
        if (reach > bestreach
            || (reach == bestreach && interval > bestinterval)) {
            bestinterval = interval;
            bestcount = count;
            bestadd = add;
            bestreach = reach;
            if (!add) {
                zerointerval = interval;
                zerocount = count;
            }
            if (count > 0x200)
                // No 'add' will improve sequence; avoid integer overflow
                break;
        }

        // Check if a greater or lesser add could extend the sequence
        int32_t nextaddfactor = nextcount*(nextcount-1)/2;
        int32_t nextreach = add*nextaddfactor + interval*nextcount;
        if (nextreach < nextpoint.minp) {
            minadd = add + 1;
            outer_maxinterval = nextmaxinterval;
        } else {
            maxadd = add - 1;
            outer_mininterval = nextmininterval;
        }

        // The maximum valid deviation between two quadratic sequences
        // can be calculated and used to further limit the add range.
        if (count > 1) {
            int32_t errdelta = sc->max_error*QUADRATIC_DEV / (count*count);
            if (minadd < add - errdelta)
                minadd = add - errdelta;
            if (maxadd > add + errdelta)
                maxadd = add + errdelta;
        }

        // See if next point would further limit the add range
        int32_t c = outer_maxinterval * nextcount;
        if (minadd*nextaddfactor < nextpoint.minp - c)
            minadd = idiv_up(nextpoint.minp - c, nextaddfactor);
        c = outer_mininterval * nextcount;
        if (maxadd*nextaddfactor > nextpoint.maxp - c)
            maxadd = idiv_down(nextpoint.maxp - c, nextaddfactor);

        // Bisect valid add range and try again with new 'add'
        if (minadd > maxadd)
            break;
        add = maxadd - (maxadd - minadd) / 4;
    }
    if (zerocount + zerocount/16 >= bestcount)
        // Prefer add=0 if it's similar to the best found sequence
        return (struct step_move){ zerointerval, zerocount, 0 };
    return (struct step_move){ bestinterval, bestcount, bestadd };
}


/****************************************************************
 * Step compress checking
 ****************************************************************/

// Verify that a given 'step_move' matches the actual step times
static int
check_line(struct stepcompress *sc, struct step_move move)
{
    if (!CHECK_LINES)
        return 0;
    if (!move.count || (!move.interval && !move.add && move.count > 1)
        || move.interval >= 0x80000000) {
        errorf("stepcompress o=%d i=%d c=%d a=%d: Invalid sequence"
               , sc->oid, move.interval, move.count, move.add);
        return ERROR_RET;
    }
    uint32_t interval = move.interval, p = 0;
    uint16_t i;
    for (i=0; i<move.count; i++) {
        struct points point = minmax_point(sc, sc->queue_pos + i);
        p += interval;
        if (p < point.minp || p > point.maxp) {
            errorf("stepcompress o=%d i=%d c=%d a=%d: Point %d: %d not in %d:%d"
                   , sc->oid, move.interval, move.count, move.add
                   , i+1, p, point.minp, point.maxp);
            return ERROR_RET;
        }
        if (interval >= 0x80000000) {
            errorf("stepcompress o=%d i=%d c=%d a=%d:"
                   " Point %d: interval overflow %d"
                   , sc->oid, move.interval, move.count, move.add
                   , i+1, interval);
            return ERROR_RET;
        }
        interval += move.add;
    }
    return 0;
}


/****************************************************************
 * Step compress interface
 ****************************************************************/

// Allocate a new 'stepcompress' object
struct stepcompress * __visible
stepcompress_alloc(uint32_t oid)
{
    struct stepcompress *sc = malloc(sizeof(*sc));
    memset(sc, 0, sizeof(*sc));
    list_init(&sc->msg_queue);
    list_init(&sc->history_list);
    sc->oid = oid;
    sc->sdir = -1;
    return sc;
}

// Fill message id information
void __visible
stepcompress_fill(struct stepcompress *sc, uint32_t max_error
                  , uint32_t invert_sdir, int32_t queue_step_msgtag
                  , int32_t set_next_step_dir_msgtag)
{
    sc->max_error = max_error;
    sc->invert_sdir = !!invert_sdir;
    sc->queue_step_msgtag = queue_step_msgtag;
    sc->set_next_step_dir_msgtag = set_next_step_dir_msgtag;
}

// Helper to free items from the history_list
static void
free_history(struct stepcompress *sc, uint64_t end_clock)
{
    while (!list_empty(&sc->history_list)) {
        struct history_move *hm = list_last_entry(
            &sc->history_list, struct history_move, node);
        if (hm->last_clock > end_clock)
            break;
        list_del(&hm->node);
        free(hm);
    }
}

// Free memory associated with a 'stepcompress' object
void __visible
stepcompress_free(struct stepcompress *sc)
{
    if (!sc)
        return;
    free(sc->queue);
    message_queue_free(&sc->msg_queue);
    free_history(sc, UINT64_MAX);
    free(sc);
}

uint32_t
stepcompress_get_oid(struct stepcompress *sc)
{
    return sc->oid;
}

int
stepcompress_get_step_dir(struct stepcompress *sc)
{
    return sc->next_step_dir;
}

/****************************************************************
 * Sync channel interface
 ****************************************************************/

struct sync_channel * __visible
sync_channel_alloc(uint32_t oid)
{
    struct sync_channel *pc = malloc(sizeof(*pc));
    memset(pc, 0, sizeof(*pc));
    list_init(&pc->msg_queue);
    pc->oid = oid;
    return pc;
}

void __visible
sync_channel_free(struct sync_channel *pc)
{
    if (!pc)
        return;
    free(pc->queue);
    message_queue_free(&pc->msg_queue);
    free(pc);
}

void __visible
sync_channel_queue_msg(struct sync_channel *pc, uint32_t *data, int len,
        uint64_t req_clock)
{
    struct queue_message *qm = message_alloc_and_encode(data, len);
    qm->req_clock = req_clock;
    qm->min_clock = req_clock;

    list_add_tail(&qm->node, &pc->msg_queue);
}

// Determine the "print time" of the last_step_clock
static void
calc_last_step_print_time(struct stepcompress *sc)
{
    double lsc = sc->last_step_clock;
    sc->last_step_print_time = sc->mcu_time_offset + (lsc - .5) / sc->mcu_freq;

    if (lsc > sc->mcu_freq * HISTORY_EXPIRE)
        free_history(sc, lsc - sc->mcu_freq * HISTORY_EXPIRE);
}

// Set the conversion rate of 'print_time' to mcu clock
static void
stepcompress_set_time(struct stepcompress *sc
                      , double time_offset, double mcu_freq)
{
    sc->mcu_time_offset = time_offset;
    sc->mcu_freq = mcu_freq;
    calc_last_step_print_time(sc);
}

// Maximium clock delta between messages in the queue
#define CLOCK_DIFF_MAX (3<<28)

// Helper to create a queue_step command from a 'struct step_move'
static void
add_move(struct stepcompress *sc, uint64_t first_clock, struct step_move *move)
{
    int32_t addfactor = move->count*(move->count-1)/2;
    uint32_t ticks = move->add*addfactor + move->interval*(move->count-1);
    uint64_t last_clock = first_clock + ticks;

    // Create and queue a queue_step command
    uint32_t msg[5] = {
        sc->queue_step_msgtag, sc->oid, move->interval, move->count, move->add
    };
    struct queue_message *qm = message_alloc_and_encode(msg, 5);
    qm->min_clock = qm->req_clock = sc->last_step_clock;
    if (move->count == 1 && first_clock >= sc->last_step_clock + CLOCK_DIFF_MAX)
        qm->req_clock = first_clock;
    list_add_tail(&qm->node, &sc->msg_queue);
    sc->last_step_clock = last_clock;

    // Create and store move in history tracking
    struct history_move *hm = malloc(sizeof(*hm));
    hm->first_clock = first_clock;
    hm->last_clock = last_clock;
    hm->start_position = sc->last_position;
    hm->step_count = sc->sdir ? move->count : -move->count;
    sc->last_position += hm->step_count;
    memcpy(&hm->sm, move, sizeof(hm->sm));
    list_add_head(&hm->node, &sc->history_list);
}

// Convert previously scheduled steps into commands for the mcu
static int
queue_flush(struct stepcompress *sc, uint64_t move_clock)
{
    if (sc->queue_pos >= sc->queue_next)
        return 0;
    while (sc->last_step_clock < move_clock) {
        struct step_move move = compress_bisect_add(sc);
        int ret = check_line(sc, move);
        if (ret)
            return ret;

        add_move(sc, sc->last_step_clock + move.interval, &move);

        if (sc->queue_pos + move.count >= sc->queue_next) {
            sc->queue_pos = sc->queue_next = sc->queue;
            break;
        }
        sc->queue_pos += move.count;
    }
    calc_last_step_print_time(sc);
    return 0;
}

// Generate a queue_step for a step far in the future from the last step
static int
stepcompress_flush_far(struct stepcompress *sc, uint64_t abs_step_clock)
{
    struct step_move move = { abs_step_clock - sc->last_step_clock, 1, 0 };
    add_move(sc, abs_step_clock, &move);
    calc_last_step_print_time(sc);
    return 0;
}

// Send the set_next_step_dir command
static int
set_next_step_dir(struct stepcompress *sc, int sdir)
{
    if (sc->sdir == sdir)
        return 0;
    int ret = queue_flush(sc, UINT64_MAX);
    if (ret)
        return ret;
    sc->sdir = sdir;
    uint32_t msg[3] = {
        sc->set_next_step_dir_msgtag, sc->oid, sdir ^ sc->invert_sdir
    };
    struct queue_message *qm = message_alloc_and_encode(msg, 3);
    qm->req_clock = sc->last_step_clock;
    list_add_tail(&qm->node, &sc->msg_queue);
    return 0;
}

// Slow path for queue_append() - handle next step far in future
static int
queue_append_far(struct stepcompress *sc)
{
    uint64_t step_clock = sc->next_step_clock;
    sc->next_step_clock = 0;
    int ret = queue_flush(sc, step_clock - CLOCK_DIFF_MAX + 1);
    if (ret)
        return ret;
    if (step_clock >= sc->last_step_clock + CLOCK_DIFF_MAX)
        return stepcompress_flush_far(sc, step_clock);
    *sc->queue_next++ = step_clock;
    return 0;
}

// Slow path for queue_append() - expand the internal queue storage
static int
queue_append_extend(struct stepcompress *sc)
{
    if (sc->queue_next - sc->queue_pos > 65535 + 2000) {
        // No point in keeping more than 64K steps in memory
        uint32_t flush = (*(sc->queue_next-65535)
                          - (uint32_t)sc->last_step_clock);
        int ret = queue_flush(sc, sc->last_step_clock + flush);
        if (ret)
            return ret;
    }

    if (sc->queue_next >= sc->queue_end) {
        // Make room in the queue
        int in_use = sc->queue_next - sc->queue_pos;
        if (sc->queue_pos > sc->queue) {
            // Shuffle the internal queue to avoid having to allocate more ram
            memmove(sc->queue, sc->queue_pos, in_use * sizeof(*sc->queue));
        } else {
            // Expand the internal queue of step times
            int alloc = sc->queue_end - sc->queue;
            if (!alloc)
                alloc = QUEUE_START_SIZE;
            while (in_use >= alloc)
                alloc *= 2;
            sc->queue = realloc(sc->queue, alloc * sizeof(*sc->queue));
            sc->queue_end = sc->queue + alloc;
        }
        sc->queue_pos = sc->queue;
        sc->queue_next = sc->queue + in_use;
    }

    *sc->queue_next++ = sc->next_step_clock;
    sc->next_step_clock = 0;
    return 0;
}

// Add a step time to the queue (flushing the queue if needed)
static int
queue_append(struct stepcompress *sc)
{
    if (unlikely(sc->next_step_dir != sc->sdir)) {
        int ret = set_next_step_dir(sc, sc->next_step_dir);
        if (ret)
            return ret;
    }
    if (unlikely(sc->next_step_clock >= sc->last_step_clock + CLOCK_DIFF_MAX))
        return queue_append_far(sc);
    if (unlikely(sc->queue_next >= sc->queue_end))
        return queue_append_extend(sc);
    *sc->queue_next++ = sc->next_step_clock;
    sc->next_step_clock = 0;
    return 0;
}

#define SDS_FILTER_TIME .000750

// Add next step time
int
stepcompress_append(struct stepcompress *sc, int sdir
                    , double print_time, double step_time)
{
    // Calculate step clock
    double offset = print_time - sc->last_step_print_time;
    double rel_sc = (step_time + offset) * sc->mcu_freq;
    uint64_t step_clock = sc->last_step_clock + (uint64_t)rel_sc;
    // Flush previous pending step (if any)
    if (sc->next_step_clock) {
        if (unlikely(sdir != sc->next_step_dir)) {
            double diff = (int64_t)(step_clock - sc->next_step_clock);
            if (diff < SDS_FILTER_TIME * sc->mcu_freq) {
                // Rollback last step to avoid rapid step+dir+step
                sc->next_step_clock = 0;
                sc->next_step_dir = sdir;
                return 0;
            }
        }
        int ret = queue_append(sc);
        if (ret)
            return ret;
    }
    // Store this step as the next pending step
    sc->next_step_clock = step_clock;
    sc->next_step_dir = sdir;
    return 0;
}

// Commit next pending step (ie, do not allow a rollback)
int
stepcompress_commit(struct stepcompress *sc)
{
    if (sc->next_step_clock)
        return queue_append(sc);
    return 0;
}

// Flush pending steps
static int
stepcompress_flush(struct stepcompress *sc, uint64_t move_clock)
{
    if (sc->next_step_clock && move_clock >= sc->next_step_clock) {
        int ret = queue_append(sc);
        if (ret)
            return ret;
    }
    return queue_flush(sc, move_clock);
}

// Reset the internal state of the stepcompress object
int __visible
stepcompress_reset(struct stepcompress *sc, uint64_t last_step_clock)
{
    int ret = stepcompress_flush(sc, UINT64_MAX);
    if (ret)
        return ret;
    sc->last_step_clock = last_step_clock;
    sc->sdir = -1;
    calc_last_step_print_time(sc);
    return 0;
}

// Set last_position in the stepcompress object
int __visible
stepcompress_set_last_position(struct stepcompress *sc, int64_t last_position)
{
    int ret = stepcompress_flush(sc, UINT64_MAX);
    if (ret)
        return ret;
    sc->last_position = last_position;
    return 0;
}

// Search history of moves to find a past position at a given clock
int64_t __visible
stepcompress_find_past_position(struct stepcompress *sc, uint64_t clock)
{
    int64_t last_position = sc->last_position;
    struct history_move *hm;
    list_for_each_entry(hm, &sc->history_list, node) {
        if (clock < hm->first_clock) {
            last_position = hm->start_position;
            continue;
        }
        if (clock >= hm->last_clock)
            return hm->start_position + hm->step_count;
        int32_t interval = hm->sm.interval, add = hm->sm.add;
        int32_t ticks = (int32_t)(clock - hm->first_clock) + interval, offset;
        if (!add) {
            offset = ticks / interval;
        } else {
            // Solve for "count" using quadratic formula
            double a = .5 * add, b = interval - .5 * add, c = -ticks;
            offset = (sqrt(b*b - 4*a*c) - b) / (2. * a);
        }
        if (hm->step_count < 0)
            return hm->start_position - offset;
        return hm->start_position + offset;
    }
    return last_position;
}

// Queue an mcu command to go out in order with stepper commands
int __visible
stepcompress_queue_msg(struct stepcompress *sc, uint32_t *data, int len)
{
    int ret = stepcompress_flush(sc, UINT64_MAX);
    if (ret)
        return ret;

    struct queue_message *qm = message_alloc_and_encode(data, len);
    qm->req_clock = sc->last_step_clock;
    list_add_tail(&qm->node, &sc->msg_queue);
    return 0;
}


/****************************************************************
 * Step compress synchronization
 ****************************************************************/

// The steppersync object is used to synchronize the output of mcu
// step commands.  The mcu can only queue a limited number of step
// commands - this code tracks when items on the mcu step queue become
// free so that new commands can be transmitted.  It also ensures the
// mcu step queue is ordered between steppers so that no stepper
// starves the other steppers of space in the mcu step queue.

struct steppersync {
    // Serial port
    struct serialqueue *sq;
    struct command_queue *cq;
    // Storage for associated stepcompress objects
    struct stepcompress **sc_list;
    int sc_num;
    // Storage for associated synchronous message objects
    struct sync_channel **pc_list;
    int pc_num;
    // Storage for list of pending move clocks
    uint64_t *move_clocks;
    int num_move_clocks;
};

// Allocate a new 'steppersync' object
struct steppersync * __visible
steppersync_alloc(struct serialqueue *sq, struct stepcompress **sc_list,
                  int sc_num, struct sync_channel **pc_list,
                  int pc_num,  int move_num)
{
    struct steppersync *ss = malloc(sizeof(*ss));
    memset(ss, 0, sizeof(*ss));
    ss->sq = sq;
    ss->cq = serialqueue_alloc_commandqueue();

    ss->sc_list = malloc(sizeof(*sc_list)*sc_num);
    memcpy(ss->sc_list, sc_list, sizeof(*sc_list)*sc_num);
    ss->sc_num = sc_num;

    ss->pc_list = malloc(sizeof(*pc_list)*pc_num);
    memcpy(ss->pc_list, pc_list, sizeof(*pc_list)*pc_num);
    ss->pc_num = pc_num;

    ss->move_clocks = malloc(sizeof(*ss->move_clocks)*move_num);
    memset(ss->move_clocks, 0, sizeof(*ss->move_clocks)*move_num);
    ss->num_move_clocks = move_num;

    return ss;
}

// Free memory associated with a 'steppersync' object
void __visible
steppersync_free(struct steppersync *ss)
{
    if (!ss)
        return;
    free(ss->sc_list);
    free(ss->move_clocks);
    serialqueue_free_commandqueue(ss->cq);
    free(ss);
}

// Set the conversion rate of 'print_time' to mcu clock
void __visible
steppersync_set_time(struct steppersync *ss, double time_offset
                     , double mcu_freq)
{
    int i;
    for (i=0; i<ss->sc_num; i++) {
        struct stepcompress *sc = ss->sc_list[i];
        stepcompress_set_time(sc, time_offset, mcu_freq);
    }
}

// Implement a binary heap algorithm to track when the next available
// 'struct move' in the mcu will be available
static void
heap_replace(struct steppersync *ss, uint64_t req_clock)
{
    uint64_t *mc = ss->move_clocks;
    int nmc = ss->num_move_clocks, pos = 0;
    for (;;) {
        int child1_pos = 2*pos+1, child2_pos = 2*pos+2;
        uint64_t child2_clock = child2_pos < nmc ? mc[child2_pos] : UINT64_MAX;
        uint64_t child1_clock = child1_pos < nmc ? mc[child1_pos] : UINT64_MAX;
        if (req_clock <= child1_clock && req_clock <= child2_clock) {
            mc[pos] = req_clock;
            break;
        }
        if (child1_clock < child2_clock) {
            mc[pos] = child1_clock;
            pos = child1_pos;
        } else {
            mc[pos] = child2_clock;
            pos = child2_pos;
        }
    }
}

// Find and transmit any scheduled steps prior to the given 'move_clock'
int __visible
steppersync_flush(struct steppersync *ss, uint64_t move_clock)
{
    // Flush each stepcompress to the specified move_clock
    int i;
    for (i=0; i<ss->sc_num; i++) {
        int ret = stepcompress_flush(ss->sc_list[i], move_clock);
        if (ret)
            return ret;
    }

    // Order commands by the reqclock of each pending command
    struct list_head msgs;
    list_init(&msgs);
    for (;;) {
        // Find message with lowest reqclock
        uint64_t req_clock = MAX_CLOCK;
        struct queue_message *qm = NULL;
        for (i=0; i<ss->sc_num; i++) {
            struct stepcompress *sc = ss->sc_list[i];
            if (!list_empty(&sc->msg_queue)) {
                struct queue_message *m = list_first_entry(
                    &sc->msg_queue, struct queue_message, node);
                if (m->req_clock < req_clock) {
                    qm = m;
                    req_clock = m->req_clock;
                }
            }
        }
        // sync_channel
        for (i=0; i<ss->pc_num; i++) {
            struct sync_channel *pc = ss->pc_list[i];
            if (!list_empty(&pc->msg_queue)) {
                struct queue_message *m = list_first_entry(
                    &pc->msg_queue, struct queue_message, node);
                if (m->req_clock < req_clock) {
                    qm = m;
                    req_clock = m->req_clock;
                }
            }
        }
        if (!qm || (qm->min_clock && req_clock > move_clock))
            break;

        uint64_t next_avail = ss->move_clocks[0];
        if (qm->min_clock)
            // The qm->min_clock field is overloaded to indicate that
            // the command uses the 'move queue' and to store the time
            // that move queue item becomes available.
            heap_replace(ss, qm->min_clock);
        // Reset the min_clock to its normal meaning (minimum transmit time)
        qm->min_clock = next_avail;

        // Batch this command
        list_del(&qm->node);
        list_add_tail(&qm->node, &msgs);
    }

    // Transmit commands
    if (!list_empty(&msgs))
        serialqueue_send_batch(ss->sq, ss->cq, &msgs);
    return 0;
}
