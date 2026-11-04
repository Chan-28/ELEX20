"""
YAMNet Transfer Learning — cabeças Dense e Conv1D
=================================================

Fluxo:
  dados brutos (float32, 16 kHz)
  → YAMNet congelado (feature extractor)
  → cabeça treinável (Dense ou Conv1D)
  → TFLite float32 + INT8 quantizado

AVISO DE DEPLOY (ESP32-S3 via Edge Impulse):
  O TFLite exportado contém APENAS a cabeça de classificação — NÃO o YAMNet.
  Para rodar no ESP32-S3, configure o projeto no Edge Impulse Studio com o
  bloco DSP "Raw audio" (não MFCC/MFE). O Studio bundla automaticamente
  YAMNet + cabeça na biblioteca Arduino exportada.
  Ver: https://docs.edgeimpulse.com/docs/edge-impulse-studio/learning-blocks/transfer-learning

CREDENCIAIS KAGGLE:
  KAGGLE_USERNAME e KAGGLE_KEY devem estar no ambiente.
  No Edge Impulse Studio: configure como segredos do bloco de treinamento.
  Localmente: ~/.kaggle/kaggle.json ou variáveis de ambiente.
"""

import argparse
import os
import shutil

import kagglehub
import numpy as np
import tensorflow as tf

SAMPLE_RATE = 16000
WINDOW_SAMPLES = 15600  # 975 ms — janela nativa do YAMNet


# ── Carregamento de dados ─────────────────────────────────────────────────────


def load_split(data_dir: str, split: str):
    x = np.load(os.path.join(data_dir, f"X_split_{split}.npy"), allow_pickle=True)
    y = np.load(os.path.join(data_dir, f"Y_split_{split}.npy"), allow_pickle=True)
    x = x.reshape(len(x), -1).astype(np.float32)
    if y.ndim == 2 and y.shape[1] > 1:
        y = np.argmax(y, axis=1)
    else:
        y = y.reshape(-1)
    return x, y.astype(np.int64)


# ── Extração de embeddings ────────────────────────────────────────────────────


def extract_embeddings_dense(yamnet, x: np.ndarray) -> np.ndarray:
    """Pool médio dos frames → vetor 1024-d por janela (entrada para Dense)."""
    out = []
    for window in x:
        _, embeddings, _ = yamnet(window[:WINDOW_SAMPLES])
        out.append(tf.reduce_mean(embeddings, axis=0).numpy())
    return np.stack(out)  # (N, 1024)


def extract_embeddings_conv(yamnet, x: np.ndarray) -> np.ndarray:
    """Sequência completa de frames (T × 1024) por janela (entrada para Conv1D).

    Para WINDOW_SAMPLES constante, T é fixo — não é necessário padding.
    """
    out = []
    for window in x:
        _, embeddings, _ = yamnet(window[:WINDOW_SAMPLES])
        out.append(embeddings.numpy())  # (T, 1024)
    return np.stack(out)  # (N, T, 1024)


# ── Arquiteturas ──────────────────────────────────────────────────────────────


def build_dense_model(num_classes: int) -> tf.keras.Model:
    """
    Cabeça Dense: recebe embedding médio (1024-d) e classifica.

    Adequada para sons estacionários: silêncio, chuva, trânsito contínuo.
    Mais leve e rápida de treinar.
    """
    return tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(1024,)),
            tf.keras.layers.Dense(128, activation="relu"),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.Dense(num_classes, activation="softmax"),
        ],
        name="dense_head",
    )


def build_conv1d_model(t_frames: int, num_classes: int) -> tf.keras.Model:
    """
    Cabeça Conv1D: processa a sequência temporal (T × 1024).

    Captura padrões no tempo: melhor para fala, música, alarmes.
    Recomendada quando Dense não atingir acurácia suficiente nessas classes.
    """
    return tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(t_frames, 1024)),
            tf.keras.layers.Conv1D(128, kernel_size=3, activation="relu", padding="same"),
            tf.keras.layers.GlobalAveragePooling1D(),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.Dense(num_classes, activation="softmax"),
        ],
        name="conv1d_head",
    )


# ── Exportação TFLite ─────────────────────────────────────────────────────────


def export_tflite(
    model: tf.keras.Model,
    embeddings: np.ndarray,
    out_dir: str,
    prefix: str,
) -> None:
    """Exporta float32 e INT8 quantizado com nomes descritivos."""
    model.save(os.path.join(out_dir, f"{prefix}_saved_model.keras"))

    # Float32 — referência e validação off-device
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    float_path = os.path.join(out_dir, f"{prefix}.tflite")
    with open(float_path, "wb") as f:
        f.write(converter.convert())

    # INT8 quantizado — deploy no ESP32-S3 via Edge Impulse SDK
    def representative_dataset():
        for i in range(min(100, len(embeddings))):
            yield [embeddings[i : i + 1]]

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_dataset
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    int8_path = os.path.join(out_dir, f"{prefix}_int8.tflite")
    with open(int8_path, "wb") as f:
        f.write(converter.convert())

    print(f"  {prefix}.tflite          (float32)")
    print(f"  {prefix}_int8.tflite     (INT8 — deploy ESP32)")
    return float_path, int8_path


# ── Treinamento ───────────────────────────────────────────────────────────────


def train_head(
    model: tf.keras.Model,
    e_train: np.ndarray,
    y_train: np.ndarray,
    e_test: np.ndarray,
    y_test: np.ndarray,
    args: argparse.Namespace,
) -> None:
    model.compile(
        optimizer=tf.keras.optimizers.Adam(args.learning_rate),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    model.fit(
        e_train,
        y_train,
        validation_data=(e_test, y_test),
        epochs=args.epochs,
        batch_size=args.batch_size,
    )


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="YAMNet transfer-learning — cabeça Dense ou Conv1D")
    parser.add_argument(
        "--data-directory",
        type=str,
        required=True,
        help="Diretório com X_split_*.npy e Y_split_*.npy (áudio bruto float32, 16 kHz, ≥ 15600 amostras por linha)",
    )
    parser.add_argument(
        "--out-directory",
        type=str,
        required=True,
        help="Diretório de saída para os modelos gerados",
    )
    parser.add_argument(
        "--head",
        type=str,
        default="dense",
        choices=["dense", "conv1d", "both"],
        help=(
            "Arquitetura da cabeça de classificação:\n"
            "  dense  — pool médio + Dense; sons estacionários (padrão)\n"
            "  conv1d — sequência temporal + Conv1D; fala/alarme/música\n"
            "  both   — treina e exporta as duas arquiteturas"
        ),
    )
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    os.makedirs(args.out_directory, exist_ok=True)

    x_train, y_train = load_split(args.data_directory, "train")
    x_test, y_test = load_split(args.data_directory, "test")

    # Normaliza labels para índices contíguos a partir de 0
    y_min = min(y_train.min(), y_test.min())
    y_train -= y_min
    y_test -= y_min
    num_classes = int(max(y_train.max(), y_test.max())) + 1
    print(f"Treino: {x_train.shape}  |  teste: {x_test.shape}  |  classes: {num_classes}")

    print("Carregando YAMNet (congelado como feature extractor)…")
    path = kagglehub.model_download("google/yamnet/tensorFlow2/yamnet")
    yamnet = tf.saved_model.load(path)

    train_dense = args.head in ("dense", "both")
    train_conv1d = args.head in ("conv1d", "both")

    last_float_path = None
    last_int8_path = None

    # ── Cabeça Dense ──────────────────────────────────────────────────────────
    if train_dense:
        print("\n" + "=" * 60)
        print("CABEÇA DENSE")
        print("=" * 60)
        print("Extraindo embeddings médios (1024-d)…")
        e_train = extract_embeddings_dense(yamnet, x_train)
        e_test = extract_embeddings_dense(yamnet, x_test)

        model = build_dense_model(num_classes)
        model.summary()
        train_head(model, e_train, y_train, e_test, y_test, args)

        print("Exportando modelos Dense…")
        float_path, int8_path = export_tflite(model, e_train, args.out_directory, "model_dense")
        last_float_path = float_path
        last_int8_path = int8_path

    # ── Cabeça Conv1D ─────────────────────────────────────────────────────────
    if train_conv1d:
        print("\n" + "=" * 60)
        print("CABEÇA CONV1D")
        print("=" * 60)
        print("Extraindo sequências de embeddings (T × 1024)…")
        e_train_seq = extract_embeddings_conv(yamnet, x_train)
        e_test_seq = extract_embeddings_conv(yamnet, x_test)
        t_frames = e_train_seq.shape[1]
        print(f"  Frames por janela: {t_frames}")

        model = build_conv1d_model(t_frames, num_classes)
        model.summary()
        train_head(model, e_train_seq, y_train, e_test_seq, y_test, args)

        print("Exportando modelos Conv1D…")
        float_path, int8_path = export_tflite(model, e_train_seq, args.out_directory, "model_conv1d")
        last_float_path = float_path
        last_int8_path = int8_path

    # ── Copia nomes padrão do Edge Impulse (quando apenas uma cabeça foi treinada)
    # O Studio espera model.tflite e model_quantized_int8_io.tflite na saída.
    if args.head != "both" and last_float_path and last_int8_path:
        shutil.copy(last_float_path, os.path.join(args.out_directory, "model.tflite"))
        shutil.copy(last_int8_path, os.path.join(args.out_directory, "model_quantized_int8_io.tflite"))
        print("\n  model.tflite                   (alias EI — float32)")
        print("  model_quantized_int8_io.tflite (alias EI — INT8)")

    print(f"\nPronto. Arquivos gerados em: {args.out_directory}")


if __name__ == "__main__":
    main()
