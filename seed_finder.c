#include <stdint.h>
#include <stdio.h>
#include <string.h>

/*
 * Recover BYOND encrypted resource seeds from known plaintext prefixes.
 *
 * Input lines:
 *   <label> <pattern_hex> <cipher_prefix_hex>
 * Output lines:
 *   <label> <seed_hex_or_NONE>
 *
 * The implementation assumes seeds are monotonically non-decreasing in stream
 * order for a single RAD/RSC container. This matches observed BYOND cache data.
 */

static inline uint32_t step_state(uint32_t state, uint8_t observed_byte) {
    uint32_t a = (uint32_t)((uint64_t)(observed_byte + state) * 0x1001u + 0x7ED55D16u);
    uint32_t c = (a >> 19) ^ a ^ 0xC761C23Cu;
    uint32_t a2 = (uint32_t)((c << 5) + (c + 0x165667B1u));
    uint32_t c2 = (a2 - 0x2C5D9B94u) ^ (a2 << 9);
    uint32_t a3 = c2 * 9u - 0x028FB93Bu;
    return (a3 >> 16) ^ a3 ^ 0xB55A4F09u;
}

static inline int from_hex(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
    if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
    return -1;
}

static int parse_hex(const char *s, uint8_t *out, int max_n) {
    int hex_len = (int)strlen(s);
    if ((hex_len & 1) != 0) return -1;
    int n = hex_len / 2;
    if (n > max_n) n = max_n;

    for (int i = 0; i < n; ++i) {
        int hi = from_hex(s[i * 2]);
        int lo = from_hex(s[i * 2 + 1]);
        if (hi < 0 || lo < 0) return -1;
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return n;
}

int main(void) {
    char label[256];
    char pattern_hex[256];
    char cipher_hex[4096];
    uint32_t min_seed = 0;

    while (scanf("%255s %255s %4095s", label, pattern_hex, cipher_hex) == 3) {
        uint8_t pattern[64];
        uint8_t cipher[64];
        int pat_n = parse_hex(pattern_hex, pattern, 64);
        int ciph_n = parse_hex(cipher_hex, cipher, 64);

        if (pat_n <= 0 || ciph_n < pat_n) {
            printf("%s NONE\n", label);
            continue;
        }

        uint32_t low = (uint32_t)(cipher[0] ^ pattern[0]);
        uint32_t start_hi = min_seed >> 8;
        uint32_t min_low = min_seed & 0xFFu;
        if (low < min_low) {
            start_hi++;
        }

        uint32_t found = 0;
        int found_ok = 0;

        for (uint32_t hi = start_hi; hi < (1u << 24); ++hi) {
            uint32_t seed = (hi << 8) | low;
            if (seed < min_seed) {
                continue;
            }

            uint32_t state = seed;
            int match = 1;
            for (int i = 0; i < pat_n; ++i) {
                uint8_t plain = (uint8_t)(cipher[i] ^ (state & 0xFF));
                if (plain != pattern[i]) {
                    match = 0;
                    break;
                }
                state = step_state(state, cipher[i]);
            }

            if (match) {
                found = seed;
                found_ok = 1;
                break;
            }
        }

        if (found_ok) {
            min_seed = found;
            printf("%s %08x\n", label, found);
        } else {
            printf("%s NONE\n", label);
        }
        fflush(stdout);
    }

    return 0;
}
