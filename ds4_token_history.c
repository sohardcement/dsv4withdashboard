#include "ds4_token_history.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define DS4_TOKEN_HISTORY_HEADER "DS4_TOKEN_USAGE_V1"

static void set_error(char *err, size_t errlen, const char *message) {
	if (!err || !errlen) return;
	snprintf(err, errlen, "%s", message ? message : "");
}

static uint64_t sat_add(uint64_t value, uint64_t add) {
	return UINT64_MAX - value < add ? UINT64_MAX : value + add;
}

static int64_t history_day(int64_t now_sec) {
	return now_sec > 0 ? now_sec / 86400 : 0;
}

static void prune_days(ds4_token_history *history, int64_t current_day) {
	if (!history || !history->len) return;
	const int64_t oldest = current_day >= DS4_TOKEN_HISTORY_MAX_DAYS - 1 ?
		current_day - (DS4_TOKEN_HISTORY_MAX_DAYS - 1) : 0;
	size_t keep = 0;
	for (size_t i = 0; i < history->len; i++) {
		if (history->days[i].day < oldest ||
			history->days[i].day > current_day) continue;
		history->days[keep++] = history->days[i];
	}
	history->len = keep;
}

static ds4_token_history_day *find_or_add_day(ds4_token_history *history,
	int64_t day) {
	size_t at = 0;
	while (at < history->len && history->days[at].day < day) at++;
	if (at < history->len && history->days[at].day == day)
		return &history->days[at];
	if (history->len == DS4_TOKEN_HISTORY_MAX_DAYS) {
		if (at == 0) return NULL;
		memmove(&history->days[0], &history->days[1],
			(history->len - 1) * sizeof(history->days[0]));
		history->len--;
		at--;
	}
	memmove(&history->days[at + 1], &history->days[at],
		(history->len - at) * sizeof(history->days[0]));
	history->days[at] = (ds4_token_history_day){ .day = day };
	history->len++;
	return &history->days[at];
}

static bool parse_u64(const char **cursor, uint64_t *value) {
	const char *p = *cursor;
	if (*p < '0' || *p > '9') return false;
	errno = 0;
	char *end = NULL;
	unsigned long long parsed = strtoull(p, &end, 10);
	if (errno == ERANGE || end == p) return false;
	*value = (uint64_t)parsed;
	*cursor = end;
	return true;
}

static bool parse_day_line(const char *line, ds4_token_history_day *day) {
	const char *p = line;
	uint64_t values[4];
	for (size_t i = 0; i < 4; i++) {
		if (!parse_u64(&p, &values[i])) return false;
		if (i < 3) {
			if (*p != '\t') return false;
			p++;
		}
	}
	if (*p == '\r') p++;
	if (*p == '\n') p++;
	if (*p || values[0] > INT64_MAX) return false;
	*day = (ds4_token_history_day){
		.day = (int64_t)values[0],
		.prompt_tokens = values[1],
		.output_tokens = values[2],
		.requests = values[3],
	};
	return true;
}

static bool ensure_parent_dir(const char *path, char *err, size_t errlen) {
	char *copy = strdup(path);
	if (!copy) abort();
	char *slash = strrchr(copy, '/');
	if (!slash || slash == copy) {
		free(copy);
		return true;
	}
	*slash = '\0';
	if (mkdir(copy, 0700) != 0 && errno != EEXIST) {
		char message[256];
		snprintf(message, sizeof(message),
			"cannot create token history directory: %s", strerror(errno));
		set_error(err, errlen, message);
		free(copy);
		return false;
	}
	free(copy);
	return true;
}

static bool save_history(const ds4_token_history *history,
	char *err, size_t errlen) {
	if (!history || !history->enabled || !history->path) return true;
	if (!ensure_parent_dir(history->path, err, errlen)) return false;
	const size_t pathlen = strlen(history->path);
	char *tmp = malloc(pathlen + 48);
	if (!tmp) abort();
	snprintf(tmp, pathlen + 48, "%s.tmp.%ld", history->path, (long)getpid());
	int fd = open(tmp, O_WRONLY | O_CREAT | O_EXCL, 0600);
	if (fd < 0) {
		char message[256];
		snprintf(message, sizeof(message),
			"cannot create token history file: %s", strerror(errno));
		set_error(err, errlen, message);
		free(tmp);
		return false;
	}
	FILE *fp = fdopen(fd, "w");
	bool ok = fp != NULL;
	if (ok) ok = fprintf(fp, "%s\n", DS4_TOKEN_HISTORY_HEADER) > 0;
	for (size_t i = 0; ok && i < history->len; i++) {
		const ds4_token_history_day *day = &history->days[i];
		ok = fprintf(fp, "%lld\t%llu\t%llu\t%llu\n",
			(long long)day->day,
			(unsigned long long)day->prompt_tokens,
			(unsigned long long)day->output_tokens,
			(unsigned long long)day->requests) > 0;
	}
	if (ok) ok = fflush(fp) == 0;
	if (ok) ok = fsync(fd) == 0;
	if (fp) {
		if (fclose(fp) != 0) ok = false;
	} else {
		close(fd);
	}
	if (ok) ok = rename(tmp, history->path) == 0;
	if (!ok) {
		char message[256];
		snprintf(message, sizeof(message),
			"cannot persist token history: %s", strerror(errno));
		set_error(err, errlen, message);
		unlink(tmp);
	}
	free(tmp);
	return ok;
}

bool ds4_token_history_init(ds4_token_history *history, const char *path,
	int64_t now_sec, char *err, size_t errlen) {
	if (!history) return false;
	memset(history, 0, sizeof(*history));
	set_error(err, errlen, "");
	if (!path || !path[0]) return true;
	if (strchr(path, '\r') || strchr(path, '\n')) {
		set_error(err, errlen, "token history path contains CR or LF");
		return false;
	}
	history->path = strdup(path);
	if (!history->path) abort();
	history->enabled = true;
	FILE *fp = fopen(path, "r");
	if (!fp) {
		if (errno == ENOENT) return true;
		char message[256];
		snprintf(message, sizeof(message),
			"cannot read token history: %s", strerror(errno));
		set_error(err, errlen, message);
		return false;
	}
	char line[512];
	bool header_ok = fgets(line, sizeof(line), fp) != NULL &&
		(!strcmp(line, DS4_TOKEN_HISTORY_HEADER "\n") ||
		 !strcmp(line, DS4_TOKEN_HISTORY_HEADER "\r\n"));
	if (!header_ok) {
		set_error(err, errlen, "invalid token history header");
		fclose(fp);
		return false;
	}
	const int64_t current_day = history_day(now_sec);
	while (fgets(line, sizeof(line), fp)) {
		ds4_token_history_day parsed;
		if (!parse_day_line(line, &parsed)) continue;
		ds4_token_history_day *day = find_or_add_day(history, parsed.day);
		if (!day) continue;
		day->prompt_tokens = sat_add(day->prompt_tokens, parsed.prompt_tokens);
		day->output_tokens = sat_add(day->output_tokens, parsed.output_tokens);
		day->requests = sat_add(day->requests, parsed.requests);
	}
	fclose(fp);
	prune_days(history, current_day);
	return true;
}

void ds4_token_history_free(ds4_token_history *history) {
	if (!history) return;
	free(history->path);
	memset(history, 0, sizeof(*history));
}

bool ds4_token_history_record(ds4_token_history *history, int64_t now_sec,
	uint64_t prompt_tokens, uint64_t output_tokens,
	char *err, size_t errlen) {
	if (!history) return false;
	set_error(err, errlen, "");
	const int64_t day_value = history_day(now_sec);
	prune_days(history, day_value);
	ds4_token_history_day *day = find_or_add_day(history, day_value);
	if (!day) {
		set_error(err, errlen, "token history day is outside retention");
		return false;
	}
	day->prompt_tokens = sat_add(day->prompt_tokens, prompt_tokens);
	day->output_tokens = sat_add(day->output_tokens, output_tokens);
	day->requests = sat_add(day->requests, 1);
	return save_history(history, err, errlen);
}

ds4_token_history_snapshot ds4_token_history_snapshot_take(
	const ds4_token_history *history) {
	ds4_token_history_snapshot snapshot = {0};
	if (!history) return snapshot;
	snapshot.persistent = history->enabled;
	snapshot.len = history->len;
	memcpy(snapshot.days, history->days,
		history->len * sizeof(snapshot.days[0]));
	for (size_t i = 0; i < snapshot.len; i++) {
		snapshot.prompt_tokens = sat_add(snapshot.prompt_tokens,
			snapshot.days[i].prompt_tokens);
		snapshot.output_tokens = sat_add(snapshot.output_tokens,
			snapshot.days[i].output_tokens);
		snapshot.requests = sat_add(snapshot.requests,
			snapshot.days[i].requests);
	}
	return snapshot;
}
