#include "../ds4_token_history.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int failures;

#define CHECK(expr) do { \
	if (!(expr)) { \
		fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #expr); \
		failures++; \
	} \
} while (0)

int main(void) {
	char dir[] = "/tmp/ds4-token-history.XXXXXX";
	CHECK(mkdtemp(dir) != NULL);
	char path[512];
	snprintf(path, sizeof(path), "%s/usage.tsv", dir);
	const int64_t day0 = 20000;
	char err[256] = {0};

	ds4_token_history history = {0};
	CHECK(ds4_token_history_init(&history, path, day0 * 86400, err, sizeof(err)));
	CHECK(history.enabled);
	CHECK(ds4_token_history_record(&history, day0 * 86400 + 10,
		100, 20, err, sizeof(err)));
	CHECK(ds4_token_history_record(&history, day0 * 86400 + 20,
		50, 10, err, sizeof(err)));
	CHECK(ds4_token_history_record(&history, (day0 + 1) * 86400 + 10,
		7, 8, err, sizeof(err)));
	ds4_token_history_snapshot snapshot =
		ds4_token_history_snapshot_take(&history, (day0 + 1) * 86400);
	CHECK(snapshot.persistent);
	CHECK(snapshot.len == 2);
	CHECK(snapshot.prompt_tokens == 157);
	CHECK(snapshot.output_tokens == 38);
	CHECK(snapshot.requests == 3);
	CHECK(snapshot.days[0].day == day0);
	CHECK(snapshot.days[0].prompt_tokens == 150);
	CHECK(snapshot.days[0].output_tokens == 30);
	CHECK(snapshot.days[0].requests == 2);

	for (int64_t offset = 2; offset < 40; offset++) {
		CHECK(ds4_token_history_record(&history,
			(day0 + offset) * 86400 + 10, 1, 0, err, sizeof(err)));
	}
	snapshot = ds4_token_history_snapshot_take(&history,
		(day0 + 39) * 86400);
	CHECK(snapshot.len == 40);
	CHECK(snapshot.prompt_tokens == 195);
	CHECK(snapshot.output_tokens == 38);
	CHECK(snapshot.requests == 41);
	CHECK(snapshot.active_days == 40);
	CHECK(snapshot.peak_tokens == 180);
	CHECK(snapshot.peak_day == day0);
	CHECK(snapshot.current_streak == 40);
	CHECK(snapshot.longest_streak == 40);
	CHECK(snapshot.first_day == day0);
	CHECK(snapshot.last_day == day0 + 39);
	ds4_token_history_free(&history);

	struct stat st;
	CHECK(stat(path, &st) == 0);
	CHECK((st.st_mode & 0777) == 0600);

	FILE *fp = fopen(path, "a");
	CHECK(fp != NULL);
	if (fp) {
		CHECK(fprintf(fp, "%llu\t1\t1\t1\n",
			(unsigned long long)INT64_MAX) > 0);
		CHECK(fclose(fp) == 0);
	}
	memset(err, 0, sizeof(err));
	CHECK(ds4_token_history_init(&history, path, (day0 + 39) * 86400,
		err, sizeof(err)));
	snapshot = ds4_token_history_snapshot_take(&history,
		(day0 + 39) * 86400);
	CHECK(snapshot.len == 40);
	CHECK(snapshot.prompt_tokens == 195);
	CHECK(snapshot.output_tokens == 38);
	CHECK(snapshot.requests == 41);
	ds4_token_history_free(&history);

	memset(err, 0, sizeof(err));
	CHECK(ds4_token_history_init(&history, "", day0 * 86400,
		err, sizeof(err)));
	CHECK(ds4_token_history_record(&history, day0 * 86400 + 30,
		9, 4, err, sizeof(err)));
	for (int64_t offset = 1; offset < 400; offset++) {
		CHECK(ds4_token_history_record(&history,
			(day0 + offset) * 86400 + 30, 1, 0, err, sizeof(err)));
	}
	snapshot = ds4_token_history_snapshot_take(&history,
		(day0 + 399) * 86400);
	CHECK(!snapshot.persistent);
	CHECK(snapshot.len == DS4_TOKEN_HISTORY_WINDOW_DAYS);
	CHECK(snapshot.prompt_tokens == 408);
	CHECK(snapshot.output_tokens == 4);
	CHECK(snapshot.requests == 400);
	CHECK(snapshot.active_days == 400);
	CHECK(snapshot.current_streak == 400);
	CHECK(snapshot.longest_streak == 400);
	CHECK(snapshot.first_day == day0);
	CHECK(snapshot.last_day == day0 + 399);
	CHECK(snapshot.days[0].day == day0 + 29);
	ds4_token_history_free(&history);

	unlink(path);
	rmdir(dir);
	if (failures) {
		fprintf(stderr, "test_token_history: %d failure(s)\n", failures);
		return 1;
	}
	puts("test_token_history: all tests passed");
	return 0;
}
