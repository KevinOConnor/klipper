// Serial port command queuing
//
// Copyright (C) 2016-2021  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

// This goal of this code is to handle low-level serial port
// communications with a microcontroller (mcu).  This code is written
// in C (instead of python) to reduce communication latencies and to
// reduce scheduling jitter.  The code queues messages to be
// transmitted, schedules transmission of commands at specified mcu
// clock times, prioritizes commands, and handles retransmissions.  A
// background thread is launched to do this work and minimize latency.

#include <fcntl.h> // fcntl
#include <math.h> // ceil
#include <poll.h> // poll
#include <pthread.h> // pthread_mutex_lock
#include <stddef.h> // offsetof
#include <stdint.h> // uint64_t
#include <stdio.h> // snprintf
#include <stdlib.h> // malloc
#include <string.h> // memset
#include <termios.h> // tcflush
#include <unistd.h> // pipe
#include "compiler.h" // __visible
#include "list.h" // list_add_tail
#include "pyhelper.h" // get_monotonic
#include "serialqueue.h" // struct queue_message


/****************************************************************
 * Poll reactor
 ****************************************************************/

// The 'poll reactor' code is a mechanism for dispatching timer and
// file descriptor events.

#define PR_NOW   0.
#define PR_NEVER 9999999999999999.

struct pollreactor_timer {
    double waketime;
    double (*callback)(void *data, double eventtime);
};

struct pollreactor {
    int num_fds, num_timers, must_exit;
    void *callback_data;
    double next_timer;
    struct pollfd *fds;
    void (**fd_callbacks)(void *data, double eventtime);
    struct pollreactor_timer *timers;
};

// Allocate a new 'struct pollreactor' object
static void
pollreactor_setup(struct pollreactor *pr, int num_fds, int num_timers
                  , void *callback_data)
{
    pr->num_fds = num_fds;
    pr->num_timers = num_timers;
    pr->must_exit = 0;
    pr->callback_data = callback_data;
    pr->next_timer = PR_NEVER;
    pr->fds = malloc(num_fds * sizeof(*pr->fds));
    memset(pr->fds, 0, num_fds * sizeof(*pr->fds));
    pr->fd_callbacks = malloc(num_fds * sizeof(*pr->fd_callbacks));
    memset(pr->fd_callbacks, 0, num_fds * sizeof(*pr->fd_callbacks));
    pr->timers = malloc(num_timers * sizeof(*pr->timers));
    memset(pr->timers, 0, num_timers * sizeof(*pr->timers));
    int i;
    for (i=0; i<num_timers; i++)
        pr->timers[i].waketime = PR_NEVER;
}

// Free resources associated with a 'struct pollreactor' object
static void
pollreactor_free(struct pollreactor *pr)
{
    free(pr->fds);
    pr->fds = NULL;
    free(pr->fd_callbacks);
    pr->fd_callbacks = NULL;
    free(pr->timers);
    pr->timers = NULL;
}

// Add a callback for when a file descriptor (fd) becomes readable
static void
pollreactor_add_fd(struct pollreactor *pr, int pos, int fd, void *callback
                   , int write_only)
{
    pr->fds[pos].fd = fd;
    pr->fds[pos].events = POLLHUP | (write_only ? 0 : POLLIN);
    pr->fds[pos].revents = 0;
    pr->fd_callbacks[pos] = callback;
}

// Add a timer callback
static void
pollreactor_add_timer(struct pollreactor *pr, int pos, void *callback)
{
    pr->timers[pos].callback = callback;
    pr->timers[pos].waketime = PR_NEVER;
}

// Return the last schedule wake-up time for a timer
static double
pollreactor_get_timer(struct pollreactor *pr, int pos)
{
    return pr->timers[pos].waketime;
}

// Set the wake-up time for a given timer
static void
pollreactor_update_timer(struct pollreactor *pr, int pos, double waketime)
{
    pr->timers[pos].waketime = waketime;
    if (waketime < pr->next_timer)
        pr->next_timer = waketime;
}

// Internal code to invoke timer callbacks
static int
pollreactor_check_timers(struct pollreactor *pr, double eventtime, int busy)
{
    if (eventtime >= pr->next_timer) {
        // Find and run pending timers
        pr->next_timer = PR_NEVER;
        int i;
        for (i=0; i<pr->num_timers; i++) {
            struct pollreactor_timer *timer = &pr->timers[i];
            double t = timer->waketime;
            if (eventtime >= t) {
                busy = 1;
                t = timer->callback(pr->callback_data, eventtime);
                timer->waketime = t;
            }
            if (t < pr->next_timer)
                pr->next_timer = t;
        }
    }
    if (busy)
        return 0;
    // Calculate sleep duration
    double timeout = ceil((pr->next_timer - eventtime) * 1000.);
    return timeout < 1. ? 1 : (timeout > 1000. ? 1000 : (int)timeout);
}

// Repeatedly check for timer and fd events and invoke their callbacks
static void
pollreactor_run(struct pollreactor *pr)
{
    double eventtime = get_monotonic();
    int busy = 1;
    while (! pr->must_exit) {
        int timeout = pollreactor_check_timers(pr, eventtime, busy);
        busy = 0;
        int ret = poll(pr->fds, pr->num_fds, timeout);
        eventtime = get_monotonic();
        if (ret > 0) {
            busy = 1;
            int i;
            for (i=0; i<pr->num_fds; i++)
                if (pr->fds[i].revents)
                    pr->fd_callbacks[i](pr->callback_data, eventtime);
        } else if (ret < 0) {
            report_errno("poll", ret);
            pr->must_exit = 1;
        }
    }
}

// Request that a currently running pollreactor_run() loop exit
static void
pollreactor_do_exit(struct pollreactor *pr)
{
    pr->must_exit = 1;
}

// Check if a pollreactor_run() loop has been requested to exit
static int
pollreactor_is_exit(struct pollreactor *pr)
{
    return pr->must_exit;
}

static int
set_non_blocking(int fd)
{
    int flags = fcntl(fd, F_GETFL);
    if (flags < 0) {
        report_errno("fcntl getfl", flags);
        return -1;
    }
    int ret = fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    if (ret < 0) {
        report_errno("fcntl setfl", flags);
        return -1;
    }
    return 0;
}


/****************************************************************
 * Serial protocol helpers
 ****************************************************************/

// Implement the standard crc "ccitt" algorithm on the given buffer
static uint16_t
crc16_ccitt(uint8_t *buf, uint8_t len)
{
    uint16_t crc = 0xffff;
    while (len--) {
        uint8_t data = *buf++;
        data ^= crc & 0xff;
        data ^= data << 4;
        crc = ((((uint16_t)data << 8) | (crc >> 8)) ^ (uint8_t)(data >> 4)
               ^ ((uint16_t)data << 3));
    }
    return crc;
}

// Verify a buffer starts with a valid mcu message
static int
check_message(uint8_t *need_sync, uint8_t *buf, int buf_len)
{
    if (buf_len < MESSAGE_MIN)
        // Need more data
        return 0;
    if (*need_sync)
        goto error;
    uint8_t msglen = buf[MESSAGE_POS_LEN];
    if (msglen < MESSAGE_MIN || msglen > MESSAGE_MAX)
        goto error;
    uint8_t msgseq = buf[MESSAGE_POS_SEQ];
    if ((msgseq & ~MESSAGE_SEQ_MASK) != MESSAGE_DEST)
        goto error;
    if (buf_len < msglen)
        // Need more data
        return 0;
    if (buf[msglen-MESSAGE_TRAILER_SYNC] != MESSAGE_SYNC)
        goto error;
    uint16_t msgcrc = ((buf[msglen-MESSAGE_TRAILER_CRC] << 8)
                       | (uint8_t)buf[msglen-MESSAGE_TRAILER_CRC+1]);
    uint16_t crc = crc16_ccitt(buf, msglen-MESSAGE_TRAILER_SIZE);
    if (crc != msgcrc)
        goto error;
    return msglen;

error: ;
    // Discard bytes until next SYNC found
    uint8_t *next_sync = memchr(buf, MESSAGE_SYNC, buf_len);
    if (next_sync) {
        *need_sync = 0;
        return -(next_sync - buf + 1);
    }
    *need_sync = 1;
    return -buf_len;
}

// Encode an integer as a variable length quantity (vlq)
static uint8_t *
encode_int(uint8_t *p, uint32_t v)
{
    int32_t sv = v;
    if (sv < (3L<<5)  && sv >= -(1L<<5))  goto f4;
    if (sv < (3L<<12) && sv >= -(1L<<12)) goto f3;
    if (sv < (3L<<19) && sv >= -(1L<<19)) goto f2;
    if (sv < (3L<<26) && sv >= -(1L<<26)) goto f1;
    *p++ = (v>>28) | 0x80;
f1: *p++ = ((v>>21) & 0x7f) | 0x80;
f2: *p++ = ((v>>14) & 0x7f) | 0x80;
f3: *p++ = ((v>>7) & 0x7f) | 0x80;
f4: *p++ = v & 0x7f;
    return p;
}


/****************************************************************
 * Command queues
 ****************************************************************/

struct command_queue {
    struct list_head stalled_queue, ready_queue;
    struct list_node node;
};

// Allocate a 'struct queue_message' object
static struct queue_message *
message_alloc(void)
{
    struct queue_message *qm = malloc(sizeof(*qm));
    memset(qm, 0, sizeof(*qm));
    return qm;
}

// Allocate a queue_message and fill it with the specified data
static struct queue_message *
message_fill(uint8_t *data, int len)
{
    struct queue_message *qm = message_alloc();
    memcpy(qm->msg, data, len);
    qm->len = len;
    return qm;
}

// Allocate a queue_message and fill it with a series of encoded vlq integers
struct queue_message *
message_alloc_and_encode(uint32_t *data, int len)
{
    struct queue_message *qm = message_alloc();
    int i;
    uint8_t *p = qm->msg;
    for (i=0; i<len; i++) {
        p = encode_int(p, data[i]);
        if (p > &qm->msg[MESSAGE_PAYLOAD_MAX])
            goto fail;
    }
    qm->len = p - qm->msg;
    return qm;

fail:
    errorf("Encode error");
    qm->len = 0;
    return qm;
}

// Free the storage from a previous message_alloc() call
static void
message_free(struct queue_message *qm)
{
    free(qm);
}

// Free all the messages on a queue
void
message_queue_free(struct list_head *root)
{
    while (!list_empty(root)) {
        struct queue_message *qm = list_first_entry(
            root, struct queue_message, node);
        list_del(&qm->node);
        message_free(qm);
    }
}


/****************************************************************
 * Serialqueue interface
 ****************************************************************/

struct serialqueue {
    // Input reading
    struct pollreactor pr;
    int serial_fd;
    int pipe_fds[2];
    uint8_t input_buf[4096];
    uint8_t need_sync;
    int input_pos;
    // Threading
    pthread_t tid;
    pthread_mutex_t lock; // protects variables below
    pthread_cond_t cond;
    int receive_waiting;
    // Baud / clock tracking
    int receive_window;
    double baud_adjust, idle_time;
    double est_freq, last_clock_time;
    uint64_t last_clock;
    double last_receive_sent_time;
    // Retransmit support
    uint64_t send_seq, receive_seq;
    uint64_t ignore_nak_seq, last_ack_seq, retransmit_seq, rtt_sample_seq;
    struct list_head sent_queue;
    double srtt, rttvar, rto;
    // Pending transmission message queues
    struct list_head pending_queues;
    int ready_bytes, stalled_bytes, need_ack_bytes, last_ack_bytes;
    uint64_t need_kick_clock;
    struct list_head notify_queue;
    // Received messages
    struct list_head receive_queue;
    // Debugging
    struct list_head old_sent, old_receive;
    // Stats
    uint32_t bytes_write, bytes_read, bytes_retransmit, bytes_invalid;
};

#define SQPF_SERIAL 0
#define SQPF_PIPE   1
#define SQPF_NUM    2

#define SQPT_RETRANSMIT 0
#define SQPT_COMMAND    1
#define SQPT_NUM        2

#define MIN_RTO 0.025
#define MAX_RTO 5.000
#define MAX_PENDING_BLOCKS 12
#define MIN_REQTIME_DELTA 0.250
#define MIN_BACKGROUND_DELTA 0.005
#define IDLE_QUERY_TIME 1.0

#define DEBUG_QUEUE_SENT 100
#define DEBUG_QUEUE_RECEIVE 100

// Create a series of empty messages and add them to a list
static void
debug_queue_alloc(struct list_head *root, int count)
{
    int i;
    for (i=0; i<count; i++) {
        struct queue_message *qm = message_alloc();
        list_add_head(&qm->node, root);
    }
}

// Copy a message to a debug queue and free old debug messages
static void
debug_queue_add(struct list_head *root, struct queue_message *qm)
{
    list_add_tail(&qm->node, root);
    struct queue_message *old = list_first_entry(
        root, struct queue_message, node);
    list_del(&old->node);
    message_free(old);
}

// Wake up the receiver thread if it is waiting
static void
check_wake_receive(struct serialqueue *sq)
{
    if (sq->receive_waiting) {
        sq->receive_waiting = 0;
        pthread_cond_signal(&sq->cond);
    }
}

// Write to the internal pipe to wake the background thread if in poll
static void
kick_bg_thread(struct serialqueue *sq)
{
    int ret = write(sq->pipe_fds[1], ".", 1);
    if (ret < 0)
        report_errno("pipe write", ret);
}

// Update internal state when the receive sequence increases
static void
update_receive_seq(struct serialqueue *sq, double eventtime, uint64_t rseq)
{
    // Remove from sent queue
    uint64_t sent_seq = sq->receive_seq;
    for (;;) {
        struct queue_message *sent = list_first_entry(
            &sq->sent_queue, struct queue_message, node);
        if (list_empty(&sq->sent_queue)) {
            // Got an ack for a message not sent; must be connection init
            sq->send_seq = rseq;
            sq->last_receive_sent_time = 0.;
            break;
        }
        sq->need_ack_bytes -= sent->len;
        list_del(&sent->node);
        debug_queue_add(&sq->old_sent, sent);
        sent_seq++;
        if (rseq == sent_seq) {
            // Found sent message corresponding with the received sequence
            sq->last_receive_sent_time = sent->receive_time;
            sq->last_ack_bytes = sent->len;
            break;
        }
    }
    sq->receive_seq = rseq;
    pollreactor_update_timer(&sq->pr, SQPT_COMMAND, PR_NOW);

    // Update retransmit info
    if (sq->rtt_sample_seq && rseq > sq->rtt_sample_seq
        && sq->last_receive_sent_time) {
        // RFC6298 rtt calculations
        double delta = eventtime - sq->last_receive_sent_time;
        if (!sq->srtt) {
            sq->rttvar = delta / 2.0;
            sq->srtt = delta * 10.0; // use a higher start default
        } else {
            sq->rttvar = (3.0 * sq->rttvar + fabs(sq->srtt - delta)) / 4.0;
            sq->srtt = (7.0 * sq->srtt + delta) / 8.0;
        }
        double rttvar4 = sq->rttvar * 4.0;
        if (rttvar4 < 0.001)
            rttvar4 = 0.001;
        sq->rto = sq->srtt + rttvar4;
        if (sq->rto < MIN_RTO)
            sq->rto = MIN_RTO;
        else if (sq->rto > MAX_RTO)
            sq->rto = MAX_RTO;
        sq->rtt_sample_seq = 0;
    }
    if (list_empty(&sq->sent_queue)) {
        pollreactor_update_timer(&sq->pr, SQPT_RETRANSMIT, PR_NEVER);
    } else {
        struct queue_message *sent = list_first_entry(
            &sq->sent_queue, struct queue_message, node);
        double nr = eventtime + sq->rto + sent->len * sq->baud_adjust;
        pollreactor_update_timer(&sq->pr, SQPT_RETRANSMIT, nr);
    }
}

// Process a well formed input message
static int
handle_message(struct serialqueue *sq, double eventtime, int len)
{
    // Calculate receive sequence number
    uint64_t rseq = ((sq->receive_seq & ~MESSAGE_SEQ_MASK)
                     | (sq->input_buf[MESSAGE_POS_SEQ] & MESSAGE_SEQ_MASK));
    if (rseq != sq->receive_seq) {
        // New sequence number
        if (rseq < sq->receive_seq)
            rseq += MESSAGE_SEQ_MASK+1;
        if (rseq > sq->send_seq && sq->receive_seq != 1)
            // An ack for a message not sent?  Out of order message?
            return -1;
        update_receive_seq(sq, eventtime, rseq);
    }

    // Check for pending messages on notify_queue
    int must_wake = 0;
    while (!list_empty(&sq->notify_queue)) {
        struct queue_message *qm = list_first_entry(
            &sq->notify_queue, struct queue_message, node);
        uint64_t wake_seq = rseq - 1 - (len > MESSAGE_MIN ? 1 : 0);
        uint64_t notify_msg_sent_seq = qm->req_clock;
        if (notify_msg_sent_seq > wake_seq)
            break;
        list_del(&qm->node);
        qm->len = 0;
        qm->sent_time = sq->last_receive_sent_time;
        qm->receive_time = eventtime;
        list_add_tail(&qm->node, &sq->receive_queue);
        must_wake = 1;
    }

    // Process message
    if (len == MESSAGE_MIN) {
        // Ack/nak message
        if (sq->last_ack_seq < rseq)
            sq->last_ack_seq = rseq;
        else if (rseq > sq->ignore_nak_seq && !list_empty(&sq->sent_queue))
            // Duplicate Ack is a Nak - do fast retransmit
            pollreactor_update_timer(&sq->pr, SQPT_RETRANSMIT, PR_NOW);
    } else {
        // Data message - add to receive queue
        struct queue_message *qm = message_fill(sq->input_buf, len);
        qm->sent_time = (rseq > sq->retransmit_seq
                         ? sq->last_receive_sent_time : 0.);
        qm->receive_time = get_monotonic(); // must be time post read()
        qm->receive_time -= sq->baud_adjust * len;
        list_add_tail(&qm->node, &sq->receive_queue);
        must_wake = 1;
    }

    if (must_wake)
        check_wake_receive(sq);
    return 0;
}

// Callback for input activity on the serial fd
static void
input_event(struct serialqueue *sq, double eventtime)
{
    int ret = read(sq->serial_fd, &sq->input_buf[sq->input_pos]
                   , sizeof(sq->input_buf) - sq->input_pos);
    if (ret <= 0) {
        if(ret < 0)
            report_errno("read", ret);
        else
            errorf("Got EOF when reading from device");
        pollreactor_do_exit(&sq->pr);
        return;
    }
    sq->input_pos += ret;
    for (;;) {
        int len = check_message(&sq->need_sync, sq->input_buf, sq->input_pos);
        if (!len)
            // Need more data
            return;
        if (len > 0) {
            // Received a valid message
            pthread_mutex_lock(&sq->lock);
            int ret = handle_message(sq, eventtime, len);
            if (ret)
                sq->bytes_invalid += len;
            else
                sq->bytes_read += len;
            pthread_mutex_unlock(&sq->lock);
        } else {
            // Skip bad data at beginning of input
            len = -len;
            pthread_mutex_lock(&sq->lock);
            sq->bytes_invalid += len;
            pthread_mutex_unlock(&sq->lock);
        }
        sq->input_pos -= len;
        if (sq->input_pos)
            memmove(sq->input_buf, &sq->input_buf[len], sq->input_pos);
    }
}

// Callback for input activity on the pipe fd (wakes command_event)
static void
kick_event(struct serialqueue *sq, double eventtime)
{
    char dummy[4096];
    int ret = read(sq->pipe_fds[0], dummy, sizeof(dummy));
    if (ret < 0)
        report_errno("pipe read", ret);
    pollreactor_update_timer(&sq->pr, SQPT_COMMAND, PR_NOW);
}

// Callback timer for when a retransmit should be done
static double
retransmit_event(struct serialqueue *sq, double eventtime)
{
    int ret = tcflush(sq->serial_fd, TCOFLUSH);
    if (ret < 0)
        report_errno("tcflush", ret);

    pthread_mutex_lock(&sq->lock);

    // Retransmit all pending messages
    uint8_t buf[MESSAGE_MAX * MAX_PENDING_BLOCKS + 1];
    int buflen = 0, first_buflen = 0;
    buf[buflen++] = MESSAGE_SYNC;
    struct queue_message *qm;
    list_for_each_entry(qm, &sq->sent_queue, node) {
        memcpy(&buf[buflen], qm->msg, qm->len);
        buflen += qm->len;
        if (!first_buflen)
            first_buflen = qm->len + 1;
    }
    ret = write(sq->serial_fd, buf, buflen);
    if (ret < 0)
        report_errno("retransmit write", ret);
    sq->bytes_retransmit += buflen;

    // Update rto
    if (pollreactor_get_timer(&sq->pr, SQPT_RETRANSMIT) == PR_NOW) {
        // Retransmit due to nak
        sq->ignore_nak_seq = sq->receive_seq;
        if (sq->receive_seq < sq->retransmit_seq)
            // Second nak for this retransmit - don't allow third
            sq->ignore_nak_seq = sq->retransmit_seq;
    } else {
        // Retransmit due to timeout
        sq->rto *= 2.0;
        if (sq->rto > MAX_RTO)
            sq->rto = MAX_RTO;
        sq->ignore_nak_seq = sq->send_seq;
    }
    sq->retransmit_seq = sq->send_seq;
    sq->rtt_sample_seq = 0;
    sq->idle_time = eventtime + buflen * sq->baud_adjust;
    double waketime = eventtime + first_buflen * sq->baud_adjust + sq->rto;

    pthread_mutex_unlock(&sq->lock);
    return waketime;
}

// Construct a block of data to be sent to the serial port
static int
build_and_send_command(struct serialqueue *sq, uint8_t *buf, double eventtime)
{
    int len = MESSAGE_HEADER_SIZE;
    while (sq->ready_bytes) {
        // Find highest priority message (message with lowest req_clock)
        uint64_t min_clock = MAX_CLOCK;
        struct command_queue *q, *cq = NULL;
        struct queue_message *qm = NULL;
        list_for_each_entry(q, &sq->pending_queues, node) {
            if (!list_empty(&q->ready_queue)) {
                struct queue_message *m = list_first_entry(
                    &q->ready_queue, struct queue_message, node);
                if (m->req_clock < min_clock) {
                    min_clock = m->req_clock;
                    cq = q;
                    qm = m;
                }
            }
        }
        // Append message to outgoing command
        if (len + qm->len > MESSAGE_MAX - MESSAGE_TRAILER_SIZE)
            break;
        list_del(&qm->node);
        if (list_empty(&cq->ready_queue) && list_empty(&cq->stalled_queue))
            list_del(&cq->node);
        memcpy(&buf[len], qm->msg, qm->len);
        len += qm->len;
        sq->ready_bytes -= qm->len;
        if (qm->notify_id) {
            // Message requires notification - add to notify list
            qm->req_clock = sq->send_seq;
            list_add_tail(&qm->node, &sq->notify_queue);
        } else {
            message_free(qm);
        }
    }

    // Fill header / trailer
    len += MESSAGE_TRAILER_SIZE;
    buf[MESSAGE_POS_LEN] = len;
    buf[MESSAGE_POS_SEQ] = MESSAGE_DEST | (sq->send_seq & MESSAGE_SEQ_MASK);
    uint16_t crc = crc16_ccitt(buf, len - MESSAGE_TRAILER_SIZE);
    buf[len - MESSAGE_TRAILER_CRC] = crc >> 8;
    buf[len - MESSAGE_TRAILER_CRC+1] = crc & 0xff;
    buf[len - MESSAGE_TRAILER_SYNC] = MESSAGE_SYNC;

    // Store message block
    if (eventtime > sq->idle_time)
        sq->idle_time = eventtime;
    sq->idle_time += len * sq->baud_adjust;
    struct queue_message *out = message_alloc();
    memcpy(out->msg, buf, len);
    out->len = len;
    out->sent_time = eventtime;
    out->receive_time = sq->idle_time;
    if (list_empty(&sq->sent_queue))
        pollreactor_update_timer(&sq->pr, SQPT_RETRANSMIT
                                 , sq->idle_time + sq->rto);
    if (!sq->rtt_sample_seq)
        sq->rtt_sample_seq = sq->send_seq;
    sq->send_seq++;
    sq->need_ack_bytes += len;
    list_add_tail(&out->node, &sq->sent_queue);
    return len;
}

// Determine the time the next serial data should be sent
static double
check_send_command(struct serialqueue *sq, double eventtime)
{
    if (sq->send_seq - sq->receive_seq >= MAX_PENDING_BLOCKS
        && sq->receive_seq != (uint64_t)-1)
        // Need an ack before more messages can be sent
        return PR_NEVER;
    if (sq->send_seq > sq->receive_seq && sq->receive_window) {
        int need_ack_bytes = sq->need_ack_bytes + MESSAGE_MAX;
        if (sq->last_ack_seq < sq->receive_seq)
            need_ack_bytes += sq->last_ack_bytes;
        if (need_ack_bytes > sq->receive_window)
            // Wait for ack from past messages before sending next message
            return PR_NEVER;
    }

    // Check for stalled messages now ready
    double idletime = eventtime > sq->idle_time ? eventtime : sq->idle_time;
    idletime += MESSAGE_MIN * sq->baud_adjust;
    double timedelta = idletime - sq->last_clock_time;
    uint64_t ack_clock = ((uint64_t)(timedelta * sq->est_freq)
                          + sq->last_clock);
    uint64_t min_stalled_clock = MAX_CLOCK, min_ready_clock = MAX_CLOCK;
    struct command_queue *cq;
    list_for_each_entry(cq, &sq->pending_queues, node) {
        // Move messages from the stalled_queue to the ready_queue
        while (!list_empty(&cq->stalled_queue)) {
            struct queue_message *qm = list_first_entry(
                &cq->stalled_queue, struct queue_message, node);
            if (ack_clock < qm->min_clock) {
                if (qm->min_clock < min_stalled_clock)
                    min_stalled_clock = qm->min_clock;
                break;
            }
            list_del(&qm->node);
            list_add_tail(&qm->node, &cq->ready_queue);
            sq->stalled_bytes -= qm->len;
            sq->ready_bytes += qm->len;
        }
        // Update min_ready_clock
        if (!list_empty(&cq->ready_queue)) {
            struct queue_message *qm = list_first_entry(
                &cq->ready_queue, struct queue_message, node);
            uint64_t req_clock = qm->req_clock;
            if (req_clock == BACKGROUND_PRIORITY_CLOCK)
                req_clock = (uint64_t)(
                    (sq->idle_time - sq->last_clock_time
                     + MIN_REQTIME_DELTA + MIN_BACKGROUND_DELTA)
                    * sq->est_freq) + sq->last_clock;
            if (req_clock < min_ready_clock)
                min_ready_clock = req_clock;
        }
    }

    // Check for messages to send
    if (sq->ready_bytes >= MESSAGE_PAYLOAD_MAX)
        return PR_NOW;
    if (! sq->est_freq) {
        if (sq->ready_bytes)
            return PR_NOW;
        sq->need_kick_clock = MAX_CLOCK;
        return PR_NEVER;
    }
    uint64_t reqclock_delta = MIN_REQTIME_DELTA * sq->est_freq;
    if (min_ready_clock <= ack_clock + reqclock_delta)
        return PR_NOW;
    uint64_t wantclock = min_ready_clock - reqclock_delta;
    if (min_stalled_clock < wantclock)
        wantclock = min_stalled_clock;
    sq->need_kick_clock = wantclock;
    return idletime + (wantclock - ack_clock) / sq->est_freq;
}

// Callback timer to send data to the serial port
static double
command_event(struct serialqueue *sq, double eventtime)
{
    pthread_mutex_lock(&sq->lock);
    uint8_t buf[MESSAGE_MAX * MAX_PENDING_BLOCKS];
    int buflen = 0;
    double waketime;
    for (;;) {
        waketime = check_send_command(sq, eventtime);
        if (waketime != PR_NOW || buflen + MESSAGE_MAX > sizeof(buf)) {
            if (buflen) {
                // Write message blocks
                int ret = write(sq->serial_fd, buf, buflen);
                if (ret < 0)
                    report_errno("write", ret);
                sq->bytes_write += buflen;
                buflen = 0;
            }
            if (waketime != PR_NOW)
                break;
        }
        buflen += build_and_send_command(sq, &buf[buflen], eventtime);
    }
    pthread_mutex_unlock(&sq->lock);
    return waketime;
}

// Main background thread for reading/writing to serial port
static void *
background_thread(void *data)
{
    struct serialqueue *sq = data;
    pollreactor_run(&sq->pr);

    pthread_mutex_lock(&sq->lock);
    check_wake_receive(sq);
    pthread_mutex_unlock(&sq->lock);

    return NULL;
}

// Create a new 'struct serialqueue' object
struct serialqueue * __visible
serialqueue_alloc(int serial_fd, int write_only)
{
    struct serialqueue *sq = malloc(sizeof(*sq));
    memset(sq, 0, sizeof(*sq));

    // Reactor setup
    sq->serial_fd = serial_fd;
    int ret = pipe(sq->pipe_fds);
    if (ret)
        goto fail;
    pollreactor_setup(&sq->pr, SQPF_NUM, SQPT_NUM, sq);
    pollreactor_add_fd(&sq->pr, SQPF_SERIAL, serial_fd, input_event
                       , write_only);
    pollreactor_add_fd(&sq->pr, SQPF_PIPE, sq->pipe_fds[0], kick_event, 0);
    pollreactor_add_timer(&sq->pr, SQPT_RETRANSMIT, retransmit_event);
    pollreactor_add_timer(&sq->pr, SQPT_COMMAND, command_event);
    set_non_blocking(serial_fd);
    set_non_blocking(sq->pipe_fds[0]);
    set_non_blocking(sq->pipe_fds[1]);

    // Retransmit setup
    sq->send_seq = 1;
    if (write_only) {
        sq->receive_seq = -1;
        sq->rto = PR_NEVER;
    } else {
        sq->receive_seq = 1;
        sq->rto = MIN_RTO;
    }

    // Queues
    sq->need_kick_clock = MAX_CLOCK;
    list_init(&sq->pending_queues);
    list_init(&sq->sent_queue);
    list_init(&sq->receive_queue);
    list_init(&sq->notify_queue);

    // Debugging
    list_init(&sq->old_sent);
    list_init(&sq->old_receive);
    debug_queue_alloc(&sq->old_sent, DEBUG_QUEUE_SENT);
    debug_queue_alloc(&sq->old_receive, DEBUG_QUEUE_RECEIVE);

    // Thread setup
    ret = pthread_mutex_init(&sq->lock, NULL);
    if (ret)
        goto fail;
    ret = pthread_cond_init(&sq->cond, NULL);
    if (ret)
        goto fail;
    ret = pthread_create(&sq->tid, NULL, background_thread, sq);
    if (ret)
        goto fail;

    return sq;

fail:
    report_errno("init", ret);
    return NULL;
}

// Request that the background thread exit
void __visible
serialqueue_exit(struct serialqueue *sq)
{
    pollreactor_do_exit(&sq->pr);
    kick_bg_thread(sq);
    int ret = pthread_join(sq->tid, NULL);
    if (ret)
        report_errno("pthread_join", ret);
}

// Free all resources associated with a serialqueue
void __visible
serialqueue_free(struct serialqueue *sq)
{
    if (!sq)
        return;
    if (!pollreactor_is_exit(&sq->pr))
        serialqueue_exit(sq);
    pthread_mutex_lock(&sq->lock);
    message_queue_free(&sq->sent_queue);
    message_queue_free(&sq->receive_queue);
    message_queue_free(&sq->notify_queue);
    message_queue_free(&sq->old_sent);
    message_queue_free(&sq->old_receive);
    while (!list_empty(&sq->pending_queues)) {
        struct command_queue *cq = list_first_entry(
            &sq->pending_queues, struct command_queue, node);
        list_del(&cq->node);
        message_queue_free(&cq->ready_queue);
        message_queue_free(&cq->stalled_queue);
    }
    pthread_mutex_unlock(&sq->lock);
    pollreactor_free(&sq->pr);
    free(sq);
}

// Allocate a 'struct command_queue'
struct command_queue * __visible
serialqueue_alloc_commandqueue(void)
{
    struct command_queue *cq = malloc(sizeof(*cq));
    memset(cq, 0, sizeof(*cq));
    list_init(&cq->ready_queue);
    list_init(&cq->stalled_queue);
    return cq;
}

// Free a 'struct command_queue'
void __visible
serialqueue_free_commandqueue(struct command_queue *cq)
{
    if (!cq)
        return;
    if (!list_empty(&cq->ready_queue) || !list_empty(&cq->stalled_queue)) {
        errorf("Memory leak! Can't free non-empty commandqueue");
        return;
    }
    free(cq);
}

// Add a batch of messages to the given command_queue
void
serialqueue_send_batch(struct serialqueue *sq, struct command_queue *cq
                       , struct list_head *msgs)
{
    // Make sure min_clock is set in list and calculate total bytes
    int len = 0;
    struct queue_message *qm;
    list_for_each_entry(qm, msgs, node) {
        if (qm->min_clock + (1LL<<31) < qm->req_clock
            && qm->req_clock != BACKGROUND_PRIORITY_CLOCK)
            qm->min_clock = qm->req_clock - (1LL<<31);
        len += qm->len;
    }
    if (! len)
        return;
    qm = list_first_entry(msgs, struct queue_message, node);

    // Add list to cq->stalled_queue
    pthread_mutex_lock(&sq->lock);
    if (list_empty(&cq->ready_queue) && list_empty(&cq->stalled_queue))
        list_add_tail(&cq->node, &sq->pending_queues);
    list_join_tail(msgs, &cq->stalled_queue);
    sq->stalled_bytes += len;
    int mustwake = 0;
    if (qm->min_clock < sq->need_kick_clock) {
        sq->need_kick_clock = 0;
        mustwake = 1;
    }
    pthread_mutex_unlock(&sq->lock);

    // Wake the background thread if necessary
    if (mustwake)
        kick_bg_thread(sq);
}

// Schedule the transmission of a message on the serial port at a
// given time and priority.
void __visible
serialqueue_send(struct serialqueue *sq, struct command_queue *cq, uint8_t *msg
                 , int len, uint64_t min_clock, uint64_t req_clock
                 , uint64_t notify_id)
{
    struct queue_message *qm = message_fill(msg, len);
    qm->min_clock = min_clock;
    qm->req_clock = req_clock;
    qm->notify_id = notify_id;

    struct list_head msgs;
    list_init(&msgs);
    list_add_tail(&qm->node, &msgs);
    serialqueue_send_batch(sq, cq, &msgs);
}

// Return a message read from the serial port (or wait for one if none
// available)
void __visible
serialqueue_pull(struct serialqueue *sq, struct pull_queue_message *pqm)
{
    pthread_mutex_lock(&sq->lock);
    // Wait for message to be available
    while (list_empty(&sq->receive_queue)) {
        if (pollreactor_is_exit(&sq->pr))
            goto exit;
        sq->receive_waiting = 1;
        int ret = pthread_cond_wait(&sq->cond, &sq->lock);
        if (ret)
            report_errno("pthread_cond_wait", ret);
    }

    // Remove message from queue
    struct queue_message *qm = list_first_entry(
        &sq->receive_queue, struct queue_message, node);
    list_del(&qm->node);

    // Copy message
    memcpy(pqm->msg, qm->msg, qm->len);
    pqm->len = qm->len;
    pqm->sent_time = qm->sent_time;
    pqm->receive_time = qm->receive_time;
    pqm->notify_id = qm->notify_id;
    if (qm->len)
        debug_queue_add(&sq->old_receive, qm);
    else
        message_free(qm);

    pthread_mutex_unlock(&sq->lock);
    return;

exit:
    pqm->len = -1;
    pthread_mutex_unlock(&sq->lock);
}

void __visible
serialqueue_set_baud_adjust(struct serialqueue *sq, double baud_adjust)
{
    pthread_mutex_lock(&sq->lock);
    sq->baud_adjust = baud_adjust;
    pthread_mutex_unlock(&sq->lock);
}

void __visible
serialqueue_set_receive_window(struct serialqueue *sq, int receive_window)
{
    pthread_mutex_lock(&sq->lock);
    sq->receive_window = receive_window;
    pthread_mutex_unlock(&sq->lock);
}

// Set the estimated clock rate of the mcu on the other end of the
// serial port
void __visible
serialqueue_set_clock_est(struct serialqueue *sq, double est_freq
                          , double last_clock_time, uint64_t last_clock)
{
    pthread_mutex_lock(&sq->lock);
    sq->est_freq = est_freq;
    sq->last_clock_time = last_clock_time;
    sq->last_clock = last_clock;
    pthread_mutex_unlock(&sq->lock);
}

// Return a string buffer containing statistics for the serial port
void __visible
serialqueue_get_stats(struct serialqueue *sq, char *buf, int len)
{
    struct serialqueue stats;
    pthread_mutex_lock(&sq->lock);
    memcpy(&stats, sq, sizeof(stats));
    pthread_mutex_unlock(&sq->lock);

    snprintf(buf, len, "bytes_write=%u bytes_read=%u"
             " bytes_retransmit=%u bytes_invalid=%u"
             " send_seq=%u receive_seq=%u retransmit_seq=%u"
             " srtt=%.3f rttvar=%.3f rto=%.3f"
             " ready_bytes=%u stalled_bytes=%u"
             , stats.bytes_write, stats.bytes_read
             , stats.bytes_retransmit, stats.bytes_invalid
             , (int)stats.send_seq, (int)stats.receive_seq
             , (int)stats.retransmit_seq
             , stats.srtt, stats.rttvar, stats.rto
             , stats.ready_bytes, stats.stalled_bytes);
}

// Extract old messages stored in the debug queues
int __visible
serialqueue_extract_old(struct serialqueue *sq, int sentq
                        , struct pull_queue_message *q, int max)
{
    int count = sentq ? DEBUG_QUEUE_SENT : DEBUG_QUEUE_RECEIVE;
    struct list_head *rootp = sentq ? &sq->old_sent : &sq->old_receive;
    struct list_head replacement, current;
    list_init(&replacement);
    debug_queue_alloc(&replacement, count);
    list_init(&current);

    // Atomically replace existing debug list with new zero'd list
    pthread_mutex_lock(&sq->lock);
    list_join_tail(rootp, &current);
    list_init(rootp);
    list_join_tail(&replacement, rootp);
    pthread_mutex_unlock(&sq->lock);

    // Walk the debug list
    int pos = 0;
    while (!list_empty(&current)) {
        struct queue_message *qm = list_first_entry(
            &current, struct queue_message, node);
        if (qm->len && pos < max) {
            struct pull_queue_message *pqm = q++;
            pos++;
            memcpy(pqm->msg, qm->msg, qm->len);
            pqm->len = qm->len;
            pqm->sent_time = qm->sent_time;
            pqm->receive_time = qm->receive_time;
        }
        list_del(&qm->node);
        message_free(qm);
    }
    return pos;
}
