// Startup code on rp2040
//
// Copyright (C) 2021  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <stdint.h> // uint32_t
#include "hardware/structs/clocks.h" // clock_hw_t
#include "hardware/structs/pll.h" // pll_hw_t
#include "hardware/structs/resets.h" // sio_hw
#include "hardware/structs/watchdog.h" // watchdog_hw
#include "hardware/structs/xosc.h" // xosc_hw
#include "sched.h" // sched_main


/****************************************************************
 * watchdog handler
 ****************************************************************/

void
watchdog_reset(void)
{
    watchdog_hw->load = 0x800000; // ~350ms
}
DECL_TASK(watchdog_reset);

void
watchdog_init(void)
{
    watchdog_reset();
    watchdog_hw->ctrl = (WATCHDOG_CTRL_PAUSE_DBG0_BITS
                         | WATCHDOG_CTRL_PAUSE_DBG1_BITS
                         | WATCHDOG_CTRL_PAUSE_JTAG_BITS
                         | WATCHDOG_CTRL_ENABLE_BITS);
}
DECL_INIT(watchdog_init);


/****************************************************************
 * Clock setup
 ****************************************************************/

#define FREQ_XOSC 12000000
#define FREQ_SYS 125000000
#define FREQ_USB 48000000

void
enable_pclock(uint32_t reset_bit)
{
    resets_hw->reset |= reset_bit;
    resets_hw->reset &= ~reset_bit;
    while (!(resets_hw->reset_done & reset_bit))
        ;
}

int
is_enabled_pclock(uint32_t reset_bit)
{
    return !(resets_hw->reset & reset_bit);
}

uint32_t
get_pclock_frequency(uint32_t reset_bit)
{
    return FREQ_SYS;
}

static void
xosc_setup(void)
{
    xosc_hw->startup = DIV_ROUND_UP(FREQ_XOSC, 1000 * 256); // 1ms
    xosc_hw->ctrl = (XOSC_CTRL_FREQ_RANGE_VALUE_1_15MHZ
                     | (XOSC_CTRL_ENABLE_VALUE_ENABLE << XOSC_CTRL_ENABLE_LSB));
    while(!(xosc_hw->status & XOSC_STATUS_STABLE_BITS))
        ;
}

static void
pll_setup(pll_hw_t *pll, uint32_t mul, uint32_t postdiv)
{
    // Setup pll
    uint32_t refdiv = 1, fbdiv = mul, postdiv2 = 2, postdiv1 = postdiv/postdiv2;
    pll->cs = refdiv;
    pll->fbdiv_int = fbdiv;
    pll->pwr = PLL_PWR_DSMPD_BITS | PLL_PWR_POSTDIVPD_BITS;
    while (!(pll->cs & PLL_CS_LOCK_BITS))
        ;

    // Setup post divider
    pll->prim = ((postdiv1 << PLL_PRIM_POSTDIV1_LSB)
                 | (postdiv2 << PLL_PRIM_POSTDIV2_LSB));
    pll->pwr = PLL_PWR_DSMPD_BITS;
}

static void
clk_aux_setup(uint32_t clk_id, uint32_t aux_id)
{
    clock_hw_t *clk = &clocks_hw->clk[clk_id];
    clk->ctrl = 0;
    clk->ctrl = aux_id | CLOCKS_CLK_PERI_CTRL_ENABLE_BITS;
}

static void
clock_setup(void)
{
    // Set clk_sys and clk_ref to use internal clock
    clock_hw_t *csys = &clocks_hw->clk[clk_sys];
    csys->ctrl &= ~CLOCKS_CLK_SYS_CTRL_SRC_BITS;
    while (csys->selected != 0x1)
        ;
    clock_hw_t *cref = &clocks_hw->clk[clk_ref];
    cref->ctrl &= ~CLOCKS_CLK_REF_CTRL_SRC_BITS;
    while (cref->selected != 0x1)
        ;

    // Reset peripherals (that can be)
    resets_hw->reset = ~(RESETS_RESET_IO_QSPI_BITS
                         | RESETS_RESET_PADS_QSPI_BITS);

    // Setup xosc, pll_sys, and switch clk_sys
    xosc_setup();
    enable_pclock(RESETS_RESET_PLL_SYS_BITS);
    pll_setup(pll_sys_hw, 125, 125*FREQ_XOSC/FREQ_SYS);
    csys->ctrl = 0;
    csys->div = 1<<CLOCKS_CLK_SYS_DIV_INT_LSB;
    csys->ctrl = CLOCKS_CLK_SYS_CTRL_SRC_VALUE_CLKSRC_CLK_SYS_AUX;
    while (!(csys->selected & (1 << 1)))
        ;

    // Setup pll_usb
    enable_pclock(RESETS_RESET_PLL_USB_BITS);
    pll_setup(pll_usb_hw, 40, 40*FREQ_XOSC/FREQ_USB);

    // Setup peripheral clocks
    clk_aux_setup(clk_peri, CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLK_SYS);
    clk_aux_setup(clk_adc, CLOCKS_CLK_ADC_CTRL_AUXSRC_VALUE_CLKSRC_PLL_USB);
    clk_aux_setup(clk_usb, CLOCKS_CLK_USB_CTRL_AUXSRC_VALUE_CLKSRC_PLL_USB);

    // Enable watchdog tick (at 12Mhz)
    cref->div = 1<<CLOCKS_CLK_REF_DIV_INT_LSB;
    cref->ctrl = CLOCKS_CLK_REF_CTRL_SRC_VALUE_XOSC_CLKSRC;
    while (!(cref->selected & (1 << 2)))
        ;
    watchdog_hw->tick = 1 | WATCHDOG_TICK_ENABLE_BITS;

    // Enable GPIO control
    enable_pclock(RESETS_RESET_IO_BANK0_BITS | RESETS_RESET_PADS_BANK0_BITS);
}

// Main entry point - called from armcm_boot.c:ResetHandler()
void
armcm_main(void)
{
    clock_setup();
    sched_main();
}
