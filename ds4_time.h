#ifndef DS4_TIME_H
#define DS4_TIME_H

#include <sys/time.h>
#include <time.h>

/* Wall-clock seconds for values exposed to API clients. */
static inline double ds4_wall_time_sec(void) {
	struct timespec ts;
	if (clock_gettime(CLOCK_REALTIME, &ts) == 0)
		return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
	struct timeval tv;
	if (gettimeofday(&tv, NULL) == 0)
		return (double)tv.tv_sec + (double)tv.tv_usec * 1e-6;
	return 0.0;
}

#endif
