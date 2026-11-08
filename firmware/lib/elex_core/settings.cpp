#include "settings.h"

#include <math.h>
#include <string.h>

namespace elex {

namespace {

struct LabelUrgency {
    const char* label;
    uint8_t urgency;
};

// Rótulos publicados, em inglês. A fonte é classes/sound_classes.json, e tests/test_classes.py confere.
const LabelUrgency kUrgencies[] = {
    {"siren", 3},      {"horn", 3},   {"alarm", 3},      {"gunshot_explosion", 3}, {"scream", 3},
    {"impact", 2},     {"train", 2},  {"power_tool", 1}, {"vehicle", 1},
    {"aircraft", 0},   {"animal", 0}, {"weather", 0},    {"speech_crowd", 0},
    {"music", 0},      {"silence", 0},
};

struct LabelAlias {
    const char* legacy;
    const char* label;
};

// Rótulos em português dos modelos treinados antes da troca (rotulo_legado no JSON).
const LabelAlias kLegacyLabels[] = {
    {"sirene", "siren"},          {"buzina", "horn"},          {"alarme", "alarm"},
    {"tiro_explosao", "gunshot_explosion"}, {"grito", "scream"}, {"impacto", "impact"},
    {"trem", "train"},            {"aeronave", "aircraft"},    {"ferramenta", "power_tool"},
    {"veiculo", "vehicle"},       {"clima", "weather"},        {"fala_multidao", "speech_crowd"},
    {"musica", "music"},          {"silencio", "silence"},
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

const char* canonical_label(const char* label) {
    if (label == nullptr) return nullptr;
    for (const auto& a : kLegacyLabels) {
        if (strcmp(a.legacy, label) == 0) return a.label;
    }
    return label;
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
