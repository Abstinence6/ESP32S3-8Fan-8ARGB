#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "FanController.h"
#include "AirflowAssistant.h"
#include "BoardConfig.h"

int main() {
    FanController fans;
    assert(fans.begin());
    AirflowAssistant assistant(fans);
    assert(assistant.begin());
    auto empty=assistant.estimate();
    assert(!empty.usable && empty.configured==0);
    assert(!assistant.configure(0,1,0,100,100));
    assert(!assistant.configure(0,3,2000,100,100));
    assert(!assistant.configure(0,1,2000,500,0));
    const auto start=Preferences::writeCount();
    assert(assistant.configure(0,1,2000,900,80));
    assert(assistant.configure(1,2,2000,750,80));
    assert(assistant.channel(0).direction==1);
    assert(Preferences::writeCount()==start+2);
    auto missing=assistant.estimate();
    assert(!missing.usable && missing.configured==2 && missing.unavailable==2);
    assert(std::string(AirflowAssistant::tendency(missing))=="unavailable");
    // Simulate realistic 2-pulse tach signals on two 3-pin channels.
    mock::pulse(board::kFanTachPins[0], 60);
    mock::pulse(board::kFanTachPins[1], 60);
    mock::currentMs+=1000;
    fans.update(mock::currentMs);
    auto balanced=assistant.estimate();
    assert(balanced.usable);
    assert(balanced.intakeDeci>0 && balanced.exhaustDeci>0);
    assert(balanced.balancePercent>0);
    const auto writes=Preferences::writeCount();
    assert(assistant.configure(1,2,2000,750,80)); // unchanged
    assert(Preferences::writeCount()==writes);
    AirflowAssistant reloaded(fans);
    assert(reloaded.begin());
    assert(reloaded.channel(1).maxRpm==2000);
    assert(reloaded.estimate().configured==2);
    Preferences::failNextWrite();
    assert(!assistant.configure(0,1,2000,1000,80));
    assert(assistant.channel(0).cfmDeci==900);
    assert(fans.getPercent(0)==100); // passive: no fan speed changes
    std::cout<<"PASS: airflow estimate, unavailable sensor, NVS persistence and safety\n";
}
