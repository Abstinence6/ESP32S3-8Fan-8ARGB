#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>

class Preferences {
public:
    bool begin(const char* namespaceName, bool) { prefix_ = namespaceName; return true; }
    size_t getBytesLength(const char* key) const {
        auto found = values().find(prefix_ + "/" + key);
        return found != values().end() ? found->second.size() : 0;
    }
    size_t getBytes(const char* key, void* dest, size_t maxlen) const {
        auto found = values().find(prefix_ + "/" + key);
        if (found == values().end() || found->second.size() > maxlen) return 0;
        std::memcpy(dest, found->second.data(), found->second.size());
        return found->second.size();
    }
    size_t putBytes(const char* key, const void* src, size_t size) {
        if (failNext()) { failNext() = false; return 0; }
        const auto* b = static_cast<const uint8_t*>(src);
        values()[prefix_ + "/" + key] = std::vector<uint8_t>(b, b + size);
        ++writes();
        return size;
    }
    static size_t writeCount() { return writes(); }
    static void failNextWrite() { failNext() = true; }
private:
    static size_t& writes() { static size_t count = 0; return count; }
    static bool& failNext() { static bool flag = false; return flag; }
    static std::map<std::string, std::vector<uint8_t>>& values() {
        static std::map<std::string, std::vector<uint8_t>> memory;
        return memory;
    }
    std::string prefix_;
};
