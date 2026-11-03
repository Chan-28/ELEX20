#include "doa.h"

#include <math.h>

namespace elex {

namespace {

constexpr size_t kFft = 1024;  // kDoaWindow com zero-padding, evita circularidade
constexpr float kPi = 3.14159265358979f;
constexpr float kSoundSpeed = 343.f;
constexpr uint8_t kPorts[kNumMics] = {0, 1, 0, 1};  // I2S de cada microfone

float g_cos[kFft];
float g_sin[kFft];
bool g_tables_ready = false;

float g_re[kNumMics][kFft];
float g_im[kNumMics][kFft];

void init_tables() {
    if (g_tables_ready) return;
    for (size_t i = 0; i < kFft; i++) {
        const float a = 2.f * kPi * static_cast<float>(i) / static_cast<float>(kFft);
        g_cos[i] = cosf(a);
        g_sin[i] = sinf(a);
    }
    g_tables_ready = true;
}

// FFT iterativa radix-2 in-place (sinal e^{-j...})
void fft(float* re, float* im) {
    for (size_t i = 1, j = 0; i < kFft; i++) {
        size_t bit = kFft >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            const float tr = re[i];
            re[i] = re[j];
            re[j] = tr;
            const float ti = im[i];
            im[i] = im[j];
            im[j] = ti;
        }
    }
    for (size_t len = 2; len <= kFft; len <<= 1) {
        const size_t step = kFft / len;
        for (size_t i = 0; i < kFft; i += len) {
            for (size_t k = 0; k < len / 2; k++) {
                const float wr = g_cos[k * step];
                const float wi = -g_sin[k * step];
                const size_t a = i + k;
                const size_t b = a + len / 2;
                const float xr = re[b] * wr - im[b] * wi;
                const float xi = re[b] * wi + im[b] * wr;
                re[b] = re[a] - xr;
                im[b] = im[a] - xi;
                re[a] += xr;
                im[a] += xi;
            }
        }
    }
}

struct PairDelay {
    float lag_samples;  // atraso do microfone j em relação ao i
    float peak;         // pico PHAT normalizado [0, 1]
};

// Correlação PHAT avaliada só nos lags inteiros em [-max_lag, max_lag], com pico parabólico.
// Positivo: o microfone j recebe o sinal depois do microfone i.
PairDelay gcc_phat_pair(uint8_t i, uint8_t j, size_t k_min, size_t k_max, int max_lag) {
    const int span = max_lag + 1;  // um lag a mais de cada lado para a parábola
    float corr[2 * 16 + 3];
    const int count = 2 * span + 1;

    size_t used = 0;
    for (int n = 0; n < count; n++) corr[n] = 0.f;
    for (size_t k = k_min; k <= k_max; k++) {
        // G = Xj * conj(Xi), normalizado em módulo (PHAT)
        const float gr = g_re[j][k] * g_re[i][k] + g_im[j][k] * g_im[i][k];
        const float gi = g_im[j][k] * g_re[i][k] - g_re[j][k] * g_im[i][k];
        const float mag = sqrtf(gr * gr + gi * gi);
        if (mag < 1e-9f) continue;
        const float ur = gr / mag;
        const float ui = gi / mag;
        used++;
        for (int n = 0; n < count; n++) {
            const int lag = n - span;
            const size_t idx = static_cast<size_t>(((static_cast<int>(k) * lag) % static_cast<int>(kFft)) + static_cast<int>(kFft)) % kFft;
            corr[n] += ur * g_cos[idx] - ui * g_sin[idx];
        }
    }
    if (used == 0) return {0.f, 0.f};
    for (int n = 0; n < count; n++) corr[n] /= static_cast<float>(used);

    int best = 1;
    for (int n = 1; n < count - 1; n++) {
        if (n - span < -max_lag || n - span > max_lag) continue;
        if (corr[n] > corr[best] || best - span < -max_lag) best = n;
    }
    float frac = 0.f;
    const float y0 = corr[best - 1];
    const float y1 = corr[best];
    const float y2 = corr[best + 1];
    const float denom = y0 - 2.f * y1 + y2;
    if (fabsf(denom) > 1e-9f) frac = 0.5f * (y0 - y2) / denom;
    if (frac > 0.5f) frac = 0.5f;
    if (frac < -0.5f) frac = -0.5f;
    return {static_cast<float>(best - span) + frac, y1 < 0.f ? 0.f : y1};
}

}  // namespace

uint8_t sector_from_azimuth(float azimuth_deg) {
    float a = fmodf(azimuth_deg, 360.f);
    if (a < 0.f) a += 360.f;
    return static_cast<uint8_t>((static_cast<int>(a / 45.f + 0.5f)) % kNumSectors);
}

const char* sector_name(uint8_t sector) {
    static const char* const names[kNumSectors] = {"N", "NE", "E", "SE", "S", "SO", "O", "NO"};
    return names[sector % kNumSectors];
}

size_t doa_loudest_window(const int16_t* mono, size_t n) {
    if (n <= kDoaWindow) return 0;
    constexpr size_t hop = 64;
    size_t best_start = 0;
    int64_t best_energy = -1;
    for (size_t start = 0; start + kDoaWindow <= n; start += hop) {
        int64_t e = 0;
        for (size_t i = 0; i < kDoaWindow; i++) e += static_cast<int64_t>(mono[start + i]) * mono[start + i];
        if (e > best_energy) {
            best_energy = e;
            best_start = start;
        }
    }
    return best_start;
}

DoaResult doa_estimate(const int16_t* const mics[kNumMics], const DoaConfig& cfg) {
    init_tables();

    for (uint8_t m = 0; m < kNumMics; m++) {
        // Remove a média e aplica janela de Hann: reduz vazamento espectral
        float mean = 0.f;
        for (size_t i = 0; i < kDoaWindow; i++) mean += mics[m][i];
        mean /= static_cast<float>(kDoaWindow);
        for (size_t i = 0; i < kFft; i++) {
            if (i < kDoaWindow) {
                const float w = 0.5f - 0.5f * cosf(2.f * kPi * static_cast<float>(i) / static_cast<float>(kDoaWindow - 1));
                g_re[m][i] = (static_cast<float>(mics[m][i]) - mean) * w;
            } else {
                g_re[m][i] = 0.f;
            }
            g_im[m][i] = 0.f;
        }
        fft(g_re[m], g_im[m]);
    }

    const float bin_hz = cfg.sample_rate / static_cast<float>(kFft);
    size_t k_min = static_cast<size_t>(cfg.f_min_hz / bin_hz);
    size_t k_max = static_cast<size_t>(cfg.f_max_hz / bin_hz);
    if (k_min < 1) k_min = 1;
    if (k_max > kFft / 2 - 1) k_max = kFft / 2 - 1;

    // Posições dos microfones (x = direita, y = frente)
    float px[kNumMics], py[kNumMics];
    for (uint8_t m = 0; m < kNumMics; m++) {
        const float a = static_cast<float>(m) * (kPi / 2.f);
        px[m] = cfg.radius_m * sinf(a);
        py[m] = cfg.radius_m * cosf(a);
    }

    // Mínimos quadrados: tau_ij = -(p_j - p_i) . u / c, com u = (ux, uy) apontando para a fonte
    float ata00 = 0.f, ata01 = 0.f, ata11 = 0.f, atb0 = 0.f, atb1 = 0.f;
    float peak_sum = 0.f;
    int n_pairs = 0;
    struct Row { float ax, ay, b; } rows[kNumMics * (kNumMics - 1) / 2];

    for (uint8_t i = 0; i < kNumMics; i++) {
        for (uint8_t j = i + 1; j < kNumMics; j++) {
            const float dx = px[j] - px[i];
            const float dy = py[j] - py[i];
            const float dist = sqrtf(dx * dx + dy * dy);
            int max_lag = static_cast<int>(ceilf(dist / kSoundSpeed * cfg.sample_rate + fabsf(cfg.port1_skew_samples)));
            if (max_lag > 15) max_lag = 15;
            if (max_lag < 1) max_lag = 1;

            const PairDelay d = gcc_phat_pair(i, j, k_min, k_max, max_lag);
            const float lag = d.lag_samples - cfg.port1_skew_samples * static_cast<float>(static_cast<int>(kPorts[j]) - static_cast<int>(kPorts[i]));
            const float tau = lag / cfg.sample_rate;

            const float ax = -dx / kSoundSpeed;
            const float ay = -dy / kSoundSpeed;
            rows[n_pairs] = {ax, ay, tau};
            ata00 += ax * ax;
            ata01 += ax * ay;
            ata11 += ay * ay;
            atb0 += ax * tau;
            atb1 += ay * tau;
            peak_sum += d.peak;
            n_pairs++;
        }
    }

    DoaResult out;
    const float det = ata00 * ata11 - ata01 * ata01;
    if (fabsf(det) < 1e-18f) return out;
    const float ux = (atb0 * ata11 - atb1 * ata01) / det;
    const float uy = (ata00 * atb1 - ata01 * atb0) / det;
    const float norm = sqrtf(ux * ux + uy * uy);
    if (norm < 1e-9f) return out;

    // Resíduo em amostras: mede a coerência entre os 6 pares com a onda plana estimada
    float res2 = 0.f;
    for (int p = 0; p < n_pairs; p++) {
        const float pred = rows[p].ax * ux + rows[p].ay * uy;
        const float e = (rows[p].b - pred) * cfg.sample_rate;
        res2 += e * e;
    }
    const float rms = sqrtf(res2 / static_cast<float>(n_pairs));
    float coherence = 1.f - rms / 2.f;
    if (coherence < 0.f) coherence = 0.f;

    float az = atan2f(ux, uy) * 180.f / kPi;
    if (az < 0.f) az += 360.f;

    float conf = (peak_sum / static_cast<float>(n_pairs)) * coherence;
    if (conf > 1.f) conf = 1.f;

    out.azimuth_deg = az;
    out.sector = sector_from_azimuth(az);
    out.confidence = conf;
    out.valid = conf >= cfg.min_confidence;
    return out;
}

}  // namespace elex
