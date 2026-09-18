#include <Arduino.h>
#include <Servo.h>
#include <EEPROM.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#if defined(__AVR__)
#include <avr/wdt.h>
#endif

/*
 * Self Driving Robot - configurable Arduino firmware v1
 *
 * This firmware is intentionally separate from all existing firmware files.
 * It requires a Python-side hardware contract before motion is enabled.
 *
 * Protocol:
 *   HELLO main_configurable_v1 1 mega2560
 *   cfg begin <config_id>
 *   cfg motor <id> <pwm> <dir>
 *   cfg servo <id> <pin> <min> <max> <center>
 *   cfg ultrasonic <name> <trig> <echo>
 *   cfg encoder <id> <pin>
 *   cfg tm1638 <stb> <clk> <dio> <force_button> <resume_button>
 *   cfg option <name> <value>
 *   cfg end <config_id> <fnv32>
 *
 * After cfg end succeeds, the Arduino echoes every accepted module/option and
 * then reports:
 *   CFG READY <config_id> <fnv32>
 *
 * Runtime commands remain compatible with the current Python controller:
 *   motor [id] <speed>
 *   servo [id] <angle>
 *   stop
 *   resume
 *   left
 *   right
 *   set left <pulse sequence>
 *   set right <pulse sequence>
 *   save left
 *   save right
 *   load
 *   heartbeat
 *   status
 *   f <speed> <pulses> <angle> [f|b <speed> <pulses> <angle>]...
 */

const uint32_t BAUD_RATE = 115200UL;
const uint32_t STATUS_INTERVAL_MS = 50UL;
const uint32_t BUTTON_POLL_MS = 25UL;
const uint32_t BUTTON_DEBOUNCE_MS = 35UL;
const uint32_t ULTRA_TIMEOUT_US = 30000UL;
const uint32_t ULTRA_COOLDOWN_US = 3000UL;
const uint32_t ADAPTIVE_CHECK_MS = 50UL;
const uint8_t ADAPTIVE_INITIAL_PWM = 160;
const uint8_t ADAPTIVE_STEP_PWM = 20;
const uint32_t EEPROM_MAGIC = 0x53445231UL;

const uint8_t MAX_MOTORS = 4;
const uint8_t MAX_SERVOS = 4;
const uint8_t MAX_ULTRASONICS = 8;
const uint8_t MAX_ENCODERS = 4;
const uint8_t MAX_SEQUENCE_CHARS = 127;
const uint8_t PULSE_QUEUE_CAPACITY = 16;
const uint32_t MAX_PULSES = 1000000UL;
const size_t SERIAL_LINE_MAX = 191;
const uint8_t MAX_TOKENS = 64;

const char FIRMWARE_ID[] = "main_configurable_v1";
const char BOARD_ID[] = "mega2560";
const uint8_t PROTOCOL_VERSION = 1;

struct MotorModule {
  uint8_t id;
  uint8_t pwm;
  uint8_t dir;
};

struct ServoModule {
  uint8_t id;
  uint8_t pin;
  uint8_t minAngle;
  uint8_t maxAngle;
  uint8_t center;
};

struct UltrasonicModule {
  char name[17];
  uint8_t trig;
  uint8_t echo;
  int distanceCm;
  bool valid;
  uint32_t nextDueMs;
};

struct EncoderModule {
  uint8_t id;
  uint8_t pin;
};

struct TM1638Module {
  uint8_t stb;
  uint8_t clk;
  uint8_t dio;
  uint8_t forceStopButton;
  uint8_t resumeButton;
  bool enabled;
};

struct SafetyOptions {
  uint16_t stopDistanceCm;
  uint16_t pulseStopDistanceCm;
  uint16_t sideReturnDistanceCm;
  uint16_t ultrasonicIntervalMs;
  uint16_t hostHeartbeatTimeoutMs;
  uint16_t pulseStallTimeoutMs;
  uint16_t directionDeadtimeMs;
};

struct HardwareConfig {
  MotorModule motors[MAX_MOTORS];
  ServoModule servos[MAX_SERVOS];
  UltrasonicModule ultras[MAX_ULTRASONICS];
  EncoderModule encoders[MAX_ENCODERS];
  TM1638Module tm;
  SafetyOptions options;
  uint8_t motorCount;
  uint8_t servoCount;
  uint8_t ultraCount;
  uint8_t encoderCount;
  bool active;
  char configId[33];
};

HardwareConfig pendingConfig;
HardwareConfig activeConfig;

Servo servoObjects[MAX_SERVOS];

volatile uint32_t encoderPulses[MAX_ENCODERS] = {0, 0, 0, 0};
volatile uint32_t encoderLastUs[MAX_ENCODERS] = {0, 0, 0, 0};

void encoderISR0() { ++encoderPulses[0]; }
void encoderISR1() { ++encoderPulses[1]; }
void encoderISR2() { ++encoderPulses[2]; }
void encoderISR3() { ++encoderPulses[3]; }

void (*encoderISRTable[MAX_ENCODERS])() = {
  encoderISR0, encoderISR1, encoderISR2, encoderISR3
};

struct PulseCommand {
  char direction;
  uint8_t speed;
  uint32_t pulses;
  uint8_t angle;
};

PulseCommand pulseQueue[PULSE_QUEUE_CAPACITY];
uint8_t queueHead = 0;
uint8_t queueTail = 0;
uint8_t queueCount = 0;

PulseCommand activePulse = {'f', 0, 0, 90};
bool pulseActive = false;
bool pulsePaused = false;
uint32_t pulseRemaining = 0;
uint32_t pulseLastEncoder = 0;
uint32_t pulseLastProgressMs = 0;

bool adaptiveActive = false;
uint8_t adaptiveCurrentPwm = 0;
uint32_t adaptiveLastCheckMs = 0;

int currentMotorSpeed = 0;
bool directionChangePending = false;
int pendingDirectionSpeed = 0;
uint32_t directionChangeDueMs = 0;

int pendingHostMotor = 0;
bool pendingHostMotorValid = false;
int pendingHostServo = 90;
bool pendingHostServoValid = false;

bool forceStopActive = false;
bool emergencyStopActive = false;

char leftSequence[MAX_SEQUENCE_CHARS + 1];
char rightSequence[MAX_SEQUENCE_CHARS + 1];

uint32_t lastHostHeartbeatMs = 0;
bool hostHeartbeatSeen = false;
bool hostTimeoutReported = false;

uint32_t lastStatusMs = 0;
uint32_t lastLoopHzMs = 0;
uint32_t loopCounter = 0;
uint16_t loopHz = 0;

uint32_t lastButtonPollMs = 0;
uint8_t buttonCandidate = 0;
uint8_t buttonStable = 0;
uint32_t buttonCandidateSinceMs = 0;

char serialBuffer[SERIAL_LINE_MAX + 1];
size_t serialLength = 0;
bool serialOverflow = false;

uint8_t activeUltra = 0;
bool ultraBusy = false;
bool waitingRise = false;
bool waitingFall = false;
uint32_t ultraStartedUs = 0;
uint32_t echoStartedUs = 0;
uint32_t ultraCooldownUntilUs = 0;

char lane = 'R';

uint16_t eepromChecksum(const uint8_t *data, size_t length) {
  uint16_t sum = 0xA55A;
  for (size_t i = 0; i < length; ++i) {
    sum = (uint16_t)(sum ^ data[i]);
    sum = (uint16_t)((sum << 1) | (sum >> 15));
  }
  return sum;
}

struct LaneStorage {
  uint32_t magic;
  char left[MAX_SEQUENCE_CHARS + 1];
  char right[MAX_SEQUENCE_CHARS + 1];
  uint16_t checksum;
};

void setDefaultLaneSequences() {
  strncpy(leftSequence, "b 255 4 50 b 255 3 130", MAX_SEQUENCE_CHARS);
  leftSequence[MAX_SEQUENCE_CHARS] = '\0';
  strncpy(rightSequence, "f 255 3 130 f 255 3 50", MAX_SEQUENCE_CHARS);
  rightSequence[MAX_SEQUENCE_CHARS] = '\0';
}

void loadLaneSequences() {
  LaneStorage storage;
  EEPROM.get(0, storage);

  const uint8_t *data = reinterpret_cast<const uint8_t *>(&storage);
  const size_t checkLength = sizeof(LaneStorage) - sizeof(storage.checksum);

  if (storage.magic != EEPROM_MAGIC ||
      storage.checksum != eepromChecksum(data, checkLength) ||
      boundedLength(storage.left, sizeof(storage.left)) >= sizeof(storage.left) ||
      boundedLength(storage.right, sizeof(storage.right)) >= sizeof(storage.right)) {
    setDefaultLaneSequences();
    return;
  }

  strncpy(leftSequence, storage.left, MAX_SEQUENCE_CHARS);
  leftSequence[MAX_SEQUENCE_CHARS] = '\0';
  strncpy(rightSequence, storage.right, MAX_SEQUENCE_CHARS);
  rightSequence[MAX_SEQUENCE_CHARS] = '\0';
}

void saveLaneSequences(bool saveLeft, bool saveRight) {
  LaneStorage storage;
  storage.magic = EEPROM_MAGIC;
  strncpy(storage.left, leftSequence, MAX_SEQUENCE_CHARS);
  storage.left[MAX_SEQUENCE_CHARS] = '\0';
  strncpy(storage.right, rightSequence, MAX_SEQUENCE_CHARS);
  storage.right[MAX_SEQUENCE_CHARS] = '\0';
  storage.checksum = 0;

  uint8_t *data = reinterpret_cast<uint8_t *>(&storage);
  storage.checksum = eepromChecksum(data, sizeof(LaneStorage) - sizeof(storage.checksum));

  LaneStorage current;
  EEPROM.get(0, current);

  const uint8_t *currentData = reinterpret_cast<const uint8_t *>(&current);
  if (current.magic != EEPROM_MAGIC ||
      current.checksum != eepromChecksum(currentData, sizeof(LaneStorage) - sizeof(current.checksum)) ||
      boundedLength(current.left, sizeof(current.left)) >= sizeof(current.left) ||
      boundedLength(current.right, sizeof(current.right)) >= sizeof(current.right)) {
    current = storage;
  }

  if (saveLeft) {
    strncpy(current.left, storage.left, MAX_SEQUENCE_CHARS);
    current.left[MAX_SEQUENCE_CHARS] = '\0';
  }
  if (saveRight) {
    strncpy(current.right, storage.right, MAX_SEQUENCE_CHARS);
    current.right[MAX_SEQUENCE_CHARS] = '\0';
  }
  current.magic = EEPROM_MAGIC;
  current.checksum = 0;
  current.checksum = eepromChecksum(
      reinterpret_cast<const uint8_t *>(&current),
      sizeof(LaneStorage) - sizeof(current.checksum)
  );
  EEPROM.put(0, current);
}

uint32_t fnv1aStart() {
  return 0x811C9DC5UL;
}

void fnv1aAdd(uint32_t &hash, const char *text) {
  while (*text) {
    hash ^= (uint8_t)*text++;
    hash *= 0x01000193UL;
  }
}

uint32_t configFingerprint(const HardwareConfig &cfg) {
  uint32_t hash = fnv1aStart();
  char line[80];

  for (uint8_t i = 0; i < cfg.motorCount; ++i) {
    snprintf(line, sizeof(line), "motor %u %u %u\n",
             cfg.motors[i].id, cfg.motors[i].pwm, cfg.motors[i].dir);
    fnv1aAdd(hash, line);
  }

  for (uint8_t i = 0; i < cfg.servoCount; ++i) {
    snprintf(line, sizeof(line), "servo %u %u %u %u %u\n",
             cfg.servos[i].id,
             cfg.servos[i].pin,
             cfg.servos[i].minAngle,
             cfg.servos[i].maxAngle,
             cfg.servos[i].center);
    fnv1aAdd(hash, line);
  }

  for (uint8_t i = 0; i < cfg.ultraCount; ++i) {
    snprintf(line, sizeof(line), "ultrasonic %s %u %u\n",
             cfg.ultras[i].name,
             cfg.ultras[i].trig,
             cfg.ultras[i].echo);
    fnv1aAdd(hash, line);
  }

  for (uint8_t i = 0; i < cfg.encoderCount; ++i) {
    snprintf(line, sizeof(line), "encoder %u %u\n",
             cfg.encoders[i].id, cfg.encoders[i].pin);
    fnv1aAdd(hash, line);
  }

  if (cfg.tm.enabled) {
    snprintf(line, sizeof(line), "tm1638 %u %u %u %u %u\n",
             cfg.tm.stb, cfg.tm.clk, cfg.tm.dio,
             cfg.tm.forceStopButton, cfg.tm.resumeButton);
    fnv1aAdd(hash, line);
  }

  snprintf(line, sizeof(line), "option stop_distance_cm %u\n", cfg.options.stopDistanceCm);
  fnv1aAdd(hash, line);
  snprintf(line, sizeof(line), "option pulse_stop_distance_cm %u\n", cfg.options.pulseStopDistanceCm);
  fnv1aAdd(hash, line);
  snprintf(line, sizeof(line), "option side_return_distance_cm %u\n", cfg.options.sideReturnDistanceCm);
  fnv1aAdd(hash, line);
  snprintf(line, sizeof(line), "option ultrasonic_interval_ms %u\n", cfg.options.ultrasonicIntervalMs);
  fnv1aAdd(hash, line);
  snprintf(line, sizeof(line), "option host_heartbeat_timeout_ms %u\n", cfg.options.hostHeartbeatTimeoutMs);
  fnv1aAdd(hash, line);
  snprintf(line, sizeof(line), "option pulse_stall_timeout_ms %u\n", cfg.options.pulseStallTimeoutMs);
  fnv1aAdd(hash, line);
  snprintf(line, sizeof(line), "option direction_deadtime_ms %u\n", cfg.options.directionDeadtimeMs);
  fnv1aAdd(hash, line);

  return hash;
}

void resetConfig(HardwareConfig &cfg) {
  memset(&cfg, 0, sizeof(cfg));
  cfg.options.stopDistanceCm = 35;
  cfg.options.pulseStopDistanceCm = 10;
  cfg.options.sideReturnDistanceCm = 20;
  cfg.options.ultrasonicIntervalMs = 50;
  cfg.options.hostHeartbeatTimeoutMs = 500;
  cfg.options.pulseStallTimeoutMs = 900;
  cfg.options.directionDeadtimeMs = 15;
  cfg.active = false;
  cfg.configId[0] = '\0';
}

bool validPin(uint8_t pin) {
  return pin >= 2 && pin <= 53;
}

bool isPwmPin(uint8_t pin) {
  return (pin >= 2 && pin <= 13) || (pin >= 44 && pin <= 46);
}

bool isInterruptPin(uint8_t pin) {
  return pin == 2 || pin == 3 || pin == 18 ||
         pin == 19 || pin == 20 || pin == 21;
}

bool pinAlreadyUsed(const HardwareConfig &cfg, uint8_t pin) {
  for (uint8_t i = 0; i < cfg.motorCount; ++i) {
    if (cfg.motors[i].pwm == pin || cfg.motors[i].dir == pin) return true;
  }
  for (uint8_t i = 0; i < cfg.servoCount; ++i) {
    if (cfg.servos[i].pin == pin) return true;
  }
  for (uint8_t i = 0; i < cfg.ultraCount; ++i) {
    if (cfg.ultras[i].trig == pin || cfg.ultras[i].echo == pin) return true;
  }
  for (uint8_t i = 0; i < cfg.encoderCount; ++i) {
    if (cfg.encoders[i].pin == pin) return true;
  }
  if (cfg.tm.enabled &&
      (cfg.tm.stb == pin || cfg.tm.clk == pin || cfg.tm.dio == pin)) {
    return true;
  }
  return false;
}

bool duplicateUltraName(const HardwareConfig &cfg, const char *name) {
  for (uint8_t i = 0; i < cfg.ultraCount; ++i) {
    if (strcmp(cfg.ultras[i].name, name) == 0) return true;
  }
  return false;
}

bool validateConfig(const HardwareConfig &cfg, char *error, size_t errorSize) {
  if (cfg.motorCount > MAX_MOTORS ||
      cfg.servoCount > MAX_SERVOS ||
      cfg.ultraCount > MAX_ULTRASONICS ||
      cfg.encoderCount > MAX_ENCODERS) {
    snprintf(error, errorSize, "COUNT_LIMIT");
    return false;
  }

  if (cfg.tm.enabled) {
    if (cfg.tm.stb == cfg.tm.clk || cfg.tm.stb == cfg.tm.dio ||
        cfg.tm.clk == cfg.tm.dio ||
        cfg.tm.forceStopButton > 7 || cfg.tm.resumeButton > 7) {
      snprintf(error, errorSize, "TM1638_PINS");
      return false;
    }
  }

  for (uint8_t i = 0; i < cfg.motorCount; ++i) {
    if (cfg.motors[i].id != i) {
      snprintf(error, errorSize, "MOTOR_IDS");
      return false;
    }
    if (!validPin(cfg.motors[i].pwm) || !validPin(cfg.motors[i].dir) ||
        cfg.motors[i].pwm == cfg.motors[i].dir ||
        !isPwmPin(cfg.motors[i].pwm)) {
      snprintf(error, errorSize, "MOTOR_PIN");
      return false;
    }
  }

  for (uint8_t i = 0; i < cfg.servoCount; ++i) {
    if (cfg.servos[i].id != i ||
        !validPin(cfg.servos[i].pin) ||
        cfg.servos[i].minAngle > cfg.servos[i].center ||
        cfg.servos[i].center > cfg.servos[i].maxAngle ||
        cfg.servos[i].maxAngle > 180) {
      snprintf(error, errorSize, "SERVO_CONFIG");
      return false;
    }
  }

  for (uint8_t i = 0; i < cfg.encoderCount; ++i) {
    if (cfg.encoders[i].id != i ||
        !validPin(cfg.encoders[i].pin) ||
        !isInterruptPin(cfg.encoders[i].pin)) {
      snprintf(error, errorSize, "ENCODER_PIN");
      return false;
    }
  }

  for (uint8_t i = 0; i < cfg.ultraCount; ++i) {
    if (!validPin(cfg.ultras[i].trig) ||
        !validPin(cfg.ultras[i].echo) ||
        cfg.ultras[i].trig == cfg.ultras[i].echo ||
        cfg.ultras[i].name[0] == '\0') {
      snprintf(error, errorSize, "ULTRA_CONFIG");
      return false;
    }
  }

  if (cfg.tm.enabled) {
    if (!validPin(cfg.tm.stb) || !validPin(cfg.tm.clk) || !validPin(cfg.tm.dio)) {
      snprintf(error, errorSize, "TM1638_CONFIG");
      return false;
    }
  }

  for (uint8_t pin = 2; pin <= 53; ++pin) {
    uint8_t hits = 0;
    for (uint8_t i = 0; i < cfg.motorCount; ++i) {
      if (cfg.motors[i].pwm == pin) ++hits;
      if (cfg.motors[i].dir == pin) ++hits;
    }
    for (uint8_t i = 0; i < cfg.servoCount; ++i) {
      if (cfg.servos[i].pin == pin) ++hits;
    }
    for (uint8_t i = 0; i < cfg.ultraCount; ++i) {
      if (cfg.ultras[i].trig == pin) ++hits;
      if (cfg.ultras[i].echo == pin) ++hits;
    }
    for (uint8_t i = 0; i < cfg.encoderCount; ++i) {
      if (cfg.encoders[i].pin == pin) ++hits;
    }
    if (cfg.tm.enabled) {
      if (cfg.tm.stb == pin) ++hits;
      if (cfg.tm.clk == pin) ++hits;
      if (cfg.tm.dio == pin) ++hits;
    }
    if (hits > 1) {
      snprintf(error, errorSize, "PIN_CONFLICT_%u", pin);
      return false;
    }
  }

  return true;
}

size_t boundedLength(const char *text, size_t maximum) {
  size_t length = 0;
  while (length < maximum && text[length] != ' ') {
    ++length;
  }
  return length;
}

bool parseLongStrict(const char *text, long minimum, long maximum, long &out) {
  if (!text || !*text) return false;
  char *end = nullptr;
  long value = strtol(text, &end, 10);
  if (end == text || *end != '\0' || value < minimum || value > maximum) {
    return false;
  }
  out = value;
  return true;
}

bool parseHex32(const char *text, uint32_t &out) {
  if (!text || !*text) return false;
  char *end = nullptr;
  unsigned long value = strtoul(text, &end, 16);
  if (end == text || *end != '\0') return false;
  out = (uint32_t)value;
  return true;
}

void echoConfig(const HardwareConfig &cfg) {
  char line[96];

  for (uint8_t i = 0; i < cfg.motorCount; ++i) {
    snprintf(line, sizeof(line), "CFG ECHO %s motor %u %u %u",
             cfg.configId, cfg.motors[i].id, cfg.motors[i].pwm, cfg.motors[i].dir);
    Serial.println(line);
  }

  for (uint8_t i = 0; i < cfg.servoCount; ++i) {
    snprintf(line, sizeof(line), "CFG ECHO %s servo %u %u %u %u %u",
             cfg.configId, cfg.servos[i].id, cfg.servos[i].pin,
             cfg.servos[i].minAngle, cfg.servos[i].maxAngle, cfg.servos[i].center);
    Serial.println(line);
  }

  for (uint8_t i = 0; i < cfg.ultraCount; ++i) {
    snprintf(line, sizeof(line), "CFG ECHO %s ultrasonic %s %u %u",
             cfg.configId, cfg.ultras[i].name,
             cfg.ultras[i].trig, cfg.ultras[i].echo);
    Serial.println(line);
  }

  for (uint8_t i = 0; i < cfg.encoderCount; ++i) {
    snprintf(line, sizeof(line), "CFG ECHO %s encoder %u %u",
             cfg.configId, cfg.encoders[i].id, cfg.encoders[i].pin);
    Serial.println(line);
  }

  if (cfg.tm.enabled) {
    snprintf(line, sizeof(line), "CFG ECHO %s tm1638 %u %u %u %u %u",
             cfg.configId, cfg.tm.stb, cfg.tm.clk, cfg.tm.dio,
             cfg.tm.forceStopButton, cfg.tm.resumeButton);
    Serial.println(line);
  }

  snprintf(line, sizeof(line), "CFG ECHO %s option stop_distance_cm %u",
           cfg.configId, cfg.options.stopDistanceCm);
  Serial.println(line);
  snprintf(line, sizeof(line), "CFG ECHO %s option pulse_stop_distance_cm %u",
           cfg.configId, cfg.options.pulseStopDistanceCm);
  Serial.println(line);
  snprintf(line, sizeof(line), "CFG ECHO %s option side_return_distance_cm %u",
           cfg.configId, cfg.options.sideReturnDistanceCm);
  Serial.println(line);
  snprintf(line, sizeof(line), "CFG ECHO %s option ultrasonic_interval_ms %u",
           cfg.configId, cfg.options.ultrasonicIntervalMs);
  Serial.println(line);
  snprintf(line, sizeof(line), "CFG ECHO %s option host_heartbeat_timeout_ms %u",
           cfg.configId, cfg.options.hostHeartbeatTimeoutMs);
  Serial.println(line);
  snprintf(line, sizeof(line), "CFG ECHO %s option pulse_stall_timeout_ms %u",
           cfg.configId, cfg.options.pulseStallTimeoutMs);
  Serial.println(line);
  snprintf(line, sizeof(line), "CFG ECHO %s option direction_deadtime_ms %u",
           cfg.configId, cfg.options.directionDeadtimeMs);
  Serial.println(line);
}

void stopAllMotors() {
  for (uint8_t i = 0; i < activeConfig.motorCount; ++i) {
    analogWrite(activeConfig.motors[i].pwm, 0);
  }
  currentMotorSpeed = 0;
  directionChangePending = false;
  pendingDirectionSpeed = 0;
}

void writeMotorHardware(int signedSpeed) {
  signedSpeed = constrain(signedSpeed, -255, 255);
  int magnitude = abs(signedSpeed);
  int direction = signedSpeed >= 0 ? HIGH : LOW;

  for (uint8_t i = 0; i < activeConfig.motorCount; ++i) {
    digitalWrite(activeConfig.motors[i].dir, direction);
    analogWrite(activeConfig.motors[i].pwm, magnitude);
  }
  currentMotorSpeed = signedSpeed;
}

void requestMotorSpeed(int speed) {
  speed = constrain(speed, -255, 255);

  if (forceStopActive || emergencyStopActive || activeConfig.motorCount == 0) {
    writeMotorHardware(0);
    return;
  }

  if (speed == currentMotorSpeed) return;

  if (currentMotorSpeed != 0 &&
      speed != 0 &&
      ((currentMotorSpeed > 0) != (speed > 0))) {
    writeMotorHardware(0);
    pendingDirectionSpeed = speed;
    directionChangePending = true;
    directionChangeDueMs = millis() + activeConfig.options.directionDeadtimeMs;
    return;
  }

  writeMotorHardware(speed);
}

void updateDirectionChange(uint32_t nowMs) {
  if (!directionChangePending) return;
  if ((int32_t)(nowMs - directionChangeDueMs) < 0) return;

  directionChangePending = false;
  requestMotorSpeed(pendingDirectionSpeed);
}

void setServoHardware(uint8_t index, int angle) {
  if (index >= activeConfig.servoCount) return;
  angle = constrain(angle,
                    activeConfig.servos[index].minAngle,
                    activeConfig.servos[index].maxAngle);
  servoObjects[index].write(angle);
}

void setServo(uint8_t index, int angle) {
  if (index >= activeConfig.servoCount) {
    Serial.println("ERR SERVO_ID");
    return;
  }

  angle = constrain(angle,
                    activeConfig.servos[index].minAngle,
                    activeConfig.servos[index].maxAngle);

  if (pulseActive) {
    pendingHostServo = angle;
    pendingHostServoValid = true;
    return;
  }

  setServoHardware(index, angle);
}

void centerAllServos() {
  for (uint8_t i = 0; i < activeConfig.servoCount; ++i) {
    setServoHardware(i, activeConfig.servos[i].center);
  }
}

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

bool parsePulseGroup(char **tokens, uint8_t start, PulseCommand &cmd) {
  char direction = (char)tolower((unsigned char)tokens[start][0]);
  if ((direction != 'f' && direction != 'b') || tokens[start][1] != '\0') {
    return false;
  }

  long speed = 0;
  long pulses = 0;
  long angle = 0;
  if (!parseLongStrict(tokens[start + 1], 1, 255, speed) ||
      !parseLongStrict(tokens[start + 2], 1, MAX_PULSES, pulses) ||
      !parseLongStrict(tokens[start + 3], 0, 180, angle)) {
    return false;
  }

  cmd.direction = direction;
  cmd.speed = (uint8_t)speed;
  cmd.pulses = (uint32_t)pulses;
  cmd.angle = (uint8_t)angle;
  return true;
}

bool enqueueSequenceText(const char *text) {
  if (!text || !*text) return false;
  char work[MAX_SEQUENCE_CHARS + 1];
  strncpy(work, text, MAX_SEQUENCE_CHARS);
  work[MAX_SEQUENCE_CHARS] = '\0';

  char *tokens[MAX_TOKENS];
  uint8_t tokenCount = 0;
  char *token = strtok(work, " \t");
  while (token && tokenCount < MAX_TOKENS) {
    tokens[tokenCount++] = token;
    token = strtok(nullptr, " \t");
  }

  if (token != nullptr || tokenCount == 0 || tokenCount % 4 != 0) return false;
  uint8_t groups = tokenCount / 4;
  if ((uint8_t)(queueCount + groups) > PULSE_QUEUE_CAPACITY) return false;

  PulseCommand commands[MAX_TOKENS / 4];
  for (uint8_t i = 0; i < groups; ++i) {
    if (!parsePulseGroup(tokens, (uint8_t)(i * 4), commands[i])) return false;
  }

  for (uint8_t i = 0; i < groups; ++i) {
    enqueuePulse(commands[i]);
  }
  return true;
}

void finishPulseSequence() {
  pulseActive = false;
  pulsePaused = false;
  adaptiveActive = false;
  pulseRemaining = 0;
  requestMotorSpeed(0);

  if (pendingHostMotorValid) {
    int requested = pendingHostMotor;
    pendingHostMotorValid = false;
    if (!forceStopActive && !emergencyStopActive) requestMotorSpeed(requested);
  }

  if (pendingHostServoValid && activeConfig.servoCount > 0) {
    setServoHardware(0, pendingHostServo);
    pendingHostServoValid = false;
  }
}

void abortPulseSequence(const char *reason) {
  clearPulseQueue();
  pulseActive = false;
  pulsePaused = false;
  adaptiveActive = false;
  pulseRemaining = 0;
  requestMotorSpeed(0);
  centerAllServos();
  pendingHostMotorValid = false;
  pendingHostServoValid = false;

  Serial.print("ERR PULSE ");
  Serial.println(reason);
}

void startNextPulse() {
  if (pulseActive || forceStopActive || emergencyStopActive || activeConfig.encoderCount == 0) {
    return;
  }

  if (!dequeuePulse(activePulse)) {
    finishPulseSequence();
    return;
  }

  pulseActive = true;
  pulsePaused = false;
  pulseRemaining = activePulse.pulses;
  pulseLastEncoder = 0;
  pulseLastProgressMs = millis();
  adaptiveLastCheckMs = millis();

  if (activePulse.speed < ADAPTIVE_INITIAL_PWM) {
    adaptiveCurrentPwm = activePulse.speed;
    adaptiveActive = false;
  } else {
    adaptiveCurrentPwm = min((uint8_t)activePulse.speed, ADAPTIVE_INITIAL_PWM);
    adaptiveActive = true;
  }

  setServoHardware(0, activePulse.angle);

  noInterrupts();
  encoderPulses[0] = 0;
  encoderLastUs[0] = micros();
  interrupts();

  int signedSpeed = activePulse.direction == 'f'
                      ? adaptiveCurrentPwm
                      : -((int)adaptiveCurrentPwm);
  requestMotorSpeed(signedSpeed);
}

uint32_t readEncoderPulses(uint8_t index) {
  if (index >= activeConfig.encoderCount) return 0;
  noInterrupts();
  uint32_t value = encoderPulses[index];
  interrupts();
  return value;
}

int findUltraByName(const char *name) {
  for (uint8_t i = 0; i < activeConfig.ultraCount; ++i) {
    if (strcmp(activeConfig.ultras[i].name, name) == 0) return i;
  }
  return -1;
}

int ultraDistance(const char *name) {
  int index = findUltraByName(name);
  return index >= 0 ? activeConfig.ultras[index].distanceCm : -1;
}

bool normalObstacle() {
  int left = ultraDistance("left");
  int right = ultraDistance("right");
  return (left > 0 && left <= activeConfig.options.stopDistanceCm) ||
         (right > 0 && right <= activeConfig.options.stopDistanceCm);
}

bool pulseObstacle() {
  int left = ultraDistance("left");
  int right = ultraDistance("right");
  return (left > 0 && left <= activeConfig.options.pulseStopDistanceCm) ||
         (right > 0 && right <= activeConfig.options.pulseStopDistanceCm);
}

void pausePulse() {
  if (!pulseActive || pulsePaused) return;
  pulsePaused = true;
  requestMotorSpeed(0);
}

void resumePulse() {
  if (!pulseActive || !pulsePaused) return;
  if (forceStopActive || emergencyStopActive || pulseObstacle()) return;

  pulsePaused = false;
  int signedSpeed = activePulse.direction == 'f'
                      ? adaptiveCurrentPwm
                      : -((int)adaptiveCurrentPwm);
  requestMotorSpeed(signedSpeed);
}

void updatePulse(uint32_t nowMs) {
  if (!pulseActive) return;

  if (forceStopActive || emergencyStopActive) {
    requestMotorSpeed(0);
    return;
  }

  if (pulseObstacle()) {
    pausePulse();
    return;
  }

  if (pulsePaused) {
    resumePulse();
    return;
  }

  uint32_t encoderNow = readEncoderPulses(0);
  uint32_t delta = encoderNow - pulseLastEncoder;
  if (delta > 0) {
    pulseLastEncoder = encoderNow;
    pulseLastProgressMs = nowMs;

    if (delta >= pulseRemaining) {
      pulseRemaining = 0;
    } else {
      pulseRemaining -= delta;
    }

    if (adaptiveActive && encoderNow > 0) {
      adaptiveActive = false;
      adaptiveCurrentPwm = activePulse.speed;
      int signedSpeed = activePulse.direction == 'f'
                          ? activePulse.speed
                          : -((int)activePulse.speed);
      requestMotorSpeed(signedSpeed);
    }
  }

  if (pulseRemaining == 0) {
    finishPulseSequence();
    return;
  }

  if ((uint32_t)(nowMs - pulseLastProgressMs) >= activeConfig.options.pulseStallTimeoutMs) {
    abortPulseSequence("STALL");
    return;
  }

  if (adaptiveActive &&
      (uint32_t)(nowMs - adaptiveLastCheckMs) >= ADAPTIVE_CHECK_MS) {
    adaptiveLastCheckMs = nowMs;

    if (adaptiveCurrentPwm < activePulse.speed) {
      uint16_t nextPwm = (uint16_t)adaptiveCurrentPwm + ADAPTIVE_STEP_PWM;
      adaptiveCurrentPwm = (uint8_t)min(nextPwm, (uint16_t)activePulse.speed);

      int signedSpeed = activePulse.direction == 'f'
                          ? adaptiveCurrentPwm
                          : -((int)adaptiveCurrentPwm);
      requestMotorSpeed(signedSpeed);
    }
  }

  if (currentMotorSpeed == 0 && !directionChangePending) {
    int signedSpeed = activePulse.direction == 'f'
                        ? adaptiveCurrentPwm
                        : -((int)adaptiveCurrentPwm);
    requestMotorSpeed(signedSpeed);
  }
}

void stopRobot(bool clearQueue) {
  if (clearQueue) clearPulseQueue();
  pulseActive = false;
  pulsePaused = false;
  adaptiveActive = false;
  pulseRemaining = 0;
  pendingHostMotorValid = false;
  pendingHostServoValid = false;
  stopAllMotors();
  centerAllServos();
  emergencyStopActive = false;
}

void manualResume() {
  if (normalObstacle()) {
    Serial.println("ERR RESUME OBSTACLE");
    return;
  }
  forceStopActive = false;
  emergencyStopActive = false;
  if (pulseActive && pulsePaused) resumePulse();
}

void updateHostSafety(uint32_t nowMs) {
  if (!hostHeartbeatSeen) return;
  if ((uint32_t)(nowMs - lastHostHeartbeatMs) <
      activeConfig.options.hostHeartbeatTimeoutMs) {
    return;
  }

  if (currentMotorSpeed != 0 || pulseActive) {
    requestMotorSpeed(0);
    if (pulseActive) pulsePaused = true;
    emergencyStopActive = true;
    if (!hostTimeoutReported) {
      Serial.println("ERR HOST_HEARTBEAT_TIMEOUT");
      hostTimeoutReported = true;
    }
  }
}

void tmWriteByte(uint8_t value) {
  for (uint8_t i = 0; i < 8; ++i) {
    digitalWrite(activeConfig.tm.clk, LOW);
    digitalWrite(activeConfig.tm.dio, (value & 0x01) ? HIGH : LOW);
    delayMicroseconds(1);
    digitalWrite(activeConfig.tm.clk, HIGH);
    delayMicroseconds(1);
    value >>= 1;
  }
}

uint8_t tmReadByte() {
  uint8_t value = 0;
  for (uint8_t i = 0; i < 8; ++i) {
    digitalWrite(activeConfig.tm.clk, LOW);
    delayMicroseconds(1);
    if (digitalRead(activeConfig.tm.dio)) {
      value |= (uint8_t)(1U << i);
    }
    digitalWrite(activeConfig.tm.clk, HIGH);
    delayMicroseconds(1);
  }
  return value;
}

uint8_t readTM1638Buttons() {
  if (!activeConfig.tm.enabled) return 0;

  uint8_t value = 0;
  digitalWrite(activeConfig.tm.stb, LOW);
  tmWriteByte(0x42);
  pinMode(activeConfig.tm.dio, INPUT_PULLUP);

  for (uint8_t row = 0; row < 4; ++row) {
    uint8_t b = tmReadByte();
    if (b & 0x01) value |= (uint8_t)(1U << (row * 2));
    if (b & 0x10) value |= (uint8_t)(1U << (row * 2 + 1));
  }

  digitalWrite(activeConfig.tm.stb, HIGH);
  pinMode(activeConfig.tm.dio, OUTPUT);
  digitalWrite(activeConfig.tm.dio, HIGH);
  return value;
}

void updateButtons(uint32_t nowMs) {
  if (!activeConfig.tm.enabled) return;
  if ((uint32_t)(nowMs - lastButtonPollMs) < BUTTON_POLL_MS) return;
  lastButtonPollMs = nowMs;

  uint8_t current = readTM1638Buttons();
  if (current != buttonCandidate) {
    buttonCandidate = current;
    buttonCandidateSinceMs = nowMs;
  }

  if (buttonCandidate != buttonStable &&
      (uint32_t)(nowMs - buttonCandidateSinceMs) >= BUTTON_DEBOUNCE_MS) {
    buttonStable = buttonCandidate;

    if (buttonStable & (uint8_t)(1U << activeConfig.tm.forceStopButton)) {
      forceStopActive = true;
      stopAllMotors();
      Serial.println("EVENT FORCE_STOP");
    }

    if (buttonStable & (uint8_t)(1U << activeConfig.tm.resumeButton)) {
      manualResume();
      Serial.println("EVENT RESUME");
    }
  }
}

void startUltra(uint8_t index) {
  if (index >= activeConfig.ultraCount) return;

  activeUltra = index;
  ultraBusy = true;
  waitingRise = true;
  waitingFall = false;
  ultraStartedUs = micros();
  echoStartedUs = 0;

  digitalWrite(activeConfig.ultras[index].trig, LOW);
  delayMicroseconds(2);
  digitalWrite(activeConfig.ultras[index].trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(activeConfig.ultras[index].trig, LOW);
}

void finishUltra(uint32_t nowMs, int distance, bool valid) {
  activeConfig.ultras[activeUltra].distanceCm = distance;
  activeConfig.ultras[activeUltra].valid = valid;
  activeConfig.ultras[activeUltra].nextDueMs =
      nowMs + activeConfig.options.ultrasonicIntervalMs;

  ultraBusy = false;
  waitingRise = false;
  waitingFall = false;
  echoStartedUs = 0;
  ultraCooldownUntilUs = micros() + ULTRA_COOLDOWN_US;
}

void updateUltrasonic(uint32_t nowMs) {
  if (activeConfig.ultraCount == 0) return;

  uint32_t nowUs = micros();

  if (ultraBusy) {
    int echo = digitalRead(activeConfig.ultras[activeUltra].echo);

    if (waitingRise) {
      if (echo == HIGH) {
        waitingRise = false;
        waitingFall = true;
        echoStartedUs = nowUs;
      }
    } else if (waitingFall && echo == LOW) {
      uint32_t duration = nowUs - echoStartedUs;
      int distance = (int)(duration / 58UL);
      finishUltra(nowMs, distance > 0 ? distance : -1, distance > 0);
      return;
    }

    if ((uint32_t)(nowUs - ultraStartedUs) >= ULTRA_TIMEOUT_US) {
      finishUltra(nowMs, -1, false);
    }
    return;
  }

  if ((int32_t)(nowUs - ultraCooldownUntilUs) < 0) return;

  for (uint8_t offset = 0; offset < activeConfig.ultraCount; ++offset) {
    uint8_t index = (uint8_t)((activeUltra + offset + 1) % activeConfig.ultraCount);
    if ((int32_t)(nowMs - activeConfig.ultras[index].nextDueMs) >= 0) {
      startUltra(index);
      return;
    }
  }
}

void sendStatus() {
  int right = ultraDistance("right");
  int left = ultraDistance("left");

  char motion = 'S';
  if (currentMotorSpeed > 0) motion = 'F';
  else if (currentMotorSpeed < 0) motion = 'B';

  Serial.print(lane);
  Serial.print(' ');
  Serial.print(motion);
  Serial.print(' ');
  Serial.print(right);
  Serial.print(' ');
  Serial.print(left);
  Serial.print(' ');
  Serial.print(loopHz);
  Serial.print(' ');
  Serial.println(pulseActive ? 1 : 0);
}

void applyHardwareConfig() {
  stopAllMotors();

  for (uint8_t i = 0; i < MAX_SERVOS; ++i) {
    servoObjects[i].detach();
  }

  for (uint8_t i = 0; i < activeConfig.encoderCount; ++i) {
    int irq = digitalPinToInterrupt(activeConfig.encoders[i].pin);
    if (irq != NOT_AN_INTERRUPT) detachInterrupt(irq);
  }

  activeConfig = pendingConfig;
  activeConfig.active = true;

  for (uint8_t i = 0; i < activeConfig.motorCount; ++i) {
    pinMode(activeConfig.motors[i].pwm, OUTPUT);
    pinMode(activeConfig.motors[i].dir, OUTPUT);
    analogWrite(activeConfig.motors[i].pwm, 0);
    digitalWrite(activeConfig.motors[i].dir, LOW);
  }

  for (uint8_t i = 0; i < activeConfig.servoCount; ++i) {
    servoObjects[i].attach(activeConfig.servos[i].pin);
    servoObjects[i].write(activeConfig.servos[i].center);
  }

  for (uint8_t i = 0; i < activeConfig.ultraCount; ++i) {
    pinMode(activeConfig.ultras[i].trig, OUTPUT);
    pinMode(activeConfig.ultras[i].echo, INPUT);
    digitalWrite(activeConfig.ultras[i].trig, LOW);
    activeConfig.ultras[i].distanceCm = -1;
    activeConfig.ultras[i].valid = false;
    activeConfig.ultras[i].nextDueMs = millis() + 10UL + i * 10UL;
  }

  for (uint8_t i = 0; i < MAX_ENCODERS; ++i) {
    encoderPulses[i] = 0;
    encoderLastUs[i] = 0;
  }

  for (uint8_t i = 0; i < activeConfig.encoderCount; ++i) {
    pinMode(activeConfig.encoders[i].pin, INPUT_PULLUP);
    int irq = digitalPinToInterrupt(activeConfig.encoders[i].pin);
    attachInterrupt(irq, encoderISRTable[i], RISING);
  }

  if (activeConfig.tm.enabled) {
    pinMode(activeConfig.tm.stb, OUTPUT);
    pinMode(activeConfig.tm.clk, OUTPUT);
    pinMode(activeConfig.tm.dio, INPUT_PULLUP);
    digitalWrite(activeConfig.tm.stb, HIGH);
    digitalWrite(activeConfig.tm.clk, HIGH);
  }

  clearPulseQueue();
  pulseActive = false;
  pulsePaused = false;
  adaptiveActive = false;
  forceStopActive = false;
  emergencyStopActive = false;
  pendingHostMotorValid = false;
  pendingHostServoValid = false;
  currentMotorSpeed = 0;
  hostHeartbeatSeen = false;
  hostTimeoutReported = false;
  lastHostHeartbeatMs = millis();
  ultraBusy = false;
  waitingRise = false;
  waitingFall = false;
  ultraCooldownUntilUs = micros();

  Serial.print("CFG APPLIED ");
  Serial.println(activeConfig.configId);
}

void handleConfigCommand(char **tokens, uint8_t count) {
  if (count < 2) {
    Serial.println("ERR CFG COMMAND");
    return;
  }

  if (strcmp(tokens[1], "begin") == 0) {
    if (count != 3) {
      Serial.println("ERR CFG BEGIN_ARGS");
      return;
    }
    if (pulseActive || currentMotorSpeed != 0) {
      Serial.println("ERR CFG BUSY");
      return;
    }

    resetConfig(pendingConfig);
    strncpy(pendingConfig.configId, tokens[2], sizeof(pendingConfig.configId) - 1);
    pendingConfig.configId[sizeof(pendingConfig.configId) - 1] = '\0';

    Serial.print("CFG BEGIN OK ");
    Serial.println(pendingConfig.configId);
    return;
  }

  if (pendingConfig.configId[0] == '\0') {
    Serial.println("ERR CFG NO_BEGIN");
    return;
  }

  if (strcmp(tokens[1], "motor") == 0) {
    if (count != 5 || pendingConfig.motorCount >= MAX_MOTORS) {
      Serial.println("ERR CFG MOTOR_ARGS");
      return;
    }

    long id, pwm, dir;
    if (!parseLongStrict(tokens[2], 0, MAX_MOTORS - 1, id) ||
        !parseLongStrict(tokens[3], 2, 53, pwm) ||
        !parseLongStrict(tokens[4], 2, 53, dir)) {
      Serial.println("ERR CFG MOTOR_VALUE");
      return;
    }

    MotorModule &m = pendingConfig.motors[pendingConfig.motorCount];
    m.id = (uint8_t)id;
    m.pwm = (uint8_t)pwm;
    m.dir = (uint8_t)dir;
    ++pendingConfig.motorCount;

    Serial.print("CFG ACCEPT ");
    Serial.print(pendingConfig.configId);
    Serial.print(" motor ");
    Serial.print(m.id);
    Serial.print(' ');
    Serial.print(m.pwm);
    Serial.print(' ');
    Serial.println(m.dir);
    return;
  }

  if (strcmp(tokens[1], "servo") == 0) {
    if (count != 7 || pendingConfig.servoCount >= MAX_SERVOS) {
      Serial.println("ERR CFG SERVO_ARGS");
      return;
    }

    long id, pin, minAngle, maxAngle, center;
    if (!parseLongStrict(tokens[2], 0, MAX_SERVOS - 1, id) ||
        !parseLongStrict(tokens[3], 2, 53, pin) ||
        !parseLongStrict(tokens[4], 0, 180, minAngle) ||
        !parseLongStrict(tokens[5], 0, 180, maxAngle) ||
        !parseLongStrict(tokens[6], 0, 180, center)) {
      Serial.println("ERR CFG SERVO_VALUE");
      return;
    }

    ServoModule &s = pendingConfig.servos[pendingConfig.servoCount];
    s.id = (uint8_t)id;
    s.pin = (uint8_t)pin;
    s.minAngle = (uint8_t)minAngle;
    s.maxAngle = (uint8_t)maxAngle;
    s.center = (uint8_t)center;
    ++pendingConfig.servoCount;

    Serial.print("CFG ACCEPT ");
    Serial.print(pendingConfig.configId);
    Serial.print(" servo ");
    Serial.print(s.id);
    Serial.print(' ');
    Serial.print(s.pin);
    Serial.print(' ');
    Serial.print(s.minAngle);
    Serial.print(' ');
    Serial.print(s.maxAngle);
    Serial.print(' ');
    Serial.println(s.center);
    return;
  }

  if (strcmp(tokens[1], "ultrasonic") == 0) {
    if (count != 5 || pendingConfig.ultraCount >= MAX_ULTRASONICS) {
      Serial.println("ERR CFG ULTRA_ARGS");
      return;
    }

    long trig, echo;
    if (!parseLongStrict(tokens[3], 2, 53, trig) ||
        !parseLongStrict(tokens[4], 2, 53, echo) ||
        strlen(tokens[2]) > 16) {
      Serial.println("ERR CFG ULTRA_VALUE");
      return;
    }

    UltrasonicModule &u = pendingConfig.ultras[pendingConfig.ultraCount];
    if (duplicateUltraName(pendingConfig, tokens[2])) {
      Serial.println("ERR CFG ULTRA_NAME");
      return;
    }

    strncpy(u.name, tokens[2], sizeof(u.name) - 1);
    u.name[sizeof(u.name) - 1] = '\0';
    u.trig = (uint8_t)trig;
    u.echo = (uint8_t)echo;
    u.distanceCm = -1;
    u.valid = false;
    u.nextDueMs = 0;
    ++pendingConfig.ultraCount;

    Serial.print("CFG ACCEPT ");
    Serial.print(pendingConfig.configId);
    Serial.print(" ultrasonic ");
    Serial.print(u.name);
    Serial.print(' ');
    Serial.print(u.trig);
    Serial.print(' ');
    Serial.println(u.echo);
    return;
  }

  if (strcmp(tokens[1], "encoder") == 0) {
    if (count != 5 || pendingConfig.encoderCount >= MAX_ENCODERS) {
      Serial.println("ERR CFG ENCODER_ARGS");
      return;
    }

    long id, pin;
    if (!parseLongStrict(tokens[2], 0, MAX_ENCODERS - 1, id) ||
        !parseLongStrict(tokens[3], 2, 53, pin)) {
      Serial.println("ERR CFG ENCODER_VALUE");
      return;
    }

    EncoderModule &e = pendingConfig.encoders[pendingConfig.encoderCount];
    e.id = (uint8_t)id;
    e.pin = (uint8_t)pin;
    ++pendingConfig.encoderCount;

    Serial.print("CFG ACCEPT ");
    Serial.print(pendingConfig.configId);
    Serial.print(" encoder ");
    Serial.print(e.id);
    Serial.print(' ');
    Serial.println(e.pin);
    return;
  }

  if (strcmp(tokens[1], "tm1638") == 0) {
    if (count != 7 || pendingConfig.tm.enabled) {
      Serial.println("ERR CFG TM_ARGS");
      return;
    }

    long stb, clk, dio, forceButton, resumeButton;
    if (!parseLongStrict(tokens[2], 2, 53, stb) ||
        !parseLongStrict(tokens[3], 2, 53, clk) ||
        !parseLongStrict(tokens[4], 2, 53, dio) ||
        !parseLongStrict(tokens[5], 0, 7, forceButton) ||
        !parseLongStrict(tokens[6], 0, 7, resumeButton)) {
      Serial.println("ERR CFG TM_VALUE");
      return;
    }

    pendingConfig.tm.stb = (uint8_t)stb;
    pendingConfig.tm.clk = (uint8_t)clk;
    pendingConfig.tm.dio = (uint8_t)dio;
    pendingConfig.tm.forceStopButton = (uint8_t)forceButton;
    pendingConfig.tm.resumeButton = (uint8_t)resumeButton;
    pendingConfig.tm.enabled = true;

    Serial.print("CFG ACCEPT ");
    Serial.print(pendingConfig.configId);
    Serial.println(" tm1638");
    return;
  }

  if (strcmp(tokens[1], "option") == 0) {
    if (count != 4) {
      Serial.println("ERR CFG OPTION_ARGS");
      return;
    }

    long value;
    if (strcmp(tokens[2], "stop_distance_cm") == 0) {
      if (!parseLongStrict(tokens[3], 1, 500, value)) {
        Serial.println("ERR CFG OPTION_VALUE");
        return;
      }
      pendingConfig.options.stopDistanceCm = (uint16_t)value;
    } else if (strcmp(tokens[2], "pulse_stop_distance_cm") == 0) {
      if (!parseLongStrict(tokens[3], 1, 200, value)) {
        Serial.println("ERR CFG OPTION_VALUE");
        return;
      }
      pendingConfig.options.pulseStopDistanceCm = (uint16_t)value;
    } else if (strcmp(tokens[2], "side_return_distance_cm") == 0) {
      if (!parseLongStrict(tokens[3], 1, 500, value)) {
        Serial.println("ERR CFG OPTION_VALUE");
        return;
      }
      pendingConfig.options.sideReturnDistanceCm = (uint16_t)value;
    } else if (strcmp(tokens[2], "ultrasonic_interval_ms") == 0) {
      if (!parseLongStrict(tokens[3], 20, 2000, value)) {
        Serial.println("ERR CFG OPTION_VALUE");
        return;
      }
      pendingConfig.options.ultrasonicIntervalMs = (uint16_t)value;
    } else if (strcmp(tokens[2], "host_heartbeat_timeout_ms") == 0) {
      if (!parseLongStrict(tokens[3], 100, 5000, value)) {
        Serial.println("ERR CFG OPTION_VALUE");
        return;
      }
      pendingConfig.options.hostHeartbeatTimeoutMs = (uint16_t)value;
    } else if (strcmp(tokens[2], "pulse_stall_timeout_ms") == 0) {
      if (!parseLongStrict(tokens[3], 100, 10000, value)) {
        Serial.println("ERR CFG OPTION_VALUE");
        return;
      }
      pendingConfig.options.pulseStallTimeoutMs = (uint16_t)value;
    } else if (strcmp(tokens[2], "direction_deadtime_ms") == 0) {
      if (!parseLongStrict(tokens[3], 0, 250, value)) {
        Serial.println("ERR CFG OPTION_VALUE");
        return;
      }
      pendingConfig.options.directionDeadtimeMs = (uint16_t)value;
    } else {
      Serial.println("ERR CFG OPTION_NAME");
      return;
    }

    Serial.print("CFG ACCEPT ");
    Serial.print(pendingConfig.configId);
    Serial.print(" option ");
    Serial.print(tokens[2]);
    Serial.print(' ');
    Serial.println(value);
    return;
  }

  if (strcmp(tokens[1], "end") == 0) {
    if (count != 4 || strcmp(tokens[2], pendingConfig.configId) != 0) {
      Serial.println("ERR CFG END_ARGS");
      return;
    }

    char error[40];
    if (!validateConfig(pendingConfig, error, sizeof(error))) {
      Serial.print("ERR CFG ");
      Serial.println(error);
      return;
    }

    uint32_t expected = 0;
    if (!parseHex32(tokens[3], expected)) {
      Serial.println("ERR CFG FINGERPRINT");
      return;
    }

    uint32_t actual = configFingerprint(pendingConfig);
    if (actual != expected) {
      Serial.print("ERR CFG FINGERPRINT_MISMATCH ");
      char buffer[9];
      snprintf(buffer, sizeof(buffer), "%08lX", (unsigned long)actual);
      Serial.println(buffer);
      return;
    }

    applyHardwareConfig();
    echoConfig(activeConfig);

    Serial.print("CFG READY ");
    Serial.print(activeConfig.configId);
    Serial.print(' ');
    char buffer[9];
    snprintf(buffer, sizeof(buffer), "%08lX", (unsigned long)actual);
    Serial.println(buffer);
    return;
  }

  Serial.println("ERR CFG UNKNOWN");
}

void processRuntimeCommand(char **tokens, uint8_t count, char *rawLine) {
  if (!activeConfig.active) {
    Serial.println("ERR NO_HARDWARE_CONFIG");
    return;
  }

  if (strcmp(tokens[0], "heartbeat") == 0) {
    if (count != 1) {
      Serial.println("ERR HEARTBEAT_ARGS");
      return;
    }
    lastHostHeartbeatMs = millis();
    hostHeartbeatSeen = true;
    hostTimeoutReported = false;
    return;
  }

  if (strcmp(tokens[0], "stop") == 0) {
    stopRobot(true);
    return;
  }

  if (strcmp(tokens[0], "resume") == 0) {
    manualResume();
    return;
  }

  if (strcmp(tokens[0], "status") == 0 || strcmp(tokens[0], "u") == 0) {
    sendStatus();
    return;
  }

  if (strcmp(tokens[0], "motor") == 0) {
    long speed = 0;
    uint8_t motorId = 0;

    if (count == 2) {
      if (!parseLongStrict(tokens[1], -255, 255, speed)) {
        Serial.println("ERR MOTOR_VALUE");
        return;
      }
      if (pulseActive) {
        pendingHostMotor = (int)speed;
        pendingHostMotorValid = true;
      } else {
        requestMotorSpeed((int)speed);
      }
      return;
    }

    if (count == 3) {
      long id;
      if (!parseLongStrict(tokens[1], 0, MAX_MOTORS - 1, id) ||
          !parseLongStrict(tokens[2], -255, 255, speed) ||
          id >= activeConfig.motorCount) {
        Serial.println("ERR MOTOR_ID");
        return;
      }

      int signedSpeed = (int)speed;
      if (pulseActive) {
        pendingHostMotor = signedSpeed;
        pendingHostMotorValid = true;
      } else {
        signedSpeed = constrain(signedSpeed, -255, 255);
        int magnitude = abs(signedSpeed);
        int direction = signedSpeed >= 0 ? HIGH : LOW;
        digitalWrite(activeConfig.motors[id].dir, direction);
        analogWrite(activeConfig.motors[id].pwm, magnitude);
      }
      return;
    }

    Serial.println("ERR MOTOR_ARGS");
    return;
  }

  if (strcmp(tokens[0], "servo") == 0) {
    long angle;
    long id = 0;

    if (count == 2) {
      if (!parseLongStrict(tokens[1], 0, 180, angle)) {
        Serial.println("ERR SERVO_VALUE");
        return;
      }
    } else if (count == 3) {
      if (!parseLongStrict(tokens[1], 0, MAX_SERVOS - 1, id) ||
          !parseLongStrict(tokens[2], 0, 180, angle) ||
          id >= activeConfig.servoCount) {
        Serial.println("ERR SERVO_ID");
        return;
      }
    } else {
      Serial.println("ERR SERVO_ARGS");
      return;
    }

    setServo((uint8_t)id, (int)angle);
    return;
  }

  if (strcmp(tokens[0], "left") == 0) {
    if (activeConfig.encoderCount == 0) {
      Serial.println("ERR LEFT_NO_ENCODER");
      return;
    }
    if (!enqueueSequenceText(leftSequence)) {
      Serial.println("ERR LEFT_SEQUENCE");
      return;
    }
    lane = 'L';
    if (!pulseActive) startNextPulse();
    return;
  }

  if (strcmp(tokens[0], "right") == 0) {
    if (activeConfig.encoderCount == 0) {
      Serial.println("ERR RIGHT_NO_ENCODER");
      return;
    }
    if (!enqueueSequenceText(rightSequence)) {
      Serial.println("ERR RIGHT_SEQUENCE");
      return;
    }
    lane = 'R';
    if (!pulseActive) startNextPulse();
    return;
  }

  if (strcmp(tokens[0], "save") == 0) {
    if (count == 2 && strcmp(tokens[1], "left") == 0) {
      saveLaneSequences(true, false);
      return;
    }
    if (count == 2 && strcmp(tokens[1], "right") == 0) {
      saveLaneSequences(false, true);
      return;
    }
    if (count == 1) {
      saveLaneSequences(true, true);
      return;
    }
    Serial.println("ERR SAVE_ARGS");
    return;
  }

  if (strcmp(tokens[0], "load") == 0) {
    if (count != 1) {
      Serial.println("ERR LOAD_ARGS");
      return;
    }
    loadLaneSequences();
    return;
  }

  if (strcmp(tokens[0], "set") == 0) {
    Serial.println("ERR SET_USE_RAW");
    return;
  }

  if (tokens[0][1] == '\0' &&
      (tolower((unsigned char)tokens[0][0]) == 'f' ||
       tolower((unsigned char)tokens[0][0]) == 'b')) {
    if (activeConfig.encoderCount == 0) {
      Serial.println("ERR PULSE_NO_ENCODER");
      return;
    }
    if (count % 4 != 0 || count < 4) {
      Serial.println("ERR PULSE_ARGS");
      return;
    }

    uint8_t groups = count / 4;
    if ((uint8_t)(queueCount + groups) > PULSE_QUEUE_CAPACITY) {
      Serial.println("ERR PULSE_QUEUE_FULL");
      return;
    }

    PulseCommand commands[MAX_TOKENS / 4];
    for (uint8_t i = 0; i < groups; ++i) {
      if (!parsePulseGroup(tokens, (uint8_t)(i * 4), commands[i])) {
        Serial.println("ERR PULSE_VALUE");
        return;
      }
    }

    for (uint8_t i = 0; i < groups; ++i) {
      enqueuePulse(commands[i]);
    }
    if (!pulseActive) startNextPulse();
    return;
  }

  Serial.println("ERR UNKNOWN_COMMAND");
}

void processLine(char *raw) {
  char *line = raw;
  while (*line && isspace((unsigned char)*line)) ++line;

  char *end = line + strlen(line);
  while (end > line && isspace((unsigned char)end[-1])) --end;
  *end = '\0';

  if (!*line) return;

  if (strcmp(line, "hello") == 0 || strcmp(line, "HELLO") == 0) {
    Serial.print("HELLO ");
    Serial.print(FIRMWARE_ID);
    Serial.print(' ');
    Serial.print(PROTOCOL_VERSION);
    Serial.print(' ');
    Serial.println(BOARD_ID);
    return;
  }

  if (strncmp(line, "cfg ", 4) == 0) {
    char work[SERIAL_LINE_MAX + 1];
    strncpy(work, line, SERIAL_LINE_MAX);
    work[SERIAL_LINE_MAX] = '\0';

    char *tokens[16];
    uint8_t count = 0;
    char *token = strtok(work, " \t");
    while (token && count < 16) {
      tokens[count++] = token;
      token = strtok(nullptr, " \t");
    }
    if (token != nullptr) {
      Serial.println("ERR CFG TOO_MANY_ARGS");
      return;
    }

    handleConfigCommand(tokens, count);
    return;
  }

  if (strncmp(line, "set left ", 9) == 0) {
    const char *value = line + 9;
    if (strlen(value) > MAX_SEQUENCE_CHARS || !*value) {
      Serial.println("ERR SET_LEFT");
      return;
    }
    strncpy(leftSequence, value, MAX_SEQUENCE_CHARS);
    leftSequence[MAX_SEQUENCE_CHARS] = '\0';
    return;
  }

  if (strncmp(line, "set right ", 10) == 0) {
    const char *value = line + 10;
    if (strlen(value) > MAX_SEQUENCE_CHARS || !*value) {
      Serial.println("ERR SET_RIGHT");
      return;
    }
    strncpy(rightSequence, value, MAX_SEQUENCE_CHARS);
    rightSequence[MAX_SEQUENCE_CHARS] = '\0';
    return;
  }

  char work[SERIAL_LINE_MAX + 1];
  strncpy(work, line, SERIAL_LINE_MAX);
  work[SERIAL_LINE_MAX] = '\0';

  char *tokens[MAX_TOKENS];
  uint8_t count = 0;
  char *token = strtok(work, " \t");
  while (token && count < MAX_TOKENS) {
    tokens[count++] = token;
    token = strtok(nullptr, " \t");
  }

  if (token != nullptr) {
    Serial.println("ERR TOO_MANY_ARGS");
    return;
  }

  if (count == 0) return;

  processRuntimeCommand(tokens, count, line);
}

void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\r') continue;

    if (c == '\n') {
      if (!serialOverflow) {
        serialBuffer[serialLength] = '\0';
        processLine(serialBuffer);
      } else {
        Serial.println("ERR SERIAL_LINE_TOO_LONG");
      }

      serialLength = 0;
      serialOverflow = false;
      continue;
    }

    if (serialLength < SERIAL_LINE_MAX) {
      serialBuffer[serialLength++] = c;
    } else {
      serialOverflow = true;
    }
  }
}

void setup() {
  resetConfig(pendingConfig);
  resetConfig(activeConfig);
  setDefaultLaneSequences();

  Serial.begin(BAUD_RATE);
  delay(20);

#if defined(__AVR__)
  wdt_enable(WDTO_2S);
#endif

  Serial.print("HELLO ");
  Serial.print(FIRMWARE_ID);
  Serial.print(' ');
  Serial.print(PROTOCOL_VERSION);
  Serial.print(' ');
  Serial.println(BOARD_ID);

  lastLoopHzMs = millis();
}

void loop() {
#if defined(__AVR__)
  wdt_reset();
#endif

  uint32_t nowMs = millis();

  readSerial();

  if (activeConfig.active) {
    updateDirectionChange(nowMs);
    updateUltrasonic(nowMs);
    updateButtons(nowMs);
    updateHostSafety(nowMs);

    if (!forceStopActive && !emergencyStopActive && normalObstacle() && !pulseActive) {
      requestMotorSpeed(0);
      emergencyStopActive = true;
    }

    updatePulse(nowMs);

    if ((uint32_t)(nowMs - lastStatusMs) >= STATUS_INTERVAL_MS) {
      lastStatusMs = nowMs;
      sendStatus();
    }
  }

  ++loopCounter;
  if ((uint32_t)(nowMs - lastLoopHzMs) >= 1000UL) {
    loopHz = (uint16_t)min(loopCounter, 65535UL);
    loopCounter = 0;
    lastLoopHzMs = nowMs;
  }
}
