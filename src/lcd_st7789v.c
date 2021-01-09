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
    uint8_t last_dcx;
    uint8_t last_data;
    struct gpio_out dcx, wrx, databits[8];
};


/****************************************************************
 * Transmit functions
 ****************************************************************/

// Write 8 bits to the st7789v using the "8080-II series" interface
static inline void
st7789v_xmit_byte(struct st7789v *h, uint8_t data, uint8_t dcx )
{
    uint8_t mask = 0x01;
    gpio_out_write(h->wrx, 0);
    if (h->last_dcx != dcx)
    {
        gpio_out_write(h->dcx, dcx);
        h->last_dcx = dcx;
    }

    for (int bit = 0; bit < 8; ++bit, mask <<=1)
    {
        const uint8_t new_data = data & mask;
        if ( new_data != (h->last_data & mask) )
        {
            gpio_out_write( h->databits[bit], new_data);
        }
    }

    gpio_out_write(h->wrx, 1);
    h->last_data = data;
}

// Transmit a series of bytes to the chip. The first byte in every
// request is assumed to be the 8-bit command; subsequent bytes
// are parameters or display data.
static void
st7789v_xmit(struct st7789v *h, uint8_t len, uint8_t *data)
{
    for (uint8_t i = 0; i < len; ++i) {
        uint8_t b = *data++;
        st7789v_xmit_byte(h, b, (i != 0) );
    }
 }

// Flood-fill bitmap data. This assumes 16bpp pixel format
static void
st7789v_floodfill(struct st7789v *h, uint8_t continuation,
                  uint32_t len, uint16_t data)
{
    // RAMWR or WRMEMC/RAMWRC command
    st7789v_xmit_byte(h, continuation ? 0x3c : 0x2c, 0);

    const uint8_t loByte = data & 0xff;
    const uint8_t hiByte = data >> 8;
    for (uint32_t i = 0; i < len; ++i) {
        st7789v_xmit_byte(h, hiByte, 1 );
        st7789v_xmit_byte(h, loByte, 1 );
    }
}

// Send 1bpp bitmap as 16bpp image data
static void
st7789v_bitmap(struct st7789v *h, uint8_t continuation, uint16_t fgcolor,
               uint16_t bgcolor, uint8_t len, uint8_t *data)
{
    // RAMWR or WRMEMC/RAMWRC command
    st7789v_xmit_byte(h, continuation ? 0x3c : 0x2c, 0);

    const uint8_t loFG = fgcolor & 0xff;
    const uint8_t hiFG = fgcolor >> 8;

    const uint8_t loBG = bgcolor & 0xff;
    const uint8_t hiBG = bgcolor >> 8;

    for (uint16_t i = 0; i < len; ++i)
    {
        uint8_t d = data[i];
        for (uint8_t j = 0; j < 8; ++j, d <<= 1)
        {
            if (d & 0x80)
            {
                st7789v_xmit_byte(h, hiFG, 1);
                st7789v_xmit_byte(h, loFG, 1);
            }
            else
            {
                st7789v_xmit_byte(h, hiBG, 1);
                st7789v_xmit_byte(h, loBG, 1);
            }
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

    h->last_dcx = 1;
    h->last_data = 0xff;
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
DECL_COMMAND(command_st7789v_send_cmd, "st7789v_send_cmd oid=%c cmds=%*s");

void
command_st7789v_floodfill_cmd(uint32_t *args)
{
    struct st7789v *h = oid_lookup(args[0], command_config_st7789v);
    uint8_t continuation = args[1];
    uint32_t len = args[2];
    uint16_t data = args[3];

    st7789v_floodfill(h, continuation, len, data);
}
DECL_COMMAND(command_st7789v_floodfill_cmd,
             "st7789v_floodfill oid=%c cont=%c len=%u data=%hu");

void
command_st7789v_bitmap_cmd(uint32_t *args)
{
    struct st7789v *h = oid_lookup(args[0], command_config_st7789v);
    uint8_t continuation = args[1];
    uint16_t fgcolor = args[2];
    uint16_t bgcolor = args[3];
    uint8_t len = args[4], *data = (void*)(size_t)args[5];

    st7789v_bitmap(h, continuation, fgcolor, bgcolor, len, data);
}

DECL_COMMAND(command_st7789v_bitmap_cmd,
             "st7789v_bitmap oid=%c cont=%c fg=%hu bg=%hu data=%*s");

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
