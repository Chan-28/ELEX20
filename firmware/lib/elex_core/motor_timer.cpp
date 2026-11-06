#include "motor_timer.h"

namespace elex {

bool MotorTimer::start(uint32_t now_ms, uint32_t duration_ms) {
    if (active_) return false;
    if (resting_ && now_ms - started_ms_ < duration_ms_ + kMotorRestMs) return false;
    active_ = true;
    resting_ = true;
    started_ms_ = now_ms;
    duration_ms_ = duration_ms;
    return true;
}

bool MotorTimer::expired(uint32_t now_ms) {
    if (!active_ || now_ms - started_ms_ < duration_ms_) return false;
    active_ = false;
    return true;
}

uint32_t MotorTimer::remaining_ms(uint32_t now_ms) const {
    if (!active_) return 0;
    const uint32_t elapsed = now_ms - started_ms_;
    return elapsed >= duration_ms_ ? 0 : duration_ms_ - elapsed;
}

}  // namespace elex
