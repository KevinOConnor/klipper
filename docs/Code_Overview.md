This document describes the overall code layout and major code flow of
Klipper.

Directory Layout
================

The **src/** directory contains the C source for the micro-controller
code. The **src/atsam/**, **src/atsamd/**, **src/avr/**,
**src/linux/**, **src/lpc176x/**, **src/pru/**, and **src/stm32/**
directories contain architecture specific micro-controller code. The
**src/simulator/** contains code stubs that allow the micro-controller
to be test compiled on other architectures. The **src/generic/**
directory contains helper code that may be useful across different
architectures. The build arranges for includes of "board/somefile.h"
to first look in the current architecture directory (eg,
src/avr/somefile.h) and then in the generic directory (eg,
src/generic/somefile.h).

The **klippy/** directory contains the host software. Most of the host
software is written in Python, however the **klippy/chelper/**
directory contains some C code helpers. The **klippy/kinematics/**
directory contains the robot kinematics code. The **klippy/extras/**
directory contains the host code extensible "modules".

The **lib/** directory contains external 3rd-party library code that
is necessary to build some targets.

The **config/** directory contains example printer configuration
files.

The **scripts/** directory contains build-time scripts useful for
compiling the micro-controller code.

The **test/** directory contains automated test cases.

During compilation, the build may create an **out/** directory. This
contains temporary build time objects. The final micro-controller
object that is built is **out/klipper.elf.hex** on AVR and
**out/klipper.bin** on ARM.

Micro-controller code flow
==========================

Execution of the micro-controller code starts in architecture specific
code (eg, **src/avr/main.c**) which ultimately calls sched_main()
located in **src/sched.c**. The sched_main() code starts by running
all functions that have been tagged with the DECL_INIT() macro. It
then goes on to repeatedly run all functions tagged with the
DECL_TASK() macro.

One of the main task functions is command_dispatch() located in
**src/command.c**. This function is called from the board specific
input/output code (eg, **src/avr/serial.c**,
**src/generic/serial_irq.c**) and it runs the command functions
associated with the commands found in the input stream. Command
functions are declared using the DECL_COMMAND() macro (see the
[protocol](Protocol.md) document for more information).

Task, init, and command functions always run with interrupts enabled
(however, they can temporarily disable interrupts if needed). These
functions should never pause, delay, or do any work that lasts more
than a few micro-seconds. These functions schedule work at specific
times by scheduling timers.

Timer functions are scheduled by calling sched_add_timer() (located in
**src/sched.c**). The scheduler code will arrange for the given
function to be called at the requested clock time. Timer interrupts
are initially handled in an architecture specific interrupt handler
(eg, **src/avr/timer.c**) which calls sched_timer_dispatch() located
in **src/sched.c**. The timer interrupt leads to execution of schedule
timer functions. Timer functions always run with interrupts disabled.
The timer functions should always complete within a few micro-seconds.
At completion of the timer event, the function may choose to
reschedule itself.

In the event an error is detected the code can invoke shutdown() (a
macro which calls sched_shutdown() located in **src/sched.c**).
Invoking shutdown() causes all functions tagged with the
DECL_SHUTDOWN() macro to be run. Shutdown functions always run with
interrupts disabled.

Much of the functionality of the micro-controller involves working
with General-Purpose Input/Output pins (GPIO). In order to abstract
the low-level architecture specific code from the high-level task
code, all GPIO events are implemented in architecture specific
wrappers (eg, **src/avr/gpio.c**). The code is compiled with gcc's
"-flto -fwhole-program" optimization which does an excellent job of
inlining functions across compilation units, so most of these tiny
gpio functions are inlined into their callers, and there is no
run-time cost to using them.

Klippy code overview
====================

The host code (Klippy) is intended to run on a low-cost computer (such
as a Raspberry Pi) paired with the micro-controller. The code is
primarily written in Python, however it does use CFFI to implement
some functionality in C code.

Initial execution starts in **klippy/klippy.py**. This reads the
command-line arguments, opens the printer config file, instantiates
the main printer objects, and starts the serial connection. The main
execution of G-code commands is in the process_commands() method in
**klippy/gcode.py**. This code translates the G-code commands into
printer object calls, which frequently translate the actions to
commands to be executed on the micro-controller (as declared via the
DECL_COMMAND macro in the micro-controller code).

There are four threads in the Klippy host code. The main thread
handles incoming gcode commands. A second thread (which resides
entirely in the **klippy/chelper/serialqueue.c** C code) handles
low-level IO with the serial port. The third thread is used to process
response messages from the micro-controller in the Python code (see
**klippy/serialhdl.py**). The fourth thread writes debug messages to
the log (see **klippy/queuelogger.py**) so that the other threads
never block on log writes.

Code flow of a move command
===========================

A typical printer movement starts when a "G1" command is sent to the
Klippy host and it completes when the corresponding step pulses are
produced on the micro-controller. This section outlines the code flow
of a typical move command. The [kinematics](Kinematics.md) document
provides further information on the mechanics of moves.

* Processing for a move command starts in gcode.py. The goal of
  gcode.py is to translate G-code into internal calls. A G1 command
  will invoke cmd_G1() in klippy/extras/gcode_move.py. The
  gcode_move.py code handles changes in origin (eg, G92), changes in
  relative vs absolute positions (eg, G90), and unit changes (eg,
  F6000=100mm/s). The code path for a move is: `_process_data() ->
  _process_commands() -> cmd_G1()`. Ultimately the ToolHead class is
  invoked to execute the actual request: `cmd_G1() -> ToolHead.move()`

* The ToolHead class (in toolhead.py) handles "look-ahead" and tracks
  the timing of printing actions. The main codepath for a move is:
  `ToolHead.move() -> MoveQueue.add_move() -> MoveQueue.flush() ->
  Move.set_junction() -> ToolHead._process_moves()`.
  * ToolHead.move() creates a Move() object with the parameters of the
  move (in cartesian space and in units of seconds and millimeters).
  * The kinematics class is given the opportunity to audit each move
  (`ToolHead.move() -> kin.check_move()`). The kinematics classes are
  located in the klippy/kinematics/ directory. The check_move() code
  may raise an error if the move is not valid. If check_move()
  completes successfully then the underlying kinematics must be able
  to handle the move.
  * MoveQueue.add_move() places the move object on the "look-ahead"
  queue.
  * MoveQueue.flush() determines the start and end velocities of each
  move.
  * Move.set_junction() implements the "trapezoid generator" on a
  move. The "trapezoid generator" breaks every move into three parts:
  a constant acceleration phase, followed by a constant velocity
  phase, followed by a constant deceleration phase. Every move
  contains these three phases in this order, but some phases may be of
  zero duration.
  * When ToolHead._process_moves() is called, everything about the
  move is known - its start location, its end location, its
  acceleration, its start/cruising/end velocity, and distance traveled
  during acceleration/cruising/deceleration. All the information is
  stored in the Move() class and is in cartesian space in units of
  millimeters and seconds.

* Klipper uses an
  [iterative solver](https://en.wikipedia.org/wiki/Root-finding_algorithm)
  to generate the step times for each stepper. For efficiency reasons,
  the stepper pulse times are generated in C code. The moves are first
  placed on a "trapezoid motion queue": `ToolHead._process_moves() ->
  trapq_append()` (in klippy/chelper/trapq.c). The step times are then
  generated: `ToolHead._process_moves() ->
  ToolHead._update_move_time() -> MCU_Stepper.generate_steps() ->
  itersolve_generate_steps() -> itersolve_gen_steps_range()` (in
  klippy/chelper/itersolve.c). The goal of the iterative solver is to
  find step times given a function that calculates a stepper position
  from a time. This is done by repeatedly "guessing" various times
  until the stepper position formula returns the desired position of
  the next step on the stepper. The feedback produced from each guess
  is used to improve future guesses so that the process rapidly
  converges to the desired time. The kinematic stepper position
  formulas are located in the klippy/chelper/ directory (eg,
  kin_cart.c, kin_corexy.c, kin_delta.c, kin_extruder.c).

* Note that the extruder is handled in its own kinematic class:
  `ToolHead._process_moves() -> PrinterExtruder.move()`. Since
  the Move() class specifies the exact movement time and since step
  pulses are sent to the micro-controller with specific timing,
  stepper movements produced by the extruder class will be in sync
  with head movement even though the code is kept separate.

* After the iterative solver calculates the step times they are added
  to an array: `itersolve_gen_steps_range() -> stepcompress_append()`
  (in klippy/chelper/stepcompress.c). The array (struct
  stepcompress.queue) stores the corresponding micro-controller clock
  counter times for every step. Here the "micro-controller clock
  counter" value directly corresponds to the micro-controller's
  hardware counter - it is relative to when the micro-controller was
  last powered up.

* The next major step is to compress the steps: `stepcompress_flush()
  -> compress_bisect_add()` (in klippy/chelper/stepcompress.c). This
  code generates and encodes a series of micro-controller "queue_step"
  commands that correspond to the list of stepper step times built in
  the previous stage. These "queue_step" commands are then queued,
  prioritized, and sent to the micro-controller (via
  stepcompress.c:steppersync and serialqueue.c:serialqueue).

* Processing of the queue_step commands on the micro-controller starts
  in src/command.c which parses the command and calls
  `command_queue_step()`. The command_queue_step() code (in
  src/stepper.c) just appends the parameters of each queue_step
  command to a per stepper queue. Under normal operation the
  queue_step command is parsed and queued at least 100ms before the
  time of its first step. Finally, the generation of stepper events is
  done in `stepper_event()`. It's called from the hardware timer
  interrupt at the scheduled time of the first step. The
  stepper_event() code generates a step pulse and then reschedules
  itself to run at the time of the next step pulse for the given
  queue_step parameters. The parameters for each queue_step command
  are "interval", "count", and "add". At a high-level, stepper_event()
  runs the following, 'count' times: `do_step(); next_wake_time =
  last_wake_time + interval; interval += add;`

The above may seem like a lot of complexity to execute a movement.
However, the only really interesting parts are in the ToolHead and
kinematic classes. It's this part of the code which specifies the
movements and their timings. The remaining parts of the processing is
mostly just communication and plumbing.

Adding a host module
====================

The Klippy host code has a dynamic module loading capability. If a
config section named "[my_module]" is found in the printer config file
then the software will automatically attempt to load the python module
klippy/extras/my_module.py . This module system is the preferred
method for adding new functionality to Klipper.

The easiest way to add a new module is to use an existing module as a
reference - see **klippy/extras/servo.py** as an example.

The following may also be useful:
* Execution of the module starts in the module level `load_config()`
  function (for config sections of the form [my_module]) or in
  `load_config_prefix()` (for config sections of the form
  [my_module my_name]). This function is passed a "config" object and
  it must return a new "printer object" associated with the given
  config section.
* During the process of instantiating a new printer object, the config
  object can be used to read parameters from the given config
  section. This is done using `config.get()`, `config.getfloat()`,
  `config.getint()`, etc. methods. Be sure to read all values from the
  config during the construction of the printer object - if the user
  specifies a config parameter that is not read during this phase then
  it will be assumed it is a typo in the config and an error will be
  raised.
* Use the `config.get_printer()` method to obtain a reference to the
  main "printer" class. This "printer" class stores references to all
  the "printer objects" that have been instantiated. Use the
  `printer.lookup_object()` method to find references to other printer
  objects. Almost all functionality (even core kinematic modules) are
  encapsulated in one of these printer objects. Note, though, that
  when a new module is instantiated, not all other printer objects
  will have been instantiated. The "gcode" and "pins" modules will
  always be available, but for other modules it is a good idea to
  defer the lookup.
* Register event handlers using the `printer.register_event_handler()`
  method if the code needs to be called during "events" raised by
  other printer objects. Each event name is a string, and by
  convention it is the name of the main source module that raises the
  event along with a short name for the action that is occurring (eg,
  "klippy:connect"). The parameters passed to each event handler are
  specific to the given event (as are exception handling and execution
  context). Two common startup events are:
  * klippy:connect - This event is generated after all printer objects
    are instantiated. It is commonly used to lookup other printer
    objects, to verify config settings, and to perform an initial
    "handshake" with printer hardware.
  * klippy:ready - This event is generated after all connect handlers
    have completed successfully. It indicates the printer is
    transitioning to a state ready to handle normal operations. Do not
    raise an error in this callback.
* If there is an error in the user's config, be sure to raise it
  during the `load_config()` or "connect event" phases. Use either
  `raise config.error("my error")` or `raise printer.config_error("my
  error")` to report the error.
* Use the "pins" module to configure a pin on a micro-controller. This
  is typically done with something similar to
  `printer.lookup_object("pins").setup_pin("pwm",
  config.get("my_pin"))`. The returned object can then be commanded at
  run-time.
* If the module needs access to system timing or external file
  descriptors then use `printer.get_reactor()` to obtain access to the
  global "event reactor" class. This reactor class allows one to
  schedule timers, wait for input on file descriptors, and to "sleep"
  the host code.
* Do not use global variables. All state should be stored in the
  printer object returned from the `load_config()` function. This is
  important as otherwise the RESTART command may not perform as
  expected. Also, for similar reasons, if any external files (or
  sockets) are opened then be sure to register a "klippy:disconnect"
  event handler and close them from that callback.
* Avoid accessing the internal member variables (or calling methods
  that start with an underscore) of other printer objects. Observing
  this convention makes it easier to manage future changes.
* If submitting the module for inclusion in the main Klipper code, be
  sure to place a copyright notice at the top of the module. See the
  existing modules for the preferred format.

Adding new kinematics
=====================

This section provides some tips on adding support to Klipper for
additional types of printer kinematics. This type of activity requires
excellent understanding of the math formulas for the target
kinematics. It also requires software development skills - though one
should only need to update the host software.

Useful steps:
1. Start by studying the
   "[code flow of a move](#code-flow-of-a-move-command)" section and
   the [Kinematics document](Kinematics.md).
2. Review the existing kinematic classes in the klippy/kinematics/
   directory. The kinematic classes are tasked with converting a move
   in cartesian coordinates to the movement on each stepper. One
   should be able to copy one of these files as a starting point.
3. Implement the C stepper kinematic position functions for each
   stepper if they are not already available (see kin_cart.c,
   kin_corexy.c, and kin_delta.c in klippy/chelper/). The function
   should call `move_get_coord()` to convert a given move time (in
   seconds) to a cartesian coordinate (in millimeters), and then
   calculate the desired stepper position (in millimeters) from that
   cartesian coordinate.
4. Implement the `calc_position()` method in the new kinematics class.
   This method calculates the position of the toolhead in cartesian
   coordinates from the position of each stepper. It does not need to
   be efficient as it is typically only called during homing and
   probing operations.
5. Other methods. Implement the `check_move()`, `get_status()`,
   `get_steppers()`, `home()`, and `set_position()` methods. These
   functions are typically used to provide kinematic specific checks.
   However, at the start of development one can use boiler-plate code
   here.
6. Implement test cases. Create a g-code file with a series of moves
   that can test important cases for the given kinematics. Follow the
   [debugging documentation](Debugging.md) to convert this g-code file
   to micro-controller commands. This is useful to exercise corner
   cases and to check for regressions.

Porting to a new micro-controller
=================================

This section provides some tips on porting Klipper's micro-controller
code to a new architecture. This type of activity requires good
knowledge of embedded development and hands-on access to the target
micro-controller.

Useful steps:
1. Start by identifying any 3rd party libraries that will be used
   during the port. Common examples include "CMSIS" wrappers and
   manufacturer "HAL" libraries. All 3rd party code needs to be GNU
   GPLv3 compatible. The 3rd party code should be committed to the
   Klipper lib/ directory. Update the lib/README file with information
   on where and when the library was obtained. It is preferable to
   copy the code into the Klipper repository unchanged, but if any
   changes are required then those changes should be listed explicitly
   in the lib/README file.
2. Create a new architecture sub-directory in the src/ directory and
   add initial Kconfig and Makefile support. Use the existing
   architectures as a guide. The src/simulator provides a basic
   example of a minimum starting point.
3. The first main coding task is to bring up communication support to
   the target board. This is the most difficult step in a new port.
   Once basic communication is working, the remaining steps tend to be
   much easier. It is typical to use an RS-232 style serial port
   during initial development as these types of hardware devices are
   generally easier to enable and control. During this phase, make
   liberal use of helper code from the src/generic/ directory (check
   how src/simulator/Makefile includes the generic C code into the
   build). It is also necessary to define timer_read_time() (which
   returns the current system clock) in this phase, but it is not
   necessary to fully support timer irq handling.
4. Get familiar with the the console.py tool (as described in the
   [debugging document](Debugging.md)) and verify connectivity to the
   micro-controller with it. This tool translates the low-level
   micro-controller communication protocol to a human readable form.
5. Add support for timer dispatch from hardware interrupts. See
   Klipper
   [commit 970831ee](https://github.com/KevinOConnor/klipper/commit/970831ee0d3b91897196e92270d98b2a3067427f)
   as an example of steps 1-5 done for the LPC176x architecture.
6. Bring up basic GPIO input and output support. See Klipper
   [commit c78b9076](https://github.com/KevinOConnor/klipper/commit/c78b90767f19c9e8510c3155b89fb7ad64ca3c54)
   as an example of this.
7. Bring up additional peripherals - for example see Klipper commit
   [65613aed](https://github.com/KevinOConnor/klipper/commit/65613aeddfb9ef86905cb1dade9e773a02ef3c27),
   [c812a40a](https://github.com/KevinOConnor/klipper/commit/c812a40a3782415e454b04bf7bd2158a6f0ec8b5),
   and
   [c381d03a](https://github.com/KevinOConnor/klipper/commit/c381d03aad5c3ee761169b7c7bced519cc14da29).
8. Create a sample Klipper config file in the config/ directory. Test
   the micro-controller with the main klippy.py program.
9. Consider adding build test cases in the test/ directory.

Coordinate Systems
==================

Internally, Klipper primarily tracks the position of the toolhead in
cartesian coordinates that are relative to the coordinate system
specified in the config file. That is, most of the Klipper code will
never experience a change in coordinate systems. If the user makes a
request to change the origin (eg, a `G92` command) then that effect is
obtained by translating future commands to the primary coordinate
system.

However, in some cases it is useful to obtain the toolhead position in
some other coordinate system and Klipper has several tools to
facilitate that. This can be seen by running the GET_POSITION
command. For example:

```
Send: GET_POSITION
Recv: // mcu: stepper_a:-2060 stepper_b:-1169 stepper_c:-1613
Recv: // stepper: stepper_a:457.254159 stepper_b:466.085669 stepper_c:465.382132
Recv: // kinematic: X:8.339144 Y:-3.131558 Z:233.347121
Recv: // toolhead: X:8.338078 Y:-3.123175 Z:233.347878 E:0.000000
Recv: // gcode: X:8.338078 Y:-3.123175 Z:233.347878 E:0.000000
Recv: // gcode base: X:0.000000 Y:0.000000 Z:0.000000 E:0.000000
Recv: // gcode homing: X:0.000000 Y:0.000000 Z:0.000000
```

The "mcu" position (`stepper.get_mcu_position()` in the code) is the
total number of steps the micro-controller has issued in a positive
direction minus the number of steps issued in a negative direction
since the micro-controller was last reset. If the robot is in motion
when the query is issued then the reported value includes moves
buffered on the micro-controller, but does not include moves on the
look-ahead queue.

The "stepper" position (`stepper.get_commanded_position()`) is the
position of the given stepper as tracked by the kinematics code. This
generally corresponds to the position (in mm) of the carriage along
its rail, relative to the position_endstop specified in the config
file. (Some kinematics track stepper positions in radians instead of
millimeters.) If the robot is in motion when the query is issued then
the reported value includes moves buffered on the micro-controller,
but does not include moves on the look-ahead queue. One may use the
`toolhead.flush_step_generation()` or `toolhead.wait_moves()` calls to
fully flush the look-ahead and step generation code.

The "kinematic" position (`kin.calc_position()`) is the cartesian
position of the toolhead as derived from "stepper" positions and is
relative to the coordinate system specified in the config file. This
may differ from the requested cartesian position due to the
granularity of the stepper motors. If the robot is in motion when the
"stepper" positions are taken then the reported value includes moves
buffered on the micro-controller, but does not include moves on the
look-ahead queue. One may use the `toolhead.flush_step_generation()`
or `toolhead.wait_moves()` calls to fully flush the look-ahead and
step generation code.

The "toolhead" position (`toolhead.get_position()`) is the last
requested position of the toolhead in cartesian coordinates relative
to the coordinate system specified in the config file. If the robot is
in motion when the query is issued then the reported value includes
all requested moves (even those in buffers waiting to be issued to the
stepper motor drivers).

The "gcode" position is the last requested position from a `G1` (or
`G0`) command in cartesian coordinates relative to the coordinate
system specified in the config file. This may differ from the
"toolhead" position if a g-code transformation (eg, bed_mesh,
bed_tilt, skew_correction) is in effect. This may differ from the
actual coordinates specified in the last `G1` command if the g-code
origin has been changed (eg, `G92`, `SET_GCODE_OFFSET`, `M221`). The
`M114` command (`gcode_move.get_status()['gcode_position']`) will
report the last g-code position relative to the current g-code
coordinate system.

The "gcode base" is the location of the g-code origin in cartesian
coordinates relative to the coordinate system specified in the config
file. Commands such as `G92`, `SET_GCODE_OFFSET`, and `M221` alter
this value.

The "gcode homing" is the location to use for the g-code origin (in
cartesian coordinates relative to the coordinate system specified in
the config file) after a `G28` home command. The `SET_GCODE_OFFSET`
command can alter this value.

Time
====

Fundamental to the operation of Klipper is the handling of clocks,
times, and timestamps. Klipper executes actions on the printer by
scheduling events to occur in the near future. For example, to turn on
a fan, the code might schedule a change to a GPIO pin in a 100ms. It
is rare for the code to attempt to take an instantaneous action. Thus,
the handling of time within Klipper is critical to correct operation.

There are three types of times tracked internally in the Klipper host
software:
* System time. The system time uses the system's monotonic clock - it
  is a floating point number stored as seconds and it is (generally)
  relative to when the host computer was last started. System times
  have limited use in the software - they are primarily used when
  interacting with the operating system. Within the host code, system
  times are frequently stored in variables named *eventtime* or
  *curtime*.
* Print time. The print time is synchronized to the main
  micro-controller clock (the micro-controller defined in the "[mcu]"
  config section). It is a floating point number stored as seconds and
  is relative to when the main mcu was last restarted. It is possible
  to convert from a "print time" to the main micro-controller's
  hardware clock by multiplying the print time by the mcu's statically
  configured frequency rate. The high-level host code uses print times
  to calculate almost all physical actions (eg, head movement, heater
  changes, etc.). Within the host code, print times are generally
  stored in variables named *print_time* or *move_time*.
* MCU clock. This is the hardware clock counter on each
  micro-controller. It is stored as an integer and its update rate is
  relative to the frequency of the given micro-controller. The host
  software translates its internal times to clocks before transmission
  to the mcu. The mcu code only ever tracks time in clock
  ticks. Within the host code, clock values are tracked as 64bit
  integers, while the mcu code uses 32bit integers. Within the host
  code, clocks are generally stored in variables with names containing
  *clock* or *ticks*.

Conversion between the different time formats is primarily implemented
in the **klippy/clocksync.py** code.

Some things to be aware of when reviewing the code:
* 32bit and 64bit clocks: To reduce bandwidth and to improve
  micro-controller efficiency, clocks on the micro-controller are
  tracked as 32bit integers. When comparing two clocks in the mcu
  code, the `timer_is_before()` function must always be used to ensure
  integer rollovers are handled properly. The host software converts
  32bit clocks to 64bit clocks by appending the high-order bits from
  the last mcu timestamp it has received - no message from the mcu is
  ever more than 2^31 clock ticks in the future or past so this
  conversion is never ambiguous. The host converts from 64bit clocks
  to 32bit clocks by simply truncating the high-order bits. To ensure
  there is no ambiguity in this conversion, the
  **klippy/chelper/serialqueue.c** code will buffer messages until
  they are within 2^31 clock ticks of their target time.
* Multiple micro-controllers: The host software supports using
  multiple micro-controllers on a single printer. In this case, the
  "MCU clock" of each micro-controller is tracked separately. The
  clocksync.py code handles clock drift between micro-controllers by
  modifying the way it converts from "print time" to "MCU clock". On
  secondary mcus, the mcu frequency that is used in this conversion is
  regularly updated to account for measured drift.
