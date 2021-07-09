// Support for standard serial port over USB emulation
//
// Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <string.h> // memmove
#include "autoconf.h" // CONFIG_USB_VENDOR_ID
#include "board/pgm.h" // PROGMEM
#include "board/usb_cdc_ep.h" // USB_CDC_EP_BULK_IN
#include "byteorder.h" // cpu_to_le16
#include "command.h" // output
#include "generic/usbstd.h" // struct usb_device_descriptor
#include "generic/usbstd_cdc.h" // struct usb_cdc_header_descriptor
#include "sched.h" // sched_wake_task
#include "usb_cdc.h" // usb_notify_ep0

// To debug a USB connection over UART, uncomment the two macros
// below, alter the board KConfig to "select USBSERIAL" on a serial
// UART build (so both USB and UART are enabled in a single build),
// compile the code using serial UART, add output() calls to the USB
// code as needed, deploy the new binary, and then connect via
// console.py using UART to see those output() messages.
//#define console_sendf(ce,va) console_sendf_usb(ce,va)
//#define command_find_and_dispatch(rb, rp, pc) ({*(pc) = rp; 1;})


/****************************************************************
 * Message block sending
 ****************************************************************/

static struct task_wake usb_bulk_in_wake;
static uint8_t transmit_buf[96], transmit_pos;

void
usb_notify_bulk_in(void)
{
    sched_wake_task(&usb_bulk_in_wake);
}

void
usb_bulk_in_task(void)
{
    if (!sched_check_wake(&usb_bulk_in_wake))
        return;
    uint_fast8_t tpos = transmit_pos;
    if (!tpos)
        return;
    uint_fast8_t max_tpos = (tpos > USB_CDC_EP_BULK_IN_SIZE
                             ? USB_CDC_EP_BULK_IN_SIZE : tpos);
    int_fast8_t ret = usb_send_bulk_in(transmit_buf, max_tpos);
    if (ret <= 0)
        return;
    uint_fast8_t needcopy = tpos - ret;
    if (needcopy) {
        memmove(transmit_buf, &transmit_buf[ret], needcopy);
        usb_notify_bulk_in();
    }
    transmit_pos = needcopy;
}
DECL_TASK(usb_bulk_in_task);

// Encode and transmit a "response" message
void
console_sendf(const struct command_encoder *ce, va_list args)
{
    // Verify space for message
    uint_fast8_t tpos = transmit_pos, max_size = READP(ce->max_size);
    if (tpos + max_size > sizeof(transmit_buf))
        // Not enough space for message
        return;

    // Generate message
    uint8_t *buf = &transmit_buf[tpos];
    uint_fast8_t msglen = command_encode_and_frame(buf, ce, args);

    // Start message transmit
    transmit_pos = tpos + msglen;
    usb_notify_bulk_in();
}


/****************************************************************
 * Message block reading
 ****************************************************************/

static struct task_wake usb_bulk_out_wake;
static uint8_t receive_buf[128], receive_pos;

void
usb_notify_bulk_out(void)
{
    sched_wake_task(&usb_bulk_out_wake);
}

void
usb_bulk_out_task(void)
{
    if (!sched_check_wake(&usb_bulk_out_wake))
        return;
    // Read data
    uint_fast8_t rpos = receive_pos, pop_count;
    if (rpos + USB_CDC_EP_BULK_OUT_SIZE <= sizeof(receive_buf)) {
        int_fast8_t ret = usb_read_bulk_out(
            &receive_buf[rpos], USB_CDC_EP_BULK_OUT_SIZE);
        if (ret > 0) {
            rpos += ret;
            usb_notify_bulk_out();
        }
    } else {
        usb_notify_bulk_out();
    }
    // Process a message block
    int_fast8_t ret = command_find_and_dispatch(receive_buf, rpos, &pop_count);
    if (ret) {
        // Move buffer
        uint_fast8_t needcopy = rpos - pop_count;
        if (needcopy) {
            memmove(receive_buf, &receive_buf[pop_count], needcopy);
            usb_notify_bulk_out();
        }
        rpos = needcopy;
    }
    receive_pos = rpos;
}
DECL_TASK(usb_bulk_out_task);


/****************************************************************
 * USB descriptors
 ****************************************************************/

#define CONCAT1(a, b) a ## b
#define CONCAT(a, b) CONCAT1(a, b)
#define USB_STR_MANUFACTURER u"Klipper"
#define USB_STR_PRODUCT CONCAT(u,CONFIG_MCU)
#define USB_STR_SERIAL CONCAT(u,CONFIG_USB_SERIAL_NUMBER)

// String descriptors
enum {
    USB_STR_ID_MANUFACTURER = 1, USB_STR_ID_PRODUCT, USB_STR_ID_SERIAL,
};

#define SIZE_cdc_string_langids (sizeof(cdc_string_langids) + 2)

static const struct usb_string_descriptor cdc_string_langids PROGMEM = {
    .bLength = SIZE_cdc_string_langids,
    .bDescriptorType = USB_DT_STRING,
    .data = { cpu_to_le16(USB_LANGID_ENGLISH_US) },
};

#define SIZE_cdc_string_manufacturer \
    (sizeof(cdc_string_manufacturer) + sizeof(USB_STR_MANUFACTURER) - 2)

static const struct usb_string_descriptor cdc_string_manufacturer PROGMEM = {
    .bLength = SIZE_cdc_string_manufacturer,
    .bDescriptorType = USB_DT_STRING,
    .data = USB_STR_MANUFACTURER,
};

#define SIZE_cdc_string_product \
    (sizeof(cdc_string_product) + sizeof(USB_STR_PRODUCT) - 2)

static const struct usb_string_descriptor cdc_string_product PROGMEM = {
    .bLength = SIZE_cdc_string_product,
    .bDescriptorType = USB_DT_STRING,
    .data = USB_STR_PRODUCT,
};

#define SIZE_cdc_string_serial \
    (sizeof(cdc_string_serial) + sizeof(USB_STR_SERIAL) - 2)

static const struct usb_string_descriptor cdc_string_serial PROGMEM = {
    .bLength = SIZE_cdc_string_serial,
    .bDescriptorType = USB_DT_STRING,
    .data = USB_STR_SERIAL,
};

// Device descriptor
static const struct usb_device_descriptor cdc_device_descriptor PROGMEM = {
    .bLength = sizeof(cdc_device_descriptor),
    .bDescriptorType = USB_DT_DEVICE,
    .bcdUSB = cpu_to_le16(0x0200),
    .bDeviceClass = USB_CLASS_COMM,
    .bMaxPacketSize0 = USB_CDC_EP0_SIZE,
    .idVendor = cpu_to_le16(CONFIG_USB_VENDOR_ID),
    .idProduct = cpu_to_le16(CONFIG_USB_DEVICE_ID),
    .bcdDevice = cpu_to_le16(0x0100),
    .iManufacturer = USB_STR_ID_MANUFACTURER,
    .iProduct = USB_STR_ID_PRODUCT,
    .iSerialNumber = USB_STR_ID_SERIAL,
    .bNumConfigurations = 1,
};

// Config descriptor
static const struct config_s {
    struct usb_config_descriptor config;
    struct usb_interface_descriptor iface0;
    struct usb_cdc_header_descriptor cdc_hdr;
    struct usb_cdc_acm_descriptor cdc_acm;
    struct usb_cdc_union_descriptor cdc_union;
    struct usb_endpoint_descriptor ep1;
    struct usb_interface_descriptor iface1;
    struct usb_endpoint_descriptor ep2;
    struct usb_endpoint_descriptor ep3;
} PACKED cdc_config_descriptor PROGMEM = {
    .config = {
        .bLength = sizeof(cdc_config_descriptor.config),
        .bDescriptorType = USB_DT_CONFIG,
        .wTotalLength = cpu_to_le16(sizeof(cdc_config_descriptor)),
        .bNumInterfaces = 2,
        .bConfigurationValue = 1,
        .bmAttributes = 0xC0,
        .bMaxPower = 50,
    },
    .iface0 = {
        .bLength = sizeof(cdc_config_descriptor.iface0),
        .bDescriptorType = USB_DT_INTERFACE,
        .bInterfaceNumber = 0,
        .bNumEndpoints = 1,
        .bInterfaceClass = USB_CLASS_COMM,
        .bInterfaceSubClass = USB_CDC_SUBCLASS_ACM,
        .bInterfaceProtocol = USB_CDC_ACM_PROTO_AT_V25TER,
    },
    .cdc_hdr = {
        .bLength = sizeof(cdc_config_descriptor.cdc_hdr),
        .bDescriptorType = USB_CDC_CS_INTERFACE,
        .bDescriptorSubType = USB_CDC_HEADER_TYPE,
        .bcdCDC = 0x0110,
    },
    .cdc_acm = {
        .bLength = sizeof(cdc_config_descriptor.cdc_acm),
        .bDescriptorType = USB_CDC_CS_INTERFACE,
        .bDescriptorSubType = USB_CDC_ACM_TYPE,
        .bmCapabilities = 0x06,
    },
    .cdc_union = {
        .bLength = sizeof(cdc_config_descriptor.cdc_union),
        .bDescriptorType = USB_CDC_CS_INTERFACE,
        .bDescriptorSubType = USB_CDC_UNION_TYPE,
        .bMasterInterface0 = 0,
        .bSlaveInterface0 = 1,
    },
    .ep1 = {
        .bLength = sizeof(cdc_config_descriptor.ep1),
        .bDescriptorType = USB_DT_ENDPOINT,
        .bEndpointAddress = USB_CDC_EP_ACM | USB_DIR_IN,
        .bmAttributes = USB_ENDPOINT_XFER_INT,
        .wMaxPacketSize = cpu_to_le16(USB_CDC_EP_ACM_SIZE),
        .bInterval = 255,
    },
    .iface1 = {
        .bLength = sizeof(cdc_config_descriptor.iface1),
        .bDescriptorType = USB_DT_INTERFACE,
        .bInterfaceNumber = 1,
        .bNumEndpoints = 2,
        .bInterfaceClass = 0x0A,
    },
    .ep2 = {
        .bLength = sizeof(cdc_config_descriptor.ep2),
        .bDescriptorType = USB_DT_ENDPOINT,
        .bEndpointAddress = USB_CDC_EP_BULK_OUT,
        .bmAttributes = USB_ENDPOINT_XFER_BULK,
        .wMaxPacketSize = cpu_to_le16(USB_CDC_EP_BULK_OUT_SIZE),
    },
    .ep3 = {
        .bLength = sizeof(cdc_config_descriptor.ep3),
        .bDescriptorType = USB_DT_ENDPOINT,
        .bEndpointAddress = USB_CDC_EP_BULK_IN | USB_DIR_IN,
        .bmAttributes = USB_ENDPOINT_XFER_BULK,
        .wMaxPacketSize = cpu_to_le16(USB_CDC_EP_BULK_IN_SIZE),
    },
};

// List of available descriptors
static const struct descriptor_s {
    uint_fast16_t wValue;
    uint_fast16_t wIndex;
    const void *desc;
    uint_fast8_t size;
} cdc_descriptors[] PROGMEM = {
    { USB_DT_DEVICE<<8, 0x0000,
      &cdc_device_descriptor, sizeof(cdc_device_descriptor) },
    { USB_DT_CONFIG<<8, 0x0000,
      &cdc_config_descriptor, sizeof(cdc_config_descriptor) },
    { USB_DT_STRING<<8, 0x0000,
      &cdc_string_langids, SIZE_cdc_string_langids },
    { (USB_DT_STRING<<8) | USB_STR_ID_MANUFACTURER, USB_LANGID_ENGLISH_US,
      &cdc_string_manufacturer, SIZE_cdc_string_manufacturer },
    { (USB_DT_STRING<<8) | USB_STR_ID_PRODUCT, USB_LANGID_ENGLISH_US,
      &cdc_string_product, SIZE_cdc_string_product },
#if !CONFIG_USB_SERIAL_NUMBER_CHIPID
    { (USB_DT_STRING<<8) | USB_STR_ID_SERIAL, USB_LANGID_ENGLISH_US,
      &cdc_string_serial, SIZE_cdc_string_serial },
#endif
};

// Fill in a USB serial string descriptor from a chip id
void
usb_fill_serial(struct usb_string_descriptor *desc, int strlen, void *id)
{
    desc->bLength = sizeof(*desc) + strlen * sizeof(desc->data[0]);
    desc->bDescriptorType = USB_DT_STRING;

    uint8_t *src = id;
    int i;
    for (i = 0; i < strlen; i++) {
        uint8_t c = i & 1 ? src[i/2] & 0x0f : src[i/2] >> 4;
        desc->data[i] = c < 10 ? c + '0' : c - 10 + 'A';
    }
}


/****************************************************************
 * USB endpoint 0 control message handling
 ****************************************************************/

// State tracking
enum {
    UX_READ = 1<<0, UX_SEND = 1<<1, UX_SEND_PROGMEM = 1<<2, UX_SEND_ZLP = 1<<3
};

static void *usb_xfer_data;
static uint8_t usb_xfer_size, usb_xfer_flags;

// Set the USB "stall" condition
static void
usb_do_stall(void)
{
    usb_stall_ep0();
    usb_xfer_flags = 0;
}

// Transfer data on the usb endpoint 0
static void
usb_do_xfer(void *data, uint_fast8_t size, uint_fast8_t flags)
{
    for (;;) {
        uint_fast8_t xs = size;
        if (xs > USB_CDC_EP0_SIZE)
            xs = USB_CDC_EP0_SIZE;
        int_fast8_t ret;
        if (flags & UX_READ)
            ret = usb_read_ep0(data, xs);
        else if (NEED_PROGMEM && flags & UX_SEND_PROGMEM)
            ret = usb_send_ep0_progmem(data, xs);
        else
            ret = usb_send_ep0(data, xs);
        if (ret == xs) {
            // Success
            data += xs;
            size -= xs;
            if (!size) {
                // Entire transfer completed successfully
                if (flags & UX_READ) {
                    // Send status packet at end of read
                    flags = UX_SEND;
                    continue;
                }
                if (xs == USB_CDC_EP0_SIZE && flags & UX_SEND_ZLP)
                    // Must send zero-length-packet
                    continue;
                usb_xfer_flags = 0;
                usb_notify_ep0();
                return;
            }
            continue;
        }
        if (ret == -1) {
            // Interface busy - retry later
            usb_xfer_data = data;
            usb_xfer_size = size;
            usb_xfer_flags = flags;
            return;
        }
        // Error
        usb_do_stall();
        return;
    }
}

static void
usb_req_get_descriptor(struct usb_ctrlrequest *req)
{
    if (req->bRequestType != USB_DIR_IN)
        goto fail;
    void *desc = NULL;
    uint_fast8_t flags, size, i;
    for (i=0; i<ARRAY_SIZE(cdc_descriptors); i++) {
        const struct descriptor_s *d = &cdc_descriptors[i];
        if (READP(d->wValue) == req->wValue
            && READP(d->wIndex) == req->wIndex) {
            flags = NEED_PROGMEM ? UX_SEND_PROGMEM : UX_SEND;
            size = READP(d->size);
            desc = (void*)READP(d->desc);
        }
    }
    if (CONFIG_USB_SERIAL_NUMBER_CHIPID
        && req->wValue == ((USB_DT_STRING<<8) | USB_STR_ID_SERIAL)
        && req->wIndex == USB_LANGID_ENGLISH_US) {
            struct usb_string_descriptor *usbserial_serialid;
            usbserial_serialid = usbserial_get_serialid();
            flags = UX_SEND;
            size = usbserial_serialid->bLength;
            desc = (void*)usbserial_serialid;
    }
    if (desc) {
        if (size > req->wLength)
            size = req->wLength;
        else if (size < req->wLength)
            flags |= UX_SEND_ZLP;
        usb_do_xfer(desc, size, flags);
        return;
    }
fail:
    usb_do_stall();
}

static void
usb_req_set_address(struct usb_ctrlrequest *req)
{
    if (req->bRequestType || req->wIndex || req->wLength) {
        usb_do_stall();
        return;
    }
    usb_set_address(req->wValue);
}

static void
usb_req_set_configuration(struct usb_ctrlrequest *req)
{
    if (req->bRequestType || req->wValue != 1 || req->wIndex || req->wLength) {
        usb_do_stall();
        return;
    }
    usb_set_configure();
    usb_notify_bulk_in();
    usb_notify_bulk_out();
    usb_do_xfer(NULL, 0, UX_SEND);
}

static struct usb_cdc_line_coding line_coding;
static uint8_t line_control_state;

static void
check_reboot(void)
{
    if (line_coding.dwDTERate == 1200 && !(line_control_state & 0x01))
        // A baud of 1200 is an Arduino style request to enter the bootloader
        usb_request_bootloader();
}

static void
usb_req_set_line_coding(struct usb_ctrlrequest *req)
{
    if (req->bRequestType != 0x21 || req->wValue || req->wIndex
        || req->wLength != sizeof(line_coding)) {
        usb_do_stall();
        return;
    }
    usb_do_xfer(&line_coding, sizeof(line_coding), UX_READ);
    check_reboot();
}

static void
usb_req_get_line_coding(struct usb_ctrlrequest *req)
{
    if (req->bRequestType != 0xa1 || req->wValue || req->wIndex
        || req->wLength < sizeof(line_coding)) {
        usb_do_stall();
        return;
    }
    usb_do_xfer(&line_coding, sizeof(line_coding), UX_SEND);
}

static void
usb_req_set_line(struct usb_ctrlrequest *req)
{
    if (req->bRequestType != 0x21 || req->wIndex || req->wLength) {
        usb_do_stall();
        return;
    }
    line_control_state = req->wValue;
    usb_do_xfer(NULL, 0, UX_SEND);
    check_reboot();
}

static void
usb_state_ready(void)
{
    struct usb_ctrlrequest req;
    int_fast8_t ret = usb_read_ep0_setup(&req, sizeof(req));
    if (ret != sizeof(req))
        return;
    switch (req.bRequest) {
    case USB_REQ_GET_DESCRIPTOR: usb_req_get_descriptor(&req); break;
    case USB_REQ_SET_ADDRESS: usb_req_set_address(&req); break;
    case USB_REQ_SET_CONFIGURATION: usb_req_set_configuration(&req); break;
    case USB_CDC_REQ_SET_LINE_CODING: usb_req_set_line_coding(&req); break;
    case USB_CDC_REQ_GET_LINE_CODING: usb_req_get_line_coding(&req); break;
    case USB_CDC_REQ_SET_CONTROL_LINE_STATE: usb_req_set_line(&req); break;
    default: usb_do_stall(); break;
    }
}

// State tracking dispatch
static struct task_wake usb_ep0_wake;

void
usb_notify_ep0(void)
{
    sched_wake_task(&usb_ep0_wake);
}

void
usb_ep0_task(void)
{
    if (!sched_check_wake(&usb_ep0_wake))
        return;
    if (usb_xfer_flags)
        usb_do_xfer(usb_xfer_data, usb_xfer_size, usb_xfer_flags);
    else
        usb_state_ready();
}
DECL_TASK(usb_ep0_task);

void
usb_shutdown(void)
{
    usb_notify_bulk_in();
    usb_notify_bulk_out();
    usb_notify_ep0();
}
DECL_SHUTDOWN(usb_shutdown);
