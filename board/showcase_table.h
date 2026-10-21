/* The showcase carousel's entries, in button order. `showcase_table.c` is generated from
 * config/showcase.yaml by scripts/export_showcase.py, together with the policies it points
 * at under `policies/`. */
#ifndef SHOWCASE_TABLE_H
#define SHOWCASE_TABLE_H

#include <stdint.h>

#include "policy.h"
#include "showcase.h"

extern const showcase_entry_t showcase_entries[];
extern const uint8_t showcase_entry_count;

#endif /* SHOWCASE_TABLE_H */
