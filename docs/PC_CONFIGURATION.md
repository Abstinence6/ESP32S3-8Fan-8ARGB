# FanARGB v8 — налаштування ESP32-S3 із Windows

**Усі змінювані параметри контролера налаштовуються через Windows GUI по USB.**
Для Wi-Fi, MQTT/Home Assistant, ARGB, вентиляторів і прив'язки DS18B20
не потрібно відкривати Serial Monitor або редагувати код прошивки.

## Підключення

1. Встановіть і запустіть новий FanARGBControl.exe.
2. Під'єднайте ESP32-S3 через USB, виберіть COM і натисніть «Підключити».
3. На сторінці **ESP32** натисніть **Прочитати все з ESP32**. Потрібна
   прошивка v8 або новіша; на v7 старі методи залишаються доступними,
   але нова сторінка лише показує запит оновити контролер.
4. Введіть параметри, натисніть **Зберегти**, дочекайтеся повідомлення
   про підтвердження від ESP. ПК перевіряє запис повторним читанням з NVS.
5. Повторне підключення або перезапуск Windows зчитує дані з ESP заново.

## Де що налаштовується

| Налаштування | Сторінка Windows | Де зберігається |
|---|---|---|
| Wi-Fi SSID, ключ, вимкнення Wi-Fi | ESP32 → Wi-Fi | ESP32 NVS |
| MQTT broker/port, ім'я, пароль, ON/OFF | ESP32 → MQTT | ESP32 NVS |
| Зовнішні MQTT-температури як резервне джерело (OFF за замовчуванням) | ESP32 → MQTT | ESP32 NVS |
| Home Assistant MQTT Discovery | ESP32 → MQTT | ESP32 NVS |
| ARGB: довжина 8 стрічок, reverse, бюджет 5V | ESP32 → ARGB | ESP32 NVS |
| ARGB яскравість і сцени | ESP32 / ARGB | ESP RAM (яскравість не постійна) |
| Fan PPR, критична температура, stall RPM | ESP32 → Вентилятори | ESP32 NVS |
| Fan криві, PID, DUAL, тип 2/3pin, калібрування | Вентилятори / Сервіс | ESP32 NVS |
| DS18B20 ROM → fan та режим PC/LOCAL/BACKUP | Датчики | ESP32 NVS |
| Вибір локального датчика NWinfo для каналу | Вентилятори | Windows QSettings: ID датчика прив'язаний до ПК |
| Зміна стану PWR_SW | Живлення ПК | Команда, *лише якщо hardware-enabled* |
| Native OpenRGB SDK / E1.31 | ARGB | Windows налаштування + ESP RAM для кадрів |
| Оновлення прошивки | Сервіс | ESP32 Flash (не NVS) |

**Неможливо надійно переналаштувати з ПК без перепрошивання:** довільні GPIO
для PWM/TACH/ARGB, апаратну обв'язку MOSFET, режими фізичного fail-ON,
початкове ввімкнення `FAN_DC_PWM_VALIDATED`/PWR_SW/DS18B20 на неперевірених
платах. Ці обмеження захищають живлення вентиляторів.

## Про паролі

- У GUI паролі приховані. Порожній пароль **не перезаписує попередній**
  для того самого SSID або MQTT-користувача.
- Для іншого Wi-Fi SSID введіть новий пароль або виберіть «відкрита мережа».
- Нова прошивка приймає UTF-8 HEX; назви мереж і паролі можуть містити
  пробіли, спецсимволи та українські літери. Обмеження Wi-Fi: SSID до
  32 байтів, ключ до 64 байтів; MQTT користувач до 31, пароль до 63.
- HEX — **лише екранування**, а не шифрування. Прокладання доступу до USB
  і до MQTT без TLS потрібно контролювати фізично/мережею. Не
  підключайте неавторизованих користувачів до COM-порту.
- ESP32 відповідає тільки прапорцями наявності пароля, а **не секретом**;
  Windows не записує ключі в QSettings/SQLite і не показує в логах.

## USB команда / відповідь v5 (для розробників)

Опис потрібний для сумісності й тестів, але звичайному користувачу
**нічого вручну надсилати не потрібно**.

```text
VERSION?                   -> FW VERSION=8 SERIAL=5 ...
WIFI CONFIG?               -> WIFI_CONFIG ENABLED=1 CONNECTED=1 SSID_HEX=... PASSWORD_SET=1 IP=...
WIFI SETHEX <ssidHex> <passwordHex|KEEP|->
WIFI OFF
MQTT CONFIG?               -> MQTT_CONFIG ENABLED=1 CONNECTED=0 HOST_HEX=... PORT=1883 USER_HEX=... AUTH=1 DISCOVERY=1 TOPIC=...
MQTT BROKER <hostname> <port>
MQTT AUTHHEX <userHex|-> <passwordHex|->
MQTT HA ON|OFF
MQTT TEMP ON|OFF
MQTT ON|OFF
MQTT CLEAR
STRIPCFG? <channel>        -> STRIPCFG CH=1 LEDS=30 REVERSE=0 BRIGHT=255
ARGBSTATUS                 -> ARGBSTATUS LIMIT_MA=... REQUESTED_MA=...
CONFIG <channel>           -> CONFIG 1 PPR=... CRIT=... STALL=...
```

Кожна команда запису має `OK ...` або `ERR ...`.
GUI не вважає OS Serial write підтвердженням збереження та читає
налаштування назад. Тайм-аут не запускає повторне збереження автоматично
і не стверджує, що NVS точно не змінилася.

## Безпека прошивання

Перепрошивання на робочому увімкненому ПК може відключити контролер
вентиляторів. Оновлюйте ESP32-S3 **тільки на безпечному окремому стенді**
або при вимкненому ПК і перевіреному fail-ON драйвері. DC PWM
залишається забороненим за замовчуванням, поки силову схему не перевірено.

### MQTT transaction in firmware serial protocol v7

With ESP32 serial protocol v7, the PC sends `MQTT TX START`, staged
`BROKER`/`AUTHHEX`/`FLAGS` changes, and `MQTT TX COMMIT`. The
firmware writes **one** CRC-checked NVS record after validation; a failed
transaction can be canceled or retried and does not partially enable MQTT.
The original serial v5/v6 commands remain as a fallback for older firmware.
`MQTT TX CLEAR` staged reset also disables external MQTT temperatures;
any uncommitted transaction expires automatically after 30 seconds.
