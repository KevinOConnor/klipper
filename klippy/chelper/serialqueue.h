#ifndef SERIALQUEUE_H
#define SERIALQUEUE_H

#include "list.h" // struct list_head

#define MAX_CLOCK 0x7fffffffffffffffLL
#define BACKGROUND_PRIORITY_CLOCK 0x7fffffff00000000LL

#define MESSAGE_MIN 5
#define MESSAGE_MAX 64
#define MESSAGE_HEADER_SIZE  2
#define MESSAGE_TRAILER_SIZE 3
#define MESSAGE_POS_LEN 0
#define MESSAGE_POS_SEQ 1
#define MESSAGE_TRAILER_CRC  3
#define MESSAGE_TRAILER_SYNC 1
#define MESSAGE_PAYLOAD_MAX (MESSAGE_MAX - MESSAGE_MIN)
#define MESSAGE_SEQ_MASK 0x0f
#define MESSAGE_DEST 0x10
#define MESSAGE_SYNC 0x7E

struct queue_message {
    int len;
    uint8_t msg[MESSAGE_MAX];
    union {
        // Filled when on a command queue
        struct {
            uint64_t min_clock, req_clock;
        };
        // Filled when in sent/receive queues
        struct {
            double sent_time, receive_time;
        };
    };
    struct list_node node;
};

struct queue_message *message_alloc_and_encode(uint32_t *data, int len);
void message_queue_free(struct list_head *root);

struct pull_queue_message {
    uint8_t msg[MESSAGE_MAX];
    int len;
    double sent_time, receive_time;
};

struct serialqueue;
struct serialqueue *serialqueue_alloc(int serial_fd, int write_only);
void serialqueue_exit(struct serialqueue *sq);
void serialqueue_free(struct serialqueue *sq);
struct command_queue *serialqueue_alloc_commandqueue(void);
void serialqueue_free_commandqueue(struct command_queue *cq);
void serialqueue_send_batch(struct serialqueue *sq, struct command_queue *cq
                            , struct list_head *msgs);
void serialqueue_send(struct serialqueue *sq, struct command_queue *cq
                      , uint8_t *msg, int len
                      , uint64_t min_clock, uint64_t req_clock);
void serialqueue_encode_and_send(
    struct serialqueue *sq, struct command_queue *cq
    , uint32_t *data, int len, uint64_t min_clock, uint64_t req_clock);
void serialqueue_pull(struct serialqueue *sq, struct pull_queue_message *pqm);
void serialqueue_set_baud_adjust(struct serialqueue *sq, double baud_adjust);
void serialqueue_set_receive_window(struct serialqueue *sq
    , int receive_window);
void serialqueue_set_clock_est(struct serialqueue *sq, double est_freq
                               , double last_clock_time, uint64_t last_clock);
void serialqueue_get_stats(struct serialqueue *sq, char *buf, int len);
int serialqueue_extract_old(struct serialqueue *sq, int sentq
                            , struct pull_queue_message *q, int max);

#endif // serialqueue.h
