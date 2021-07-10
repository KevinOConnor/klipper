This document describes the protocol Klipper uses to communicate over [CAN
bus](https://en.wikipedia.org/wiki/CAN_bus). See [CANBUS.md] for information on
configuring Klipper with CAN bus.

# Micro-controller id assignment

Klipper uses only CAN 2.0A standard size CAN bus packets, which are limited to 8
data bytes and an 11-bit CAN bus identifier. In order to support efficient
communication, each micro-controller is assigned at run-time a unique 1-byte CAN
bus nodeid (`canbus_nodeid`) for general Klipper command and response traffic.
Klipper command messages going from host to micro-controller use the CAN bus id
of `canbus_nodeid * 2 + 256`, while Klipper response messages from micro-
controller to host use `canbus_nodeid * 2 + 256 + 1`.

Each micro-controller has a factory assigned unique chip identifier that is used
during id assignment. This identifier can exceed the length of one CAN packet,
so a hash function is used to generate a unique 6-byte id (`canbus_uuid`) from
the factory id.

# Admin messages

Admin messages are used for id assignment. Admin messages sent from host to
micro-controller use the CAN bus id `0x3f0` and messages sent from micro-
controller to host use the CAN bus id `0x3f1`. All micro-controllers listen to
messages on id `0x3f0`; that id can be thought of as a "broadcast address".

## CMD_QUERY_UNASSIGNED message

This command queries all micro-controllers that have not yet been assigned a
`canbus_nodeid`. Unassigned micro-controllers will respond with a
RESP_NEED_NODEID response message.

The CMD_QUERY_UNASSIGNED message format is: `<1-byte message_id = 0x00>`

## CMD_SET_NODEID message

This command assigns a `canbus_nodeid` to the micro-controller with a given
`canbus_uuid`.

The CMD_SET_NODEID message format is: `<1-byte message_id = 0x01><6-byte canbus_uuid><1-byte canbus_nodeid>`

## RESP_NEED_NODEID message

The RESP_NEED_NODEID message format is: `<1-byte message_id = 0x20><6-byte canbus_uuid>`

# Data Packets

A micro-controller that has been assigned a nodeid via the CMD_SET_NODEID
command can send and receive data packets.

The packet data in messages using the node's receive CAN bus id (
`canbus_nodeid * 2 + 256`) are simply appended to a buffer, and when a complete
[mcu protocol message](Protocol.md) is found its contents are parsed and
processed. The data is treated as a byte stream - there is no requirement for
the start of a Klipper message block to align with the start of a CAN bus
packet.

Similarly, mcu protocol message responses are sent from micro-controller to host
by copying the message data into one or more packets with the node's transmit
CAN bus id (`canbus_nodeid * 2 + 256 + 1`).
