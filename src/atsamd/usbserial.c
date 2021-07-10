// Hardware interface to USB on samd
//
// Copyright (C) 2018-2019  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <string.h> // memcpy
#include "autoconf.h" // CONFIG_FLASH_START
#include "board/armcm_boot.h" // armcm_enable_irq
#include "board/io.h" // readl
#include "board/irq.h" // irq_disable
#include "board/usb_cdc.h" // usb_notify_ep0
#include "board/usb_cdc_ep.h" // USB_CDC_EP_BULK_IN
#include "board/misc.h" // timer_read_time
#include "command.h" // DECL_CONSTANT_STR
#include "internal.h" // enable_pclock
#include "sched.h" // DECL_INIT


/****************************************************************
 * USB transfer memory
 ****************************************************************/

static uint8_t __aligned(4) ep0out[USB_CDC_EP0_SIZE];
static uint8_t __aligned(4) ep0in[USB_CDC_EP0_SIZE];
static uint8_t __aligned(4) acmin[USB_CDC_EP_ACM_SIZE];
static uint8_t __aligned(4) bulkout[USB_CDC_EP_BULK_OUT_SIZE];
static uint8_t __aligned(4) bulkin[USB_CDC_EP_BULK_IN_SIZE];

static UsbDeviceDescriptor usb_desc[USB_CDC_EP_BULK_IN + 1] = {
    [0] = { {
        {
            .ADDR.reg = (uint32_t)ep0out,
            .PCKSIZE.reg = USB_DEVICE_PCKSIZE_SIZE(sizeof(ep0out) >> 4),
        }, {
            .ADDR.reg = (uint32_t)ep0in,
            .PCKSIZE.reg = USB_DEVICE_PCKSIZE_SIZE(sizeof(ep0in) >> 4),
        },
    } },
    [USB_CDC_EP_ACM] = { {
        {
        }, {
            .ADDR.reg = (uint32_t)acmin,
            .PCKSIZE.reg = USB_DEVICE_PCKSIZE_SIZE(sizeof(acmin) >> 4),
        },
    } },
    [USB_CDC_EP_BULK_OUT] = { {
        {
            .ADDR.reg = (uint32_t)bulkout,
            .PCKSIZE.reg = USB_DEVICE_PCKSIZE_SIZE(sizeof(bulkout) >> 4),
        }, {
        },
    } },
    [USB_CDC_EP_BULK_IN] = { {
        {
        }, {
            .ADDR.reg = (uint32_t)bulkin,
            .PCKSIZE.reg = USB_DEVICE_PCKSIZE_SIZE(sizeof(bulkin) >> 4),
        },
    } },
};

#define EP0 USB->DEVICE.DeviceEndpoint[0]
#define EP_ACM USB->DEVICE.DeviceEndpoint[USB_CDC_EP_ACM]
#define EP_BULKOUT USB->DEVICE.DeviceEndpoint[USB_CDC_EP_BULK_OUT]
#define EP_BULKIN USB->DEVICE.DeviceEndpoint[USB_CDC_EP_BULK_IN]

static int_fast8_t
usb_write_packet(uint32_t ep, uint32_t bank, const void *data, uint_fast8_t len)
{
    // Check if there is room for this packet
    UsbDeviceEndpoint *ude = &USB->DEVICE.DeviceEndpoint[ep];
    uint8_t sts = ude->EPSTATUS.reg;
    uint8_t bkrdy = (bank ? USB_DEVICE_EPSTATUS_BK1RDY
                     : USB_DEVICE_EPSTATUS_BK0RDY);
    if (sts & bkrdy)
        return -1;
    // Copy the packet to the given buffer
    UsbDeviceDescBank *uddb = &usb_desc[ep].DeviceDescBank[bank];
    memcpy((void*)uddb->ADDR.reg, data, len);
    // Inform the USB hardware of the available packet
    uint32_t pcksize = uddb->PCKSIZE.reg;
    uint32_t c = pcksize & ~USB_DEVICE_PCKSIZE_BYTE_COUNT_Msk;
    uddb->PCKSIZE.reg = c | USB_DEVICE_PCKSIZE_BYTE_COUNT(len);
    ude->EPSTATUSSET.reg = bkrdy;
    return len;
}

static int_fast8_t
usb_read_packet(uint32_t ep, uint32_t bank, void *data, uint_fast8_t max_len)
{
    // Check if there is a packet ready
    UsbDeviceEndpoint *ude = &USB->DEVICE.DeviceEndpoint[ep];
    uint8_t sts = ude->EPSTATUS.reg;
    uint8_t bkrdy = (bank ? USB_DEVICE_EPSTATUS_BK1RDY
                     : USB_DEVICE_EPSTATUS_BK0RDY);
    if (!(sts & bkrdy))
        return -1;
    // Copy the packet to the given buffer
    UsbDeviceDescBank *uddb = &usb_desc[ep].DeviceDescBank[bank];
    uint32_t pcksize = uddb->PCKSIZE.reg;
    uint32_t c = pcksize & USB_DEVICE_PCKSIZE_BYTE_COUNT_Msk;
    if (c > max_len)
        c = max_len;
    memcpy(data, (void*)uddb->ADDR.reg, c);
    // Notify the USB hardware that the space is now available
    ude->EPSTATUSCLR.reg = bkrdy;
    return c;
}


/****************************************************************
 * Interface
 ****************************************************************/

int_fast8_t
usb_read_bulk_out(void *data, uint_fast8_t max_len)
{
    return usb_read_packet(USB_CDC_EP_BULK_OUT, 0, data, max_len);
}

int_fast8_t
usb_send_bulk_in(void *data, uint_fast8_t len)
{
    return usb_write_packet(USB_CDC_EP_BULK_IN, 1, data, len);
}

int_fast8_t
usb_read_ep0(void *data, uint_fast8_t max_len)
{
    return usb_read_packet(0, 0, data, max_len);
}

int_fast8_t
usb_read_ep0_setup(void *data, uint_fast8_t max_len)
{
    return usb_read_ep0(data, max_len);
}

int_fast8_t
usb_send_ep0(const void *data, uint_fast8_t len)
{
    return usb_write_packet(0, 1, data, len);
}

void
usb_stall_ep0(void)
{
    EP0.EPSTATUSSET.reg = USB_DEVICE_EPSTATUS_STALLRQ(3);
}

static uint8_t set_address;

void
usb_set_address(uint_fast8_t addr)
{
    writeb(&set_address, addr | USB_DEVICE_DADD_ADDEN);
    usb_send_ep0(NULL, 0);
}

void
usb_set_configure(void)
{
    EP_ACM.EPCFG.reg = USB_DEVICE_EPCFG_EPTYPE1(4);

    EP_BULKOUT.EPCFG.reg = USB_DEVICE_EPCFG_EPTYPE0(3);
    EP_BULKOUT.EPINTENSET.reg = (
        USB_DEVICE_EPINTENSET_TRCPT0 | USB_DEVICE_EPINTENSET_TRCPT1);

    EP_BULKIN.EPCFG.reg = USB_DEVICE_EPCFG_EPTYPE1(3);
    EP_BULKIN.EPINTENSET.reg = (
        USB_DEVICE_EPINTENSET_TRCPT0 | USB_DEVICE_EPINTENSET_TRCPT1);
}

#if CONFIG_ARDUINO_STYLE_BOOTLOADER_TRIGGERING
#define NVM_MEMORY ((volatile uint16_t *)0x000000)

static inline uint8_t nvmReady(void) {
#if defined(__SAMD51__)
    return NVMCTRL->STATUS.reg & NVMCTRL_STATUS_READY;
#else
    return NVMCTRL->INTFLAG.reg & NVMCTRL_INTFLAG_READY;
#endif
}
#endif

void
usb_request_bootloader(void)
{
    if (!CONFIG_FLASH_START)
        return;

#if CONFIG_ARDUINO_STYLE_BOOTLOADER_TRIGGERING
    //delay restart
    uint32_t end = timer_read_time() + timer_from_us(250 * 1000);
    while (timer_is_before(timer_read_time(), end))
        irq_poll();
#endif

    // Bootloader hack
    irq_disable();

#if CONFIG_MACH_SAMD21
    writel((void*)0x20007FFC, 0x07738135);
#elif CONFIG_MACH_SAMD51
    writel((void*)(HSRAM_ADDR + HSRAM_SIZE - 4), 0xf01669ef);
#endif

#if CONFIG_ARDUINO_STYLE_BOOTLOADER_TRIGGERING
    // Erase application
    while (!(nvmReady()))
        ;

    NVMCTRL->STATUS.reg |= NVMCTRL_STATUS_MASK;
    NVMCTRL->ADDR.reg  = (uintptr_t)&NVM_MEMORY[CONFIG_FLASH_START / 4];
    NVMCTRL->CTRLA.reg = NVMCTRL_CTRLA_CMD_ER | NVMCTRL_CTRLA_CMDEX_KEY;

    while (!nvmReady())
        ;
#endif

    NVIC_SystemReset();

#if CONFIG_ARDUINO_STYLE_BOOTLOADER_TRIGGERING
    while (1);
#endif
}


/****************************************************************
 * Setup and interrupts
 ****************************************************************/

void
USB_Handler(void)
{
    uint8_t s = USB->DEVICE.INTFLAG.reg;
    if (s & USB_DEVICE_INTFLAG_EORST) {
        USB->DEVICE.INTFLAG.reg = USB_DEVICE_INTFLAG_EORST;
        // Enable endpoint 0 irqs
        EP0.EPINTENSET.reg = (
            USB_DEVICE_EPINTENSET_TRCPT0 | USB_DEVICE_EPINTENSET_TRCPT1
            | USB_DEVICE_EPINTENSET_RXSTP);
    }

    uint16_t ep = USB->DEVICE.EPINTSMRY.reg;
    if (ep & (1<<0)) {
        uint8_t sts = EP0.EPINTFLAG.reg;
        EP0.EPINTFLAG.reg = sts;
        if (set_address && sts & USB_DEVICE_EPINTFLAG_TRCPT1) {
            // Apply address after last "in" message transmitted
            USB->DEVICE.DADD.reg = set_address;
            set_address = 0;
        }
        usb_notify_ep0();
    }
    if (ep & (1<<USB_CDC_EP_BULK_OUT)) {
        uint8_t sts = EP_BULKOUT.EPINTFLAG.reg;
        EP_BULKOUT.EPINTFLAG.reg = sts;
        usb_notify_bulk_out();
    }
    if (ep & (1<<USB_CDC_EP_BULK_IN)) {
        uint8_t sts = EP_BULKIN.EPINTFLAG.reg;
        EP_BULKIN.EPINTFLAG.reg = sts;
        usb_notify_bulk_in();
    }
}

DECL_CONSTANT_STR("RESERVE_PINS_USB", "PA24,PA25");

void
usbserial_init(void)
{
    // configure usb clock
    enable_pclock(USB_GCLK_ID, ID_USB);
    // configure USBD+ and USBD- pins
    uint32_t ptype = CONFIG_MACH_SAMD21 ? 'G' : 'H';
    gpio_peripheral(GPIO('A', 24), ptype, 0);
    gpio_peripheral(GPIO('A', 25), ptype, 0);
    uint32_t trim = GET_FUSE(USB_FUSES_TRIM);
    uint32_t transp = GET_FUSE(USB_FUSES_TRANSP);
    uint32_t transn = GET_FUSE(USB_FUSES_TRANSN);
    USB->DEVICE.PADCAL.reg = (USB_PADCAL_TRIM(trim) | USB_PADCAL_TRANSP(transp)
                              | USB_PADCAL_TRANSN(transn));
    // Enable USB in device mode
    USB->DEVICE.CTRLA.reg = USB_CTRLA_ENABLE;
    USB->DEVICE.DESCADD.reg = (uint32_t)usb_desc;
    EP0.EPCFG.reg = USB_DEVICE_EPCFG_EPTYPE0(1) | USB_DEVICE_EPCFG_EPTYPE1(1);
    EP_ACM.EPCFG.reg = USB_DEVICE_EPCFG_EPTYPE1(4);
    USB->DEVICE.CTRLB.reg = 0;
    // enable irqs
    USB->DEVICE.INTENSET.reg = USB_DEVICE_INTENSET_EORST;
#if CONFIG_MACH_SAMD21
    armcm_enable_irq(USB_Handler, USB_IRQn, 1);
#elif CONFIG_MACH_SAMD51
    armcm_enable_irq(USB_Handler, USB_0_IRQn, 1);
    armcm_enable_irq(USB_Handler, USB_1_IRQn, 1);
    armcm_enable_irq(USB_Handler, USB_2_IRQn, 1);
    armcm_enable_irq(USB_Handler, USB_3_IRQn, 1);
#endif
}
DECL_INIT(usbserial_init);
