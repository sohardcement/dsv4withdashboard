#ifndef DS4_TOKEN_HISTORY_H
#define DS4_TOKEN_HISTORY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define DS4_TOKEN_HISTORY_MAX_DAYS 30

typedef struct {
	int64_t day;
	uint64_t prompt_tokens;
	uint64_t output_tokens;
	uint64_t requests;
} ds4_token_history_day;

typedef struct {
	char *path;
	ds4_token_history_day days[DS4_TOKEN_HISTORY_MAX_DAYS];
	size_t len;
	bool enabled;
} ds4_token_history;

typedef struct {
	bool persistent;
	ds4_token_history_day days[DS4_TOKEN_HISTORY_MAX_DAYS];
	size_t len;
	uint64_t prompt_tokens;
	uint64_t output_tokens;
	uint64_t requests;
} ds4_token_history_snapshot;

bool ds4_token_history_init(ds4_token_history *history, const char *path,
	int64_t now_sec, char *err, size_t errlen);
void ds4_token_history_free(ds4_token_history *history);
bool ds4_token_history_record(ds4_token_history *history, int64_t now_sec,
	uint64_t prompt_tokens, uint64_t output_tokens,
	char *err, size_t errlen);
ds4_token_history_snapshot ds4_token_history_snapshot_take(
	const ds4_token_history *history);

#endif
