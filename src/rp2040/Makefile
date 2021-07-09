# Additional RP2040 build rules

# Setup the toolchain
CROSS_PREFIX=arm-none-eabi-

dirs-y += src/rp2040 src/generic lib/rp2040/elf2uf2

CFLAGS += -mcpu=cortex-m0plus -mthumb -Ilib/cmsis-core
CFLAGS += -Ilib/rp2040 -Ilib/rp2040/cmsis_include

CFLAGS_klipper.elf += --specs=nano.specs --specs=nosys.specs
CFLAGS_klipper.elf += -T $(OUT)src/rp2040/rp2040_link.ld
$(OUT)klipper.elf: $(OUT)stage2.o $(OUT)src/rp2040/rp2040_link.ld

# Add source files
src-y += rp2040/main.c rp2040/gpio.c rp2040/adc.c generic/crc16_ccitt.c
src-y += generic/armcm_boot.c generic/armcm_irq.c generic/armcm_reset.c
src-y += generic/timer_irq.c rp2040/timer.c rp2040/bootrom.c
src-$(CONFIG_USBSERIAL) += rp2040/usbserial.c generic/usb_cdc.c
src-$(CONFIG_USBSERIAL) += rp2040/chipid.c
src-$(CONFIG_SERIAL) += rp2040/serial.c generic/serial_irq.c

# rp2040 stage2 building
$(OUT)stage2.o: lib/rp2040/boot_stage2/boot2_w25q080.S
	@echo "  Building rp2040 stage2 $@"
	$(Q)$(CC) $(CFLAGS) -Ilib/rp2040/boot_stage2 -Ilib/rp2040/boot_stage2/asminclude -DPICO_FLASH_SPI_CLKDIV=2 -c $< -o $(OUT)stage2raw1.o
	$(Q)$(LD) $(OUT)stage2raw1.o --script=lib/rp2040/boot_stage2/boot_stage2.ld -o $(OUT)stage2raw.o
	$(Q)$(OBJCOPY) -O binary $(OUT)stage2raw.o $(OUT)stage2raw.bin
	$(Q)lib/rp2040/boot_stage2/pad_checksum -s 0xffffffff $(OUT)stage2raw.bin $(OUT)stage2.S
	$(Q)$(CC) $(CFLAGS) -c $(OUT)stage2.S -o $(OUT)stage2.o
OBJS_klipper.elf += $(OUT)stage2.o

# Binary output file rules
target-y += $(OUT)klipper.uf2

$(OUT)lib/rp2040/elf2uf2/elf2uf2: lib/rp2040/elf2uf2/main.cpp
	@echo "  Building $@"
	$(Q)g++ -g -O -Ilib/rp2040 $< -o $@

$(OUT)klipper.uf2: $(OUT)klipper.elf $(OUT)lib/rp2040/elf2uf2/elf2uf2
	@echo "  Creating uf2 file $@"
	$(Q)$(OUT)lib/rp2040/elf2uf2/elf2uf2 $< $@

# Flash rules
flash: $(OUT)klipper.uf2
	@echo "Error: Flashing not supported on rp2040."
	@echo "Place target board in bootloader mode (hold bootsel button"
	@echo "during powerup), mount the device as a usb drive, and copy"
	@echo "$< to the device."
	@exit -1
