// Code to setup clocks and gpio on stm32f2/stm32f4
//
// Copyright (C) 2019  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "autoconf.h" // CONFIG_CLOCK_REF_FREQ
#include "board/armcm_boot.h" // VectorTable
#include "board/irq.h" // irq_disable
#include "board/usb_cdc.h" // usb_request_bootloader
#include "command.h" // DECL_CONSTANT_STR
#include "internal.h" // enable_pclock
#include "sched.h" // sched_main

#define FREQ_PERIPH_DIV (CONFIG_MACH_STM32F401 ? 2 : 4)
#define FREQ_PERIPH (CONFIG_CLOCK_FREQ / FREQ_PERIPH_DIV)
#define FREQ_USB 48000000

// Enable a peripheral clock
void
enable_pclock(uint32_t periph_base)
{
    if (periph_base < APB2PERIPH_BASE) {
        uint32_t pos = (periph_base - APB1PERIPH_BASE) / 0x400;
        RCC->APB1ENR |= (1<<pos);
        RCC->APB1ENR;
    } else if (periph_base < AHB1PERIPH_BASE) {
        uint32_t pos = (periph_base - APB2PERIPH_BASE) / 0x400;
        RCC->APB2ENR |= (1<<pos);
        RCC->APB2ENR;
    } else if (periph_base < AHB2PERIPH_BASE) {
        uint32_t pos = (periph_base - AHB1PERIPH_BASE) / 0x400;
        RCC->AHB1ENR |= (1<<pos);
        RCC->AHB1ENR;
    }
}

// Check if a peripheral clock has been enabled
int
is_enabled_pclock(uint32_t periph_base)
{
    if (periph_base < APB2PERIPH_BASE) {
        uint32_t pos = (periph_base - APB1PERIPH_BASE) / 0x400;
        return RCC->APB1ENR & (1<<pos);
    } else if (periph_base < AHB1PERIPH_BASE) {
        uint32_t pos = (periph_base - APB2PERIPH_BASE) / 0x400;
        return RCC->APB2ENR & (1<<pos);
    } else if (periph_base < AHB2PERIPH_BASE) {
        uint32_t pos = (periph_base - AHB1PERIPH_BASE) / 0x400;
        return RCC->AHB1ENR & (1<<pos);
    }
    return 0;
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
    uint32_t rcc_pos = ((uint32_t)regs - AHB1PERIPH_BASE) / 0x400;
    RCC->AHB1ENR |= 1 << rcc_pos;
    RCC->AHB1ENR;
}

// Set the mode and extended function of a pin
void
gpio_peripheral(uint32_t gpio, uint32_t mode, int pullup)
{
    GPIO_TypeDef *regs = digital_regs[GPIO2PORT(gpio)];

    // Enable GPIO clock
    gpio_clock_enable(regs);

    // Configure GPIO
    uint32_t mode_bits = mode & 0xf, func = (mode >> 4) & 0xf, od = mode >> 8;
    uint32_t pup = pullup ? (pullup > 0 ? 1 : 2) : 0;
    uint32_t pos = gpio % 16, af_reg = pos / 8;
    uint32_t af_shift = (pos % 8) * 4, af_msk = 0x0f << af_shift;
    uint32_t m_shift = pos * 2, m_msk = 0x03 << m_shift;

    regs->AFR[af_reg] = (regs->AFR[af_reg] & ~af_msk) | (func << af_shift);
    regs->MODER = (regs->MODER & ~m_msk) | (mode_bits << m_shift);
    regs->PUPDR = (regs->PUPDR & ~m_msk) | (pup << m_shift);
    regs->OTYPER = (regs->OTYPER & ~(1 << pos)) | (od << pos);
    regs->OSPEEDR = (regs->OSPEEDR & ~m_msk) | (0x02 << m_shift);
}

#define USB_BOOT_FLAG_ADDR (CONFIG_RAM_START + CONFIG_RAM_SIZE - 4096)
#define USB_BOOT_FLAG 0x55534220424f4f54 // "USB BOOT"

// Handle USB reboot requests
void
usb_request_bootloader(void)
{
    irq_disable();
    if (CONFIG_STM32_FLASH_START_4000) {
        // HID Bootloader
        RCC->APB1ENR |= RCC_APB1ENR_PWREN;
        RCC->APB1ENR;
        PWR->CR |= PWR_CR_DBP;
        // HID Bootloader magic key
        RTC->BKP4R = 0x424C;
        PWR->CR &= ~PWR_CR_DBP;
    } else {
        // System DFU Bootloader
        *(uint64_t*)USB_BOOT_FLAG_ADDR = USB_BOOT_FLAG;
    }
    NVIC_SystemReset();
}

#if !CONFIG_STM32_CLOCK_REF_INTERNAL
DECL_CONSTANT_STR("RESERVE_PINS_crystal", "PH0,PH1");
#endif

// Clock configuration
static void
enable_clock_stm32f20x(void)
{
#if CONFIG_MACH_STM32F207
    uint32_t pll_base = 1000000, pll_freq = CONFIG_CLOCK_FREQ * 2, pllcfgr;
    __IO uint32_t StartUpCounter = 0, HSEStatus = 0;

    if (!CONFIG_STM32_CLOCK_REF_INTERNAL) {
        // Configure 120Mhz PLL from external crystal (HSE)
        uint32_t div = CONFIG_CLOCK_REF_FREQ / pll_base;
        RCC->CR |= RCC_CR_HSEON;  // Enable HSE
        pllcfgr = RCC_PLLCFGR_PLLSRC_HSE | (div << RCC_PLLCFGR_PLLM_Pos);

        /* Wait till HSE is ready and if Time out is reached exit */
        do
        {
          HSEStatus = RCC->CR & RCC_CR_HSERDY;
          StartUpCounter++;
        } while((HSEStatus == 0) && (StartUpCounter != 0x0500));


    } else {
        // Configure 120Mhz PLL from internal 16Mhz oscillator (HSI)
        uint32_t div = 16000000 / pll_base;
        pllcfgr = RCC_PLLCFGR_PLLSRC_HSI | (div << RCC_PLLCFGR_PLLM_Pos);
    }

    RCC->CFGR |= RCC_CFGR_PPRE1_DIV4 | RCC_CFGR_PPRE2_DIV4 | RCC_CFGR_HPRE_DIV1;

    RCC->PLLCFGR = (pllcfgr | ((pll_freq/pll_base) << RCC_PLLCFGR_PLLN_Pos)
                    | (0 << RCC_PLLCFGR_PLLP_Pos)
                    | ((pll_freq/FREQ_USB) << RCC_PLLCFGR_PLLQ_Pos));
    RCC->CR |= RCC_CR_PLLON;

    // Wait for PLL lock
    while (!(RCC->CR & RCC_CR_PLLRDY))
        ;

    // Set flash latency
    FLASH->ACR = (FLASH_ACR_LATENCY_3WS | FLASH_ACR_ICEN | FLASH_ACR_DCEN
                  | FLASH_ACR_PRFTEN);
#endif
}

static void
enable_clock_stm32f40x(void)
{
#if CONFIG_MACH_STM32F405 || CONFIG_MACH_STM32F407 \
    || CONFIG_MACH_STM32F401 || CONFIG_MACH_STM32F429
    uint32_t pll_base = (CONFIG_STM32_CLOCK_REF_25M) ? 1000000 : 2000000;
    uint32_t pllp = (CONFIG_MACH_STM32F401) ? 4 : 2;
    uint32_t pll_freq = CONFIG_CLOCK_FREQ * pllp, pllcfgr;
    if (!CONFIG_STM32_CLOCK_REF_INTERNAL) {
        // Configure 168Mhz PLL from external crystal (HSE)
        uint32_t div = CONFIG_CLOCK_REF_FREQ / pll_base;
        RCC->CR |= RCC_CR_HSEON;
        pllcfgr = RCC_PLLCFGR_PLLSRC_HSE | (div << RCC_PLLCFGR_PLLM_Pos);
    } else {
        // Configure 168Mhz PLL from internal 16Mhz oscillator (HSI)
        uint32_t div = 16000000 / pll_base;
        pllcfgr = RCC_PLLCFGR_PLLSRC_HSI | (div << RCC_PLLCFGR_PLLM_Pos);
    }
    // Switch system clock to PLL
#if CONFIG_MACH_STM32F401
    RCC->CFGR = RCC_CFGR_PPRE1_DIV2 | RCC_CFGR_PPRE2_DIV2;
#else
    RCC->CFGR = RCC_CFGR_PPRE1_DIV4 | RCC_CFGR_PPRE2_DIV4;
#endif

    RCC->PLLCFGR = (pllcfgr | ((pll_freq/pll_base) << RCC_PLLCFGR_PLLN_Pos)
                    | (((pllp >> 1) - 1) << RCC_PLLCFGR_PLLP_Pos)
                    | ((pll_freq/FREQ_USB) << RCC_PLLCFGR_PLLQ_Pos));
    RCC->CR |= RCC_CR_PLLON;

    // Wait for PLL lock
    while (!(RCC->CR & RCC_CR_PLLRDY))
        ;

    // Set flash latency
    FLASH->ACR = (FLASH_ACR_LATENCY_5WS | FLASH_ACR_ICEN | FLASH_ACR_DCEN
                  | FLASH_ACR_PRFTEN);
#endif
}

static void
enable_clock_stm32f446(void)
{
#if CONFIG_MACH_STM32F446
    uint32_t pll_base = 2000000, pll_freq = CONFIG_CLOCK_FREQ * 2, pllcfgr;
    if (!CONFIG_STM32_CLOCK_REF_INTERNAL) {
        // Configure 180Mhz PLL from external crystal (HSE)
        uint32_t div = CONFIG_CLOCK_REF_FREQ / pll_base;
        RCC->CR |= RCC_CR_HSEON;
        pllcfgr = RCC_PLLCFGR_PLLSRC_HSE | (div << RCC_PLLCFGR_PLLM_Pos);
    } else {
        // Configure 180Mhz PLL from internal 16Mhz oscillator (HSI)
        uint32_t div = 16000000 / pll_base;
        pllcfgr = RCC_PLLCFGR_PLLSRC_HSI | (div << RCC_PLLCFGR_PLLM_Pos);
    }
    RCC->CFGR = RCC_CFGR_PPRE1_DIV4 | RCC_CFGR_PPRE2_DIV4;
    RCC->PLLCFGR = (pllcfgr | ((pll_freq/pll_base) << RCC_PLLCFGR_PLLN_Pos)
                    | (0 << RCC_PLLCFGR_PLLP_Pos)
                    | ((pll_freq/FREQ_USB) << RCC_PLLCFGR_PLLQ_Pos)
                    | (6 << RCC_PLLCFGR_PLLR_Pos));
    RCC->CR |= RCC_CR_PLLON;

    // Enable "over drive"
    enable_pclock(PWR_BASE);
    PWR->CR = (3 << PWR_CR_VOS_Pos) | PWR_CR_ODEN;
    while (!(PWR->CSR & PWR_CSR_ODRDY))
        ;
    PWR->CR = (3 << PWR_CR_VOS_Pos) | PWR_CR_ODEN | PWR_CR_ODSWEN;
    while (!(PWR->CSR & PWR_CSR_ODSWRDY))
        ;

    // Enable 48Mhz USB clock
    if (CONFIG_USBSERIAL) {
        uint32_t ref = (CONFIG_STM32_CLOCK_REF_INTERNAL
                        ? 16000000 : CONFIG_CLOCK_REF_FREQ);
        uint32_t plls_base = 2000000, plls_freq = FREQ_USB * 4;
        RCC->PLLSAICFGR = (
            ((ref/plls_base) << RCC_PLLSAICFGR_PLLSAIM_Pos)
            | ((plls_freq/plls_base) << RCC_PLLSAICFGR_PLLSAIN_Pos)
            | (((plls_freq/FREQ_USB)/2 - 1) << RCC_PLLSAICFGR_PLLSAIP_Pos)
            | ((plls_freq/FREQ_USB) << RCC_PLLSAICFGR_PLLSAIQ_Pos));
        RCC->CR |= RCC_CR_PLLSAION;
        while (!(RCC->CR & RCC_CR_PLLSAIRDY))
            ;

        RCC->DCKCFGR2 = RCC_DCKCFGR2_CK48MSEL;
    }

    // Wait for PLL lock
    while (!(RCC->CR & RCC_CR_PLLRDY))
        ;

    // Set flash latency
    FLASH->ACR = (FLASH_ACR_LATENCY_5WS | FLASH_ACR_ICEN | FLASH_ACR_DCEN
                  | FLASH_ACR_PRFTEN);
#endif
}

// Main clock setup called at chip startup
static void
clock_setup(void)
{
    // Configure and enable PLL
    if (CONFIG_MACH_STM32F207)
        enable_clock_stm32f20x();
    else if (CONFIG_MACH_STM32F405 || CONFIG_MACH_STM32F407
            || CONFIG_MACH_STM32F401 || CONFIG_MACH_STM32F429)
        enable_clock_stm32f40x();
    else
        enable_clock_stm32f446();

    // Switch system clock to PLL
    RCC->CFGR &= (uint32_t)((uint32_t)~(RCC_CFGR_SW));
    RCC->CFGR |= RCC_CFGR_SW_PLL;

    while ((RCC->CFGR & RCC_CFGR_SWS_Msk) != RCC_CFGR_SWS_PLL)
        ;
}

void
earlyBoot(void)
{
    // Enable Watchdog and USB
    RCC->APB1ENR |= RCC_APB1ENR_WWDGEN | RCC_APB1ENR_PWREN;
    RCC->AHB2ENR |= RCC_AHB2RSTR_OTGFSRST;
}

// Main entry point - called from armcm_boot.c:ResetHandler()
void
armcm_main(void)
{
#if !CONFIG_MACH_STM32F207
    if (CONFIG_USBSERIAL && *(uint64_t*)USB_BOOT_FLAG_ADDR == USB_BOOT_FLAG) {
        *(uint64_t*)USB_BOOT_FLAG_ADDR = 0;
        uint32_t *sysbase = (uint32_t*)0x1fff0000;
        asm volatile("mov sp, %0\n bx %1"
                     : : "r"(sysbase[0]), "r"(sysbase[1]));
    }
#endif
    earlyBoot();

    // Run SystemInit() and then restore VTOR
    SystemInit();

    clock_setup();

    sched_main();
}
