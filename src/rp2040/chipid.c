// Support for extracting the hardware chip id on rp2040
//
// Copyright (C) 2021  Lasse Dalegaard <dalegaard@gmail.com>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#define CHIP_UID_LEN 8

#include <string.h> // memcpy
#include "autoconf.h" // CONFIG_USB_SERIAL_NUMBER_CHIPID
#include "board/irq.h" // irq_disable, irq_enable
#include "generic/usb_cdc.h" // usb_fill_serial
#include "generic/usbstd.h" // usb_string_descriptor
#include "sched.h" // DECL_INIT
#include "hardware/structs/ioqspi.h" // ioqspi_hw
#include "hardware/structs/ssi.h" // ssi_hw
#include "internal.h"

static struct {
    struct usb_string_descriptor desc;
    uint16_t data[CHIP_UID_LEN * 2];
} cdc_chipid;

struct usb_string_descriptor *
usbserial_get_serialid(void)
{
    return &cdc_chipid.desc;
}

// Functions for reading out the flash chip ID. Adapted from the official
// Pi SDK.

static void _ramfunc
flash_cs_force(int high)
{
    uint32_t field_val = high ?
        IO_QSPI_GPIO_QSPI_SS_CTRL_OUTOVER_VALUE_HIGH :
        IO_QSPI_GPIO_QSPI_SS_CTRL_OUTOVER_VALUE_LOW;
    hw_write_masked(&ioqspi_hw->io[1].ctrl,
        field_val << IO_QSPI_GPIO_QSPI_SS_CTRL_OUTOVER_LSB,
        IO_QSPI_GPIO_QSPI_SS_CTRL_OUTOVER_BITS
    );
}

// To re-enable XIP we need to call flash_enter_xip. It's available in the
// bootrom, but that version is a generic one that works for most devices and
// the tradeoff for that is enabling a low performance mode.
// Instead we copy out the boot2 XIP enabling stage, and save it in RAM
// so we can call it later on.

#define BOOT2_SIZE 0x100

static uint8_t boot2_copy[BOOT2_SIZE] __aligned(16);

static void
flash_enter_xip_prepare(void)
{
  void * volatile target = (void *)XIP_BASE; // Avoids warning
  memcpy(boot2_copy, target, BOOT2_SIZE);
  barrier();
}

static void _ramfunc
flash_enter_xip_perform(void)
{
  ((void (*)(void))boot2_copy+1)();
}

#define FLASH_RUID_CMD         0x4B
#define FLASH_RUID_DUMMY_BYTES 4
#define FLASH_RUID_DATA_BYTES  8
#define FLASH_RUID_TOTAL_BYTES (1+FLASH_RUID_DUMMY_BYTES+FLASH_RUID_DATA_BYTES)

static void _ramfunc
read_unique_id(uint8_t *out)
{
    uint8_t txbuf[FLASH_RUID_TOTAL_BYTES] = {0};
    uint8_t rxbuf[FLASH_RUID_TOTAL_BYTES] = {0};

    uint8_t *txptr = txbuf;
    uint8_t *rxptr = rxbuf;

    int tx_remaining = FLASH_RUID_TOTAL_BYTES;
    int rx_remaining = FLASH_RUID_TOTAL_BYTES;

    txbuf[0] = FLASH_RUID_CMD;

    // Set up flash so we can work with it without XIP getting in the way
    flash_enter_xip_prepare();
    irq_disable();
    barrier();
    connect_internal_flash();
    flash_exit_xip();
    flash_cs_force(0);

    while (tx_remaining || rx_remaining) {
        uint32_t flags = ssi_hw->sr;
        int can_put = !!(flags & SSI_SR_TFNF_BITS);
        int can_get = !!(flags & SSI_SR_RFNE_BITS);
        if (can_put && tx_remaining) {
            ssi_hw->dr0 = *txptr++;
            tx_remaining--;
        }
        if (can_get && rx_remaining) {
            *rxptr++ = (uint8_t)ssi_hw->dr0;
            --rx_remaining;
        }
    }

    // Restore XIP
    flash_cs_force(1);
    flash_flush_cache();
    flash_enter_xip_perform();
    barrier();
    irq_enable();

    memcpy(out, rxbuf+1+FLASH_RUID_DUMMY_BYTES, FLASH_RUID_DATA_BYTES);
}

void
chipid_init(void)
{
    if (!CONFIG_USB_SERIAL_NUMBER_CHIPID)
        return;

    uint8_t data[8] = {0};
    read_unique_id(data);

    usb_fill_serial(&cdc_chipid.desc, ARRAY_SIZE(cdc_chipid.data)
                    , data);
}
DECL_INIT(chipid_init);
