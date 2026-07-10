#ifndef DS4_CALL_HISTORY_H
#define DS4_CALL_HISTORY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define DS4_CALL_HISTORY_CAPACITY 200

typedef enum {
	DS4_CALL_ACTIVE = 0,
	DS4_CALL_COMPLETED,
	DS4_CALL_FAILED,
} ds4_call_status;

typedef struct {
	uint64_t request_id;
	char caller[64];
	char api[16];
	char kind[16];
	bool stream;
	bool has_tools;
	ds4_call_status status;
	double started_at;
	double finished_at;
	int prompt_tokens;
	int cached_tokens;
	int cache_write_tokens;
	int output_tokens;
	char cache_source[32];
	char finish[32];
	char error[160];
} ds4_call_record;

typedef struct {
	char caller[64];
	uint64_t calls;
	uint64_t failures;
	uint64_t prompt_tokens;
	uint64_t cached_tokens;
	double average_terminal_duration;
	double recent_activity;
} ds4_call_caller;

typedef struct {
	ds4_call_record *records;
	size_t len;
	size_t capacity;
	size_t allocated;
	uint64_t next_request_id;
} ds4_call_history;

typedef struct {
	ds4_call_record *records;
	size_t records_len;
	ds4_call_caller *callers;
	size_t callers_len;
} ds4_call_history_snapshot;

void ds4_call_history_init(ds4_call_history *history);
void ds4_call_history_free(ds4_call_history *history);
uint64_t ds4_call_history_begin(ds4_call_history *history, const char *caller,
                                 const char *api, const char *kind, bool stream,
                                 bool has_tools, double started_at);
void ds4_call_history_update_prompt(ds4_call_history *history, uint64_t request_id,
                                    int prompt_tokens, int cached_tokens,
                                    const char *cache_source);
void ds4_call_history_finish(ds4_call_history *history, uint64_t request_id,
                             ds4_call_status status, double finished_at,
                             int output_tokens, const char *cache_source,
                             const char *finish, const char *error);
ds4_call_history_snapshot ds4_call_history_snapshot_take(
	const ds4_call_history *history, double now);
void ds4_call_history_snapshot_free(ds4_call_history_snapshot *snapshot);

#endif
