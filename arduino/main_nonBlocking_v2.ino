#include <Arduino.h>
#include <Servo.h>
#include <EEPROM.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#if defined(__AVR__)
#include <avr/wdt.h>
#endif

/*
 * Self Driving Robot - Arduino motion/safety controller v2
 *
 * New module; main_nonBlocking.ino is intentionally untouched.
 * Keeps the six-field telemetry format used by python/controller/controller.py.
 *
 * Target: Arduino Mega-class AVR.
 */

/* =========================
   CONFIG
   ========================= */
const uint32_t BAUD_RATE = 115200UL;

const uint32_t STATUS_INTERVAL_MS = 50UL;
const uint32_t BUTTON_POLL_MS = 25UL;
const uint32_t BUTTON_DEBOUNCE_MS = 35UL;

const uint32_t ULTRA_INTERVAL_MS = 120UL;
const uint32_t ULTRA_TIMEOUT_US = 30000UL;
const uint32_t ULTRA_COOLDOWN_US = 3000UL;

const int STOP_DISTANCE_CM = 35;
const int PULSE_STOP_DISTANCE_CM = 10;
const int SIDE_RETURN_DISTANCE_CM = 20;

const uint32_t PULSE_STALL_TIMEOUT_MS = 900UL;
const uint32_t ADAPTIVE_CHECK_MS = 50UL;
const int ADAPTIVE_INITIAL_PWM = 160;
const int ADAPTIVE_STEP_PWM = 20;

const uint32_t DIRECTION_DEADTIME_MS = 15UL;

const int SERVO_MIN = 10;
const int SERVO_MAX = 170;
const int SERVO_CENTER = 90;

const uint32_t ENCODER_DEBOUNCE_US = 0UL;

const size_t SERIAL_LINE_MAX = 191;
const size_t MAX_SEQUENCE_CHARS = 127;
const uint8_t PULSE_QUEUE_CAPACITY = 16;
const long MAX_PULSES = 1000000L;

/* =========================
   PINS
   ========================= */
const uint8_t TM_STB_PIN = 26;
const uint8_t TM_CLK_PIN = 28;
const uint8_t TM_DIO_PIN = 30;

const uint8_t TM_FORCE_STOP_KEY_BIT = 0;
const uint8_t TM_RESUME_KEY_BIT = 7;

const uint8_t MOTOR_PWM_LEFT = 10;
const uint8_t MOTOR_DIR_LEFT = 12;
const uint8_t MOTOR_PWM_RIGHT = 11;
const uint8_t MOTOR_DIR_RIGHT = 13;

const uint8_t SERVO_PIN = 9;
const uint8_t ENCODER_PIN = 2;

const uint8_t ULTRA_LEFT_TRIG = 4;
const uint8_t ULTRA_LEFT_ECHO = 5;
const uint8_t ULTRA_RIGHT_TRIG = 6;
const uint8_t ULTRA_RIGHT_ECHO = 7;
const uint8_t ULTRA_SIDE_TRIG = 8;
const uint8_t ULTRA_SIDE_ECHO = 24;

/* =========================
   SERVO
   ========================= */
Servo steering;
int servoCurrent = SERVO_CENTER;

/* =========================
   ENCODER
   ========================= */
volatile uint32_t encoderPulses = 0;
volatile uint32_t encoderLastUs = 0;

void encoderISR() {
  uint32_t nowUs = micros();

  if (ENCODER_DEBOUNCE_US == 0UL ||
      (uint32_t)(nowUs - encoderLastUs) >= ENCODER_DEBOUNCE_US) {
    ++encoderPulses;
    encoderLastUs = nowUs;
  }
}

uint32_t readEncoder() {
  noInterrupts();
  uint32_t value = encoderPulses;
  interrupts();
  return value;
}

void resetEncoder() {
  noInterrupts();
  encoderPulses = 0;
  encoderLastUs = micros();
  interrupts();
}

/* =========================
   TM1638
   ========================= */
class TM1638Panel {
public:
  enum Mode {
    CLEAR_MODE = 0,
    STOP_MODE,
    LEFT_MODE,
    RIGHT_MODE,
    ALL_ON_MODE,
    FORCE_STOP_MODE
  };

  void begin(uint8_t stb, uint8_t clk, uint8_t dio) {
    stbPin = stb;
    clkPin = clk;
    dioPin = dio;

    pinMode(stbPin, OUTPUT);
    pinMode(clkPin, OUTPUT);
    pinMode(dioPin, OUTPUT);

    digitalWrite(stbPin, HIGH);
    digitalWrite(clkPin, HIGH);
    digitalWrite(dioPin, HIGH);

    mode = CLEAR_MODE;
    dirty = true;
    blink = false;
    blinkVisible = true;
    blinkMask = 0;
    ledMask = 0;
    lastBlinkMs = millis();

    render();
    sendCommand(0x88 | 7);
    flush();
  }

  void update(uint32_t nowMs) {
    if (blink && (uint32_t)(nowMs - lastBlinkMs) >= 250UL) {
      lastBlinkMs = nowMs;
      blinkVisible = !blinkVisible;
      dirty = true;
    }

    if (dirty) {
      flush();
    }
  }

  uint8_t buttons() {
    uint8_t value = 0;

    digitalWrite(stbPin, LOW);
    writeByte(0x42);
    pinMode(dioPin, INPUT_PULLUP);

    for (uint8_t row = 0; row < 4; ++row) {
      uint8_t b = readByte();
      if (b & 0x01) value |= (uint8_t)(1U << (row * 2));
      if (b & 0x10) value |= (uint8_t)(1U << (row * 2 + 1));
    }

    digitalWrite(stbPin, HIGH);
    pinMode(dioPin, OUTPUT);
    digitalWrite(dioPin, HIGH);

    return value;
  }

  void clear() { setMode(CLEAR_MODE, false, 0); }
  void stop() { setMode(STOP_MODE, false, 0); }
  void forceStop() { setMode(FORCE_STOP_MODE, false, 0); }
  void left() { setMode(LEFT_MODE, true, 0x07); }
  void right() { setMode(RIGHT_MODE, true, 0xE0); }

  void allOn() {
    mode = ALL_ON_MODE;
    blink = false;
    blinkVisible = true;
    blinkMask = 0;
    ledMask = 0xFF;
    clearDisplay();
    dirty = true;
  }

private:
  uint8_t stbPin = 0;
  uint8_t clkPin = 0;
  uint8_t dioPin = 0;

  uint8_t display[8] = {0};
  uint8_t ledMask = 0;
  uint8_t blinkMask = 0;

  bool blink = false;
  bool blinkVisible = true;
  bool dirty = false;

  uint32_t lastBlinkMs = 0;
  Mode mode = CLEAR_MODE;

  void setMode(Mode next, bool shouldBlink, uint8_t mask) {
    mode = next;
    blink = shouldBlink;
    blinkVisible = true;
    blinkMask = mask;
    render();
    dirty = true;
  }

  void clearDisplay() {
    for (uint8_t i = 0; i < 8; ++i) display[i] = 0;
  }

  void render() {
    clearDisplay();

    switch (mode) {
      case CLEAR_MODE:
        ledMask = 0;
        break;

      case STOP_MODE:
      case FORCE_STOP_MODE:
        putWord(2, "STOP");
        ledMask = 0xFF;
        break;

      case LEFT_MODE:
        putWord(0, "LEFT");
        ledMask = 0;
        break;

      case RIGHT_MODE:
        putWord(3, "RIGHT");
        ledMask = 0;
        break;

      case ALL_ON_MODE:
        ledMask = 0xFF;
        break;
    }
  }

  void putWord(uint8_t start, const char *text) {
    for (uint8_t i = 0; i < 8 && text[i] != '\0'; ++i) {
      uint8_t pos = (uint8_t)(start + i);
      if (pos < 8) display[pos] = segment(text[i]);
    }
  }

  static uint8_t segment(char c) {
    switch (toupper((unsigned char)c)) {
      case '0': return 0x3F;
      case '1': return 0x06;
      case '2': return 0x5B;
      case '3': return 0x4F;
      case '4': return 0x66;
      case '5': return 0x6D;
      case '6': return 0x7D;
      case '7': return 0x07;
      case '8': return 0x7F;
      case '9': return 0x6F;
      case 'A': return 0x77;
      case 'B': return 0x7C;
      case 'C': return 0x39;
      case 'D': return 0x5E;
      case 'E': return 0x79;
      case 'F': return 0x71;
      case 'G': return 0x3D;
      case 'H': return 0x76;
      case 'I': return 0x06;
      case 'J': return 0x1E;
      case 'L': return 0x38;
      case 'N': return 0x54;
      case 'O': return 0x3F;
      case 'P': return 0x73;
      case 'R': return 0x50;
      case 'S': return 0x6D;
      case 'T': return 0x78;
      case 'U': return 0x3E;
      case 'Y': return 0x6E;
      case '-': return 0x40;
      case '_': return 0x08;
      case ' ': return 0x00;
      default: return 0x00;
    }
  }

  void sendCommand(uint8_t command) {
    digitalWrite(stbPin, LOW);
    writeByte(command);
    digitalWrite(stbPin, HIGH);
  }

  void writeByte(uint8_t value) {
    for (uint8_t i = 0; i < 8; ++i) {
      digitalWrite(clkPin, LOW);
      digitalWrite(dioPin, (value & 0x01) ? HIGH : LOW);
      delayMicroseconds(1);
      digitalWrite(clkPin, HIGH);
      delayMicroseconds(1);
      value >>= 1;
    }
  }

  uint8_t readByte() {
    uint8_t value = 0;
    for (uint8_t i = 0; i < 8; ++i) {
      digitalWrite(clkPin, LOW);
      delayMicroseconds(1);
      if (digitalRead(dioPin)) value |= (uint8_t)(1U << i);
      digitalWrite(clkPin, HIGH);
      delayMicroseconds(1);
    }
    return value;
  }

  void flush() {
    sendCommand(0x40);

    digitalWrite(stbPin, LOW);
    writeByte(0xC0);

    for (uint8_t i = 0; i < 8; ++i) {
      bool steady = (ledMask & (uint8_t)(1U << i)) != 0;
      bool flashing = blink && blinkVisible &&
                      ((blinkMask & (uint8_t)(1U << i)) != 0);
      writeByte(display[i]);
      writeByte((steady || flashing) ? 0x01 : 0x00);
    }

    digitalWrite(stbPin, HIGH);
    dirty = false;
  }
};

TM1638Panel panel;

/* =========================
   ULTRASONIC ROUND-ROBIN
   ========================= */
struct Ultrasonic {
  uint8_t trig = 0;
  uint8_t echo = 0;
  int distance = -1;
  bool valid = false;
  uint32_t nextDueMs = 0;
};

Ultrasonic ultra[3];

uint8_t activeUltra = 0;
bool ultraBusy = false;
bool waitingRise = false;
bool waitingFall = false;
uint32_t ultraStartedUs = 0;
uint32_t echoStartedUs = 0;
uint32_t ultraCooldownUntilUs = 0;

void beginUltra(uint8_t index, uint8_t trig, uint8_t echo, uint32_t initialDelayMs) {
  ultra[index].trig = trig;
  ultra[index].echo = echo;
  ultra[index].distance = -1;
  ultra[index].valid = false;
  ultra[index].nextDueMs = millis() + initialDelayMs;

  pinMode(trig, OUTPUT);
  pinMode(echo, INPUT);
  digitalWrite(trig, LOW);
}

void startUltra(uint8_t index) {
  activeUltra = index;
  ultraBusy = true;
  waitingRise = true;
  waitingFall = false;
  ultraStartedUs = micros();
  echoStartedUs = 0;

  digitalWrite(ultra[index].trig, LOW);
  delayMicroseconds(2);
  digitalWrite(ultra[index].trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(ultra[index].trig, LOW);
}

void finishUltra(uint32_t nowMs, int distance, bool valid) {
  ultra[activeUltra].distance = distance;
  ultra[activeUltra].valid = valid;
  ultra[activeUltra].nextDueMs = nowMs + ULTRA_INTERVAL_MS;

  ultraBusy = false;
  waitingRise = false;
  waitingFall = false;
  echoStartedUs = 0;
  ultraCooldownUntilUs = micros() + ULTRA_COOLDOWN_US;
}

void updateUltra(uint32_t nowMs) {
  uint32_t nowUs = micros();

  if (ultraBusy) {
    int echo = digitalRead(ultra[activeUltra].echo);

    if (waitingRise) {
      if (echo == HIGH) {
        waitingRise = false;
        waitingFall = true;
        echoStartedUs = nowUs;
      }
    } else if (waitingFall && echo == LOW) {
      uint32_t duration = nowUs - echoStartedUs;
      int cm = (int)(duration / 58UL);
      finishUltra(nowMs, cm > 0 ? cm : -1, cm > 0);
      return;
    }

    if ((uint32_t)(nowUs - ultraStartedUs) >= ULTRA_TIMEOUT_US) {
      finishUltra(nowMs, -1, false);
    }
    return;
  }

  if ((int32_t)(nowUs - ultraCooldownUntilUs) < 0) return;

  for (uint8_t offset = 1; offset <= 3; ++offset) {
    uint8_t index = (uint8_t)((activeUltra + offset) % 3);
    if ((int32_t)(nowMs - ultra[index].nextDueMs) >= 0) {
      startUltra(index);
      return;
    }
  }
}

int ultraCm(uint8_t index) {
  return ultra[index].distance;
}

bool normalObstacle() {
  int left = ultraCm(0);
  int right = ultraCm(1);
  return (left > 0 && left <= STOP_DISTANCE_CM) ||
         (right > 0 && right <= STOP_DISTANCE_CM);
}

bool pulseObstacle() {
  int left = ultraCm(0);
  int right = ultraCm(1);
  return (left > 0 && left <= PULSE_STOP_DISTANCE_CM) ||
         (right > 0 && right <= PULSE_STOP_DISTANCE_CM);
}

/* =========================
   LANE CONFIG / EEPROM
   ========================= */
#define CONFIG_MAGIC 0x52A7

struct LaneConfig {
  uint16_t magic;
  char leftSequence[MAX_SEQUENCE_CHARS + 1];
  char rightSequence[MAX_SEQUENCE_CHARS + 1];
  uint16_t checksum;
};

LaneConfig laneConfig;

uint16_t checksumLaneConfig(const LaneConfig &cfg) {
  const uint8_t *data = reinterpret_cast<const uint8_t *>(&cfg);
  const size_t length = sizeof(LaneConfig) - sizeof(cfg.checksum);

  uint16_t sum = 0;
  for (size_t i = 0; i < length; ++i) sum = (uint16_t)(sum + data[i]);
  return sum;
}

void setDefaultLaneConfig() {
  laneConfig.magic = CONFIG_MAGIC;
  strncpy(laneConfig.leftSequence, "b 255 4 50 b 255 3 130", MAX_SEQUENCE_CHARS);
  laneConfig.leftSequence[MAX_SEQUENCE_CHARS] = '\0';

  strncpy(laneConfig.rightSequence, "f 255 3 130 f 255 3 50", MAX_SEQUENCE_CHARS);
  laneConfig.rightSequence[MAX_SEQUENCE_CHARS] = '\0';

  laneConfig.checksum = checksumLaneConfig(laneConfig);
}

void loadLaneConfig() {
  EEPROM.get(0, laneConfig);

  if (laneConfig.magic != CONFIG_MAGIC ||
      laneConfig.checksum != checksumLaneConfig(laneConfig)) {
    setDefaultLaneConfig();
  }
}

void saveLaneConfig() {
  laneConfig.magic = CONFIG_MAGIC;
  laneConfig.checksum = checksumLaneConfig(laneConfig);
  EEPROM.put(0, laneConfig);
}

/* =========================
   PULSE QUEUE
   ========================= */
struct PulseCommand {
  char direction = 'f';
  int speed = 0;
  long pulses = 0;
  int angle = SERVO_CENTER;
};

PulseCommand pulseQueue[PULSE_QUEUE_CAPACITY];
uint8_t queueHead = 0;
uint8_t queueTail = 0;
uint8_t queueCount = 0;

void clearPulseQueue() {
  queueHead = 0;
  queueTail = 0;
  queueCount = 0;
}

bool enqueuePulse(const PulseCommand &cmd) {
  if (queueCount >= PULSE_QUEUE_CAPACITY) return false;

  pulseQueue[queueTail] = cmd;
  queueTail = (uint8_t)((queueTail + 1) % PULSE_QUEUE_CAPACITY);
  ++queueCount;
  return true;
}

bool dequeuePulse(PulseCommand &cmd) {
  if (queueCount == 0) return false;

  cmd = pulseQueue[queueHead];
  queueHead = (uint8_t)((queueHead + 1) % PULSE_QUEUE_CAPACITY);
  --queueCount;
  return true;
}

char *trim(char *text) {
  while (*text && isspace((unsigned char)*text)) ++text;

  char *end = text + strlen(text);
  while (end > text && isspace((unsigned char)end[-1])) --end;
  *end = '\0';

  return text;
}

bool equalsIgnoreCase(const char *a, const char *b) {
  while (*a && *b) {
    if (tolower((unsigned char)*a) != tolower((unsigned char)*b)) return false;
    ++a;
    ++b;
  }
  return *a == '\0' && *b == '\0';
}

bool startsWithIgnoreCase(const char *text, const char *prefix) {
  while (*prefix) {
    if (!*text) return false;
    if (tolower((unsigned char)*text) != tolower((unsigned char)*prefix)) return false;
    ++text;
    ++prefix;
  }
  return true;
}

bool parseIntStrict(const char *token, long minValue, long maxValue, long &value) {
  if (!token || !*token) return false;

  char *end = nullptr;
  long parsed = strtol(token, &end, 10);

  if (end == token || *end != '\0') return false;
  if (parsed < minValue || parsed > maxValue) return false;

  value = parsed;
  return true;
}

bool parsePulseTokenGroup(char *group, PulseCommand &cmd) {
  char *tokens[4] = {nullptr, nullptr, nullptr, nullptr};
  uint8_t count = 0;

  char *token = strtok(group, " \t");
  while (token && count < 4) {
    tokens[count++] = token;
    token = strtok(nullptr, " \t");
  }

  if (count != 4 || token != nullptr) return false;

  char direction = (char)tolower((unsigned char)tokens[0][0]);
  if ((direction != 'f' && direction != 'b') || tokens[0][1] != '\0') return false;

  long speed = 0;
  long pulses = 0;
  long angle = 0;

  if (!parseIntStrict(tokens[1], 1, 255, speed)) return false;
  if (!parseIntStrict(tokens[2], 1, MAX_PULSES, pulses)) return false;
  if (!parseIntStrict(tokens[3], SERVO_MIN, SERVO_MAX, angle)) return false;

  cmd.direction = direction;
  cmd.speed = (int)speed;
  cmd.pulses = pulses;
  cmd.angle = (int)angle;
  return true;
}

bool validateSequence(const char *sequence) {
  if (!sequence || !*sequence) return false;
  if (strlen(sequence) > MAX_SEQUENCE_CHARS) return false;

  char work[MAX_SEQUENCE_CHARS + 1];
  strncpy(work, sequence, MAX_SEQUENCE_CHARS);
  work[MAX_SEQUENCE_CHARS] = '\0';

  char *cursor = work;

  while (*cursor) {
    while (*cursor && isspace((unsigned char)*cursor)) ++cursor;
    if (!*cursor) break;

    char *groupStart = cursor;
    int fields = 0;

    while (*cursor && fields < 4) {
      while (*cursor && isspace((unsigned char)*cursor)) ++cursor;
      if (!*cursor) break;

      ++fields;
      while (*cursor && !isspace((unsigned char)*cursor)) ++cursor;
    }

    if (fields != 4) return false;
    *cursor = '\0';

    PulseCommand cmd;
    if (!parsePulseTokenGroup(groupStart, cmd)) return false;

    ++cursor;
  }

  return true;
}

bool enqueueSequence(const char *sequence) {
  if (!validateSequence(sequence)) return false;

  char work[MAX_SEQUENCE_CHARS + 1];
  strncpy(work, sequence, MAX_SEQUENCE_CHARS);
  work[MAX_SEQUENCE_CHARS] = '\0';

  char *tokens[32];
  uint8_t tokenCount = 0;

  char *token = strtok(work, " \t");
  while (token && tokenCount < 32) {
    tokens[tokenCount++] = token;
    token = strtok(nullptr, " \t");
  }

  if (token != nullptr || tokenCount == 0 || (tokenCount % 4) != 0) return false;
  if (queueCount + (tokenCount / 4) > PULSE_QUEUE_CAPACITY) return false;

  for (uint8_t i = 0; i < tokenCount; i += 4) {
    PulseCommand cmd;
    char group[48];

    snprintf(group, sizeof(group), "%s %s %s %s",
             tokens[i], tokens[i + 1], tokens[i + 2], tokens[i + 3]);

    if (!parsePulseTokenGroup(group, cmd)) return false;
    if (!enqueuePulse(cmd)) return false;
  }

  return true;
}

/* =========================
   MOTOR / PULSE STATE
   ========================= */
int currentMotorSpeed = 0;
bool directionChangePending = false;
int pendingDirectionSpeed = 0;
uint32_t directionChangeDueMs = 0;

bool pulseActive = false;
bool pulsePaused = false;
PulseCommand activePulse;
long pulseRemaining = 0;
uint32_t pulseLastEncoder = 0;

bool adaptiveActive = false;
int adaptiveTargetSpeed = 0;
int adaptiveCurrentPwm = 0;
uint32_t adaptiveStartedMs = 0;
uint32_t adaptiveLastCheckMs = 0;
uint32_t adaptiveLastEncoder = 0;

bool pendingHostMotorValid = false;
int pendingHostMotor = 0;

bool pendingHostServoValid = false;
int pendingHostServo = SERVO_CENTER;

/* =========================
   LANE / SAFETY STATE
   ========================= */
bool laneChangingMode = true;
char lane = 'R';

enum LaneState {
  LANE_NORMAL = 0,
  LANE_LEFT,
  LANE_RETURNING
};

LaneState laneState = LANE_NORMAL;

bool emergencyStopActive = false;

/* =========================
   TIMING / SERIAL
   ========================= */
uint32_t lastStatusMs = 0;
uint32_t lastButtonPollMs = 0;
uint32_t buttonCandidateSinceMs = 0;

uint32_t loopCounter = 0;
uint32_t lastLoopHzMs = 0;
uint16_t loopHz = 0;

uint8_t buttonStable = 0;
uint8_t buttonCandidate = 0;

char serialBuffer[SERIAL_LINE_MAX + 1];
size_t serialLength = 0;
bool serialOverflow = false;

/* =========================
   SERVO
   ========================= */
int clampServo(int angle) {
  return constrain(angle, SERVO_MIN, SERVO_MAX);
}

void setServo(int angle) {
  angle = clampServo(angle);

  if (pulseActive) {
    pendingHostServo = angle;
    pendingHostServoValid = true;
    return;
  }

  steering.write(angle);
  servoCurrent = angle;
}

void centerServo() {
  steering.write(SERVO_CENTER);
  servoCurrent = SERVO_CENTER;
}

/* =========================
   MOTOR HARDWARE
   ========================= */
void writeMotorHardware(int signedSpeed) {
  signedSpeed = constrain(signedSpeed, -255, 255);

  int magnitude = abs(signedSpeed);
  int direction = (signedSpeed >= 0) ? HIGH : LOW;

  digitalWrite(MOTOR_DIR_LEFT, direction);
  digitalWrite(MOTOR_DIR_RIGHT, direction);
  analogWrite(MOTOR_PWM_LEFT, magnitude);
  analogWrite(MOTOR_PWM_RIGHT, magnitude);

  currentMotorSpeed = signedSpeed;
}

void requestMotorSpeed(int speed) {
  speed = constrain(speed, -255, 255);

  if (pulseActive) {
    if (speed == 0) {
      emergencyStopActive ? writeMotorHardware(0) : void();
      pulsePaused = false;
      pulseActive = false;
      adaptiveActive = false;
      clearPulseQueue();
      pendingHostMotorValid = false;
      pendingHostServoValid = false;
      laneState = LANE_NORMAL;
      lane = 'R';
      centerServo();
      writeMotorHardware(0);
      return;
    }

    pendingHostMotor = speed;
    pendingHostMotorValid = true;
    return;
  }

  if (directionChangePending) {
    if (speed == 0 || (speed > 0) == (pendingDirectionSpeed > 0)) {
      directionChangePending = false;
      pendingDirectionSpeed = 0;
    }
  }

  if (currentMotorSpeed != 0 && speed != 0 &&
      ((currentMotorSpeed > 0) != (speed > 0))) {
    writeMotorHardware(0);
    directionChangePending = true;
    pendingDirectionSpeed = speed;
    directionChangeDueMs = millis() + DIRECTION_DEADTIME_MS;
    return;
  }

  writeMotorHardware(speed);
}

void serviceDirectionChange(uint32_t nowMs) {
  if (!directionChangePending) return;
  if ((int32_t)(nowMs - directionChangeDueMs) < 0) return;

  int speed = pendingDirectionSpeed;
  directionChangePending = false;
  pendingDirectionSpeed = 0;
  writeMotorHardware(speed);
}

/* =========================
   PULSE EXECUTION
   ========================= */
void stopPulseMotionOnly() {
  pulseActive = false;
  pulsePaused = false;
  adaptiveActive = false;
  pulseRemaining = 0;
  writeMotorHardware(0);
}

void beginAdaptiveStartup(int signedSpeed) {
  signedSpeed = constrain(signedSpeed, -255, 255);

  if (signedSpeed == 0) {
    adaptiveActive = false;
    writeMotorHardware(0);
    return;
  }

  adaptiveActive = true;
  adaptiveTargetSpeed = signedSpeed;
  adaptiveCurrentPwm = min(abs(signedSpeed), ADAPTIVE_INITIAL_PWM);
  adaptiveStartedMs = millis();
  adaptiveLastCheckMs = adaptiveStartedMs;
  adaptiveLastEncoder = readEncoder();

  int signedStart = (signedSpeed > 0) ? adaptiveCurrentPwm : -adaptiveCurrentPwm;
  writeMotorHardware(signedStart);
}

void abortPulseSequence() {
  stopPulseMotionOnly();
  clearPulseQueue();
  laneState = LANE_NORMAL;
  lane = 'R';
  centerServo();
  panel.stop();
}

void startPulse(const PulseCommand &cmd) {
  activePulse = cmd;
  pulseRemaining = cmd.pulses;
  pulseActive = true;
  pulsePaused = false;
  resetEncoder();

  int signedSpeed = (cmd.direction == 'f') ? cmd.speed : -cmd.speed;
  beginAdaptiveStartup(signedSpeed);
  steering.write(clampServo(cmd.angle));
  servoCurrent = clampServo(cmd.angle);
}

void startNextPulseOrFinish() {
  PulseCommand next;
  if (dequeuePulse(next)) {
    startPulse(next);
    return;
  }

  pulseActive = false;
  pulsePaused = false;
  adaptiveActive = false;
  writeMotorHardware(0);
  centerServo();

  if (laneState == LANE_RETURNING) {
    laneState = LANE_NORMAL;
    lane = 'R';
    panel.clear();
  } else if (laneState == LANE_LEFT) {
    panel.left();
  } else {
    panel.clear();
  }

  if (pendingHostServoValid) {
    steering.write(clampServo(pendingHostServo));
    servoCurrent = clampServo(pendingHostServo);
    pendingHostServoValid = false;
  }

  if (pendingHostMotorValid) {
    int speed = pendingHostMotor;
    pendingHostMotorValid = false;
    requestMotorSpeed(speed);
  }
}

void pausePulseMotion() {
  if (!pulseActive || pulsePaused) return;

  uint32_t traveled = readEncoder();
  if ((long)traveled >= pulseRemaining) {
    pulseRemaining = 0;
  } else {
    pulseRemaining -= (long)traveled;
  }

  writeMotorHardware(0);
  adaptiveActive = false;
  pulsePaused = true;
  resetEncoder();

  if (pulseRemaining <= 0) {
    startNextPulseOrFinish();
  }
}

void resumePulseMotion() {
  if (!pulseActive || !pulsePaused) return;

  pulsePaused = false;
  resetEncoder();

  int signedSpeed = (activePulse.direction == 'f') ? activePulse.speed : -activePulse.speed;
  beginAdaptiveStartup(signedSpeed);
}

void updateAdaptiveStartup(uint32_t nowMs) {
  if (!adaptiveActive || !pulseActive || pulsePaused) return;

  if ((uint32_t)(nowMs - adaptiveLastCheckMs) < ADAPTIVE_CHECK_MS) return;

  uint32_t encoderNow = readEncoder();

  if (encoderNow != adaptiveLastEncoder) {
    adaptiveActive = false;
    return;
  }

  if ((uint32_t)(nowMs - adaptiveStartedMs) >= PULSE_STALL_TIMEOUT_MS) {
    abortPulseSequence();
    return;
  }

  int targetMagnitude = abs(adaptiveTargetSpeed);
  if (adaptiveCurrentPwm < targetMagnitude) {
    adaptiveCurrentPwm += ADAPTIVE_STEP_PWM;
    if (adaptiveCurrentPwm > targetMagnitude) adaptiveCurrentPwm = targetMagnitude;

    int signedSpeed = (adaptiveTargetSpeed > 0) ? adaptiveCurrentPwm : -adaptiveCurrentPwm;
    writeMotorHardware(signedSpeed);
  }

  adaptiveLastEncoder = encoderNow;
  adaptiveLastCheckMs = nowMs;
}

void updatePulseMotion(uint32_t nowMs) {
  if (!pulseActive) return;

  updateAdaptiveStartup(nowMs);

  if (!pulseActive || pulsePaused) return;

  if (pulseObstacle()) {
    pausePulseMotion();
    return;
  }

  uint32_t encoderNow = readEncoder();
  if ((long)encoderNow >= pulseRemaining) {
    startNextPulseOrFinish();
  }
}

/* =========================
   LANE CONTROL
   ========================= */
void startLaneChangeLeft() {
  if (!laneChangingMode || laneState != LANE_NORMAL || pulseActive) return;
  if (!validateSequence(laneConfig.leftSequence)) {
    abortPulseSequence();
    return;
  }

  clearPulseQueue();
  if (!enqueueSequence(laneConfig.leftSequence)) {
    abortPulseSequence();
    return;
  }

  laneState = LANE_LEFT;
  lane = 'L';
  panel.left();
  startNextPulseOrFinish();
}

void startReturnToRightLane() {
  if (laneState != LANE_LEFT || pulseActive) return;
  if (!validateSequence(laneConfig.rightSequence)) {
    abortPulseSequence();
    return;
  }

  clearPulseQueue();
  if (!enqueueSequence(laneConfig.rightSequence)) {
    abortPulseSequence();
    return;
  }

  laneState = LANE_RETURNING;
  lane = 'R';
  panel.right();
  startNextPulseOrFinish();
}

/* =========================
   FORCE STOP
   ========================= */
void clearSerialState() {
  serialLength = 0;
  serialBuffer[0] = '\0';
  serialOverflow = false;

  while (Serial.available() > 0) Serial.read();
}

void enterForceStop() {
  emergencyStopActive = true;

  clearPulseQueue();
  pulseActive = false;
  pulsePaused = false;
  adaptiveActive = false;

  pendingHostMotorValid = false;
  pendingHostServoValid = false;

  laneState = LANE_NORMAL;
  lane = 'R';

  directionChangePending = false;
  pendingDirectionSpeed = 0;

  writeMotorHardware(0);
  centerServo();
  clearSerialState();
  panel.forceStop();
}

void exitForceStop() {
  emergencyStopActive = false;
  clearSerialState();
  writeMotorHardware(0);
  centerServo();
  panel.clear();
}

/* =========================
   BUTTONS
   ========================= */
void handleButtons(uint32_t nowMs) {
  if ((uint32_t)(nowMs - lastButtonPollMs) < BUTTON_POLL_MS) return;
  lastButtonPollMs = nowMs;

  uint8_t raw = panel.buttons();

  if (raw != buttonCandidate) {
    buttonCandidate = raw;
    buttonCandidateSinceMs = nowMs;
    return;
  }

  if (buttonCandidate != buttonStable &&
      (uint32_t)(nowMs - buttonCandidateSinceMs) >= BUTTON_DEBOUNCE_MS) {
    uint8_t rising = (uint8_t)(buttonCandidate & (uint8_t)~buttonStable);
    buttonStable = buttonCandidate;

    if (rising & (uint8_t)(1U << TM_FORCE_STOP_KEY_BIT)) {
      enterForceStop();
    }

    if (rising & (uint8_t)(1U << TM_RESUME_KEY_BIT)) {
      exitForceStop();
    }
  }
}

/* =========================
   SERIAL
   ========================= */
void processSerialLine(char *rawLine);

void pollSerial() {
  const size_t MAX_BYTES_PER_LOOP = 256;
  size_t processed = 0;

  while (Serial.available() > 0 && processed < MAX_BYTES_PER_LOOP) {
    char c = (char)Serial.read();
    ++processed;

    if (c == '\n' || c == '\r') {
      if (serialOverflow) {
        serialOverflow = false;
        serialLength = 0;
        serialBuffer[0] = '\0';
        continue;
      }

      if (serialLength > 0) {
        serialBuffer[serialLength] = '\0';
        processSerialLine(serialBuffer);
        serialLength = 0;
        serialBuffer[0] = '\0';
      }
      continue;
    }

    if (serialOverflow) continue;

    if (serialLength < SERIAL_LINE_MAX) {
      serialBuffer[serialLength++] = c;
      serialBuffer[serialLength] = '\0';
    } else {
      serialOverflow = true;
      serialLength = 0;
      serialBuffer[0] = '\0';
    }
  }
}

void handlePulseCommandLine(const char *line) {
  if (pulseActive) {
    if (queueCount >= PULSE_QUEUE_CAPACITY) return;

    char copy[MAX_SEQUENCE_CHARS + 1];
    strncpy(copy, line, MAX_SEQUENCE_CHARS);
    copy[MAX_SEQUENCE_CHARS] = '\0';

    enqueueSequence(copy);
    return;
  }

  clearPulseQueue();

  if (enqueueSequence(line)) {
    startNextPulseOrFinish();
  }
}

void processSerialLine(char *rawLine) {
  char lineCopy[SERIAL_LINE_MAX + 1];
  strncpy(lineCopy, rawLine, SERIAL_LINE_MAX);
  lineCopy[SERIAL_LINE_MAX] = '\0';

  char *line = trim(lineCopy);
  if (!*line) return;

  if (emergencyStopActive) {
    if (equalsIgnoreCase(line, "resume")) exitForceStop();
    return;
  }

  if (equalsIgnoreCase(line, "stop")) {
    clearPulseQueue();
    pulseActive = false;
    pulsePaused = false;
    adaptiveActive = false;
    pendingHostMotorValid = false;
    pendingHostServoValid = false;
    laneState = LANE_NORMAL;
    lane = 'R';
    directionChangePending = false;
    pendingDirectionSpeed = 0;
    writeMotorHardware(0);
    centerServo();
    panel.stop();
    return;
  }

  if (equalsIgnoreCase(line, "resume")) {
    exitForceStop();
    return;
  }

  if (equalsIgnoreCase(line, "left")) {
    panel.left();
    return;
  }

  if (equalsIgnoreCase(line, "right")) {
    panel.right();
    return;
  }

  if (equalsIgnoreCase(line, "clear") ||
      equalsIgnoreCase(line, "clear leds") ||
      equalsIgnoreCase(line, "clearleds")) {
    panel.clear();
    return;
  }

  if (equalsIgnoreCase(line, "allleds") ||
      equalsIgnoreCase(line, "all leds on")) {
    panel.allOn();
    return;
  }

  if (startsWithIgnoreCase(line, "motor ")) {
    long speed = 0;
    if (parseIntStrict(trim(line + 6), -255, 255, speed)) {
      requestMotorSpeed((int)speed);
    }
    return;
  }

  if (startsWithIgnoreCase(line, "servo ")) {
    long angle = 0;
    if (parseIntStrict(trim(line + 6), SERVO_MIN, SERVO_MAX, angle)) {
      setServo((int)angle);
    }
    return;
  }

  if (startsWithIgnoreCase(line, "set left ")) {
    char *sequence = trim(line + 9);
    if (validateSequence(sequence)) {
      strncpy(laneConfig.leftSequence, sequence, MAX_SEQUENCE_CHARS);
      laneConfig.leftSequence[MAX_SEQUENCE_CHARS] = '\0';
    }
    return;
  }

  if (startsWithIgnoreCase(line, "set right ")) {
    char *sequence = trim(line + 10);
    if (validateSequence(sequence)) {
      strncpy(laneConfig.rightSequence, sequence, MAX_SEQUENCE_CHARS);
      laneConfig.rightSequence[MAX_SEQUENCE_CHARS] = '\0';
    }
    return;
  }

  if (equalsIgnoreCase(line, "save") ||
      equalsIgnoreCase(line, "save left") ||
      equalsIgnoreCase(line, "save right")) {
    saveLaneConfig();
    return;
  }

  if (equalsIgnoreCase(line, "load")) {
    loadLaneConfig();
    return;
  }

  if (equalsIgnoreCase(line, "lane auto")) {
    laneChangingMode = true;
    return;
  }

  if (equalsIgnoreCase(line, "lane manual") ||
      equalsIgnoreCase(line, "lane stop")) {
    laneChangingMode = false;
    return;
  }

  if (equalsIgnoreCase(line, "status") ||
      equalsIgnoreCase(line, "u")) {
    sendStatus();
    return;
  }

  handlePulseCommandLine(line);
}

/* =========================
   TELEMETRY
   ========================= */
char motionChar() {
  if (currentMotorSpeed == 0) return 'S';
  return currentMotorSpeed > 0 ? 'F' : 'B';
}

void sendStatus() {
  if (Serial.availableForWrite() < 32) return;

  Serial.print(lane);
  Serial.print(' ');
  Serial.print(motionChar());
  Serial.print(' ');
  Serial.print(ultraCm(1));
  Serial.print(' ');
  Serial.print(ultraCm(0));
  Serial.print(' ');
  Serial.print(loopHz);
  Serial.print(' ');
  Serial.println(pulseActive ? 1 : 0);
}

/* =========================
   SETUP / LOOP
   ========================= */
void setup() {
#if defined(__AVR__)
  MCUSR = 0;
  wdt_disable();
#endif

  pinMode(MOTOR_PWM_LEFT, OUTPUT);
  pinMode(MOTOR_DIR_LEFT, OUTPUT);
  pinMode(MOTOR_PWM_RIGHT, OUTPUT);
  pinMode(MOTOR_DIR_RIGHT, OUTPUT);

  analogWrite(MOTOR_PWM_LEFT, 0);
  analogWrite(MOTOR_PWM_RIGHT, 0);
  digitalWrite(MOTOR_DIR_LEFT, LOW);
  digitalWrite(MOTOR_DIR_RIGHT, LOW);

  Serial.begin(BAUD_RATE);

  attachInterrupt(digitalPinToInterrupt(ENCODER_PIN), encoderISR, FALLING);
  resetEncoder();

  beginUltra(0, ULTRA_LEFT_TRIG, ULTRA_LEFT_ECHO, 0);
  beginUltra(1, ULTRA_RIGHT_TRIG, ULTRA_RIGHT_ECHO, 40);
  beginUltra(2, ULTRA_SIDE_TRIG, ULTRA_SIDE_ECHO, 80);

  steering.attach(SERVO_PIN);
  centerServo();

  loadLaneConfig();

  panel.begin(TM_STB_PIN, TM_CLK_PIN, TM_DIO_PIN);
  panel.clear();

  lastLoopHzMs = millis();
  lastStatusMs = lastLoopHzMs;

#if defined(__AVR__)
  wdt_enable(WDTO_2S);
#endif
}

void loop() {
#if defined(__AVR__)
  wdt_reset();
#endif

  uint32_t nowMs = millis();

  ++loopCounter;
  if ((uint32_t)(nowMs - lastLoopHzMs) >= 1000UL) {
    loopHz = (uint16_t)min(loopCounter, 65535UL);
    loopCounter = 0;
    lastLoopHzMs = nowMs;
  }

  panel.update(nowMs);
  handleButtons(nowMs);
  pollSerial();
  updateUltra(nowMs);
  serviceDirectionChange(nowMs);

  if (emergencyStopActive) {
    if ((uint32_t)(nowMs - lastStatusMs) >= STATUS_INTERVAL_MS) {
      lastStatusMs = nowMs;
      sendStatus();
    }
    return;
  }

  if (pulseActive) {
    updatePulseMotion(nowMs);

    if (pulseActive && pulsePaused && !pulseObstacle()) {
      resumePulseMotion();
    }
  } else {
    if (lane == 'R' && normalObstacle()) {
      if (!laneChangingMode) {
        clearPulseQueue();
        writeMotorHardware(0);
        centerServo();
        panel.stop();
      } else if (laneState == LANE_NORMAL) {
        startLaneChangeLeft();
      }
    }

    if (laneState == LANE_LEFT) {
      int sideDistance = ultraCm(2);
      if (sideDistance > 0 && sideDistance <= SIDE_RETURN_DISTANCE_CM) {
        startReturnToRightLane();
      }
    }

    if (pendingHostServoValid) {
      steering.write(clampServo(pendingHostServo));
      servoCurrent = clampServo(pendingHostServo);
      pendingHostServoValid = false;
    }

    if (pendingHostMotorValid) {
      int speed = pendingHostMotor;
      pendingHostMotorValid = false;
      requestMotorSpeed(speed);
    }
  }

  if ((uint32_t)(nowMs - lastStatusMs) >= STATUS_INTERVAL_MS) {
    lastStatusMs = nowMs;
    sendStatus();
  }
}
