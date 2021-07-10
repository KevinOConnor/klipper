#ifndef __DRIVER_A4954_H
#define __DRIVER_A4954_H

#include <stdint.h> // uint8_t

struct a4954 *a4954_oid_lookup(uint8_t oid);
void a4954_set_phase(struct a4954 *a, uint32_t phase, uint32_t scale);
void a4954_disable(struct a4954 *a);
void a4954_enable(struct a4954 *a);

#endif // driver_a4954.h
