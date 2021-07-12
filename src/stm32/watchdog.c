// Watchdog handler on STM32
//
// Copyright (C) 2019  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "internal.h" // IWDG
#include "sched.h" // DECL_TASK

void
watchdog_reset(void)
{
    IWDG->KR = 0xAAAA;
}
DECL_TASK(watchdog_reset);

void
watchdog_init(void)
{
    IWDG->KR = 0x5555;
    IWDG->PR = 0;
    IWDG->RLR = 0x0FFF; // 410-512ms timeout (depending on stm32 chip)
    IWDG->KR = 0xCCCC;
#ifndef CONFIG_MACH_STM32F1
    DBGMCU->APB1FZ |= 0x1000; // stop the watchdog with debug.
#endif
}
DECL_INIT(watchdog_init);
