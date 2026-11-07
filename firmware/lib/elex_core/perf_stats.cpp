#include "perf_stats.h"

#include <math.h>

namespace elex {

void PerfStats::add(float ms) {
    if (!isfinite(ms) || ms < 0.f) return;
    count_++;
    sum_ms_ += ms;
    if (ms > max_ms_) max_ms_ = ms;
}

PerfWindow PerfStats::take() {
    PerfWindow w;
    w.count = count_;
    if (count_ > 0) {
        w.avg_ms = static_cast<float>(sum_ms_ / count_);
        w.max_ms = max_ms_;
    }
    count_ = 0;
    sum_ms_ = 0.0;
    max_ms_ = 0.f;
    return w;
}

float round1(float v) { return roundf(v * 10.f) / 10.f; }

}  // namespace elex
