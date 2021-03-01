// Commands for sending messages to an st7789V display connected
// using the "8080-II series" interface
//
// Copyright (C) 2020  Martijn van Buul <martijn.van.buul@gmail.com>
// Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "autoconf.h" // CONFIG_CLOCK_FREQ
#include "basecmd.h" // oid_alloc
#include "board/gpio.h" // gpio_out_write
#include "board/irq.h" // irq_disable
#include "board/misc.h" // timer_from_us
#include "command.h" // DECL_COMMAND
#include "sched.h" // DECL_SHUTDOWN

struct st7789v {
    struct gpio_out dcx, wrx, databits[8];
};

/****************************************************************
 * Transmit functions
 ****************************************************************/

// Write 8 bits to the st7789v using the "8080-II series" interface
static inline void
st7789v_xmit_byte(struct st7789v *h, uint8_t data)
{
    gpio_out_write(h->wrx, 0);
    uint8_t mask = 0x01;
    for (int bit = 0; bit < 8; ++bit, mask <<=1)
    {
        const uint8_t new_data = data & mask;
        gpio_out_write( h->databits[bit], new_data);
    }

    gpio_out_write(h->wrx, 1);
}

// Data is encrypted using an run-length encoded algorithm resembling
// the PackBits encoding. The data stream is devided into packets; each
// packet consisting of a one-byte header followed by data.
//
// Header(n) Data
//  0-63     (1+n) literal bytes of data. The first write is written with
//           DCX asserted.
//  64-127   (n - 63) literal bytes of data. DCX is not asserted.
//  128-255  2 bytes of data, repeated (n-126) times. DCX is not asserted.
static void
st7789v_xmit(struct st7789v *h, uint8_t len, uint8_t *data)
{
    while (len-- > 0)
    {
        uint8_t count = *data++;
        if (count < 128)
        {
            if (count < 64)
            {
                // count+1 bytes of data, first byte has DCX asserted.
                --len; // consume 1 byte
                // first byte with DCX asserted
                gpio_out_write(h->dcx, 0);
                st7789v_xmit_byte(h, *data++);
                gpio_out_write(h->dcx, 1);
            }
            else
            {
                // count - 63 bytes of data.
                count -= 63;
            }

            len -= count;
            for(; count > 0; --count)
            {
                st7789v_xmit_byte(h, *data++);
            }
            continue;
        }

        // 2 bytes of data, repeated count-126 times.
        len -= 2;

        const uint8_t msb = *data++;
        const uint8_t lsb = *data++;
        for (count -= 126; count>0; --count)
        {
            st7789v_xmit_byte(h, msb);
            st7789v_xmit_byte(h, lsb);
        }
    }
 }

/****************************************************************
 * Interface
 ****************************************************************/

void
command_config_st7789v(uint32_t *args)
{
    struct st7789v *h = oid_alloc(args[0], command_config_st7789v, sizeof(*h));
    h->dcx = gpio_out_setup(args[1], 1);
    h->wrx = gpio_out_setup(args[2], 1);

    for (int bit = 0; bit < 8; ++bit)
    {
        h->databits[bit] = gpio_out_setup(args[3 + bit], 1);
    }
}
DECL_COMMAND(command_config_st7789v,
             "config_st7789v oid=%c dcx_pin=%u wrx_pin=%u"
             " d8_pin=%u d9_pin=%u d10_pin=%u d11_pin=%u"
             " d12_pin=%u d13_pin=%u d14_pin=%u d15_pin=%u");

void
command_st7789v_send_cmd(uint32_t *args)
{
    struct st7789v *h = oid_lookup(args[0], command_config_st7789v);
    uint8_t len = args[1], *cmds = (void*)(size_t)args[2];
    st7789v_xmit(h, len, cmds);
}
DECL_COMMAND(command_st7789v_send_cmd, "st7789v_send_cmd oid=%c data=%*s");

void
st7789v_shutdown(void)
{
    uint8_t i;
    struct st7789v *h;
    foreach_oid(i, h, command_config_st7789v) {
        gpio_out_write(h->dcx, 0);
        gpio_out_write(h->wrx, 0);
        for (uint8_t j = 0; j < 8; ++j)
        {
            gpio_out_write(h->databits[j], 0);
        }
    }
}
DECL_SHUTDOWN(st7789v_shutdown);
