#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include "Arduino.h"
#include "ConfigWire.h"
#include "FanController.h"
#include "ArgbController.h"
#include "CoolingController.h"
#include "MqttBridge.h"
#include "NetworkRgbBridge.h"
#include "SerialConsole.h"

int main() {
    char name[33] = {}, secret[65] = {};
    assert(configwire::decode("4D792057692D4669", name, sizeof(name)));
    assert(std::strcmp(name, "My Wi-Fi") == 0);
    assert(configwire::decode("-", secret, sizeof(secret), true) && !secret[0]);
    assert(!configwire::decode("-", name, sizeof(name)));
    assert(!configwire::decode("AA0", name, sizeof(name)));
    assert(!configwire::decode("00", name, sizeof(name)));
    assert(!configwire::decode("GH", name, sizeof(name)));
    assert(!configwire::decode("41424344", name, 4));
    Serial.out.clear();
    configwire::printHex(Serial, "My Wi-Fi");
    assert(Serial.out == "4D792057692D4669");

    FanController fans;
    ArgbController leds;
    assert(fans.begin());
    assert(leds.begin());
    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    NetworkRgbBridge wifi(leds);
    MqttBridge mqtt(cooling, fans, leds, wifi);
    assert(mqtt.begin());
    SerialConsole console(Serial, fans, leds, cooling, &wifi, &mqtt);
    console.begin();
    Serial.out.clear();

    Serial.send("MQTT BROKER mqtt.local 1883\nMQTT AUTHHEX 68612075736572 73656372657420313233\nMQTT HA OFF\nMQTT OFF\nMQTT CONFIG?\n");
    console.poll();
    assert(Serial.out.find("ERR") == std::string::npos);
    assert(Serial.out.find("MQTT_CONFIG ENABLED=0") != std::string::npos);
    assert(Serial.out.find("HOST_HEX=6D7174742E6C6F63616C") != std::string::npos);
    assert(Serial.out.find("USER_HEX=68612075736572") != std::string::npos);
    assert(Serial.out.find("DISCOVERY=0") != std::string::npos);
    assert(Serial.out.find("secret") == std::string::npos);
    assert(Serial.out.find("73656372657420313233") == std::string::npos);

    Serial.out.clear();
    Serial.send("MQTT AUTHHEX 68612075736572 00\nMQTT AUTHHEX 6861 G1\n");
    console.poll();
    assert(Serial.out.find("ERR MQTT credentials") != std::string::npos);
    Serial.out.clear();
    Serial.send("MQTT CLEAR\nMQTT CONFIG?\n");
    console.poll();
    assert(Serial.out.find("HOST_HEX=-") != std::string::npos);
    assert(Serial.out.find("AUTH=0") != std::string::npos);

    Serial.out.clear();
    Serial.send("WIFI CONFIG?\nWIFI SETHEX 4D792057692D4669 3132333435363738\nSTRIPCFG? 1\nARGBSTATUS\n");
    console.poll();
    assert(Serial.out.find("WIFI_CONFIG ENABLED=0") != std::string::npos);
    assert(Serial.out.find("ERR WIFI config") != std::string::npos); // mock Wi-Fi deliberately disabled
    assert(Serial.out.find("STRIPCFG CH=1 LEDS=") != std::string::npos);
    assert(Serial.out.find("ARGBSTATUS LIMIT_MA=") != std::string::npos);

    // Independent native LED effects are persisted only on an explicit SAVE.
    Serial.out.clear();
    Serial.send("FX SET 2 2 10 20 30 90 100 110 3 64 0\nFX BOOT 2 0\nFX SAVE\nFX? 2\n");
    console.poll();
    assert(Serial.out.find("OK FX_SAVED") != std::string::npos);
    assert(Serial.out.find("FX CH=2 MODE=2") != std::string::npos);
    assert(leds.getMode(1) == ArgbController::Mode::Effect);

    // Reactive scene protocol accepts only explicit bounded metric values.
    Serial.out.clear();
    Serial.send("RFX SET 2 26 1 2 100 900 2 10 20 30 100 110 120 3 64 0\n"
                "RVAL 2 550\nRFX BOOT 2 0\nRFX SAVE\nRFX? 2\n");
    console.poll();
    assert(Serial.out.find("OK RFX_SAVED") != std::string::npos);
    assert(Serial.out.find("RFX CH=2 SRC=26 FALL=1 STYLE=2") != std::string::npos);
    assert(Serial.out.find(" FRESH=1 VALUE=550") != std::string::npos);
    assert(leds.getMode(1) == ArgbController::Mode::Reactive);
    Serial.out.clear();
    Serial.send("RVAL 9 100\nRVAL 1 10000001\nRFX SET 2 26 25 2 0 1000 2 1 2 3 4 5 6 3 64 0\n");
    console.poll();
    assert(Serial.out.find("ERR arguments") != std::string::npos);
    assert(Serial.out.find("ERR RFX invalid") != std::string::npos);

    // Command line >239 bytes must not bypass parser or change the fans.
    Serial.out.clear();
    Serial.send(std::string(300, 'X') + "\nSTATUS\n");
    console.poll();
    assert(Serial.out.find("ERR line too long") != std::string::npos);
    assert(Serial.out.find("CH 1 FAN=") != std::string::npos);
    std::cout << "PASS: safe USB provisioning, MQTT NVS, discovery, config readback\n";
}
