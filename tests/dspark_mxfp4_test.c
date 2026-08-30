#include "quants.h"

#include <stdint.h>
#include <stdio.h>

int main(void) {
	uint8_t block[17] = {127};
	float got[32];
	const float values[16] = {
		0.0f, 0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f,
		0.0f, -0.5f, -1.0f, -1.5f, -2.0f, -3.0f, -4.0f, -6.0f,
	};

	for (int i = 0; i < 16; i++) block[1 + i] = (uint8_t)(((15 - i) << 4) | i);
	ds4q_mxfp4_to_f32_row(block, got, 32);
	for (int i = 0; i < 16; i++) {
		if (got[i] != values[i] || got[i + 16] != values[15 - i]) {
			fprintf(stderr,
				"MXFP4 mismatch at %d: got %.9g and %.9g\n",
				i,
				got[i],
				got[i + 16]);
			return 1;
		}
	}
	return 0;
}
