# Python Runtime & Arduino Hardware Contract

این بخش روش اجرای Python و قرارداد سخت‌افزاری جدید با Arduino را توضیح می‌دهد.

## حالت عادی

بدون flag جدید، ارتباط Python همان رفتار قبلی را دارد:

~~~bash
python python/main.py --mode race
~~~

## حالت Strict Hardware Contract

برای firmware جدید:

~~~bash
python python/main.py \
  --mode race \
  --arduino-config python/arduino_configs/mega2560_default.json
~~~

با دادن --arduino-config، Python قبل از شروع control loop:

1. به Arduino وصل می‌شود.
2. firmware ID و protocol version را می‌گیرد.
3. config JSON را locally validate می‌کند.
4. تمام moduleها و optionها را به Arduino می‌فرستد.
5. پاسخ و echo Arduino را بررسی می‌کند.
6. fingerprint FNV-1a را در دو طرف مقایسه می‌کند.
7. فقط بعد از موفقیت کامل وارد Race/City می‌شود.

هر mismatch یا ERR CFG باعث توقف startup می‌شود.

خروجی خطای این بخش با exit code 2 خاتمه پیدا می‌کند.

## Flagها

### --arduino-config PATH

فعال‌کردن strict hardware contract و مشخص‌کردن JSON profile.

~~~bash
python python/main.py \
  --mode race \
  --arduino-config python/arduino_configs/mega2560_default.json
~~~

### --arduino-contract-timeout SECONDS

timeout هر مرحله از handshake.

پیش‌فرض:

~~~text
3.0
~~~

مثال:

~~~bash
python python/main.py \
  --mode race \
  --arduino-config python/arduino_configs/mega2560_default.json \
  --arduino-contract-timeout 5
~~~

### ترکیب ممنوع

این دو گزینه با هم قابل استفاده نیستند:

~~~text
--arduino-config
--without-arduino
~~~

## Config JSON

فایل نمونه:

~~~text
python/arduino_configs/mega2560_default.json
~~~

ساختار اصلی:

~~~json
{
  "schema_version": 1,
  "config_id": "mega2560_default",
  "firmware": {
    "id": "main_configurable_v1",
    "protocol": 1
  },
  "board": "mega2560",
  "modules": [
    {
      "type": "motor",
      "id": 0,
      "pwm": 10,
      "dir": 12
    },
    {
      "type": "servo",
      "id": 0,
      "pin": 9,
      "min": 30,
      "max": 150,
      "center": 90
    },
    {
      "type": "ultrasonic",
      "name": "left",
      "trig": 4,
      "echo": 5
    }
  ],
  "options": {
    "stop_distance_cm": 35,
    "pulse_stop_distance_cm": 10,
    "side_return_distance_cm": 20,
    "ultrasonic_interval_ms": 50,
    "host_heartbeat_timeout_ms": 500,
    "pulse_stall_timeout_ms": 900,
    "direction_deadtime_ms": 15
  }
}
~~~

## مدل moduleها

### Motor

~~~json
{
  "type": "motor",
  "id": 0,
  "pwm": 10,
  "dir": 12
}
~~~

### Servo

~~~json
{
  "type": "servo",
  "id": 0,
  "pin": 9,
  "min": 30,
  "max": 150,
  "center": 90
}
~~~

### Ultrasonic

~~~json
{
  "type": "ultrasonic",
  "name": "right",
  "trig": 6,
  "echo": 7
}
~~~

### Encoder

~~~json
{
  "type": "encoder",
  "id": 0,
  "pin": 2
}
~~~

### TM1638

~~~json
{
  "type": "tm1638",
  "stb": 26,
  "clk": 28,
  "dio": 30,
  "force_stop_button": 0,
  "resume_button": 7
}
~~~

## معماری فایل‌ها

~~~text
python/
├── main.py
├── controller/
│   └── controller.py
├── arduino/
│   ├── arduino_connection.py
│   └── hardware_contract.py
├── arduino_configs/
│   └── mega2560_default.json
└── test/
    └── test_unit_arduino_contract.py
~~~

hardware_contract.py مسئول:

- parse و validation profile
- ساخت protocol commands
- محاسبه fingerprint
- انتظار برای ACK
- مقایسه echo
- اعلام خطای strict startup

## جریان کامل

~~~text
Python
  │
  │ hello
  ▼
Arduino
  │ HELLO main_configurable_v1 1 mega2560
  │
  │ cfg begin ...
  │ cfg motor ...
  │ cfg servo ...
  │ cfg ultrasonic ...
  │ cfg encoder ...
  │ cfg option ...
  │ cfg end ... FNV32
  ▼
Arduino validation
  │
  ├── ERR CFG ...  ──────> Python stops
  │
  └── CFG ECHO ...
      CFG READY ... FNV32
              │
              ▼
       Python fingerprint check
              │
        ┌─────┴─────┐
        │           │
      match      mismatch
        │           │
       OK        Python stops
        │
        ▼
   Race / City
~~~

## تفاوت با firmwareهای قدیمی

firmwareهای قدیمی پین‌ها را داخل .ino تعریف می‌کنند. در نتیجه عوض‌کردن سخت‌افزار یعنی تغییر و upload firmware.

در main_configurable_v1.ino همان firmware می‌تواند برای profileهای مختلف استفاده شود؛ فقط JSON و wiring باید تغییر کند.

این قابلیت عمداً opt-in است تا deploymentهای فعلی بدون تغییر باقی بمانند.
