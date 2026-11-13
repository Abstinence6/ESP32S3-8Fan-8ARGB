#pragma once
#include <Arduino.h>
#include <stddef.h>
#include <string.h>

// Wire-only hex codec for UTF-8 config values; no plaintext secrets in
// responses. '-' represents empty values. Reject NUL to preserve C-string
// invariants for Wi-Fi and MQTT libraries.
namespace configwire {
inline int nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
inline bool decode(const char* hex, char* out, size_t capacity, bool allowEmpty = false) {
    if (!hex || !out || capacity < 1) return false;
    if (strcmp(hex, "-") == 0) {
        if (!allowEmpty) return false;
        out[0] = 0;
        return true;
    }
    const size_t n = strlen(hex);
    if (n == 0 || n % 2 != 0 || n / 2 >= capacity) return false;
    for (size_t i = 0; i < n; i += 2) {
        const int hi = nibble(hex[i]);
        const int lo = nibble(hex[i + 1]);
        if (hi < 0 || lo < 0 || (hi == 0 && lo == 0)) return false;
        out[i / 2] = static_cast<char>((hi << 4) | lo);
    }
    out[n / 2] = 0;
    return true;
}
inline void printHex(Stream& out, const char* value) {
    if (!value || !*value) {
        out.print(F("-"));
        return;
    }
    static const char digits[] = "0123456789ABCDEF";
    for (const unsigned char* p = reinterpret_cast<const unsigned char*>(value); *p; ++p) {
        const char encoded[] = { digits[*p >> 4], digits[*p & 0x0f], 0 };
        out.print(encoded);
    }
}
} // namespace configwire
