// Helper functions for C / Python interface
//
// Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <errno.h> // errno
#include <stdarg.h> // va_start
#include <stdint.h> // uint8_t
#include <stdio.h> // fprintf
#include <string.h> // strerror
#include <time.h> // struct timespec
#include "compiler.h" // __visible
#include "pyhelper.h" // get_monotonic

// Return the monotonic system time as a double
double __visible
get_monotonic(void)
{
    struct timespec ts;
    int ret = clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    if (ret) {
        report_errno("clock_gettime", ret);
        return 0.;
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec * .000000001;
}

// Fill a 'struct timespec' with a system time stored in a double
struct timespec
fill_time(double time)
{
    time_t t = time;
    return (struct timespec) {t, (time - t)*1000000000. };
}

// Log an error message
void
errorf(const char *fmt, ...)
{
    char buf[512];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    buf[sizeof(buf)-1] = '\0';
    python_logging_callback(buf);
}

// Report 'errno' in a message written to stderr
void
report_errno(char *where, int rc)
{
    int e = errno;
    errorf("Got error %d in %s: (%d)%s", rc, where, e, strerror(e));
}

// Return a hex character for a given number
#define GETHEX(x) ((x) < 10 ? '0' + (x) : 'a' + (x) - 10)

// Translate a binary string into an ASCII string with escape sequences
char *
dump_string(char *outbuf, int outbuf_size, char *inbuf, int inbuf_size)
{
    char *outend = &outbuf[outbuf_size-5], *o = outbuf;
    uint8_t *inend = (void*)&inbuf[inbuf_size], *p = (void*)inbuf;
    while (p < inend && o < outend) {
        uint8_t c = *p++;
        if (c > 31 && c < 127 && c != '\\') {
            *o++ = c;
            continue;
        }
        *o++ = '\\';
        *o++ = 'x';
        *o++ = GETHEX(c >> 4);
        *o++ = GETHEX(c & 0x0f);
    }
    *o = '\0';
    return outbuf;
}
