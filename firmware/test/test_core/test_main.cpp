// Testes nativos (sem hardware) da biblioteca elex_core com sinais sintéticos.
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <unity.h>

#include "backoff.h"
#include "doa.h"
#include "motor_timer.h"
#include "settings.h"

using namespace elex;

namespace {

constexpr size_t kLen = 2048;
constexpr float kFs = 16000.f;
constexpr float kPi = 3.14159265358979f;

int16_t g_mics[kNumMics][kLen];

// Sinal de banda larga determinístico: soma de senoides com fase pseudoaleatória.
// Avaliado em tempo contínuo, então atrasos fracionários são exatos.
float broadband(float t, uint32_t seed) {
    uint32_t s = seed;
    float acc = 0.f;
    for (int k = 0; k < 48; k++) {
        s = s * 1664525u + 1013904223u;
        const float f = 350.f + static_cast<float>(s % 5400u);
        s = s * 1664525u + 1013904223u;
        const float ph = static_cast<float>(s % 6283u) / 1000.f;
        acc += sinf(2.f * kPi * f * t + ph);
    }
    return acc / 48.f;
}

// Gera o campo de uma fonte em onda plana vinda de azimute_deg (0 = frente, horário)
void synth(float azimuth_deg, float radius, float port1_skew, float noise_amp, uint32_t seed) {
    const float c = 343.f;
    const float az = azimuth_deg * kPi / 180.f;
    const float ux = sinf(az), uy = cosf(az);
    uint32_t rng = seed * 2654435761u + 12345u;
    for (uint8_t m = 0; m < kNumMics; m++) {
        const float a = static_cast<float>(m) * kPi / 2.f;
        const float px = radius * sinf(a), py = radius * cosf(a);
        float t_arrival = -(px * ux + py * uy) / c;
        if (m == 1 || m == 3) t_arrival += port1_skew / kFs;
        for (size_t n = 0; n < kLen; n++) {
            const float t = static_cast<float>(n) / kFs - t_arrival;
            rng = rng * 1664525u + 1013904223u;
            const float noise = (static_cast<float>(rng >> 8) / 8388608.f - 1.f) * noise_amp;
            g_mics[m][n] = static_cast<int16_t>(8000.f * (broadband(t, 7u) + noise));
        }
    }
}

float angle_diff(float a, float b) {
    float d = fmodf(a - b + 540.f, 360.f) - 180.f;
    return fabsf(d);
}

DoaResult run(float skew_cfg = 0.f) {
    const int16_t* mics[kNumMics] = {g_mics[0] + 600, g_mics[1] + 600, g_mics[2] + 600, g_mics[3] + 600};
    DoaConfig cfg;
    cfg.port1_skew_samples = skew_cfg;
    return doa_estimate(mics, cfg);
}

}  // namespace

void setUp() {}
void tearDown() {}

void test_oito_setores_sem_ruido() {
    for (int s = 0; s < 8; s++) {
        const float az = 45.f * static_cast<float>(s);
        synth(az, 0.09f, 0.f, 0.f, 1);
        const DoaResult r = run();
        TEST_ASSERT_TRUE_MESSAGE(r.valid, "resultado deveria ser válido");
        TEST_ASSERT_FLOAT_WITHIN(8.f, 0.f, angle_diff(r.azimuth_deg, az));
        TEST_ASSERT_EQUAL_UINT8(s, r.sector);
    }
}

void test_azimutes_intermediarios() {
    const float azs[] = {20.f, 70.f, 110.f, 200.f, 250.f, 340.f};
    for (float az : azs) {
        synth(az, 0.09f, 0.f, 0.f, 2);
        const DoaResult r = run();
        TEST_ASSERT_TRUE(r.valid);
        TEST_ASSERT_FLOAT_WITHIN(10.f, 0.f, angle_diff(r.azimuth_deg, az));
    }
}

void test_com_ruido() {
    // Ruído do mesmo nível do sinal (≈ 0 dB): ainda estima, com confiança menor
    synth(135.f, 0.09f, 0.f, 0.2f, 3);
    const DoaResult r = run();
    TEST_ASSERT_TRUE(r.valid);
    TEST_ASSERT_FLOAT_WITHIN(10.f, 0.f, angle_diff(r.azimuth_deg, 135.f));
    TEST_ASSERT_TRUE(r.confidence < 0.8f);
}

void test_ruido_dominante_e_rejeitado() {
    // Sinal ≈ 7 dB abaixo do ruído: o resultado deve ser marcado inválido
    synth(135.f, 0.09f, 0.f, 0.4f, 3);
    TEST_ASSERT_FALSE(run().valid);
}

void test_calibracao_de_desvio_entre_i2s() {
    // O desvio entre os dois controladores I2S derruba a coerência dos pares;
    // informar o desvio medido recupera a confiança (e o azimute fora dos eixos).
    synth(90.f, 0.09f, 2.f, 0.f, 4);
    const DoaResult sem = run(0.f);
    const DoaResult com = run(2.f);
    TEST_ASSERT_TRUE(com.valid);
    TEST_ASSERT_FLOAT_WITHIN(10.f, 0.f, angle_diff(com.azimuth_deg, 90.f));
    TEST_ASSERT_TRUE(com.confidence > sem.confidence + 0.3f);

    synth(30.f, 0.09f, 3.f, 0.f, 5);
    const DoaResult d = run(3.f);
    TEST_ASSERT_TRUE(d.valid);
    TEST_ASSERT_FLOAT_WITHIN(10.f, 0.f, angle_diff(d.azimuth_deg, 30.f));
}

void test_silencio_nao_e_valido() {
    for (uint8_t m = 0; m < kNumMics; m++)
        for (size_t n = 0; n < kLen; n++) g_mics[m][n] = 0;
    TEST_ASSERT_FALSE(run().valid);
}

void test_ruido_incoerente_tem_baixa_confianca() {
    uint32_t rng = 99u;
    for (uint8_t m = 0; m < kNumMics; m++) {
        for (size_t n = 0; n < kLen; n++) {
            rng = rng * 1664525u + 1013904223u;
            g_mics[m][n] = static_cast<int16_t>((static_cast<int32_t>(rng >> 16) - 32768) / 4);
        }
    }
    const DoaResult r = run();
    TEST_ASSERT_TRUE(r.confidence < 0.5f);
}

void test_janela_mais_energetica() {
    static int16_t mono[3000];
    for (size_t i = 0; i < 3000; i++) mono[i] = 10;
    for (size_t i = 1500; i < 2100; i++) mono[i] = 12000;
    const size_t start = doa_loudest_window(mono, 3000);
    TEST_ASSERT_TRUE(start >= 1100 && start <= 1700);
    TEST_ASSERT_EQUAL_UINT32(0, static_cast<uint32_t>(doa_loudest_window(mono, 100)));
}

void test_setores() {
    TEST_ASSERT_EQUAL_UINT8(0, sector_from_azimuth(0.f));
    TEST_ASSERT_EQUAL_UINT8(0, sector_from_azimuth(22.f));
    TEST_ASSERT_EQUAL_UINT8(1, sector_from_azimuth(23.f));
    TEST_ASSERT_EQUAL_UINT8(0, sector_from_azimuth(359.f));
    TEST_ASSERT_EQUAL_UINT8(6, sector_from_azimuth(-90.f));
    TEST_ASSERT_EQUAL_STRING("NE", sector_name(1));
    TEST_ASSERT_EQUAL_STRING("SO", sector_name(5));
}

void test_comandos_validos_e_invalidos() {
    Settings s;
    TEST_ASSERT_TRUE(settings_apply(s, "threshold", 0.8f));
    TEST_ASSERT_EQUAL_FLOAT(0.8f, s.threshold);
    TEST_ASSERT_FALSE(settings_apply(s, "threshold", 0.1f));
    TEST_ASSERT_FALSE(settings_apply(s, "threshold", 1.5f));
    TEST_ASSERT_FALSE(settings_apply(s, "threshold", NAN));
    TEST_ASSERT_EQUAL_FLOAT(0.8f, s.threshold);
    TEST_ASSERT_TRUE(settings_apply(s, "motor_enabled", 0.f));
    TEST_ASSERT_FALSE(s.motor_enabled);
    TEST_ASSERT_FALSE(settings_apply(s, "motor_enabled", 2.f));
    TEST_ASSERT_TRUE(settings_apply(s, "port1_skew", -3.5f));
    TEST_ASSERT_FALSE(settings_apply(s, "port1_skew", 20.f));
    TEST_ASSERT_TRUE(settings_apply(s, "motor_max_ms", 800.f));
    TEST_ASSERT_EQUAL_UINT16(800, s.motor_max_ms);
    TEST_ASSERT_FALSE(settings_apply(s, "motor_max_ms", 5000.f));
    TEST_ASSERT_FALSE(settings_apply(s, "desconhecida", 1.f));
    TEST_ASSERT_FALSE(settings_apply(s, nullptr, 1.f));
}

void test_urgencia_e_motor() {
    TEST_ASSERT_EQUAL_UINT8(3, urgency_for_label("sirene"));
    TEST_ASSERT_EQUAL_UINT8(3, urgency_for_label("tiro_explosao"));
    TEST_ASSERT_EQUAL_UINT8(2, urgency_for_label("impacto"));
    TEST_ASSERT_EQUAL_UINT8(1, urgency_for_label("ferramenta"));
    TEST_ASSERT_EQUAL_UINT8(0, urgency_for_label("musica"));
    TEST_ASSERT_EQUAL_UINT8(0, urgency_for_label("rotulo_inexistente"));
    TEST_ASSERT_EQUAL_UINT8(0, urgency_for_label(nullptr));
    TEST_ASSERT_EQUAL_UINT8(0, motor_duty_for_urgency(0));
    TEST_ASSERT_TRUE(motor_duty_for_urgency(3) > motor_duty_for_urgency(1));
}

void test_recuo_primeira_tentativa_imediata() {
    Backoff b(1000, 8000);
    TEST_ASSERT_TRUE(b.due(0));
    b.attempted(0);
    TEST_ASSERT_FALSE(b.due(999));
    TEST_ASSERT_TRUE(b.due(1000));
}

void test_recuo_dobra_ate_o_teto() {
    Backoff b(1000, 5000);
    uint32_t agora = 0;
    const uint32_t esperadas[] = {1000, 2000, 4000, 5000, 5000};
    for (const uint32_t espera : esperadas) {
        TEST_ASSERT_TRUE(b.due(agora));
        b.attempted(agora);
        TEST_ASSERT_EQUAL_UINT32(espera, b.wait_ms());
        TEST_ASSERT_FALSE(b.due(agora + espera - 1));
        agora += espera;
    }
}

void test_recuo_recomeca_ao_conectar() {
    Backoff b(1000, 8000);
    b.attempted(0);
    b.attempted(1000);
    b.attempted(3000);
    TEST_ASSERT_EQUAL_UINT32(4000, b.wait_ms());
    b.connected();
    // Queda longe da última tentativa: reconecta na hora
    TEST_ASSERT_TRUE(b.due(60000));
    b.attempted(60000);
    TEST_ASSERT_EQUAL_UINT32(1000, b.wait_ms());
}

void test_recuo_enlace_instavel_respeita_espera_minima() {
    Backoff b(1000, 8000);
    b.attempted(5000);
    b.connected();
    // A conexão caiu logo depois de subir: não tenta de novo em laço apertado
    TEST_ASSERT_FALSE(b.due(5100));
    TEST_ASSERT_TRUE(b.due(6000));
}

void test_recuo_atravessa_virada_do_millis() {
    Backoff b(1000, 8000);
    const uint32_t antes = UINT32_MAX - 200;
    b.attempted(antes);
    TEST_ASSERT_FALSE(b.due(antes + 999));  // já virou, vale 798
    TEST_ASSERT_TRUE(b.due(antes + 1000));
}

void test_recuo_teto_nao_transborda() {
    Backoff b(3000000000u, UINT32_MAX);
    b.attempted(0);
    b.attempted(0);
    TEST_ASSERT_EQUAL_UINT32(UINT32_MAX, b.wait_ms());
}

void test_recuo_teto_menor_que_piso() {
    Backoff b(5000, 1000);
    b.attempted(0);
    b.attempted(0);
    TEST_ASSERT_EQUAL_UINT32(5000, b.wait_ms());
}

void test_motor_desliga_no_tempo_e_uma_vez() {
    MotorTimer t;
    TEST_ASSERT_TRUE(t.start(1000, 600));
    TEST_ASSERT_TRUE(t.active());
    TEST_ASSERT_EQUAL_UINT32(600, t.remaining_ms(1000));
    TEST_ASSERT_EQUAL_UINT32(1, t.remaining_ms(1599));
    TEST_ASSERT_FALSE(t.expired(1599));
    TEST_ASSERT_TRUE(t.expired(1600));
    TEST_ASSERT_FALSE(t.active());
    TEST_ASSERT_FALSE(t.expired(1601));
    TEST_ASSERT_EQUAL_UINT32(0, t.remaining_ms(1601));
}

void test_motor_atrasado_desliga_mesmo_assim() {
    MotorTimer t;
    t.start(0, 600);
    TEST_ASSERT_EQUAL_UINT32(0, t.remaining_ms(5000));
    TEST_ASSERT_TRUE(t.expired(5000));
}

void test_motor_respeita_descanso() {
    MotorTimer t;
    t.start(0, 600);
    TEST_ASSERT_FALSE(t.start(100, 600));  // ainda vibrando: não prolonga
    TEST_ASSERT_TRUE(t.expired(600));
    TEST_ASSERT_FALSE(t.start(899, 600));
    TEST_ASSERT_TRUE(t.start(900, 600));
}

void test_motor_primeira_vibracao_em_qualquer_momento() {
    // Sem vibração anterior não há descanso, mesmo depois de 25 dias ligado
    MotorTimer t;
    TEST_ASSERT_TRUE(t.start(0x80000010u, 600));
}

void test_motor_atravessa_virada_do_millis() {
    MotorTimer t;
    const uint32_t inicio = UINT32_MAX - 100;
    t.start(inicio, 600);
    TEST_ASSERT_EQUAL_UINT32(1, t.remaining_ms(inicio + 599));
    TEST_ASSERT_FALSE(t.expired(inicio + 599));
    TEST_ASSERT_TRUE(t.expired(inicio + 600));
    TEST_ASSERT_FALSE(t.start(inicio + 899, 600));
    TEST_ASSERT_TRUE(t.start(inicio + 900, 600));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_oito_setores_sem_ruido);
    RUN_TEST(test_azimutes_intermediarios);
    RUN_TEST(test_com_ruido);
    RUN_TEST(test_ruido_dominante_e_rejeitado);
    RUN_TEST(test_calibracao_de_desvio_entre_i2s);
    RUN_TEST(test_silencio_nao_e_valido);
    RUN_TEST(test_ruido_incoerente_tem_baixa_confianca);
    RUN_TEST(test_janela_mais_energetica);
    RUN_TEST(test_setores);
    RUN_TEST(test_comandos_validos_e_invalidos);
    RUN_TEST(test_urgencia_e_motor);
    RUN_TEST(test_recuo_primeira_tentativa_imediata);
    RUN_TEST(test_recuo_dobra_ate_o_teto);
    RUN_TEST(test_recuo_recomeca_ao_conectar);
    RUN_TEST(test_recuo_enlace_instavel_respeita_espera_minima);
    RUN_TEST(test_recuo_atravessa_virada_do_millis);
    RUN_TEST(test_recuo_teto_nao_transborda);
    RUN_TEST(test_recuo_teto_menor_que_piso);
    RUN_TEST(test_motor_desliga_no_tempo_e_uma_vez);
    RUN_TEST(test_motor_atrasado_desliga_mesmo_assim);
    RUN_TEST(test_motor_respeita_descanso);
    RUN_TEST(test_motor_primeira_vibracao_em_qualquer_momento);
    RUN_TEST(test_motor_atravessa_virada_do_millis);
    return UNITY_END();
}
