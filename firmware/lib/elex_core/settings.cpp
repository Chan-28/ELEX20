#include "settings.h"

#include <math.h>
#include <string.h>

namespace elex {

namespace {

struct LabelUrgency {
    const char* label;
    uint8_t urgency;
};

const LabelUrgency kUrgencies[] = {
    {"siren", 3},         {"car_horn", 3},        {"gun_shot", 3},
    {"dog_bark", 2},      {"drilling", 2},        {"jackhammer", 2},
    {"engine_idling", 1}, {"children_playing", 1}, {"street_music", 1},
    {"air_conditioner", 0},
};

bool in_range(float v, float lo, float hi) { return isfinite(v) && v >= lo && v <= hi; }

}  // namespace

bool settings_apply(Settings& s, const char* key, float value) {
    if (key == nullptr) return false;
    if (strcmp(key, "threshold") == 0) {
        if (!in_range(value, 0.30f, 0.99f)) return false;
        s.threshold = value;
    } else if (strcmp(key, "doa_enabled") == 0) {
        if (value != 0.f && value != 1.f) return false;
        s.doa_enabled = value == 1.f;
    } else if (strcmp(key, "motor_enabled") == 0) {
        if (value != 0.f && value != 1.f) return false;
        s.motor_enabled = value == 1.f;
    } else if (strcmp(key, "port1_skew") == 0) {
        if (!in_range(value, -8.f, 8.f)) return false;
        s.port1_skew = value;
    } else if (strcmp(key, "motor_max_ms") == 0) {
        if (!in_range(value, 100.f, 2000.f)) return false;
        s.motor_max_ms = static_cast<uint16_t>(value);
    } else {
        return false;
    }
    return true;
}

uint8_t urgency_for_label(const char* label) {
    if (label == nullptr) return 0;
    for (const auto& e : kUrgencies) {
        if (strcmp(e.label, label) == 0) return e.urgency;
    }
    return 0;
}

uint8_t motor_duty_for_urgency(uint8_t urgency) {
    switch (urgency) {
        case 1: return 100;
        case 2: return 180;
        case 3: return 255;
        default: return 0;
    }
}

}  // namespace elex
