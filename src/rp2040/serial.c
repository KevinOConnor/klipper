// rp2040 serial
//
// Copyright (C) 2021  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <stdint.h> // uint32_t
#include "autoconf.h" // CONFIG_SERIAL
#include "board/armcm_boot.h" // armcm_enable_irq
#include "board/irq.h" // irq_save
#include "board/serial_irq.h" // serial_rx_data
#include "hardware/structs/resets.h" // RESETS_RESET_UART0_BITS
#include "hardware/structs/uart.h" // UART0_BASE
#include "internal.h" // UART0_IRQn
#include "sched.h" // DECL_INIT

#define UARTx uart0_hw
#define UARTx_IRQn UART0_IRQ_IRQn
#define GPIO_Rx 1
#define GPIO_Tx 0

// Write tx bytes to the serial port
static void
kick_tx(void)
{
    for (;;) {
        if (UARTx->fr & UART_UARTFR_TXFF_BITS) {
            // Output fifo full - enable tx irq
            UARTx->imsc = (UART_UARTIMSC_RXIM_BITS | UART_UARTIMSC_RTIM_BITS
                           | UART_UARTIMSC_TXIM_BITS);
            break;
        }
        uint8_t data;
        int ret = serial_get_tx_byte(&data);
        if (ret) {
            // No more data to send - disable tx irq
            UARTx->imsc = UART_UARTIMSC_RXIM_BITS | UART_UARTIMSC_RTIM_BITS;
            break;
        }
        UARTx->dr = data;
    }
}

void
UARTx_IRQHandler(void)
{
    uint32_t mis = UARTx->mis;
    if (mis & (UART_UARTMIS_RXMIS_BITS | UART_UARTMIS_RTMIS_BITS)) {
        do {
            serial_rx_byte(UARTx->dr);
        } while (!(UARTx->fr & UART_UARTFR_RXFE_BITS));
    } else if (mis & UART_UARTMIS_TXMIS_BITS) {
        kick_tx();
    }
}

void
serial_enable_tx_irq(void)
{
    if (!(UARTx->fr & UART_UARTFR_TXFF_BITS)) {
        irqstatus_t flag = irq_save();
        kick_tx();
        irq_restore(flag);
    }
}

void
serial_init(void)
{
    enable_pclock(RESETS_RESET_UART0_BITS);

    // Setup baud
    uint32_t pclk = get_pclock_frequency(RESETS_RESET_UART0_BITS);
    uint32_t div = DIV_ROUND_CLOSEST(pclk * 4, CONFIG_SERIAL_BAUD);
    UARTx->ibrd = div >> 6;
    UARTx->fbrd = div & 0x3f;

    // Enable fifo, set 8N1
    UARTx->lcr_h = UART_UARTLCR_H_FEN_BITS | UART_UARTLCR_H_WLEN_BITS;
    UARTx->ifls = 0;
    UARTx->cr = (UART_UARTCR_RXE_BITS | UART_UARTCR_TXE_BITS
                 | UART_UARTCR_UARTEN_BITS);

    // Setup pins
    gpio_peripheral(GPIO_Rx, 2, 1);
    gpio_peripheral(GPIO_Tx, 2, 0);

    // Enable receive irq
    armcm_enable_irq(UARTx_IRQHandler, UARTx_IRQn, 0);
    UARTx->imsc = UART_UARTIMSC_RXIM_BITS | UART_UARTIMSC_RTIM_BITS;
}
DECL_INIT(serial_init);
