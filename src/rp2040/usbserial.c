// Hardware interface to USB on rp2040
//
// Copyright (C) 2021  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <string.h> // memcpy
#include "board/armcm_boot.h" // armcm_enable_irq
#include "board/io.h" // writeb
#include "board/usb_cdc.h" // usb_notify_ep0
#include "board/usb_cdc_ep.h" // USB_CDC_EP_BULK_IN
#include "board/usbstd.h" // USB_ENDPOINT_XFER_INT
#include "hardware/structs/resets.h" // RESETS_RESET_USBCTRL_BITS
#include "hardware/structs/usb.h" // usb_hw
#include "internal.h" // enable_pclock
#include "sched.h" // DECL_INIT


/****************************************************************
 * USB transfer memory
 ****************************************************************/

#define DPBUF_SIZE 64

static uint32_t
usb_buf_offset(uint32_t ep)
{
    return 0x100 + ep * DPBUF_SIZE * 2;
}

static int_fast8_t
usb_write_packet(uint32_t ep, const void *data, uint_fast8_t len)
{
    // Check if there is room for this packet
    uint32_t epb = usb_dpram->ep_buf_ctrl[ep].in;
    if (epb & (USB_BUF_CTRL_AVAIL|USB_BUF_CTRL_FULL))
        return -1;
    uint32_t pid = (epb ^ USB_BUF_CTRL_DATA1_PID) & USB_BUF_CTRL_DATA1_PID;
    uint32_t new_epb = USB_BUF_CTRL_FULL | USB_BUF_CTRL_LAST | pid | len;
    usb_dpram->ep_buf_ctrl[ep].in = new_epb;
    // Copy the packet to the hw buffer
    void *addr = (void*)usb_dpram + usb_buf_offset(ep);
    memcpy(addr, data, len);
    // Inform the USB hardware of the available packet
    usb_dpram->ep_buf_ctrl[ep].in = new_epb | USB_BUF_CTRL_AVAIL;
    return len;
}

static int_fast8_t
usb_read_packet(uint32_t ep, void *data, uint_fast8_t max_len)
{
    // Check if there is a packet ready
    uint32_t epb = usb_dpram->ep_buf_ctrl[ep].out;
    if ((epb & (USB_BUF_CTRL_AVAIL|USB_BUF_CTRL_FULL)) != USB_BUF_CTRL_FULL)
        return -1;
    // Copy the packet to the given buffer
    uint32_t pid = (epb ^ USB_BUF_CTRL_DATA1_PID) & USB_BUF_CTRL_DATA1_PID;
    uint32_t new_epb = USB_BUF_CTRL_LAST | pid | DPBUF_SIZE;
    usb_dpram->ep_buf_ctrl[ep].out = new_epb;
    uint32_t c = epb & USB_BUF_CTRL_LEN_MASK;
    if (c > max_len)
        c = max_len;
    void *addr = (void*)usb_dpram + usb_buf_offset(ep);
    memcpy(data, addr, c);
    // Notify the USB hardware that the space is now available
    usb_dpram->ep_buf_ctrl[ep].out = new_epb | USB_BUF_CTRL_AVAIL;
    return c;
}


/****************************************************************
 * Interface
 ****************************************************************/

int_fast8_t
usb_read_bulk_out(void *data, uint_fast8_t max_len)
{
    return usb_read_packet(USB_CDC_EP_BULK_OUT, data, max_len);
}

int_fast8_t
usb_send_bulk_in(void *data, uint_fast8_t len)
{
    return usb_write_packet(USB_CDC_EP_BULK_IN, data, len);
}

int_fast8_t
usb_read_ep0_setup(void *data, uint_fast8_t max_len)
{
    if (!(usb_hw->intr & USB_INTR_SETUP_REQ_BITS)) {
        usb_hw->inte = USB_INTE_BUFF_STATUS_BITS | USB_INTE_SETUP_REQ_BITS;
        return -1;
    }
    usb_dpram->ep_buf_ctrl[0].in = 0;
    usb_dpram->ep_buf_ctrl[0].out = (USB_BUF_CTRL_DATA1_PID | USB_BUF_CTRL_LAST
                                     | USB_BUF_CTRL_AVAIL | DPBUF_SIZE);
    usb_hw->sie_status = USB_SIE_STATUS_SETUP_REC_BITS;
    memcpy(data, (void*)usb_dpram->setup_packet, max_len);
    if (usb_hw->intr & USB_INTR_SETUP_REQ_BITS) {
        // Raced with next setup packet
        usb_notify_ep0();
        return -1;
    }
    return max_len;
}

int_fast8_t
usb_read_ep0(void *data, uint_fast8_t max_len)
{
    if (usb_hw->intr & USB_INTR_SETUP_REQ_BITS)
        // Early end of transmission
        return -2;
    return usb_read_packet(0, data, max_len);
}

int_fast8_t
usb_send_ep0(const void *data, uint_fast8_t len)
{
    if (usb_hw->intr & USB_INTR_SETUP_REQ_BITS || usb_hw->buf_status & 2)
        // Early end of transmission
        return -2;
    return usb_write_packet(0, data, len);
}

void
usb_stall_ep0(void)
{
    usb_dpram->ep_buf_ctrl[0].in = 0;
    usb_dpram->ep_buf_ctrl[0].out = 0;
    usb_hw->ep_stall_arm = USB_EP_STALL_ARM_BITS;
    usb_dpram->ep_buf_ctrl[0].in = USB_BUF_CTRL_STALL;
    usb_dpram->ep_buf_ctrl[0].out = USB_BUF_CTRL_STALL;
    usb_notify_ep0();
}

static uint8_t set_address;

void
usb_set_address(uint_fast8_t addr)
{
    writeb(&set_address, addr);
    usb_send_ep0(NULL, 0);
}

void
usb_set_configure(void)
{
    usb_dpram->ep_buf_ctrl[USB_CDC_EP_BULK_IN].in = USB_BUF_CTRL_DATA1_PID;
    usb_dpram->ep_buf_ctrl[USB_CDC_EP_BULK_OUT].out = (
        USB_BUF_CTRL_AVAIL | USB_BUF_CTRL_LAST | DPBUF_SIZE);
}

void
usb_request_bootloader(void)
{
    // Use the bootrom-provided code to reset into BOOTSEL mode
    reset_to_usb_boot(0, 0);
}


/****************************************************************
 * Setup and interrupts
 ****************************************************************/

void
USB_Handler(void)
{
    uint32_t ints = usb_hw->ints;
    if (ints & USB_INTS_SETUP_REQ_BITS) {
        usb_hw->inte = USB_INTE_BUFF_STATUS_BITS;
        usb_notify_ep0();
    }
    if (ints & USB_INTS_BUFF_STATUS_BITS) {
        uint32_t buf_status = usb_hw->buf_status;
        usb_hw->buf_status = buf_status;
        if (buf_status & (1 << (USB_CDC_EP_BULK_OUT*2 + 1)))
            usb_notify_bulk_out();
        if (buf_status & (1 << (USB_CDC_EP_BULK_IN*2)))
            usb_notify_bulk_in();
        if (buf_status & 3) {
            usb_notify_ep0();
            if (buf_status & 1 && set_address) {
                usb_hw->dev_addr_ctrl = set_address;
                set_address = 0;
            }
        }
    }
}

static void
endpoint_setup(void)
{
    // ACM
    uint32_t ep_acm = (EP_CTRL_ENABLE_BITS | usb_buf_offset(USB_CDC_EP_ACM)
                       | (USB_ENDPOINT_XFER_INT << EP_CTRL_BUFFER_TYPE_LSB));
    usb_dpram->ep_ctrl[USB_CDC_EP_ACM-1].in = ep_acm;
    // BULK
    uint32_t ep_out = (EP_CTRL_ENABLE_BITS | usb_buf_offset(USB_CDC_EP_BULK_OUT)
                       | EP_CTRL_INTERRUPT_PER_BUFFER
                       | (USB_ENDPOINT_XFER_BULK << EP_CTRL_BUFFER_TYPE_LSB));
    usb_dpram->ep_ctrl[USB_CDC_EP_BULK_OUT-1].out = ep_out;
    uint32_t ep_in = (EP_CTRL_ENABLE_BITS | usb_buf_offset(USB_CDC_EP_BULK_IN)
                      | EP_CTRL_INTERRUPT_PER_BUFFER
                      | (USB_ENDPOINT_XFER_BULK << EP_CTRL_BUFFER_TYPE_LSB));
    usb_dpram->ep_ctrl[USB_CDC_EP_BULK_IN-1].in = ep_in;
    usb_dpram->ep_buf_ctrl[USB_CDC_EP_BULK_IN].in = USB_BUF_CTRL_FULL;
}

void
usbserial_init(void)
{
    // Configure usb clock
    enable_pclock(RESETS_RESET_USBCTRL_BITS);

    // Setup shared memory area
    memset(usb_dpram, 0, sizeof(*usb_dpram));
    endpoint_setup();

    // Enable USB in device mode
    usb_hw->muxing = USB_USB_MUXING_TO_PHY_BITS | USB_USB_MUXING_SOFTCON_BITS;
    usb_hw->pwr = (USB_USB_PWR_VBUS_DETECT_BITS
                   | USB_USB_PWR_VBUS_DETECT_OVERRIDE_EN_BITS);
    usb_hw->main_ctrl = USB_MAIN_CTRL_CONTROLLER_EN_BITS;

    // Enable irqs
    usb_hw->sie_ctrl = USB_SIE_CTRL_EP0_INT_1BUF_BITS;
    usb_hw->inte = USB_INTE_BUFF_STATUS_BITS | USB_INTE_SETUP_REQ_BITS;
    armcm_enable_irq(USB_Handler, USBCTRL_IRQ_IRQn, 1);

    // Enable USB pullup
    usb_hw->sie_ctrl = (USB_SIE_CTRL_EP0_INT_1BUF_BITS
                        | USB_SIE_CTRL_PULLUP_EN_BITS);

    // XXX - errata reset workaround??
}
DECL_INIT(usbserial_init);
