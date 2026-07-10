#include "ds4_host_metrics.h"

#include <limits.h>
#include <string.h>
#include <time.h>

#if defined(__APPLE__)
#include <mach/mach.h>
#include <sys/sysctl.h>
#elif defined(__linux__)
#include <math.h>
#include <stdio.h>
#endif

#define DS4_HOST_PRESSURE_WARNING_AVG10 10.0
#define DS4_HOST_PRESSURE_CRITICAL_AVG10 20.0

static double host_metrics_now(void) {
	struct timespec ts;

	if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
		return 0.0;
	return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

const char *ds4_host_pressure_name(ds4_host_pressure pressure) {
	switch (pressure) {
	case DS4_HOST_PRESSURE_NORMAL:
		return "normal";
	case DS4_HOST_PRESSURE_WARNING:
		return "warning";
	case DS4_HOST_PRESSURE_CRITICAL:
		return "critical";
	case DS4_HOST_PRESSURE_UNKNOWN:
	default:
		return "unknown";
	}
}

#if defined(__APPLE__)
static bool host_metrics_multiply(uint64_t count, uint64_t size, uint64_t *out) {
	if (count && size > UINT64_MAX / count)
		return false;
	*out = count * size;
	return true;
}

static bool host_metrics_sample_macos(ds4_host_metrics *out) {
	uint64_t total = 0;
	size_t total_size = sizeof(total);
	vm_statistics64_data_t vm = {0};
	mach_msg_type_number_t vm_count = HOST_VM_INFO64_COUNT;
	vm_size_t page_size = 0;
	uint64_t available_pages;
	uint64_t available = 0;
	struct xsw_usage swap = {0};
	size_t swap_size = sizeof(swap);
	task_basic_info_64_data_t task = {0};
	mach_msg_type_number_t task_count = TASK_BASIC_INFO_64_COUNT;
	host_t host;

	if (sysctlbyname("hw.memsize", &total, &total_size, NULL, 0) != 0 || !total)
		return false;
	out->memory_total_bytes = total;
	host = mach_host_self();
	if (host == MACH_PORT_NULL)
		goto sampled;
	if (host_page_size(host, &page_size) == KERN_SUCCESS &&
		host_statistics64(host, HOST_VM_INFO64, (host_info64_t)&vm,
			&vm_count) == KERN_SUCCESS) {
		available_pages = (uint64_t)vm.free_count + (uint64_t)vm.inactive_count;
		if (available_pages >= (uint64_t)vm.free_count &&
			host_metrics_multiply(available_pages, (uint64_t)page_size, &available)) {
			out->memory_available_bytes = available > total ? total : available;
			out->memory_used_bytes = total - out->memory_available_bytes;
		}
	}
	mach_port_deallocate(mach_task_self(), host);
sampled:
	if (sysctlbyname("vm.swapusage", &swap, &swap_size, NULL, 0) == 0) {
		out->swap_total_bytes = swap.xsu_total;
		if (swap.xsu_used <= swap.xsu_total)
			out->swap_used_bytes = swap.xsu_used;
	}
	if (task_info(mach_task_self(), TASK_BASIC_INFO_64, (task_info_t)&task,
		&task_count) == KERN_SUCCESS)
		out->process_rss_bytes = task.resident_size;
	out->sampled_at = host_metrics_now();
	out->available = true;
	return true;
}
#elif defined(__linux__)
static bool host_metrics_meminfo_value(const char *line, const char *name, uint64_t *value) {
	unsigned long long kb;
	size_t name_len = strlen(name);

	if (strncmp(line, name, name_len) || line[name_len] != ':')
		return false;
	if (sscanf(line + name_len + 1, " %llu kB", &kb) != 1 ||
		kb > UINT64_MAX / 1024)
		return false;
	*value = (uint64_t)kb * 1024;
	return true;
}

static void host_metrics_process_rss(ds4_host_metrics *out) {
	FILE *f = fopen("/proc/self/status", "r");
	char line[256];

	if (!f)
		return;
	while (fgets(line, sizeof(line), f)) {
		if (host_metrics_meminfo_value(line, "VmRSS", &out->process_rss_bytes))
			break;
	}
	fclose(f);
}

static void host_metrics_pressure(ds4_host_metrics *out) {
	FILE *f = fopen("/proc/pressure/memory", "r");
	char line[256];
	double avg10;

	if (!f)
		return;
	while (fgets(line, sizeof(line), f)) {
		if (strncmp(line, "some ", 5) || sscanf(line + 5, "avg10=%lf", &avg10) != 1)
			continue;
		if (!isfinite(avg10) || avg10 < 0.0)
			break;
		out->pressure = avg10 >= DS4_HOST_PRESSURE_CRITICAL_AVG10 ?
			DS4_HOST_PRESSURE_CRITICAL : avg10 >= DS4_HOST_PRESSURE_WARNING_AVG10 ?
			DS4_HOST_PRESSURE_WARNING : DS4_HOST_PRESSURE_NORMAL;
		break;
	}
	fclose(f);
}

static bool host_metrics_sample_linux(ds4_host_metrics *out) {
	FILE *f = fopen("/proc/meminfo", "r");
	char line[256];
	uint64_t memory_available = 0, swap_free = 0;
	bool have_memory_available = false, have_swap_free = false;

	if (!f)
		return false;
	while (fgets(line, sizeof(line), f)) {
		if (host_metrics_meminfo_value(line, "MemTotal", &out->memory_total_bytes))
			continue;
		if (host_metrics_meminfo_value(line, "MemAvailable", &memory_available)) {
			have_memory_available = true;
			continue;
		}
		if (host_metrics_meminfo_value(line, "SwapTotal", &out->swap_total_bytes))
			continue;
		if (host_metrics_meminfo_value(line, "SwapFree", &swap_free))
			have_swap_free = true;
	}
	fclose(f);
	if (!out->memory_total_bytes)
		return false;
	if (have_memory_available) {
		out->memory_available_bytes = memory_available > out->memory_total_bytes ?
			out->memory_total_bytes : memory_available;
		out->memory_used_bytes = out->memory_total_bytes - out->memory_available_bytes;
	}
	if (out->swap_total_bytes && have_swap_free)
		out->swap_used_bytes = swap_free >= out->swap_total_bytes ? 0 :
			out->swap_total_bytes - swap_free;
	host_metrics_process_rss(out);
	host_metrics_pressure(out);
	out->sampled_at = host_metrics_now();
	out->available = true;
	return true;
}
#endif

bool ds4_host_metrics_sample(ds4_host_metrics *out) {
	if (!out)
		return false;
	memset(out, 0, sizeof(*out));

#if defined(__APPLE__)
	return host_metrics_sample_macos(out);
#elif defined(__linux__)
	return host_metrics_sample_linux(out);
#else
	return false;
#endif
}
