#include "backoff.h"

namespace elex {

Backoff::Backoff(uint32_t min_ms, uint32_t max_ms)
    : min_ms_(min_ms), max_ms_(max_ms < min_ms ? min_ms : max_ms), next_ms_(min_ms) {}

bool Backoff::due(uint32_t now_ms) const { return now_ms - last_ms_ >= wait_ms_; }

void Backoff::attempted(uint32_t now_ms) {
    last_ms_ = now_ms;
    wait_ms_ = next_ms_;
    next_ms_ = next_ms_ > max_ms_ / 2 ? max_ms_ : next_ms_ * 2;
}

void Backoff::connected() {
    next_ms_ = min_ms_;
    if (wait_ms_ > min_ms_) wait_ms_ = min_ms_;
}

}  // namespace elex
