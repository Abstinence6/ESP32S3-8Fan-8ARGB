#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
out="$(mktemp)"
trap 'rm -f "$out"' EXIT
g++ -std=c++17 -Wall -Wextra -Werror -DFAN_DC_PWM_VALIDATED=1 -Itest/native/mock -Iinclude \
  test/native/mock/Arduino.cpp src/FanController.cpp src/ArgbController.cpp \
  src/CoolingController.cpp src/NetworkRgbBridge.cpp src/MqttBridge.cpp src/PcPowerController.cpp src/SerialConsole.cpp src/main.cpp test/native/test_main.cpp -o "$out"
"$out"

# Verify safety interlock in the unmodified default (FAN_DC_PWM_VALIDATED=0).
g++ -std=c++17 -Wall -Wextra -Werror -Itest/native/mock -Iinclude \
  test/native/mock/Arduino.cpp src/FanController.cpp test/native/test_dc_guard.cpp -o "$out"
"$out"

# Operational safety in the as-shipped default with an unvalidated DC key.
g++ -std=c++17 -Wall -Wextra -Werror -Itest/native/mock -Iinclude \
  test/native/mock/Arduino.cpp src/FanController.cpp src/ArgbController.cpp \
  src/CoolingController.cpp src/NetworkRgbBridge.cpp src/MqttBridge.cpp src/PcPowerController.cpp src/SerialConsole.cpp \
  test/native/test_operational_safety.cpp -o "$out"
"$out"

# MQTT command routing and safe NVS configuration (no ESP hardware needed).
g++ -std=c++17 -Wall -Wextra -Werror -Itest/native/mock -Iinclude \
  test/native/mock/Arduino.cpp src/FanController.cpp src/ArgbController.cpp \
  src/CoolingController.cpp src/NetworkRgbBridge.cpp src/MqttBridge.cpp src/PcPowerController.cpp \
  test/native/test_mqtt.cpp -o "$out"
"$out"

# NVS v3->v4 migration and corrupt saved data.
g++ -std=c++17 -Wall -Wextra -Werror -Itest/native/mock -Iinclude \
  test/native/mock/Arduino.cpp src/FanController.cpp src/CoolingController.cpp \
  test/native/test_migration.cpp -o "$out"
"$out"

# PC PWR_SW is opt-in: use two compile-time checked pins and a fake 3.3V status.
g++ -std=c++17 -Wall -Wextra -Werror -DPC_POWER_ENABLED=1 \
  -DPC_POWER_GPIO=33 -DPC_SENSE_GPIO=34 -Itest/native/mock -Iinclude \
  test/native/mock/Arduino.cpp src/PcPowerController.cpp \
  test/native/test_pc_power.cpp -o "$out"
"$out"
