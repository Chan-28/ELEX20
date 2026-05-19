#include "Adafruit_ADS1X15.h"

Adafruit_ADS1115::Adafruit_ADS1115(uint8_t i2cAddress)
  : i2cAddress_(i2cAddress), wire_(&Wire), gain_(GAIN_ONE), dataRate_(RATE_ADS1115_860SPS) {}

bool Adafruit_ADS1115::begin(uint8_t i2cAddress, TwoWire* wire) {
  i2cAddress_ = i2cAddress;
  wire_ = wire != nullptr ? wire : &Wire;
  wire_->begin();

  // A simple read/write probe: if the device NACKs, requestFrom() returns 0.
  wire_->beginTransmission(i2cAddress_);
  return wire_->endTransmission() == 0;
}

void Adafruit_ADS1115::setGain(adsGain_t gain) {
  gain_ = gain;
}

void Adafruit_ADS1115::setDataRate(adsDataRate_t rate) {
  dataRate_ = rate;
}

void Adafruit_ADS1115::writeRegister16(uint8_t reg, uint16_t value) {
  wire_->beginTransmission(i2cAddress_);
  wire_->write(reg);
  wire_->write(static_cast<uint8_t>(value >> 8));
  wire_->write(static_cast<uint8_t>(value & 0xFF));
  wire_->endTransmission();
}

uint16_t Adafruit_ADS1115::readRegister16(uint8_t reg) {
  wire_->beginTransmission(i2cAddress_);
  wire_->write(reg);
  wire_->endTransmission(false);
  wire_->requestFrom(static_cast<int>(i2cAddress_), 2);

  uint16_t value = 0;
  if (wire_->available() >= 2) {
    value = static_cast<uint16_t>(wire_->read()) << 8;
    value |= static_cast<uint16_t>(wire_->read());
  }
  return value;
}

uint16_t Adafruit_ADS1115::buildConfig(uint8_t channel) const {
  uint16_t config = 0;

  // OS = 1 (start single conversion)
  config |= 0x8000;

  // Single-ended channel selection
  channel &= 0x03;
  config |= static_cast<uint16_t>(0x04 + channel) << 12;

  // Gain / PGA
  switch (gain_) {
    case GAIN_TWOTHIRDS: config |= 0x0000; break;
    case GAIN_ONE:       config |= 0x0200; break;
    case GAIN_TWO:       config |= 0x0400; break;
    case GAIN_FOUR:      config |= 0x0600; break;
    case GAIN_EIGHT:     config |= 0x0800; break;
    case GAIN_SIXTEEN:   config |= 0x0A00; break;
    default:             config |= 0x0200; break;
  }

  // Single-shot mode
  config |= 0x0100;

  // Data rate
  switch (dataRate_) {
    case RATE_ADS1115_8SPS:   config |= 0x0000; break;
    case RATE_ADS1115_16SPS:  config |= 0x0020; break;
    case RATE_ADS1115_32SPS:  config |= 0x0040; break;
    case RATE_ADS1115_64SPS:  config |= 0x0060; break;
    case RATE_ADS1115_128SPS: config |= 0x0080; break;
    case RATE_ADS1115_250SPS: config |= 0x00A0; break;
    case RATE_ADS1115_475SPS: config |= 0x00C0; break;
    case RATE_ADS1115_860SPS: config |= 0x00E0; break;
    default:                  config |= 0x00E0; break;
  }

  // Comparator disabled
  config |= 0x0003;
  return config;
}

int16_t Adafruit_ADS1115::readADC_SingleEnded(uint8_t channel) {
  if (wire_ == nullptr) {
    return 0;
  }

  writeRegister16(ADS1115_REG_CONFIG, buildConfig(channel));

  // Poll until conversion completes.
  for (uint16_t attempt = 0; attempt < 1000; ++attempt) {
    uint16_t config = readRegister16(ADS1115_REG_CONFIG);
    if (config & 0x8000) {
      break;
    }
    delayMicroseconds(200);
  }

  return static_cast<int16_t>(readRegister16(ADS1115_REG_CONVERSION));
}
