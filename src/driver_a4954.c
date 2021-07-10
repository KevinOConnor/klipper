// Code for controlling an a4954 h-bridge
//
// Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "board/irq.h" // irq_disable
#include "board/gpio.h" // gpio_pwm_write
#include "basecmd.h" // oid_alloc
#include "command.h" // DECL_COMMAND
#include "driver_a4954.h" // a4954_oid_lookup
#include "sched.h" // DECL_SHUTDOWN

struct a4954 {
    struct gpio_out in1, in2, in3, in4;
    struct gpio_pwm vref12, vref34;
    uint32_t last_phase;
    uint8_t flags;
};

enum { AF_ENABLED = 1 };

// Generated with the following python script:
//  "".join(["%.0f,"%(math.sin(math.pi*i/512.)*1024-i*4) for i in range(256)])
static const uint8_t sine_table[256] = {
    0,2,5,7,9,11,14,16,18,21,23,25,27,30,32,34,
    36,39,41,43,45,48,50,52,54,56,59,61,63,65,67,70,
    72,74,76,78,80,82,85,87,89,91,93,95,97,99,101,103,
    105,107,109,111,113,115,117,119,121,123,125,127,129,130,132,134,
    136,138,139,141,143,145,146,148,150,151,153,155,156,158,160,161,
    163,164,166,167,169,170,172,173,174,176,177,179,180,181,182,184,
    185,186,187,188,190,191,192,193,194,195,196,197,198,199,200,201,
    202,202,203,204,205,206,206,207,208,208,209,210,210,211,211,212,
    212,213,213,213,214,214,214,215,215,215,215,215,215,215,216,216,
    216,216,215,215,215,215,215,215,214,214,214,214,213,213,212,212,
    211,211,210,210,209,208,208,207,206,206,205,204,203,202,201,200,
    199,198,197,196,195,193,192,191,190,188,187,186,184,183,181,180,
    178,176,175,173,171,170,168,166,164,162,160,158,156,154,152,150,
    148,146,143,141,139,137,134,132,129,127,124,122,119,116,114,111,
    108,106,103,100,97,94,91,88,85,82,79,76,72,69,66,62,
    59,56,52,49,45,42,38,34,31,27,23,20,16,12,8,4,
};

// Calculate a sine value from a phase (phase is between 0-512)
static uint32_t
lookup_sine(uint32_t phase, uint32_t scale)
{
    uint32_t idx = phase & 0xff;
    if (phase & 0x100)
        idx = ARRAY_SIZE(sine_table) - 1 - idx;
    uint32_t sin = sine_table[idx] + idx*4;
    return DIV_ROUND_CLOSEST(scale * sin, 1024);
}

// Set the phase and current of the a4954 driver. Caller must disable irqs.
void
a4954_set_phase(struct a4954 *a, uint32_t phase, uint32_t scale)
{
    // Determine phase change
    uint32_t last_phase = a->last_phase, phase_xor = last_phase ^ phase;
    a->last_phase = phase;

    // Calculate new coil power
    uint32_t coil1_pow = lookup_sine(phase, scale);
    uint32_t coil2_pow = lookup_sine(phase + 256, scale);

    //output("set_phase lp=%u p=%u px=%u c1=%u c2=%u"
    //       , last_phase, phase, (phase_xor & 0x300)>>8, coil1_pow, coil2_pow);

    // Apply update
    struct gpio_pwm vref12 = a->vref12, vref34 = a->vref34;
    gpio_pwm_write(vref12, coil1_pow);
    gpio_pwm_write(vref34, coil2_pow);
    if (phase_xor & 0x200) {
        struct gpio_out in1 = a->in1, in2 = a->in2;
        gpio_out_toggle_noirq(in1);
        gpio_out_toggle_noirq(in2);
    }
    if ((phase_xor + 256) & 0x200) {
        struct gpio_out in3 = a->in3, in4 = a->in4;
        gpio_out_toggle_noirq(in3);
        gpio_out_toggle_noirq(in4);
    }
}

void
a4954_disable(struct a4954 *a)
{
    if (!a->flags)
        // Already disabled
        return;

    struct gpio_pwm vref12 = a->vref12, vref34 = a->vref34;
    gpio_pwm_write(vref12, 0);
    gpio_pwm_write(vref34, 0);
    struct gpio_out in1 = a->in1, in2 = a->in2;
    gpio_out_write(in1, 0);
    gpio_out_write(in2, 0);
    struct gpio_out in3 = a->in3, in4 = a->in4;
    gpio_out_write(in3, 0);
    gpio_out_write(in4, 0);

    a->flags = 0;
}

void
a4954_enable(struct a4954 *a)
{
    if (a->flags)
        // Already enabled
        return;
    a->flags = AF_ENABLED;

    uint32_t phase = a->last_phase;
    struct gpio_out in1 = a->in1, in2 = a->in2;
    if (phase & 0x200) {
        gpio_out_write(in1, 1);
        gpio_out_write(in2, 0);
    } else {
        gpio_out_write(in1, 0);
        gpio_out_write(in2, 1);
    }
    struct gpio_out in3 = a->in3, in4 = a->in4;
    if ((phase + 256) & 0x200) {
        gpio_out_write(in3, 1);
        gpio_out_write(in4, 0);
    } else {
        gpio_out_write(in3, 0);
        gpio_out_write(in4, 1);
    }
}

void
command_config_a4954(uint32_t *args)
{
    struct gpio_out in1 = gpio_out_setup(args[1], 0);
    struct gpio_out in2 = gpio_out_setup(args[2], 0);
    struct gpio_out in3 = gpio_out_setup(args[3], 0);
    struct gpio_out in4 = gpio_out_setup(args[4], 0);
    struct gpio_pwm vref12 = gpio_pwm_setup(args[5], 1, 0);
    struct gpio_pwm vref34 = gpio_pwm_setup(args[6], 1, 0);
    struct a4954 *a = oid_alloc(args[0], command_config_a4954, sizeof(*a));
    a->in1 = in1;
    a->in2 = in2;
    a->in3 = in3;
    a->in4 = in4;
    a->vref12 = vref12;
    a->vref34 = vref34;
}
DECL_COMMAND(command_config_a4954,
             "config_a4954 oid=%c in1_pin=%u in2_pin=%u in3_pin=%u in4_pin=%u"
             " vref12_pin=%u vref34_pin=%u");

struct a4954 *
a4954_oid_lookup(uint8_t oid)
{
    return oid_lookup(oid, command_config_a4954);
}

void
a4954_shutdown(void)
{
    uint8_t i;
    struct a4954 *a;
    foreach_oid(i, a, command_config_a4954) {
        a4954_disable(a);
    }
}
DECL_SHUTDOWN(a4954_shutdown);
