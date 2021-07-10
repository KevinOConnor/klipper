This document contains guidelines for contributing an example Klipper
configuration to the Klipper github repository (located in the [config
directory](../config/)).

Note that the [Klipper Community Discourse
server](https://community.klipper3d.org) is also a useful resource for finding
and sharing config files.

# Guidelines

1. Select the appropriate config filename prefix.
   1. The `printer` prefix is used for stock printers sold by a mainstream
manufacturer.
   2. The `generic` prefix is used for a 3d printer board that may be used in many
different types of printers.
   3. The `kit` prefix is for 3d printers that are assembled according to a widely
used specification. These "kit" printers are generally distinct from normal
"printers" in that they are not sold by a manufacturer.
   4. The `sample` prefix is used for config "snippets" that one may copy-and-paste
into the main config file.
   5. The `example` prefix is used to describe printer kinematics. This type of
config is typically only added along with code for a new type of printer
kinematics.

2. Use the appropriate filename suffix. The `printer` config files must end in a
year followed by `.cfg` (eg, `-2019.cfg`). In this case, the year is an
approximate year the given printer was sold. All example configuration files
must end in `.cfg`.
3. Klipper must be able to start `printer`, `generic`, and `kit` example config
file without error. These config files should be added to the
[test/klippy/printers.test](../test/klippy/printers.test) regression test case.
Add new config files to that test case in the appropriate section and in
alphabetical order within that section.
4. The example configuration should be for the "stock" configuration of the
printer. (There are too many "customized" configurations to track in the main
Klipper repository.) Similarly, we only add example config files for printers,
kits, and boards that have mainstream popularity (eg, there should be at least
a 100 of them in active use). Consider using the [Klipper Community Discourse
server](https://community.klipper3d.org) for other configs.
5. Only specify those devices present on the given printer or board. Do not
specify settings specific to your particular setup.
   1. For `generic` config files, only those devices on the mainboard should be
described. For example, it would not make sense to add a display config section
to a "generic" config as there is no way to know if the board will be
attached to that type of display. If the board has a specific hardware port to
facilitate an optional peripheral (eg, a bltouch port) then one can add a
"commented out" config section for the given device.
   2. Do not specify `pressure_advance` in an example config, as that value is
specific to the filament, not the printer hardware. Similarly, do not specify
`max_extrude_only_velocity` nor `max_extrude_only_accel` settings.
   3. Do not specify a config section containing a host path or host hardware. For
example, do not specify `[virtual_sdcard]` nor `[temperature_host]` config
sections.
   4. Only define macros that utilize functionality specific to the given printer or
to define g-codes that are commonly emitted by slicers configured for the given
printer.

6. Where possible, it is best to use the same wording, phrasing, indentation, and
section ordering as the existing config files.
   1. The top of each config file should list the type of micro-controller the user
should select during "make menuconfig". It should also have a reference to
"docs/Config_Reference.md".
   2. Do not copy the field documentation into the example config files. (Doing so
creates a maintenance burden as an update to the documentation would then
require changing it in many places.)
   3. Example config files should not contain a "SAVE_CONFIG" section. If
necessary, copy the relevant fields from the SAVE_CONFIG section to the
appropriate section in the main config area.
   4. Use `field: value` syntax instead of `field=value`.
   5. When adding an extruder `rotation_distance` it is preferable to specify a
`gear_ratio` if the extruder has a gearing mechanism. We expect the
rotation_distance in the example configs to correlate with the circumference of
the hobbed gear in the extruder - it is normally in the range of 20 to 35mm.
When specifying a `gear_ratio` it is preferable to specify the actual gears on
the mechanism (eg, prefer `gear_ratio: 80:20` over `gear_ratio: 4:1`).
   6. Avoid defining field values that are set to their default value. For example,
one should not specify `min_extrude_temp: 170` as that is already the default
value.
   7. Where possible, lines should not exceed 80 columns.
   8. Avoid adding attribution or revision messages to the config files. (For
example, avoid adding lines like "this file was created by ...".) Place
attribution and change history in the git commit message.

7. Do not use any deprecated features in the example config file. The
`step_distance` and `pin_map` parameters are deprecated and should not be in
any example config file.
8. Do not disable a default safety system in an example config file. For example,
a config should not specify a custom `max_extrude_cross_section`. Do not enable
debugging features. For example there should not be a `force_move` config
section.

Example config files are submitted by creating a github "pull request". Please
also follow the directions in the [contributing document](CONTRIBUTING.md).
