# Arduino Firmware

این پوشه چند نسل firmware مستقل دارد. فایل‌های قدیمی عمداً دست‌نخورده نگه داشته شده‌اند.

## Firmwareها

| فایل | مدل پیکربندی | قرارداد Python | کاربرد |
|---|---|---|---|
| main.ino | پین‌ها داخل کد | ندارد | firmware قدیمی |
| main_Blocking.ino | پین‌ها داخل کد | ندارد | نسخه legacy و blocking |
| main_nonBlocking.ino | پین‌ها داخل کد | ندارد | non-blocking قدیمی؛ دست‌نخورده |
| main_nonBlocking_v2.ino | پین‌ها داخل کد | ندارد | نسخه hardened با fixed hardware mapping |
| main_configurable_v1.ino | از Python دریافت می‌شود | دارد | نسخه جدید قابل‌کانفیگ و قابل‌اعتبارسنجی |

## main_configurable_v1.ino

این firmware برای این طراحی شده که Arduino هیچ فرض ضمنی درباره پین‌ها نداشته باشد.

Python در زمان startup می‌تواند تعریف کند:

- چند motor داریم و PWM/DIR هرکدام کجاست.
- چند servo داریم و محدوده و center هرکدام چیست.
- چند ultrasonic داریم و نام منطقی، TRIG و ECHO هرکدام چیست.
- چند encoder داریم و پین interrupt آن‌ها چیست.
- آیا TM1638 وجود دارد و کلیدهای force-stop و resume کدام‌اند.
- پارامترهای safety و timing.

### ماژول‌های پشتیبانی‌شده

حداکثرهای firmware:

~~~text
motor       4
servo       4
ultrasonic  8
encoder     4
tm1638      1
~~~

هدف این firmware Arduino Mega 2560 است.

### اعتبارسنجی روی Arduino

قبل از فعال‌شدن سخت‌افزار، firmware موارد زیر را بررسی می‌کند:

- تعداد moduleها از حد مجاز بیشتر نباشد.
- ID مربوط به motor/servo/encoder از صفر و بدون gap باشد.
- پین‌ها تکراری نباشند.
- PWM motor روی پین PWM باشد.
- encoder روی پین interrupt-capable باشد.
- بازه servo معتبر باشد.
- TRIG/ECHO یک ultrasonic یکی نباشند.
- نام ultrasonicها تکراری نباشد.
- تنظیمات safety در محدوده باشند.

در صورت خطا:

~~~text
ERR CFG <REASON>
~~~

ارسال می‌شود و config فعال نمی‌شود.

## Handshake

ابتدا Python باید نسخه firmware را تشخیص دهد:

~~~text
hello

HELLO main_configurable_v1 1 mega2560
~~~

سپس configuration ارسال می‌شود:

~~~text
cfg begin mega2560_default
cfg motor 0 10 12
cfg motor 1 11 13
cfg servo 0 9 30 150 90
cfg encoder 0 2
cfg ultrasonic left 4 5
cfg ultrasonic right 6 7
cfg ultrasonic side 8 24
cfg tm1638 26 28 30 0 7
cfg option stop_distance_cm 35
...
cfg end mega2560_default <FNV32>
~~~

Arduino configuration را validate می‌کند، fingerprint را دوباره حساب می‌کند و تمام مقادیر پذیرفته‌شده را echo می‌کند:

~~~text
CFG ECHO mega2560_default motor 0 10 12
CFG ECHO mega2560_default servo 0 9 30 150 90
...
CFG READY mega2560_default <FNV32>
~~~

Python فقط وقتی startup را موفق اعلام می‌کند که:

1. firmware ID درست باشد.
2. protocol version درست باشد.
3. board درست باشد.
4. Arduino تمام module/optionها را echo کرده باشد.
5. fingerprint دو طرف دقیقاً برابر باشد.

## Runtime

بعد از موفق‌شدن handshake، فرمان‌های runtime زیر در دسترس‌اند:

~~~text
motor 200
motor -200
motor 0

motor 0 180

servo 90
servo 0 90

stop
resume
heartbeat

left
right

set left <pulse sequence>
set right <pulse sequence>
save left
save right
load

status
u
~~~

Pulse:

~~~text
f <speed> <pulses> <angle>
b <speed> <pulses> <angle>
~~~

چند pulse می‌تواند در یک خط ارسال شود.

## Sensor naming

برای سازگاری با Python فعلی، ultrasonicهای جلوی ربات را بهتر است دقیقاً این نام‌ها داشته باشند:

~~~text
left
right
~~~

نام اختیاری سوم:

~~~text
side
~~~

اگر این نام‌ها در config نباشند، telemetry مربوطه مقدار -1 می‌دهد.

## Safety

firmware شامل این لایه‌هاست:

- heartbeat timeout
- توقف در obstacle جلویی
- pause/resume برای pulse هنگام نزدیک‌شدن مانع
- stall timeout برای encoder
- dead-time هنگام تغییر جهت
- serial line length limit
- watchdog روی AVR
- TM1638 force-stop/resume در صورت configure شدن

این نسخه برای دریافت command از buffer ثابت استفاده می‌کند.

## مثال

profile نمونه در Python:

~~~text
../python/arduino_configs/mega2560_default.json
~~~

برای استفاده:

~~~bash
python python/main.py --mode race --arduino-config python/arduino_configs/mega2560_default.json
~~~

این flag اختیاری است. بدون آن Python رفتار قدیمی را ادامه می‌دهد و handshake جدید اجرا نمی‌شود.

## نکته مهم

main_configurable_v1.ino را با profile مربوط به همان firmware استفاده کنید. اگر Python با --arduino-config به firmware دیگری وصل شود، firmware ID/protocol mismatch گزارش می‌شود و Python اجرا را متوقف می‌کند.
