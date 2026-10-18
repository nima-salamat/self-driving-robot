# Selected adaptive-PWM firmware extension

The `ODOM1` telemetry contract described here is implemented by the EEPROM/set-based adaptive-PWM sketches, including `new_main_adaptive_pwm_with_savingPulseInEEPROM` and the active `new_main_adaptive_pwm_with_savingPulseInEEPROM_FIX` variant.

The sketch preserves its default seven-field status output. The explicit host
command `encoder telemetry on` enables the `ODOM1` version extension:

```text
<lane> <motion> <right_cm> <left_cm> <rear_left_cm> <loop_hz> <pulse_active> ODOM1 <cumulative_signed_pulses> <raw_segment_count> <servo_command> <epoch> <front_valid> <front_sample_seq> <front_age_ms> <rear_left_valid> <rear_left_sample_seq> <rear_left_age_ms>
```

Example legacy line remains exactly `R F 25 -1 30 1000 0`. The right field is
the physically connected forward range sensor; left is disconnected; side is
mounted rear-left. A validity bit plus sequence/measurement age distinguishes
a fresh positive range from repeated old data or no echo. A no-echo result is
invalid, never clear space.

`ODOM1` uses the custom single-channel `Encoder.h` falling-edge pulse counter.
There is no direction sensing. The separate signed cumulative estimate uses
the motor direction commanded at synchronization boundaries, while the raw
counter continues to reset for existing pulse-segment completion/pause logic.
Coast, reversal delays, slip, missed events, counter overflow, and motion while
host telemetry is lost remain uncertainty; host reconnection starts a mapped
trajectory gap.

`lane adaptive <1..34 cm>` is explicit and acknowledged only while stopped,
with an empty pulse queue and legacy lane state inactive. It disables automatic
EEPROM lane sequences without writing EEPROM. While active, host motor/servo
setpoints are accepted, legacy pulse macros/config/save and lane-auto ownership
are rejected, the ordinary 35 cm legacy stop is bypassed, and the configured
front/right emergency threshold remains Arduino-enforced. The MCU stops on
front sample invalidity/staleness and on a 500 ms missing heartbeat; watchdog or
emergency latches reject subsequent speed commands until explicit safe release
conditions hold. Force stop remains authoritative.

The servo neutral is 95 degrees. The 4 cm example emergency limit is not a
verified physical stopping distance. No passage is declared clear from the
disconnected left sensor or the rear-left sensor.
