// Code to setup clocks and gpio on stm32f1
//
// Copyright (C) 2019  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "autoconf.h" // CONFIG_CLOCK_REF_FREQ
#include "board/armcm_boot.h" // VectorTable
#include "board/irq.h" // irq_disable
#include "board/usb_cdc.h" // usb_request_bootloader
#include "internal.h" // enable_pclock
#include "sched.h" // sched_main

#define FREQ_PERIPH (CONFIG_CLOCK_FREQ / 2)

// Enable a peripheral clock
void
enable_pclock(uint32_t periph_base)
{
    if (periph_base < APB2PERIPH_BASE) {
        uint32_t pos = (periph_base - APB1PERIPH_BASE) / 0x400;
        RCC->APB1ENR |= (1<<pos);
        RCC->APB1ENR;
    } else if (periph_base < AHBPERIPH_BASE) {
        uint32_t pos = (periph_base - APB2PERIPH_BASE) / 0x400;
        RCC->APB2ENR |= (1<<pos);
        RCC->APB2ENR;
    } else {
        uint32_t pos = (periph_base - AHBPERIPH_BASE) / 0x400;
        RCC->AHBENR |= (1<<pos);
        RCC->AHBENR;
    }
}

// Check if a peripheral clock has been enabled
int
is_enabled_pclock(uint32_t periph_base)
{
    if (periph_base < APB2PERIPH_BASE) {
        uint32_t pos = (periph_base - APB1PERIPH_BASE) / 0x400;
        return RCC->APB1ENR & (1<<pos);
    } else if (periph_base < AHBPERIPH_BASE) {
        uint32_t pos = (periph_base - APB2PERIPH_BASE) / 0x400;
        return RCC->APB2ENR & (1<<pos);
    } else {
        uint32_t pos = (periph_base - AHBPERIPH_BASE) / 0x400;
        return RCC->AHBENR & (1<<pos);
    }
}

// Return the frequency of the given peripheral clock
uint32_t
get_pclock_frequency(uint32_t periph_base)
{
    return FREQ_PERIPH;
}

// Enable a GPIO peripheral clock
void
gpio_clock_enable(GPIO_TypeDef *regs)
{
    uint32_t rcc_pos = ((uint32_t)regs - APB2PERIPH_BASE) / 0x400;
    RCC->APB2ENR |= 1 << rcc_pos;
    RCC->APB2ENR;
}


static void stm32f1_alternative_remap(uint32_t mapr_mask, uint32_t mapr_value)
{
    // The MAPR register is a mix of write only and r/w bits
    // We have to save the written values in a global variable
    static uint32_t mapr = 0;

    mapr &= ~mapr_mask;
    mapr |= mapr_value;
    AFIO->MAPR = mapr;
}

// Set the mode and extended function of a pin
void
gpio_peripheral(uint32_t gpio, uint32_t mode, int pullup)
{
    GPIO_TypeDef *regs = digital_regs[GPIO2PORT(gpio)];

    // Enable GPIO clock
    gpio_clock_enable(regs);

    // Configure GPIO
    uint32_t pos = gpio % 16, shift = (pos % 8) * 4, msk = 0xf << shift, cfg;
    if (mode == GPIO_INPUT) {
        cfg = pullup ? 0x8 : 0x4;
    } else if (mode == GPIO_OUTPUT) {
        cfg = 0x1;
    } else if (mode == (GPIO_OUTPUT | GPIO_OPEN_DRAIN)) {
        cfg = 0x5;
    } else if (mode == GPIO_ANALOG) {
        cfg = 0x0;
    } else {
        if (mode & GPIO_OPEN_DRAIN)
            // Alternate function with open-drain mode
            cfg = 0xd;
        else if (pullup > 0)
            // Alternate function input pins use GPIO_INPUT mode on the stm32f1
            cfg = 0x8;
        else
            cfg = 0x9;
    }
    if (pos & 0x8)
        regs->CRH = (regs->CRH & ~msk) | (cfg << shift);
    else
        regs->CRL = (regs->CRL & ~msk) | (cfg << shift);

    if (pullup > 0)
        regs->BSRR = 1 << pos;
    else if (pullup < 0)
        regs->BSRR = 1 << (pos + 16);

    if (gpio == GPIO('A', 13) || gpio == GPIO('A', 14))
        // Disable SWD to free PA13, PA14
        stm32f1_alternative_remap(AFIO_MAPR_SWJ_CFG_Msk,
                                  AFIO_MAPR_SWJ_CFG_DISABLE);

    // STM32F1 remaps functions to pins in a very different
    // way from other STM32s.
    // Code below is emulating a few mappings to work like an STM32F4
    uint32_t func = (mode >> 4) & 0xf;
    if (gpio == GPIO('B', 8) || gpio == GPIO('B', 9)) {
        if (func == 9) {
            // CAN
            stm32f1_alternative_remap(AFIO_MAPR_CAN_REMAP_Msk,
                                      AFIO_MAPR_CAN_REMAP_REMAP2);
        } else if (func == 4) {
            // I2C1 Alt
            stm32f1_alternative_remap(AFIO_MAPR_I2C1_REMAP_Msk,
                                      AFIO_MAPR_I2C1_REMAP);
        }
    }
    // Add more as needed
}



// Handle USB reboot requests
void
usb_request_bootloader(void)
{
    if (!(CONFIG_STM32_FLASH_START_2000 || CONFIG_STM32_FLASH_START_800))
        return;
    // Enter "stm32duino" or HID bootloader
    irq_disable();
    RCC->APB1ENR |= RCC_APB1ENR_PWREN | RCC_APB1ENR_BKPEN;
    PWR->CR |= PWR_CR_DBP;
    if (CONFIG_STM32_FLASH_START_800)
        // HID Bootloader magic key
        BKP->DR4 = 0x424C;
    else
        // stm32duino bootloader magic key
        BKP->DR10 = 0x01;
    PWR->CR &=~ PWR_CR_DBP;
    NVIC_SystemReset();
}

// Main clock setup called at chip startup
static void
clock_setup(void)
{
    // Configure and enable PLL
    uint32_t cfgr;
    if (!CONFIG_STM32_CLOCK_REF_INTERNAL) {
        // Configure 72Mhz PLL from external crystal (HSE)
        RCC->CR |= RCC_CR_HSEON;
        uint32_t div = CONFIG_CLOCK_FREQ / (CONFIG_CLOCK_REF_FREQ / 2);
        cfgr = 1 << RCC_CFGR_PLLSRC_Pos;
        if ((div & 1) && div <= 16)
            cfgr |= RCC_CFGR_PLLXTPRE_HSE_DIV2;
        else
            div /= 2;
        cfgr |= (div - 2) << RCC_CFGR_PLLMULL_Pos;
    } else {
        // Configure 72Mhz PLL from internal 8Mhz oscillator (HSI)
        uint32_t div2 = (CONFIG_CLOCK_FREQ / 8000000) * 2;
        cfgr = ((0 << RCC_CFGR_PLLSRC_Pos)
                | ((div2 - 2) << RCC_CFGR_PLLMULL_Pos));
    }
    cfgr |= RCC_CFGR_PPRE1_DIV2 | RCC_CFGR_PPRE2_DIV2 | RCC_CFGR_ADCPRE_DIV8;
    RCC->CFGR = cfgr;
    RCC->CR |= RCC_CR_PLLON;

    // Set flash latency
    FLASH->ACR = (2 << FLASH_ACR_LATENCY_Pos) | FLASH_ACR_PRFTBE;

    // Wait for PLL lock
    while (!(RCC->CR & RCC_CR_PLLRDY))
        ;

    // Switch system clock to PLL
    RCC->CFGR = cfgr | RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS_Msk) != RCC_CFGR_SWS_PLL)
        ;
}

// Main entry point - called from armcm_boot.c:ResetHandler()
void
armcm_main(void)
{
    // Run SystemInit() and then restore VTOR
    SystemInit();
    SCB->VTOR = (uint32_t)VectorTable;

    // Reset peripheral clocks (for some bootloaders that don't)
    RCC->AHBENR = 0x14;
    RCC->APB1ENR = 0;
    RCC->APB2ENR = 0;

    // Setup clocks
    clock_setup();

    // Disable JTAG to free PA15, PB3, PB4
    enable_pclock(AFIO_BASE);
    stm32f1_alternative_remap(AFIO_MAPR_SWJ_CFG_Msk,
                              AFIO_MAPR_SWJ_CFG_JTAGDISABLE);

    sched_main();
}
