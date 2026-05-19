#ifndef ADAFRUIT_ADS1X15_H
#define ADAFRUIT_ADS1X15_H

#include <Arduino.h>
#include <Wire.h>

// Minimal local replacement for the Adafruit ADS1X15 API used by this project.

typedef enum {
  GAIN_TWOTHIRDS = 0,
  GAIN_ONE = 1,
  GAIN_TWO = 2,
  GAIN_FOUR = 3,
  GAIN_EIGHT = 4,
  GAIN_SIXTEEN = 5
} adsGain_t;

typedef enum {
  RATE_ADS1115_8SPS = 0,
  RATE_ADS1115_16SPS = 1,
  RATE_ADS1115_32SPS = 2,
  RATE_ADS1115_64SPS = 3,
  RATE_ADS1115_128SPS = 4,
  RATE_ADS1115_250SPS = 5,
  RATE_ADS1115_475SPS = 6,
  RATE_ADS1115_860SPS = 7
} adsDataRate_t;

class Adafruit_ADS1115 {
public:
  explicit Adafruit_ADS1115(uint8_t i2cAddress = 0x48);

  bool begin(uint8_t i2cAddress = 0x48, TwoWire* wire = &Wire);
  void setGain(adsGain_t gain);
  void setDataRate(adsDataRate_t rate);
  int16_t readADC_SingleEnded(uint8_t channel);

private:
  static constexpr uint8_t ADS1115_REG_CONVERSION = 0x00;
  static constexpr uint8_t ADS1115_REG_CONFIG = 0x01;

  uint8_t i2cAddress_;
  TwoWire* wire_;
  adsGain_t gain_;
  adsDataRate_t dataRate_;

  void writeRegister16(uint8_t reg, uint16_t value);
  uint16_t readRegister16(uint8_t reg);
  uint16_t buildConfig(uint8_t channel) const;
};

#endif // ADAFRUIT_ADS1X15_H
