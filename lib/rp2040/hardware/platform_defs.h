/*
 * Copyright (c) 2020 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef _HARDWARE_PLATFORM_DEFS_H
#define _HARDWARE_PLATFORM_DEFS_H

// This header is included from C and assembler - only define macros

#ifndef _u
#ifdef __ASSEMBLER__
#define _u(x) x
#else
#define _u(x) x ## u
#endif
#endif

#define NUM_CORES _u(2)
#define NUM_DMA_CHANNELS _u(12)
#define NUM_IRQS _u(32)
#define NUM_PIOS _u(2)
#define NUM_PIO_STATE_MACHINES _u(4)
#define NUM_PWM_SLICES _u(8)
#define NUM_SPIN_LOCKS _u(32)
#define NUM_UARTS _u(2)
#define NUM_I2CS _u(2)
#define NUM_SPIS _u(2)

#define NUM_ADC_CHANNELS _u(5)

#define NUM_BANK0_GPIOS _u(30)

#define PIO_INSTRUCTION_COUNT _u(32)

#define XOSC_MHZ _u(12)

// PICO_CONFIG: PICO_STACK_SIZE, Stack Size, min=0x100, default=0x800, advanced=true, group=pico_standard_link
#ifndef PICO_STACK_SIZE
#define PICO_STACK_SIZE _u(0x800)
#endif

// PICO_CONFIG: PICO_HEAP_SIZE, Heap size to reserve, min=0x100, default=0x800, advanced=true, group=pico_standard_link
#ifndef PICO_HEAP_SIZE
#define PICO_HEAP_SIZE _u(0x800)
#endif

// PICO_CONFIG: PICO_NO_RAM_VECTOR_TABLE, Enable/disable the RAM vector table, type=bool, default=0, advanced=true, group=pico_runtime
#ifndef PICO_NO_RAM_VECTOR_TABLE
#define PICO_NO_RAM_VECTOR_TABLE 0
#endif

#endif

