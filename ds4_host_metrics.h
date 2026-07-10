#ifndef DS4_HOST_METRICS_H
#define DS4_HOST_METRICS_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
	DS4_HOST_PRESSURE_UNKNOWN,
	DS4_HOST_PRESSURE_NORMAL,
	DS4_HOST_PRESSURE_WARNING,
	DS4_HOST_PRESSURE_CRITICAL,
} ds4_host_pressure;

typedef struct {
	uint64_t memory_total_bytes, memory_used_bytes, memory_available_bytes;
	uint64_t swap_total_bytes, swap_used_bytes, process_rss_bytes;
	ds4_host_pressure pressure;
	double sampled_at;
	bool available;
} ds4_host_metrics;

bool ds4_host_metrics_sample(ds4_host_metrics *out);
const char *ds4_host_pressure_name(ds4_host_pressure pressure);

#endif
