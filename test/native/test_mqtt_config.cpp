#include <cassert>
#include <iostream>
#include <string>
#include "Arduino.h"
#include "FanController.h"
#include "CoolingController.h"
#include "ArgbController.h"
#include "MqttBridge.h"
#include "SerialConsole.h"
int main() {
    FanController fans;
    ArgbController argb;
    assert(fans.begin() && argb.begin());
    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    MqttBridge mqtt;
    assert(mqtt.begin(fans, cooling, argb));
    SerialConsole console(Serial, fans, argb, cooling, nullptr, &mqtt);
    console.begin();
    Serial.out.clear();
    Serial.send("MQTT STATUS\nMQTT ENABLE 1\nMQTT HOST 192.168.1.5 1883\n"
                "MQTT AUTH user password\nMQTT PREFIX cooling/system\nMQTT ENABLE 1\nMQTT STATUS\n"
                "TYPE 1 4\nALLFAN 45\n");
    console.poll();
    assert(Serial.out.find("MQTT ENABLED=0") != std::string::npos);
    assert(Serial.out.find("ERR MQTT enable") != std::string::npos);
    assert(Serial.out.find("OK MQTT_HOST") != std::string::npos);
    assert(Serial.out.find("OK MQTT_AUTH") != std::string::npos);
    assert(Serial.out.find("OK MQTT_PREFIX") != std::string::npos);
    assert(Serial.out.find("MQTT ENABLED=1 CONNECTED=0 HOST=192.168.1.5 PORT=1883 PREFIX=cooling/system") != std::string::npos);
    assert(Serial.out.find("password") == std::string::npos);
    assert(Serial.out.find("ERR only 2-pin or 3-pin supported") != std::string::npos);
    assert(Serial.out.find("ERR fan control blocked") != std::string::npos);
    assert(fans.getPercent(0) == 100);
    assert(!mqtt.setPrefix("bad/#"));
    std::cout << "PASS: MQTT config/status and serial safety interlock\n";
}
