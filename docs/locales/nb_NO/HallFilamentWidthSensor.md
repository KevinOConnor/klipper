This document describes Filament Width Sensor host module. Hardware used for
developing this host module is based on Two Hall liniar sensors (ss49e for
example). Sensors in the body are located opposite sides. Principle of operation
: two hall sensors work in differential mode, temperature drift same for sensor.
Special temperature compensation not needed. You can find designs at
[thingiverse.com](https://www.thingiverse.com/thing:4138933)

[Hall based filament width sensor assembly
video](https://www.youtube.com/watch?v=TDO9tME8vp4)

## How does it work?

Sensor generates two analog output based on calculated filament width. Sum of
output voltage always equals to detected filament width . Host module monitors
voltage changes and adjusts extrusion multiplier. I use aux2 connector on ramps-
like board analog11 and analog12 pins. You can use different pins and differenr
boards

## Configuration


    [hall_filament_width_sensor]
    
    adc1: analog11
    adc2: analog12
    # adc1 and adc2 channels select own pins Analog input pins on 3d printer board
    # Sensor power supply can be 3.3v or 5v
    
    Cal_dia1: 1.50 # Reference diameter point 1 (mm)
    Cal_dia2: 2.00 # Reference diameter point 2 (mm)
    
    # The measurement principle provides for two-point calibration
    # In calibration process you must use rods of known diameter
    # I use drill rods as the base diameter.
    # nominal filament diameter must be between Cal_dia1 and Cal_dia2
    # Your size may differ from the indicated ones, for example 2.05
    
    Raw_dia1:10630 # Raw sensor value for reference point 1
    Raw_dia2:8300  # Raw sensor value for reference point 2
    
    # Raw value of sensor in units
    # can be readed by command QUERY_RAW_FILAMENT_WIDTH
    
    default_nominal_filament_diameter: 1.75 # This parameter is in millimeters (mm)
    
    max_difference: 0.15
    # Maximum allowed filament diameter difference in millimeters (mm)
    # If difference between nominal filament diameter and sensor output is more
    # than +- max_difference, extrusion multiplier set back to %100
    
    measurement_delay: 70
    # The distance from sensor to the melting chamber/hot-end in millimeters (mm).
    # The filament between the sensor and the hot-end will be treated as the default_nominal_filament_diameter.
    # Host module works with FIFO logic. It keeps each sensor value and position in
    # an array and POP them back in correct position.
    
    #enable:False
    # Sensor enabled or disabled after power on. Disabled by default
    
    # measurement_interval:10
    # Sensor readings done with 10 mm intervals by default. If necessary you are free to change this setting
    
    #logging: False
    #  Out diameter to terminal and klipper.log
    #  can be turn on|of by command
    
    #Virtual filament_switch_sensor suppurt. Create sensor named hall_filament_width_sensor.
    #
    #min_diameter:1.0
    #Minimal diameter for trigger virtual filament_switch_sensor.
    #use_current_dia_while_delay: False
    #   Use the current diameter instead of the nominal diamenter while the measurement delay has not run through.
    #
    #Values from filament_switch_sensor. See the "filament_switch_sensor" section for information on these parameters.
    #
    #pause_on_runout: True
    #runout_gcode:
    #insert_gcode:
    #event_delay: 3.0
    #pause_delay: 0.5


## Commands

**QUERY_FILAMENT_WIDTH** - Return the current measured filament width as result

**RESET_FILAMENT_WIDTH_SENSOR** вЂ“ Clear all sensor readings. Can be used after
filament change.

**DISABLE_FILAMENT_WIDTH_SENSOR** вЂ“ Turn off the filament width sensor and
stop using it to do flow control

**ENABLE_FILAMENT_WIDTH_SENSOR** - Turn on the filament width sensor and start
using it to do flow control

**QUERY_RAW_FILAMENT_WIDTH** Return the current ADC channel values and RAW
sensor value for calibration points

**ENABLE_FILAMENT_WIDTH_LOG** - Turn on diameter logging

**DISABLE_FILAMENT_WIDTH_LOG** - Turn off diameter logging

## Menu variables

**hall_filament_width_sensor.Diameter** current measured filament width in mm

**hall_filament_width_sensor.Raw** current raw measured filament width in units

**hall_filament_width_sensor.is_active** Sensor on or off

## Template for menu variables


    [menu __main __filament __width_current]
    type: command
    enable: {'hall_filament_width_sensor' in printer}
    name: Dia: {'%.2F' % printer.hall_filament_width_sensor.Diameter}
    index: 0
    
    [menu __main __filament __raw_width_current]
    type: command
    enable: {'hall_filament_width_sensor' in printer}
    name: Raw: {'%4.0F' % printer.hall_filament_width_sensor.Raw}
    index: 1


## Calibration procedure

Insert first calibration rod (1.5 mm size) get first raw sensor value

To get raw sensor value you can use menu item or **QUERY_RAW_FILAMENT_WIDTH**
command in terminal

Insert second calibration rod (2.0 mm size) get second raw sensor value

Save raw values in config

## How to enable sensor

After power on by default sensor disabled. Enable sensor in start g-code by
command **ENABLE_FILAMENT_WIDTH_SENSOR** or change enable parameter in config

## Logging

After power on by default diameter Logging disabled. Data to log added on every
measurement interval (10 mm by default)
