#include <cassert>
#include "HardwareTemperature.h"
#include "FanController.h"
#include "CoolingController.h"
#include "BoardConfig.h"

int main() {
    static_assert(board::allowedAuxPin(18), "GPIO18 example must not overlap existing pins");
    static_assert(!board::allowedAuxPin(21), "fan PWM pin must be rejected");
    static_assert(!board::allowedAuxPin(46), "boot strap must be rejected");
    FanController fans;
    assert(fans.begin());
    MockSerial events;
    CoolingController cooling(fans, events);
    assert(cooling.begin());
    HardwareTemperature sensor;
    assert(sensor.begin());
    assert(!sensor.enabled()); // shipping default must not claim a probe
    assert(!sensor.fresh(10000));
    assert(sensor.mode(0) == HardwareTemperature::Mode::PcOnly);
    assert(sensor.setMode(0, HardwareTemperature::Mode::PcOnly));
    assert(!sensor.setMode(0, HardwareTemperature::Mode::Local));
    assert(!sensor.setMode(0, HardwareTemperature::Mode::Backup));
    assert(!sensor.setMode(8, HardwareTemperature::Mode::PcOnly));
    assert(sensor.acceptsPc(0));
    sensor.update(10000, cooling);
    assert(!cooling.temperatureFresh(0, 10000));
    return 0;
}
