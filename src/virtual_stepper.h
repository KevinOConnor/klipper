#ifndef __VIRTUAL_STEPPER_H
#define __VIRTUAL_STEPPER_H

#include <stdint.h> // uint8_t

struct virtual_stepper *virtual_stepper_oid_lookup(uint8_t oid);
uint32_t virtual_stepper_get_position(struct virtual_stepper *s);

#endif // stepper.h
