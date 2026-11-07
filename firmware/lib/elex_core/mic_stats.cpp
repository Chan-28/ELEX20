#include "mic_stats.h"

#include <math.h>

namespace elex {

namespace {
constexpr double kFullScale = 32768.0;
constexpr double kHumHz[] = {50.0, 60.0, 100.0, 120.0, 150.0, 180.0};
constexpr double kPi = 3.14159265358979323846;
}  // namespace

float to_dbfs(double amplitude) {
    if (amplitude <= 0.0) return -120.f;
    const double db = 20.0 * log10(amplitude / kFullScale);
    return db < -120.0 ? -120.f : static_cast<float>(db);
}

MicStats::MicStats(uint32_t sample_rate) : rate_(sample_rate), block_len_(sample_rate / 10) {
    for (int k = 0; k < kHumBins; k++) coeff_[k] = static_cast<float>(2.0 * cos(2.0 * kPi * kHumHz[k] / rate_));
}

void MicStats::close_block() {
    for (int k = 0; k < kHumBins; k++) {
        const float p = s1_[k] * s1_[k] + s2_[k] * s2_[k] - coeff_[k] * s1_[k] * s2_[k];
        const double amp = 2.0 * sqrt(p > 0.f ? p : 0.f) / block_len_;  // amplitude de pico
        hum_power_ += amp * amp / 2.0;                                     // potência da senoide
        s1_[k] = s2_[k] = 0.f;
    }
    blocks_++;
    in_block_ = 0;
}

void MicStats::add(const int16_t* x, size_t n) {
    for (size_t i = 0; i < n; i++) {
        const int32_t v = x[i];
        sum_ += v;
        sum_sq_ += static_cast<int64_t>(v) * v;
        const int32_t a = v < 0 ? -v : v;
        if (a > peak_) peak_ = a;
        if (v >= 32767 || v <= -32768) clipped_++;
        if (v == 0) zeros_++;

        const float xf = static_cast<float>(v);
        for (int k = 0; k < kHumBins; k++) {
            const float s0 = xf + coeff_[k] * s1_[k] - s2_[k];
            s2_[k] = s1_[k];
            s1_[k] = s0;
        }
        if (++in_block_ >= block_len_) close_block();
    }
    n_ += static_cast<uint32_t>(n);
}

MicReport MicStats::take() {
    MicReport r;
    r.samples = n_;
    if (n_ > 0) {
        const double mean = static_cast<double>(sum_) / n_;
        const double var = static_cast<double>(sum_sq_) / n_ - mean * mean;
        const double rms = var > 0.0 ? sqrt(var) : 0.0;
        r.dc = static_cast<float>(mean);
        r.rms_dbfs = to_dbfs(rms);
        r.peak_dbfs = to_dbfs(peak_);
        r.clip_pct = 100.f * clipped_ / n_;
        r.zero_pct = 100.f * zeros_ / n_;
        if (blocks_ > 0 && rms > 0.0) {
            const double hum = hum_power_ / blocks_;
            if (hum > 0.0) {
                const double db = 10.0 * log10(hum / (rms * rms));
                r.hum_db = db < -120.0 ? -120.f : static_cast<float>(db);
            }
        }
    }
    *this = MicStats(rate_);
    return r;
}

}  // namespace elex
