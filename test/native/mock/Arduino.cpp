#include "Arduino.h"

namespace mock {
uint32_t currentMs = 0;
std::array<uint32_t, 8> duty = {};
std::array<uint8_t, 8> pin = {};
std::array<void(*)(void*), 64> handlers = {};
std::array<void*, 64> handlerArgs = {};
void pulse(uint8_t inputPin, unsigned count) {
    while (count-- && handlers[inputPin]) handlers[inputPin](handlerArgs[inputPin]);
}
}

MockSerial Serial;
uint32_t millis() { return mock::currentMs; }
void delay(uint32_t) {}
double ledcSetup(uint8_t, double freq, uint8_t) { return freq; }
void ledcAttachPin(uint8_t pin, uint8_t channel) { mock::pin[channel] = pin; }
void ledcWrite(uint8_t channel, uint32_t value) { mock::duty[channel] = value; }
void pinMode(uint8_t, uint8_t) {}
int digitalPinToInterrupt(uint8_t pin) { return pin; }
void attachInterruptArg(int pin, void (*isr)(void*), void* arg, int) {
    mock::handlers[pin] = isr;
    mock::handlerArgs[pin] = arg;
}
