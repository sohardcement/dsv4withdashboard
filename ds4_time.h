#ifndef DS4_TIME_H
#define DS4_TIME_H

#include <sys/time.h>
#include <time.h>

/* Wall-clock seconds for values exposed to API clients. */
static inline double ds4_time_sec_from_parts(time_t seconds, long nanoseconds) {
	return (double)seconds + (double)nanoseconds * 1e-9;
}

static inline double ds4_wall_time_sec(void) {
	struct timespec ts;
	if (clock_gettime(CLOCK_REALTIME, &ts) == 0)
		return ds4_time_sec_from_parts(ts.tv_sec, ts.tv_nsec);
	struct timeval tv;
	if (gettimeofday(&tv, NULL) == 0)
		return ds4_time_sec_from_parts(tv.tv_sec, tv.tv_usec * 1000L);
	return 0.0;
}

#endif
