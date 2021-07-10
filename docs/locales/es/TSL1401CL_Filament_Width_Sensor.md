This document describes Filament Width Sensor host module. Hardware used for
developing this host module is based on TSL1401CL linear sensor array but it can
work with any sensor array that has analog output. You can find designs at [thin
giverse.com](https://www.thingiverse.com/search?q=filament%20width%20sensor)

## How does it work?

Sensor generates analog output based on calculated filament width. Output
voltage always equals to detected filament width (Ex. 1.65v, 1.70v, 3.0v). Host
module monitors voltage changes and adjusts extrusion multiplier.

## Configuration


    [tsl1401cl_filament_width_sensor]
    pin: analog5
    # Analog input pin for sensor output on Ramps board
    
    default_nominal_filament_diameter: 1.75
    # This parameter is in millimeters (mm)
    
    max_difference: 0.2
    #  Maximum allowed filament diameter difference in millimeters (mm)
    #  If difference between nominal filament diameter and sensor output is more
    #  than +- max_difference, extrusion multiplier set back to %100
    
    measurement_delay 100
    #  The distance from sensor to the melting chamber/hot-end in millimeters (mm).
    #  The filament between the sensor and the hot-end will be treated as the default_nominal_filament_diameter.
    #  Host module works with FIFO logic. It keeps each sensor value and position in
    #  an array and POP them back in correct position.


Sensor readings done with 10 mm intervals by default. If necessary you are free
to change this setting by editing ***MEASUREMENT_INTERVAL_MM*** parameter in
**filament_width_sensor.py** file.

## Commands

**QUERY_FILAMENT_WIDTH** - Return the current measured filament width as result
**RESET_FILAMENT_WIDTH_SENSOR** – Clear all sensor readings. Can be used after
filament change. **DISABLE_FILAMENT_WIDTH_SENSOR** – Turn off the filament width
sensor and stop using it to do flow control **ENABLE_FILAMENT_WIDTH_SENSOR** -
Turn on the filament width sensor and start using it to do flow control
