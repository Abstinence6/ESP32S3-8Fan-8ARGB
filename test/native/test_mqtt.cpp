#include <cassert>
#include <iostream>
#include <string>
#include "Arduino.h"
#include "MqttBridge.h"

int main() {
    FanController fans;
    ArgbController lights;
    assert(fans.begin());
    assert(lights.begin());
    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    NetworkRgbBridge network(lights);
    MqttBridge mqtt(cooling, fans, lights, network);
    assert(mqtt.begin());
    assert(!mqtt.connected());
    assert(!mqtt.setBroker("", 1883));
    assert(!mqtt.setBroker("127.0.0.1", 0));
    assert(mqtt.setBroker("127.0.0.1", 1883));
    assert(mqtt.setCredentials("fan", "test"));
    assert(mqtt.setEnabled(false));
    assert(mqtt.setEnabled(true));
    MqttBridge afterReboot(cooling, fans, lights, network);
    assert(afterReboot.begin());
    afterReboot.printStatus(Serial);
    assert(Serial.out.find("HOST=127.0.0.1 PORT=1883 AUTH=1") != std::string::npos);
    const std::string base = afterReboot.baseTopic();
    assert(!afterReboot.applyCommand((base+"/fan/1/set").c_str(), "50", 1000));
    assert(!afterReboot.applyCommand((base+"/fan/1/power/set").c_str(), "OFF", 1000));
    assert(fans.getPercent(0) == 100 && cooling.mode(0) == CoolingController::Mode::Auto);
    assert(afterReboot.applyCommand((base+"/fan/1/set").c_str(), "100", 1000));
    assert(!afterReboot.applyCommand((base+"/fan/1/set").c_str(), "101", 1000));
    assert(!afterReboot.applyCommand((base+"/fan/1/set").c_str(), "-1", 1000));
    assert(!afterReboot.applyCommand((base+"/fan/9/set").c_str(), "100", 1000));
    assert(!afterReboot.applyCommand("esp32fan/untrusted/fan/1/set", "100", 1000));
    assert(!afterReboot.applyCommand((base+"/fan/1/temp/set").c_str(), "550", 1200));
    assert(cooling.temperature(0) == 0);
    assert(afterReboot.setExternalTemperatures(true));
    assert(afterReboot.applyCommand((base+"/fan/1/temp/set").c_str(), "550", 1200));
    assert(cooling.temperature(0) == 550);
    // Fresh USB temperature preempts MQTT; MQTT may resume only after expiry.
    cooling.setTemperature(0, 650, 1300);
    assert(!afterReboot.applyCommand((base+"/fan/1/temp/set").c_str(), "250", 1400));
    assert(cooling.temperature(0) == 650);
    assert(afterReboot.applyCommand((base+"/fan/1/temp/set").c_str(), "450", 11500));
    assert(cooling.temperature(0) == 450);
    MqttBridge afterTempReboot(cooling, fans, lights, network);
    assert(afterTempReboot.begin());
    assert(afterTempReboot.externalTemperaturesEnabled());
    assert(!afterReboot.applyCommand((base+"/fan/1/temp/set").c_str(), "1500", 1200));
    assert(afterReboot.applyCommand((base+"/fan/1/mode/set").c_str(), "auto", 1200));
    assert(afterReboot.applyCommand((base+"/light/2/rgb/set").c_str(), "255,0,14", 1200));
    assert(lights.getMode(1) == ArgbController::Mode::Solid);
    assert(!afterReboot.applyCommand((base+"/light/2/rgb/set").c_str(), "256,0,14", 1200));
    assert(afterReboot.applyCommand((base+"/light/2/set").c_str(), "OFF", 1200));
    std::cout << "PASS: MQTT NVS, fan interlock, temp and ARGB routing\n";
}
