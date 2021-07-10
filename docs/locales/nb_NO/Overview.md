Welcome to the Klipper documentation. If new to Klipper, start with the
[features](Features.md) and [installation](Installation.md) documents.

# Overview information

- [Features](Features.md): A high-level list of features in Klipper.
- [FAQ](FAQ.md): Frequently asked questions.
- [Releases](Releases.md): The history of Klipper releases.
- [Config changes](Config_Changes.md): Recent software changes that may require
users to update their printer config file.
- [Contact](Contact.md): Information on bug reporting and general communication
with the Klipper developers.

# Configuration and Tuning Guides

- [Installation](Installation.md): Guide to installing Klipper.
- [Config Reference](Config_Reference.md): Description of config parameters.
  - [Rotation Distance](Rotation_Distance.md): Calculating the rotation_distance
stepper parameter.

- [Config checks](Config_checks.md): Verify basic pin settings in the config
file.
- [Bed level](Bed_Level.md): Information on "bed leveling" in Klipper.
  - [Delta calibrate](Delta_Calibrate.md): Calibration of delta kinematics.
  - [Probe calibrate](Probe_Calibrate.md): Calibration of automatic Z probes.
  - [BL-Touch](BLTouch.md): Configure a "BL-Touch" Z probe.
  - [Manual level](Manual_Level.md): Calibration of Z endstops (and similar).
  - [Bed Mesh](Bed_Mesh.md): Bed height correction based on XY locations.
  - [Endstop phase](Endstop_Phase.md): Stepper assisted Z endstop positioning.

- [Resonance compensation](Resonance_Compensation.md): A tool to reduce ringing
in prints.
  - [Measuring resonances](Measuring_Resonances.md): Information on using adxl345
accelerometer hardware to measure resonance.

- [Pressure advance](Pressure_Advance.md): Calibrate extruder pressure.
- [Slicers](Slicers.md): Configure "slicer" software for Klipper.
- [Command Templates](Command_Templates.md): G-Code macros and conditional
evaluation.
- [TMC Drivers](TMC_Drivers.md): Using Trinamic stepper motor drivers with
Klipper.
- [Skew correction](skew_correction.md): Adjustments for axes not perfectly
square.
- [PWM tools](Using_PWM_Tools.md): Guide on how to use PWM controlled tools such
as lasers or spindles.
- [G-Codes](G-Codes.md): Information on commands supported by Klipper.

# Developer Documentation

- [Code overview](Code_Overview.md): Developers should read this first.
- [Kinematics](Kinematics.md): Technical details on how Klipper implements
motion.
- [Protocol](Protocol.md): Information on the low-level messaging protocol
between host and micro-controller.
- [API Server](API_Server.md): Information on Klipper's command and control API.
- [MCU commands](MCU_Commands.md): A description of low-level commands
implemented in the micro-controller software.
- [CAN bus protocol](CANBUS_protocol.md): Klipper CAN bus message format.
- [Debugging](Debugging.md): Information on how to test and debug Klipper.
- [Benchmarks](Benchmarks.md): Information on the Klipper benchmark method.
- [Contributing](CONTRIBUTING.md): Information on how to submit improvements to
Klipper.
- [Packaging](Packaging.md): Information on building OS packages.

# Device Specific Documents

- [Example configs](Example_Configs.md): Information on adding an example config
file to Klipper.
- [SDCard Updates](SDCard_Updates.md): Flash a micro-controller by copying a
binary to an sdcard in the micro-controller.
- [Raspberry Pi as Micro-controller](RPi_microcontroller.md): Details for
controlling devices wired to the GPIO pins of a Raspberry Pi.
- [Beaglebone](beaglebone.md): Details for running Klipper on the Beaglebone PRU.
- [Bootloaders](Bootloaders.md): Developer information on micro-controller
flashing.
- [CAN bus](CANBUS.md): Information on using CAN bus with Klipper.
- [TSL1401CL filament width sensor](TSL1401CL_Filament_Width_Sensor.md)
- [Hall filament width sensor](HallFilamentWidthSensor.md)
