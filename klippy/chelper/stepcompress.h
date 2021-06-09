#ifndef STEPCOMPRESS_H
#define STEPCOMPRESS_H

#include <stdint.h> // uint32_t

#define ERROR_RET -989898989

struct stepcompress *stepcompress_alloc(uint32_t oid);
void stepcompress_fill(struct stepcompress *sc, uint32_t max_error
                       , uint32_t invert_sdir, int32_t queue_step_msgtag
                       , int32_t set_next_step_dir_msgtag);
void stepcompress_free(struct stepcompress *sc);
uint32_t stepcompress_get_oid(struct stepcompress *sc);
int stepcompress_get_step_dir(struct stepcompress *sc);
int stepcompress_append(struct stepcompress *sc, int sdir
                        , double print_time, double step_time);
int stepcompress_commit(struct stepcompress *sc);
int stepcompress_reset(struct stepcompress *sc, uint64_t last_step_clock);
int stepcompress_queue_msg(struct stepcompress *sc, uint32_t *data, int len);

struct sync_channel *sync_channel_alloc(uint32_t oid);
void sync_channel_free(struct sync_channel *pc);
void sync_channel_queue_msg(struct sync_channel *pc, uint32_t *data, int len,
        uint64_t req_clock);

struct serialqueue;
struct steppersync *steppersync_alloc(
    struct serialqueue *sq, struct stepcompress **sc_list, int sc_num,
    struct sync_channel **pc_list, int pc_num, int move_num);
void steppersync_free(struct steppersync *ss);
void steppersync_set_time(struct steppersync *ss, double time_offset
                          , double mcu_freq);
int steppersync_flush(struct steppersync *ss, uint64_t move_clock);

#endif // stepcompress.h
