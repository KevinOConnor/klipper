Many of today's popular controller boards ship with a bootloader capable of
updating firmware via SD Card. While this is convenient in many circumstances,
these bootloaders typically provide no other way to update firmware. This can be
a nuisance if your board is mounted in a location that is difficult to access or
if you need to update firmware often. After Klipper has been initially flashed
to a controller it is possible to transfer new firmware to the SD Card and
initiate the flashing procedure via ssh.

# Typical Upgrade Procedure

The procedure for updating MCU firmware using the SD Card is similar to that of
other methods. Instead of using `make flash` it is necessary to run a helper
script, `flash-sdcard.sh`. Updating a BigTreeTech SKR 1.3 might look like the
following:

```
sudo service klipper stop
cd ~/klipper
git pull
make clean
make menuconfig
make
./scripts/flash-sdcard.sh /dev/ttyACM0 btt-skr-v1.3
sudo service klipper start
```

It is up to the user to determine the device location and board name. If a user
needs to flash multiple boards, `flash-sdcard.sh` (or `make flash` if
appropriate) should be run for each board prior to restarting the Klipper
service.

Supported boards can be listed with the following command:

```
./scripts/flash-sdcard.sh -l
```

If you do not see your board listed it may be necessary to add a new board
definition as [described below](#board-definitions).

# Advanced Usage

The above commands assume that your MCU connects at the default baud rate of
250000 and the firmware is located at `~/klipper/out/klipper.bin`. The
`flash- sdcard.sh` script provides options for changing these defaults. All
options can be viewed by the help screen:

```
./scripts/flash-sdcard.sh -h
SD Card upload utility for Klipper

usage: flash_sdcard.sh [-h] [-l] [-b <baud>] [-f <firmware>]
                       <device> <board>

positional arguments:
  <device>        device serial port
  <board>         board type

optional arguments:
  -h              show this message
  -l              list available boards
  -b <baud>       serial baud rate (default is 250000)
  -f <firmware>   path to klipper.bin
```

If your board is flashed with firmware that connects at a custom baud rate it is
possible to upgrade by specifying the `-b` option:

```
./scripts/flash-sdcard.sh -b 115200 /dev/ttyAMA0 btt-skr-v1.3
```

If you wish to flash a build of Klipper located somewhere other than the default
location it can be done by specifying the `-f` option:

```
./scripts/flash-sdcard.sh -f ~/downloads/klipper.bin /dev/ttyAMA0 btt-skr-v1.3
```

Note that when upgrading a MKS Robin E3 it is not necessary to manually run
`update_mks_robin.py` and supply the resulting binary to `flash-sdcard.sh`. This
procedure is automated during the upload process.

# Caveats

- As mentioned in the introduction, this method only works for upgrading
firmware. The initial flashing procedure must be done manually per the
instructions that apply to your controller board.
- While it is possible to flash a build that changes the Serial Baud or
connection interface (ie: from USB to UART), verification will always fail as
the script will be unable to reconnect to the MCU to verify the current
version.
- Only boards that use SPI for SD Card communication are supported. Boards that
use SDIO, such as the Flymaker Flyboard and MKS Robin Nano V1/V2, will not
work.

# Board Definitions

Most common boards should be available, however it is possible to add a new
board definition if necessary. Board definitions are located in
`~/klipper/scripts/spi_flash/board_defs.py`. The definitions are stored in
dictionary, for example:

```python
BOARD_DEFS = {
    'generic-lpc1768': {
        'mcu': "lpc1768",
        'spi_bus': "ssp1",
        "cs_pin": "P0.6"
    },
    ...<further definitions>
}
```

The following fields may be specified:

- `mcu`: The mcu type. This can be retrevied after configuring the build via
`make menuconfig` by running `cat .config | grep CONFIG_MCU`. This field is
required.
- `spi_bus`: The SPI bus connected to the SD Card. This should be retreived from
the board's schematic. This field is required.
- `cs_pin`: The Chip Select Pin connected to the SD Card. This should be
retreived from the board schematic. This field is required.
- `firmware_path`: The path on the SD Card where firmware should be transferred.
The default is `firmware.bin`.
- `current_firmware_path` The path on the SD Card where the renamed firmware file
is located after a successful flash. The default is `firmware.cur`.

If software SPI is required the `spi_bus` field should be set to `swspi` and the
following additional field should be specified:

- `spi_pins`: This should be 3 comma separated pins that are connected to the SD
Card in the format of `miso,mosi,sclk`.

It should be exceedingly rare that Software SPI is necessary, typically only
boards with design errors will require it. The `btt-skr-pro` board definition
provides an example.

Prior to creating a new board definition one should check to see if an existing
board definition meets the criteria necessary for the new board. If this is the
case, a `BOARD_ALIAS` may be specified. For example, the following alias may be
added to specify `my-new-board` as an alias for `generic-lpc1768`:

```python
BOARD_ALIASES = {
    ...<previous aliases>,
    'my-new-board': BOARD_DEFS['generic-lpc1768'],
}
```

If you need a new board definition and you are uncomfortable with the procedure
outlined above it is recommended that you request one in the [Klipper Community
Discord](Contact.md#discord).
