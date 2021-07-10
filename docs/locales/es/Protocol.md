The Klipper messaging protocol is used for low-level communication between the
Klipper host software and the Klipper micro-controller software. At a high level
the protocol can be thought of as a series of command and response strings that
are compressed, transmitted, and then processed at the receiving side. An
example series of commands in uncompressed human-readable format might look
like:

```
set_digital_out pin=PA3 value=1
set_digital_out pin=PA7 value=1
schedule_digital_out oid=8 clock=4000000 value=0
queue_step oid=7 interval=7458 count=10 add=331
queue_step oid=7 interval=11717 count=4 add=1281
```

See the [mcu commands](MCU_Commands.md) document for information on available
commands. See the [debugging](Debugging.md) document for information on how to
translate a G-Code file into its corresponding human-readable micro-controller
commands.

This page provides a high-level description of the Klipper messaging protocol
itself. It describes how messages are declared, encoded in binary format (the
"compression" scheme), and transmitted.

The goal of the protocol is to enable an error-free communication channel
between the host and micro-controller that is low-latency, low-bandwidth, and
low-complexity for the micro-controller.

# Micro-controller Interface

The Klipper transmission protocol can be thought of as a
[RPC](https://en.wikipedia.org/wiki/Remote_procedure_call) mechanism between
micro-controller and host. The micro-controller software declares the commands
that the host may invoke along with the response messages that it can generate.
The host uses that information to command the micro-controller to perform
actions and to interpret the results.

## Declaring commands

The micro-controller software declares a "command" by using the DECL_COMMAND()
macro in the C code. For example:

```
DECL_COMMAND(command_update_digital_out, "update_digital_out oid=%c value=%c");
```

The above declares a command named "update_digital_out". This allows the host
to "invoke" this command which would cause the command_update_digital_out() C
function to be executed in the micro-controller. The above also indicates that
the command takes two integer parameters. When the command_update_digital_out()
C code is executed, it will be passed an array containing these two integers -
the first corresponding to the 'oid' and the second corresponding to the
'value'.

In general, the parameters are described with printf() style syntax (eg,
"%u"). The formatting directly corresponds to the human-readable view of
commands (eg, "update_digital_out oid=7 value=1"). In the above example,
"value=" is a parameter name and "%c" indicates the parameter is an integer.
Internally, the parameter name is only used as documentation. In this example,
the "%c" is also used as documentation to indicate the expected integer is 1
byte in size (the declared integer size does not impact the parsing or
encoding).

The micro-controller build will collect all commands declared with
DECL_COMMAND(), determine their parameters, and arrange for them to be callable.

## Declaring responses

To send information from the micro-controller to the host a "response" is
generated. These are both declared and transmitted using the sendf() C macro.
For example:

```
sendf("status clock=%u status=%c", sched_read_time(), sched_is_shutdown());
```

The above transmits a "status" response message that contains two integer
parameters ("clock" and "status"). The micro-controller build automatically
finds all sendf() calls and generates encoders for them. The first parameter of
the sendf() function describes the response and it is in the same format as
command declarations.

The host can arrange to register a callback function for each response. So, in
effect, commands allow the host to invoke C functions in the micro-controller
and responses allow the micro-controller software to invoke code in the host.

The sendf() macro should only be invoked from command or task handlers, and it
should not be invoked from interrupts or timers. The code does not need to issue
a sendf() in response to a received command, it is not limited in the number of
times sendf() may be invoked, and it may invoke sendf() at any time from a task
handler.

### Output responses

To simplify debugging, there is also an output() C function. For example:

```
output("The value of %u is %s with size %u.", x, buf, buf_len);
```

The output() function is similar in usage to printf() - it is intended to
generate and format arbitrary messages for human consumption.

## Declaring enumerations

Enumerations allow the host code to use string identifiers for parameters that
the micro-controller handles as integers. They are declared in the micro-
controller code - for example:

```
DECL_ENUMERATION("spi_bus", "spi", 0);

DECL_ENUMERATION_RANGE("pin", "PC0", 16, 8);
```

If the first example, the DECL_ENUMERATION() macro defines an enumeration for
any command/response message with a parameter name of "spi_bus" or parameter
name with a suffix of "_spi_bus". For those parameters the string "spi" is a
valid value and it will be transmitted with an integer value of zero.

It's also possible to declare an enumeration range. In the second example, a
"pin" parameter (or any parameter with a suffix of "_pin") would accept PC0,
PC1, PC2, ..., PC7 as valid values. The strings will be transmitted with
integers 16, 17, 18, ..., 23.

## Declaring constants

Constants can also be exported. For example, the following:

```
DECL_CONSTANT("SERIAL_BAUD", 250000);
```

would export a constant named "SERIAL_BAUD" with a value of 250000 from the
micro-controller to the host. It is also possible to declare a constant that is
a string - for example:

```
DECL_CONSTANT_STR("MCU", "pru");
```

# Low-level message encoding

To accomplish the above RPC mechanism, each command and response is encoded into
a binary format for transmission. This section describes the transmission
system.

## Message Blocks

All data sent from host to micro-controller and vice-versa are contained in
"message blocks". A message block has a two byte header and a three byte
trailer. The format of a message block is:

```
<1 byte length><1 byte sequence><n-byte content><2 byte crc><1 byte sync>
```

The length byte contains the number of bytes in the message block including the
header and trailer bytes (thus the minimum message length is 5 bytes). The
maximum message block length is currently 64 bytes. The sequence byte contains a
4 bit sequence number in the low-order bits and the high-order bits always
contain 0x10 (the high-order bits are reserved for future use). The content
bytes contain arbitrary data and its format is described in the following
section. The crc bytes contain a 16bit CCITT
[CRC](https://en.wikipedia.org/wiki/Cyclic_redundancy_check) of the message
block including the header bytes but excluding the trailer bytes. The sync byte
is 0x7e.

The format of the message block is inspired by
[HDLC](https://en.wikipedia.org/wiki/High-Level_Data_Link_Control) message
frames. Like in HDLC, the message block may optionally contain an additional
sync character at the start of the block. Unlike in HDLC, a sync character is
not exclusive to the framing and may be present in the message block content.

## Message Block Contents

Each message block sent from host to micro-controller contains a series of zero
or more message commands in its contents. Each command starts with a [Variable
Length Quantity](#variable-length-quantities) (VLQ) encoded integer command-id
followed by zero or more VLQ parameters for the given command.

As an example, the following four commands might be placed in a single message
block:

```
update_digital_out oid=6 value=1
update_digital_out oid=5 value=0
get_config
get_clock
```

and encoded into the following eight VLQ integers:

```
<id_update_digital_out><6><1><id_update_digital_out><5><0><id_get_config><id_get_clock>
```

In order to encode and parse the message contents, both the host and micro-
controller must agree on the command ids and the number of parameters each
command has. So, in the above example, both the host and micro-controller would
know that "id_update_digital_out" is always followed by two parameters, and
"id_get_config" and "id_get_clock" have zero parameters. The host and micro-
controller share a "data dictionary" that maps the command descriptions (eg,
"update_digital_out oid=%c value=%c") to their integer command-ids. When
processing the data, the parser will know to expect a specific number of VLQ
encoded parameters following a given command id.

The message contents for blocks sent from micro-controller to host follow the
same format. The identifiers in these messages are "response ids", but they
serve the same purpose and follow the same encoding rules. In practice, message
blocks sent from the micro-controller to the host never contain more than one
response in the message block contents.

### Variable Length Quantities

See the [wikipedia article](https://en.wikipedia.org/wiki/Variable-
length_quantity) for more information on the general format of VLQ encoded
integers. Klipper uses an encoding scheme that supports both positive and
negative integers. Integers close to zero use less bytes to encode and positive
integers typically encode using less bytes than negative integers. The following
table shows the number of bytes each integer takes to encode:

| Integer | Encoded size |
| ------- | ------------ |
| -32 .. 95 | 1 |
| -4096 .. 12287 | 2 |
| -524288 .. 1572863 | 3 |
| -67108864 .. 201326591 | 4 |
| -2147483648 .. 4294967295 | 5 |

### Variable length strings

As an exception to the above encoding rules, if a parameter to a command or
response is a dynamic string then the parameter is not encoded as a simple VLQ
integer. Instead it is encoded by transmitting the length as a VLQ encoded
integer followed by the contents itself:

```
<VLQ encoded length><n-byte contents>
```

The command descriptions found in the data dictionary allow both the host and
micro-controller to know which command parameters use simple VLQ encoding and
which parameters use string encoding.

# Data Dictionary

In order for meaningful communications to be established between micro-
controller and host, both sides must agree on a "data dictionary". This data
dictionary contains the integer identifiers for commands and responses along
with their descriptions.

The micro-controller build uses the contents of DECL_COMMAND() and sendf()
macros to generate the data dictionary. The build automatically assigns unique
identifiers to each command and response. This system allows both the host and
micro-controller code to seamlessly use descriptive human-readable names while
still using minimal bandwidth.

The host queries the data dictionary when it first connects to the micro-
controller. Once the host downloads the data dictionary from the micro-
controller, it uses that data dictionary to encode all commands and to parse all
responses from the micro-controller. The host must therefore handle a dynamic
data dictionary. However, to keep the micro-controller software simple, the
micro-controller always uses its static (compiled in) data dictionary.

The data dictionary is queried by sending "identify" commands to the micro-
controller. The micro-controller will respond to each identify command with an
"identify_response" message. Since these two commands are needed prior to
obtaining the data dictionary, their integer ids and parameter types are hard-
coded in both the micro-controller and the host. The "identify_response"
response id is 0, the "identify" command id is 1. Other than having hard-coded
ids the identify command and its response are declared and transmitted the same
way as other commands and responses. No other command or response is hard-coded.

The format of the transmitted data dictionary itself is a zlib compressed JSON
string. The micro-controller build process generates the string, compresses it,
and stores it in the text section of the micro-controller flash. The data
dictionary can be much larger than the maximum message block size - the host
downloads it by sending multiple identify commands requesting progressive chunks
of the data dictionary. Once all chunks are obtained the host will assemble the
chunks, uncompress the data, and parse the contents.

In addition to information on the communication protocol, the data dictionary
also contains the software version, enumerations (as defined by
DECL_ENUMERATION), and constants (as defined by DECL_CONSTANT).

# Message flow

Message commands sent from host to micro-controller are intended to be error-
free. The micro-controller will check the CRC and sequence numbers in each
message block to ensure the commands are accurate and in-order. The micro-
controller always processes message blocks in-order - should it receive a block
out-of-order it will discard it and any other out-of-order blocks until it
receives blocks with the correct sequencing.

The low-level host code implements an automatic retransmission system for lost
and corrupt message blocks sent to the micro-controller. To facilitate this, the
micro-controller transmits an "ack message block" after each successfully
received message block. The host schedules a timeout after sending each block
and it will retransmit should the timeout expire without receiving a
corresponding "ack". In addition, if the micro-controller detects a corrupt or
out-of-order block it may transmit a "nak message block" to facilitate fast
retransmission.

An "ack" is a message block with empty content (ie, a 5 byte message block)
and a sequence number greater than the last received host sequence number. A
"nak" is a message block with empty content and a sequence number less than
the last received host sequence number.

The protocol facilitates a "window" transmission system so that the host can
have many outstanding message blocks in-flight at a time. (This is in addition
to the many commands that may be present in a given message block.) This allows
maximum bandwidth utilization even in the event of transmission latency. The
timeout, retransmit, windowing, and ack mechanism are inspired by similar
mechanisms in
[TCP](https://en.wikipedia.org/wiki/Transmission_Control_Protocol).

In the other direction, message blocks sent from micro-controller to host are
designed to be error-free, but they do not have assured transmission. (Responses
should not be corrupt, but they may go missing.) This is done to keep the
implementation in the micro-controller simple. There is no automatic
retransmission system for responses - the high-level code is expected to be
capable of handling an occasional missing response (usually by re-requesting the
content or setting up a recurring schedule of response transmission). The
sequence number field in message blocks sent to the host is always one greater
than the last received sequence number of message blocks received from the host.
It is not used to track sequences of response message blocks.
