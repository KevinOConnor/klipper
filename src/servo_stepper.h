#ifndef __SERVO_STEPPER_H
#define __SERVO_STEPPER_H

#include <stdint.h> // uint8_t

struct servo_stepper *servo_stepper_oid_lookup(uint8_t oid);
void servo_stepper_update(struct servo_stepper *ss, uint32_t position);

#endif // servo_stepper.h
