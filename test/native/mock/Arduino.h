#pragma once

#include <array>
#include <cstdint>
#include <sstream>
#include <string>

#define IRAM_ATTR
#define INPUT_PULLUP 1
#define FALLING 2
#define F(s) s

typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
inline void portENTER_CRITICAL(portMUX_TYPE*) {}
inline void portEXIT_CRITICAL(portMUX_TYPE*) {}
inline void portENTER_CRITICAL_ISR(portMUX_TYPE*) {}
inline void portEXIT_CRITICAL_ISR(portMUX_TYPE*) {}

namespace mock {
extern uint32_t currentMs;
extern std::array<uint32_t, 8> duty;
extern std::array<uint8_t, 8> pin;
extern std::array<void(*)(void*), 64> handlers;
extern std::array<void*, 64> handlerArgs;
void pulse(uint8_t inputPin, unsigned count);
}

uint32_t millis();
void delay(uint32_t);
double ledcSetup(uint8_t channel, double freq, uint8_t bits);
void ledcAttachPin(uint8_t pin, uint8_t channel);
void ledcWrite(uint8_t channel, uint32_t value);
void pinMode(uint8_t, uint8_t);
int digitalPinToInterrupt(uint8_t pin);
void attachInterruptArg(int pin, void (*isr)(void*), void* arg, int mode);

class Stream {
public:
    virtual ~Stream() = default;
    virtual int available() = 0;
    virtual int read() = 0;
    virtual void emit(const std::string&) = 0;
    void print(const char* s) { emit(s); }
    void println(const char* s) { emit(s); emit("\n"); }
    template<typename T> void print(T t) { std::ostringstream ss; ss << +t; emit(ss.str()); }
    template<typename T> void println(T t) { print(t); emit("\n"); }
};

class MockSerial : public Stream {
public:
    void begin(uint32_t) {}
    std::string in, out;
    int available() override { return static_cast<int>(in.size()); }
    int read() override { int c = in[0]; in.erase(0,1); return c; }
    void emit(const std::string& value) override { out += value; }
    void send(const std::string& s) { in += s; }
};
extern MockSerial Serial;
