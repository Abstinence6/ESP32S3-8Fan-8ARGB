#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
out="$(mktemp)"
trap 'rm -f "$out"' EXIT
g++ -std=c++17 -Wall -Wextra -Werror -Itest/native/mock -Iinclude \
  test/native/mock/Arduino.cpp src/FanController.cpp src/ArgbController.cpp \
  src/CoolingController.cpp src/SerialConsole.cpp src/main.cpp test/native/test_main.cpp -o "$out"
"$out"
