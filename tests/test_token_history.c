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
		ds4_token_history_snapshot_take(&history);
	CHECK(snapshot.persistent);
	CHECK(snapshot.len == 2);
	CHECK(snapshot.prompt_tokens == 157);
	CHECK(snapshot.output_tokens == 38);
	CHECK(snapshot.requests == 3);
	CHECK(snapshot.days[0].day == day0);
	CHECK(snapshot.days[0].prompt_tokens == 150);
	CHECK(snapshot.days[0].output_tokens == 30);
	CHECK(snapshot.days[0].requests == 2);
	ds4_token_history_free(&history);

	struct stat st;
	CHECK(stat(path, &st) == 0);
	CHECK((st.st_mode & 0777) == 0600);

	memset(err, 0, sizeof(err));
	CHECK(ds4_token_history_init(&history, path, (day0 + 1) * 86400,
		err, sizeof(err)));
	snapshot = ds4_token_history_snapshot_take(&history);
	CHECK(snapshot.len == 2);
	CHECK(snapshot.prompt_tokens == 157);
	CHECK(snapshot.output_tokens == 38);
	CHECK(snapshot.requests == 3);
	ds4_token_history_free(&history);

	memset(err, 0, sizeof(err));
	CHECK(ds4_token_history_init(&history, "", day0 * 86400,
		err, sizeof(err)));
	CHECK(ds4_token_history_record(&history, day0 * 86400 + 30,
		9, 4, err, sizeof(err)));
	snapshot = ds4_token_history_snapshot_take(&history);
	CHECK(!snapshot.persistent);
	CHECK(snapshot.len == 1);
	CHECK(snapshot.prompt_tokens == 9);
	CHECK(snapshot.output_tokens == 4);
	CHECK(snapshot.requests == 1);
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
