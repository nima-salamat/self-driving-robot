#pragma once

// Arduino's .ino preprocessor emits function prototypes before sketch-local
// type definitions. These declarations make custom parameter types visible
// to those generated prototypes; each firmware defines the complete structs.
struct LaneConfig;
struct PulseCommand;
