#include "autoconf.h" // CONFIG_MACH_atmega644p
#include "gpio.h" // gpio_out_write

#define STEPS 16
#define DUTY_CYCLE (256/STEPS)

ISR(TIMER0_OVF_vect)
{
	if (OCR0B + DUTY_CYCLE >= 255) {
		OCR0B = 255;
		TIMSK0 &= ~(1 << TOIE0);
	} else {
		OCR0B += DUTY_CYCLE;
	}
}

void timer0_restart(uint8_t val)
{
	TCNT0 = 0;
	OCR0B = DUTY_CYCLE - 1;
	// Fast Mode + Inverted mode
	if (val) {
		// HIGH
		TCCR0A = (1 << WGM01) | (1 << WGM00) | (1 << COM0B1);
	} else {
		// LOW
		TCCR0A = (1 << WGM01) | (1 << WGM00) | (1 << COM0B1) | (1 << COM0B0);
	}
	// Pre-scaler to 1, or 62.5kHz
	TCCR0B = (1 << CS00);
	// Enable TIMER0_OVF_vect interrupt
	TIMSK0 |= (1 << TOIE0);
}

void timer0_stop()
{
	TCCR0A = 0;
	TIMSK0 &= ~(1 << TOIE0);
}
