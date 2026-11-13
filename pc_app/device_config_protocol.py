"""Typed commands and safe parsing for configuring ESP32 through USB.

Secrets are sent as UTF-8 hexadecimal because the legacy serial parser is
whitespace-delimited; they are never stored in QSettings or logged. The USB
port is a trusted local provisioning link, NOT an encrypted connection.
"""
from __future__ import annotations

import re

_HEX = re.compile(r"^(?:[0-9A-Fa-f]{2})+$")
_BROKER = re.compile(r"^[A-Za-z0-9._:-]+$")


def encode_value(value: str, max_bytes: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("Некоректний текст налаштування")
    data = value.encode("utf-8")
    if len(data) > max_bytes or (not data and not empty):
        raise ValueError(f"Значення має містити 1–{max_bytes} байтів UTF-8")
    return data.hex().upper() if data else "-"


def decode_value(hex_text: str, max_bytes: int) -> str:
    if hex_text == "-":
        return ""
    if (not isinstance(hex_text, str) or len(hex_text) > max_bytes * 2 or
            not _HEX.fullmatch(hex_text)):
        raise ValueError("Некоректна HEX-відповідь від ESP")
    raw = bytes.fromhex(hex_text)
    if b"\x00" in raw:
        raise ValueError("Нульовий байт у відповіді ESP")
    return raw.decode("utf-8")


def fields(line: str, prefix: str) -> dict[str, str]:
    if not line.startswith(prefix + " "):
        raise ValueError("Неправильна відповідь ESP")
    params = {}
    for item in line[len(prefix) + 1:].split():
        if "=" in item:
            key, value = item.split("=", 1)
            params[key] = value
    return params


def wifi_command(ssid: str, password: str, *, previous_ssid: str = "",
                 configured: bool = False, open_network: bool = False) -> str:
    identifier = encode_value(ssid, 32)
    if open_network:
        token = "-"
    elif password:
        raw = password.encode("utf-8")
        if not 8 <= len(raw) <= 64:
            raise ValueError("WPA2 пароль має містити 8–64 байти UTF-8")
        token = encode_value(password, 64)
    elif configured and ssid == previous_ssid:
        token = "KEEP"
    else:
        raise ValueError("Введи пароль нової Wi-Fi мережі або вибери відкриту мережу")
    return f"WIFI SETHEX {identifier} {token}"


def mqtt_commands(*, host: str, port: int, username: str, password: str,
                  enabled: bool, discovery: bool,
                  current: dict[str, object] | None = None) -> list[str]:
    previous = current or {}
    broker = host.strip()
    if broker and (len(broker) > 63 or not _BROKER.fullmatch(broker)):
        raise ValueError("MQTT broker: потрібна IP-адреса або hostname без пробілів")
    if enabled and not broker:
        raise ValueError("Введи MQTT broker перед увімкненням")
    if not 1 <= port <= 65535:
        raise ValueError("MQTT порт повинен бути 1–65535")
    if not username and password:
        raise ValueError("Вкажи MQTT користувача, перш ніж вводити пароль")
    if len(username.encode("utf-8")) >= 32:
        raise ValueError("MQTT ім’я користувача завелике (макс. 31 байт)")
    if len(password.encode("utf-8")) >= 64:
        raise ValueError("MQTT пароль завеликий (макс. 63 байти)")
    commands = []
    if broker and (broker != previous.get("host") or port != previous.get("port")):
        commands.append(f"MQTT BROKER {broker} {port}")
    old_user = str(previous.get("username", ""))
    if username:
        if password:
            commands.append(
                f"MQTT AUTHHEX {encode_value(username, 31)} {encode_value(password, 63)}"
            )
        elif username != old_user:
            raise ValueError("Для нового MQTT користувача потрібно вказати пароль")
    elif old_user:
        commands.append("MQTT AUTH CLEAR")
    if discovery != previous.get("discovery"):
        commands.append(f"MQTT HA {'ON' if discovery else 'OFF'}")
    if enabled != previous.get("enabled"):
        commands.append(f"MQTT {'ON' if enabled else 'OFF'}")
    return commands
