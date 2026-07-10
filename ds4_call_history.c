#include "ds4_call_history.h"

#include <stdlib.h>
#include <string.h>

static void copy_text(char *dst, size_t dstlen, const char *src) {
	if (!dst || !dstlen) return;
	if (!src) src = "";
	strncpy(dst, src, dstlen - 1);
	dst[dstlen - 1] = '\0';
}

static void prune(ds4_call_history *history) {
	if (!history) return;
	while (history->len > history->capacity) {
		size_t victim = history->len;
		for (size_t i = 0; i < history->len; i++) {
			if (history->records[i].status != DS4_CALL_ACTIVE) {
				victim = i;
				break;
			}
		}
		if (victim == history->len) break;
		memmove(&history->records[victim], &history->records[victim + 1],
				(history->len - victim - 1) * sizeof(*history->records));
		history->len--;
	}
}

static ds4_call_record *find_record(ds4_call_history *history, uint64_t request_id) {
	if (!history || !request_id) return NULL;
	for (size_t i = 0; i < history->len; i++)
		if (history->records[i].request_id == request_id) return &history->records[i];
	return NULL;
}

void ds4_call_history_init(ds4_call_history *history) {
	if (!history) return;
	memset(history, 0, sizeof(*history));
	history->capacity = DS4_CALL_HISTORY_CAPACITY;
}

void ds4_call_history_free(ds4_call_history *history) {
	if (!history) return;
	free(history->records);
	memset(history, 0, sizeof(*history));
}

uint64_t ds4_call_history_begin(ds4_call_history *history, const char *caller,
                                 const char *api, const char *kind, bool stream,
                                 bool has_tools, double started_at) {
	if (!history) return 0;
	if (!history->capacity) history->capacity = DS4_CALL_HISTORY_CAPACITY;
	prune(history);
	if (history->len == history->allocated) {
		size_t allocated = history->allocated + DS4_CALL_HISTORY_CAPACITY;
		ds4_call_record *records = realloc(history->records,
			allocated * sizeof(*records));
		if (!records) abort();
		history->records = records;
		history->allocated = allocated;
	}
	ds4_call_record *record = &history->records[history->len++];
	memset(record, 0, sizeof(*record));
	record->request_id = ++history->next_request_id;
	if (!record->request_id) record->request_id = ++history->next_request_id;
	copy_text(record->caller, sizeof(record->caller), caller);
	copy_text(record->api, sizeof(record->api), api);
	copy_text(record->kind, sizeof(record->kind), kind);
	record->stream = stream;
	record->has_tools = has_tools;
	record->status = DS4_CALL_ACTIVE;
	record->started_at = started_at;
	prune(history);
	return record->request_id;
}

void ds4_call_history_update_prompt(ds4_call_history *history, uint64_t request_id,
                                    int prompt_tokens, int cached_tokens,
                                    const char *cache_source) {
	ds4_call_record *record = find_record(history, request_id);
	if (!record) return;
	if (prompt_tokens < 0) prompt_tokens = 0;
	if (cached_tokens < 0) cached_tokens = 0;
	if (cached_tokens > prompt_tokens) cached_tokens = prompt_tokens;
	record->prompt_tokens = prompt_tokens;
	record->cached_tokens = cached_tokens;
	record->cache_write_tokens = prompt_tokens - cached_tokens;
	copy_text(record->cache_source, sizeof(record->cache_source), cache_source);
}

void ds4_call_history_finish(ds4_call_history *history, uint64_t request_id,
                             ds4_call_status status, double finished_at,
                             int output_tokens, const char *cache_source,
                             const char *finish, const char *error) {
	ds4_call_record *record = find_record(history, request_id);
	if (!record) return;
	record->status = status == DS4_CALL_ACTIVE ? DS4_CALL_FAILED : status;
	record->finished_at = finished_at;
	record->output_tokens = output_tokens < 0 ? 0 : output_tokens;
	copy_text(record->cache_source, sizeof(record->cache_source), cache_source);
	copy_text(record->finish, sizeof(record->finish), finish);
	copy_text(record->error, sizeof(record->error), error);
	prune(history);
}

ds4_call_history_snapshot ds4_call_history_snapshot_take(
	const ds4_call_history *history, double now) {
	ds4_call_history_snapshot snapshot = {0};
	if (!history || !history->len) return snapshot;
	snapshot.records = malloc(history->len * sizeof(*snapshot.records));
	if (!snapshot.records) abort();
	memcpy(snapshot.records, history->records, history->len * sizeof(*snapshot.records));
	snapshot.records_len = history->len;
	snapshot.callers = calloc(history->len, sizeof(*snapshot.callers));
	if (!snapshot.callers) abort();
	for (size_t i = 0; i < history->len; i++) {
		const ds4_call_record *record = &history->records[i];
		size_t j;
		for (j = 0; j < snapshot.callers_len; j++)
			if (!strcmp(snapshot.callers[j].caller, record->caller)) break;
		if (j == snapshot.callers_len) {
			copy_text(snapshot.callers[j].caller, sizeof(snapshot.callers[j].caller), record->caller);
			snapshot.callers_len++;
		}
		ds4_call_caller *caller = &snapshot.callers[j];
		caller->calls++;
		if (record->status == DS4_CALL_FAILED) caller->failures++;
		caller->prompt_tokens += (uint64_t)record->prompt_tokens;
		caller->cached_tokens += (uint64_t)record->cached_tokens;
		double activity = record->status == DS4_CALL_ACTIVE ? now : record->finished_at;
		if (activity > caller->recent_activity) caller->recent_activity = activity;
	}
	for (size_t j = 0; j < snapshot.callers_len; j++) {
		double total = 0.0;
		uint64_t count = 0;
		for (size_t i = 0; i < history->len; i++) {
			const ds4_call_record *record = &history->records[i];
			if (strcmp(record->caller, snapshot.callers[j].caller) ||
				record->status == DS4_CALL_ACTIVE) continue;
			double duration = record->finished_at - record->started_at;
			total += duration < 0.0 ? 0.0 : duration;
			count++;
		}
		if (count) snapshot.callers[j].average_terminal_duration = total / (double)count;
	}
	return snapshot;
}

void ds4_call_history_snapshot_free(ds4_call_history_snapshot *snapshot) {
	if (!snapshot) return;
	free(snapshot->records);
	free(snapshot->callers);
	memset(snapshot, 0, sizeof(*snapshot));
}
