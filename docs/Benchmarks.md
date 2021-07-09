This document describes Klipper benchmarks.

Micro-controller Benchmarks
===========================

This section describes the mechanism used to generate the Klipper
micro-controller step rate benchmarks.

The primary goal of the benchmarks is to provide a consistent
mechanism for measuring the impact of coding changes within the
software. A secondary goal is to provide high-level metrics for
comparing the performance between chips and between software
platforms.

The step rate benchmark is designed to find the maximum stepping rate
that the hardware and software can reach. This benchmark stepping rate
is not achievable in day-to-day use as Klipper needs to perform other
tasks (eg, mcu/host communication, temperature reading, endstop
checking) in any real-world usage.

In general, the pins for the benchmark tests are chosen to flash LEDs
or other innocuous pins. **Always verify that it is safe to drive the
configured pins prior to running a benchmark.** It is not recommended
to drive an actual stepper during a benchmark.

## Step rate benchmark test ##

The test is performed using the console.py tool (described in
[Debugging.md](Debugging.md)). The micro-controller is configured for
the particular hardware platform (see below) and then the following is
cut-and-paste into the console.py terminal window:
```
SET start_clock {clock+freq}
SET ticks 1000

reset_step_clock oid=0 clock={start_clock}
set_next_step_dir oid=0 dir=0
queue_step oid=0 interval={ticks} count=60000 add=0
set_next_step_dir oid=0 dir=1
queue_step oid=0 interval=3000 count=1 add=0

reset_step_clock oid=1 clock={start_clock}
set_next_step_dir oid=1 dir=0
queue_step oid=1 interval={ticks} count=60000 add=0
set_next_step_dir oid=1 dir=1
queue_step oid=1 interval=3000 count=1 add=0

reset_step_clock oid=2 clock={start_clock}
set_next_step_dir oid=2 dir=0
queue_step oid=2 interval={ticks} count=60000 add=0
set_next_step_dir oid=2 dir=1
queue_step oid=2 interval=3000 count=1 add=0
```

The above tests three steppers simultaneously stepping. If running the
above results in a "Rescheduled timer in the past" or "Stepper too far
in past" error then it indicates the `ticks` parameter is too low (it
results in a stepping rate that is too fast). The goal is to find the
lowest setting of the ticks parameter that reliably results in a
successful completion of the test. It should be possible to bisect the
ticks parameter until a stable value is found.

On a failure, one can copy-and-paste the following to clear the error
in preparation for the next test:
```
clear_shutdown
```

To obtain the single stepper and dual stepper benchmarks, the same
configuration sequence is used, but only the first block (for the
single stepper case) or first two blocks (for the dual stepper case)
of the above test is cut-and-paste into the console.py window.

To produce the benchmarks found in the Features.md document, the total
number of steps per second is calculated by multiplying the number of
active steppers with the nominal mcu frequency and dividing by the
final ticks parameter. The results are rounded to the nearest K. For
example, with three active steppers:
```
ECHO Test result is: {"%.0fK" % (3. * freq / ticks / 1000.)}
```

Benchmarks may be run with the micro-controller code compiled using a
"step pulse duration" of zero (the tables below report this as "no
delay"). This configuration is believed to be valid in real-world
usage when one is solely using Trinamic stepper drivers. The results
of these benchmarks are not reported in the Features.md document.

### AVR step rate benchmark ###

The following configuration sequence is used on AVR chips:
```
PINS arduino
allocate_oids count=3
config_stepper oid=0 step_pin=ar29 dir_pin=ar28 invert_step=0
config_stepper oid=1 step_pin=ar27 dir_pin=ar26 invert_step=0
config_stepper oid=2 step_pin=ar23 dir_pin=ar22 invert_step=0
finalize_config crc=0
```

The test was last run on commit `01d2183f` with gcc version `avr-gcc
(GCC) 5.4.0`. Both the 16Mhz and 20Mhz tests were run using simulavr
configured for an atmega644p (previous tests have confirmed simulavr
results match tests on both a 16Mhz at90usb and a 16Mhz atmega2560).

| avr              | ticks |
| ---------------- | ----- |
| 1 stepper        | 104   |
| 2 stepper        | 296   |
| 3 stepper        | 472   |

### Arduino Due step rate benchmark ###

The following configuration sequence is used on the Due:
```
allocate_oids count=3
config_stepper oid=0 step_pin=PB27 dir_pin=PA21 invert_step=0
config_stepper oid=1 step_pin=PB26 dir_pin=PC30 invert_step=0
config_stepper oid=2 step_pin=PA21 dir_pin=PC30 invert_step=0
finalize_config crc=0
```

The test was last run on commit `8d4a5c16` with gcc version
`arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0`.

| sam3x8e              | ticks |
| -------------------- | ----- |
| 1 stepper            | 388   |
| 2 stepper            | 405   |
| 3 stepper            | 576   |
| 1 stepper (no delay) | 77    |
| 3 stepper (no delay) | 299   |

### Duet Maestro step rate benchmark ###

The following configuration sequence is used on the Duet Maestro:
```
allocate_oids count=3
config_stepper oid=0 step_pin=PC26 dir_pin=PC18 invert_step=0
config_stepper oid=1 step_pin=PC26 dir_pin=PA8 invert_step=0
config_stepper oid=2 step_pin=PC26 dir_pin=PB4 invert_step=0
finalize_config crc=0
```

The test was last run on commit `8d4a5c16` with gcc version
`arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0`.

| sam4s8c              | ticks |
| -------------------- | ----- |
| 1 stepper            | 527   |
| 2 stepper            | 535   |
| 3 stepper            | 638   |
| 1 stepper (no delay) | 70    |
| 3 stepper (no delay) | 254   |

### Duet Wifi step rate benchmark ###

The following configuration sequence is used on the Duet Wifi:
```
allocate_oids count=4
config_stepper oid=0 step_pin=PD6 dir_pin=PD11 invert_step=0
config_stepper oid=1 step_pin=PD7 dir_pin=PD12 invert_step=0
config_stepper oid=2 step_pin=PD8 dir_pin=PD13 invert_step=0
config_stepper oid=3 step_pin=PD5 dir_pin=PA1 invert_step=0
finalize_config crc=0

```

The test was last run on commit `59a60d68` with gcc version
`arm-none-eabi-gcc 7.3.1 20180622 (release)
[ARM/embedded-7-branch revision 261907]`.

| sam4e8e          | ticks |
| ---------------- | ----- |
| 1 stepper        | 519   |
| 2 stepper        | 520   |
| 3 stepper        | 525   |
| 4 stepper        | 703   |

### Beaglebone PRU step rate benchmark ###

The following configuration sequence is used on the PRU:
```
PINS beaglebone
allocate_oids count=3
config_stepper oid=0 step_pin=P8_13 dir_pin=P8_12 invert_step=0
config_stepper oid=1 step_pin=P8_15 dir_pin=P8_14 invert_step=0
config_stepper oid=2 step_pin=P8_19 dir_pin=P8_18 invert_step=0
finalize_config crc=0
```

The test was last run on commit `b161a69e` with gcc version `pru-gcc
(GCC) 8.0.0 20170530 (experimental)`.

| pru              | ticks |
| ---------------- | ----- |
| 1 stepper        | 861   |
| 2 stepper        | 853   |
| 3 stepper        | 883   |

### STM32F042 step rate benchmark ###

The following configuration sequence is used on the STM32F042:
```
allocate_oids count=3
config_stepper oid=0 step_pin=PA1 dir_pin=PA2 invert_step=0
config_stepper oid=1 step_pin=PA3 dir_pin=PA2 invert_step=0
config_stepper oid=2 step_pin=PB8 dir_pin=PA2 invert_step=0
finalize_config crc=0
```

The test was last run on commit `0b0c47c5` with gcc version
`arm-none-eabi-gcc (Fedora 9.2.0-1.fc30) 9.2.0`.

| stm32f042        | ticks |
| ---------------- | ----- |
| 1 stepper        | 247   |
| 2 stepper        | 328   |
| 3 stepper        | 558   |

### STM32F103 step rate benchmark ###

The following configuration sequence is used on the STM32F103:
```
allocate_oids count=3
config_stepper oid=0 step_pin=PC13 dir_pin=PB5 invert_step=0
config_stepper oid=1 step_pin=PB3 dir_pin=PB6 invert_step=0
config_stepper oid=2 step_pin=PA4 dir_pin=PB7 invert_step=0
finalize_config crc=0
```

The test was last run on commit `8d4a5c16` with gcc version
`arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0`.

| stm32f103            | ticks |
| -------------------- | ----- |
| 1 stepper            | 347   |
| 2 stepper            | 372   |
| 3 stepper            | 600   |
| 1 stepper (no delay) | 71    |
| 3 stepper (no delay) | 288   |

### STM32F4 step rate benchmark ###

The following configuration sequence is used on the STM32F4:
```
allocate_oids count=4
config_stepper oid=0 step_pin=PA5 dir_pin=PB5 invert_step=0
config_stepper oid=1 step_pin=PB2 dir_pin=PB6 invert_step=0
config_stepper oid=2 step_pin=PB3 dir_pin=PB7 invert_step=0
config_stepper oid=3 step_pin=PB3 dir_pin=PB8 invert_step=0
finalize_config crc=0
```

The test was last run on commit `8d4a5c16` with gcc version
`arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0`. The STM32F407 results
were obtained by running an STM32F407 binary on an STM32F446 (and thus
using a 168Mhz clock).

| stm32f446            | ticks |
| -------------------- | ----- |
| 1 stepper            | 757   |
| 2 stepper            | 761   |
| 3 stepper            | 757   |
| 4 stepper            | 767   |
| 1 stepper (no delay) | 51    |
| 3 stepper (no delay) | 226   |

| stm32f407            | ticks |
| -------------------- | ----- |
| 1 stepper            | 709   |
| 2 stepper            | 714   |
| 3 stepper            | 709   |
| 4 stepper            | 729   |
| 1 stepper (no delay) | 52    |
| 3 stepper (no delay) | 226   |

### LPC176x step rate benchmark ###

The following configuration sequence is used on the LPC176x:
```
allocate_oids count=3
config_stepper oid=0 step_pin=P1.20 dir_pin=P1.18 invert_step=0
config_stepper oid=1 step_pin=P1.21 dir_pin=P1.18 invert_step=0
config_stepper oid=2 step_pin=P1.23 dir_pin=P1.18 invert_step=0
finalize_config crc=0
```

The test was last run on commit `8d4a5c16` with gcc version
`arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0`. The 120Mhz LPC1769
results were obtained by overclocking an LPC1768 to 120Mhz.

| lpc1768              | ticks |
| -------------------- | ----- |
| 1 stepper            | 448   |
| 2 stepper            | 450   |
| 3 stepper            | 523   |
| 1 stepper (no delay) | 56    |
| 3 stepper (no delay) | 240   |

| lpc1769              | ticks |
| -------------------- | ----- |
| 1 stepper            | 525   |
| 2 stepper            | 526   |
| 3 stepper            | 545   |
| 1 stepper (no delay) | 56    |
| 3 stepper (no delay) | 240   |

### SAMD21 step rate benchmark ###

The following configuration sequence is used on the SAMD21:
```
allocate_oids count=3
config_stepper oid=0 step_pin=PA27 dir_pin=PA20 invert_step=0
config_stepper oid=1 step_pin=PB3 dir_pin=PA21 invert_step=0
config_stepper oid=2 step_pin=PA17 dir_pin=PA21 invert_step=0
finalize_config crc=0
```

The test was last run on commit `8d4a5c16` with gcc version
`arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0` on a SAMD21G18
micro-controller.

| samd21               | ticks |
| -------------------- | ----- |
| 1 stepper            | 277   |
| 2 stepper            | 410   |
| 3 stepper            | 664   |
| 1 stepper (no delay) | 83    |
| 3 stepper (no delay) | 321   |

### SAMD51 step rate benchmark ###

The following configuration sequence is used on the SAMD51:
```
allocate_oids count=5
config_stepper oid=0 step_pin=PA22 dir_pin=PA20 invert_step=0
config_stepper oid=1 step_pin=PA22 dir_pin=PA21 invert_step=0
config_stepper oid=2 step_pin=PA22 dir_pin=PA19 invert_step=0
config_stepper oid=3 step_pin=PA22 dir_pin=PA18 invert_step=0
config_stepper oid=4 step_pin=PA23 dir_pin=PA17 invert_step=0
finalize_config crc=0
```

The test was last run on commit `524ebbc7` with gcc version
`arm-none-eabi-gcc (Fedora 9.2.0-1.fc30) 9.2.0` on a SAMD51J19A
micro-controller.

| samd51               | ticks |
| -------------------- | ----- |
| 1 stepper            | 516   |
| 2 stepper            | 520   |
| 3 stepper            | 520   |
| 4 stepper            | 631   |
| 1 stepper (200Mhz)   | 839   |
| 2 stepper (200Mhz)   | 838   |
| 3 stepper (200Mhz)   | 838   |
| 4 stepper (200Mhz)   | 838   |
| 5 stepper (200Mhz)   | 891   |
| 1 stepper (no delay) | 42    |
| 3 stepper (no delay) | 194   |

### RP2040 step rate benchmark ###

The following configuration sequence is used on the RP2040:

```
allocate_oids count=4
config_stepper oid=0 step_pin=gpio25 dir_pin=gpio3 invert_step=0
config_stepper oid=1 step_pin=gpio26 dir_pin=gpio4 invert_step=0
config_stepper oid=2 step_pin=gpio27 dir_pin=gpio5 invert_step=0
config_stepper oid=3 step_pin=gpio28 dir_pin=gpio6 invert_step=0
finalize_config crc=0
```

The test was last run on commit `c5667193` with gcc version
`arm-none-eabi-gcc (Fedora 10.2.0-4.fc34) 10.2.0` on a Raspberry Pi
Pico board.

| rp2040               | ticks |
| -------------------- | ----- |
| 1 stepper            | 52    |
| 2 stepper            | 52    |
| 3 stepper            | 52    |
| 4 stepper            | 66    |
| 1 stepper (no delay) | 5     |
| 3 stepper (no delay) | 22    |

### Linux MCU step rate benchmark ###

The following configuration sequence is used on a Raspberry Pi:
```
allocate_oids count=3
config_stepper oid=0 step_pin=gpio2 dir_pin=gpio3 invert_step=0
config_stepper oid=1 step_pin=gpio4 dir_pin=gpio5 invert_step=0
config_stepper oid=2 step_pin=gpio6 dir_pin=gpio7 invert_step=0
finalize_config crc=0
```

The test was last run on commit `db0fb5d5` with gcc version `gcc
(Raspbian 6.3.0-18+rpi1+deb9u1) 6.3.0 20170516` on a Raspberry Pi 3
(revision a22082).

| Linux (RPi3)         | ticks |
| -------------------- | ----- |
| 1 stepper            | 349   |
| 2 stepper            | 350   |
| 3 stepper            | 400   |

## Command dispatch benchmark ##

The command dispatch benchmark tests how many "dummy" commands the
micro-controller can process. It is primarily a test of the hardware
communication mechanism. The test is run using the console.py tool
(described in [Debugging.md](Debugging.md)). The following is
cut-and-paste into the console.py terminal window:
```
DELAY {clock + 2*freq} get_uptime
FLOOD 100000 0.0 debug_nop
get_uptime
```

When the test completes, determine the difference between the clocks
reported in the two "uptime" response messages. The total number of
commands per second is then `100000 * mcu_frequency / clock_diff`.

Note that this test may saturate the USB/CPU capacity of a Raspberry
Pi. If running on a Raspberry Pi, Beaglebone, or similar host computer
then increase the delay (eg, `DELAY {clock + 20*freq} get_uptime`).
Where applicable, the benchmarks below are with console.py running on
a desktop class machine with the device connected via a high-speed
hub.

| MCU                 | Rate | Build    | Build compiler      |
| ------------------- | ---- | -------- | ------------------- |
| stm32f042 (CAN)     |  18K | c105adc8 | arm-none-eabi-gcc (GNU Tools 7-2018-q3-update) 7.3.1 |
| atmega2560 (serial) |  23K | b161a69e | avr-gcc (GCC) 4.8.1 |
| sam3x8e (serial)    |  23K | b161a69e | arm-none-eabi-gcc (Fedora 7.1.0-5.fc27) 7.1.0 |
| at90usb1286 (USB)   |  75K | 01d2183f | avr-gcc (GCC) 5.4.0 |
| samd21 (USB)        | 223K | 01d2183f | arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0 |
| pru (shared memory) | 260K | c5968a08 | pru-gcc (GCC) 8.0.0 20170530 (experimental) |
| stm32f103 (USB)     | 355K | 01d2183f | arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0 |
| sam3x8e (USB)       | 418K | 01d2183f | arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0 |
| lpc1768 (USB)       | 534K | 01d2183f | arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0 |
| lpc1769 (USB)       | 628K | 01d2183f | arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0 |
| sam4s8c (USB)       | 650K | 8d4a5c16 | arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0 |
| samd51 (USB)        | 864K | 01d2183f | arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0 |
| stm32f446 (USB)     | 870K | 01d2183f | arm-none-eabi-gcc (Fedora 7.4.0-1.fc30) 7.4.0 |
| rp2040 (USB)        | 873K | c5667193 | arm-none-eabi-gcc (Fedora 10.2.0-4.fc34) 10.2.0 |

Host Benchmarks
===============

It is possible to run timing tests on the host software using the
"batch mode" processing mechanism (described in
[Debugging.md](Debugging.md)). This is typically done by choosing a
large and complex G-Code file and timing how long it takes for the
host software to process it. For example:
```
time ~/klippy-env/bin/python ./klippy/klippy.py config/example-cartesian.cfg -i something_complex.gcode -o /dev/null -d out/klipper.dict
```
