import sys
import os
os.environ["QT_API"] = "pyqt6"
import logging
import csv
import time
import tempfile
import shutil
import subprocess
from pathlib import Path
import math
import mne
import numpy as np
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QThread, pyqtSignal
import pyqtgraph as pg
from typing import Any, cast
from collections import deque

mne.viz.set_browser_backend('qt')
LOGGER = logging.getLogger("janela_neuro")


def configurar_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


# Nota: Python e R devem estar instalados globalmente no sistema.
# Este código assume que ambos estão disponíveis no PATH do usuário.


def caminho_saida_dir() -> Path:
    """Retorna diretório estável de saída sem depender do diretório de execução."""
    base_dir = Path(__file__).resolve().parent
    output_dir = Path(os.environ.get("NEURO_OUTPUT_DIR", base_dir / "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def calcular_parametros_sinal(raw, n_segmentos=20) -> tuple[list[dict], dict]:
    """
    Modificado para segmentar o sinal em N partes.
    Isso garante que o R tenha dados suficientes para gerar estatísticas.
    """
    dados = raw.get_data()
    sfreq = float(raw.info.get("sfreq", 1.0))
    ch_names = raw.ch_names
    
    # Tamanho de cada segmento
    n_amostras_total = dados.shape[1]
    tamanho_seg = n_amostras_total / n_segmentos
    
    metricas_acumuladas = []

    for i, canal_completo in enumerate(dados):
        for s in range(n_segmentos):
            start = int(s * tamanho_seg)
            end = int(start + tamanho_seg)
            sinal = canal_completo[start:end]
            
            if sinal.size < 2: continue
            
            # Cálculo de métricas por segmento
            rms = float(np.sqrt(np.mean(np.square(sinal))))
            wl = float(np.sum(np.abs(np.diff(sinal))))
            cruzamentos = int(np.sum((sinal[:-1] * sinal[1:]) < 0))
            zcr = float(cruzamentos / (sinal.size - 1))
            
            # Espectro para freq mediana
            psd = np.abs(np.fft.rfft(sinal - np.mean(sinal))) ** 2
            freqs = np.fft.rfftfreq(sinal.size, d=1.0 / sfreq)
            if np.sum(psd) > 0:
                idx_mediana = np.searchsorted(np.cumsum(psd), np.sum(psd) / 2.0)
                freq_mediana = float(freqs[min(idx_mediana, len(freqs)-1)])
            else:
                freq_mediana = 0.0

            metricas_acumuladas.append({
                "canal": ch_names[i],
                "rms": rms,
                "freq_mediana": freq_mediana,
                "zcr": zcr,
                "waveform_length": wl,
            })

    # Médias globais
    medias = {k: float(np.mean([m[k] for m in metricas_acumuladas])) for k in ["rms", "freq_mediana", "zcr", "waveform_length"]}
    return metricas_acumuladas, medias

# UI STYLE SHEET (Inspirado no estilo limpo do HTML5 UP)
ESTILO_PREMIUM = """
    QMainWindow { background-color: #f4f4f4; }
    QDialog, QMessageBox {
        background-color: #ffffff;
        color: #1f2937;
    }
    QToolTip {
        background-color: #ffffff;
        color: #111827;
        border: 1px solid #d1d5db;
    }
    QMenu, QMenuBar, QStatusBar, QScrollArea, QFrame {
        background-color: #ffffff;
        color: #1f2937;
    }
    
    /* Painel Lateral Estilo 'Sidebar' */
    QWidget#Sidebar { 
        background-color: #2c3e50; 
        border-right: 3px solid #1a252f;
    }
    
    QLabel { font-family: 'Helvetica Neue', Helvetica, Arial; color: #333; }
    QLabel#Logo { 
        background-color: #000000;
        color: #ffffff; 
        font-size: 22px; 
        font-weight: 300; 
        letter-spacing: 2px;
        border-radius: 6px;
        padding: 20px;
    }
    
    /* Botões Estilo Flat Design */
    QPushButton {
        background-color: transparent;
        color: #bdc3c7;
        border: 1px solid #7f8c8d;
        border-radius: 2px;
        padding: 12px;
        text-align: left;
        font-size: 13px;
        margin: 5px 15px;
    }
    QPushButton:hover { 
        color: #ffffff; 
        border-color: #ffffff; 
        background-color: #34495e; 
    }
    
    /* Containers de Gráficos */
    QGroupBox {
        background-color: #ffffff;
        border: 1px solid #dcdde1;
        border-top: 4px solid #3498db;
        border-radius: 4px;
        margin-top: 20px;
        font-weight: bold;
        color: #2c3e50;
    }
"""


class LSLRealtimeWorker(QThread):
    """Worker que captura dados do LSL continuamente em tempo real."""
    
    # Sinais emitidos quando novos dados chegam
    dados_atualizados = pyqtSignal(np.ndarray, np.ndarray)  # (raw_bruto, raw_filt)
    status_atualizado = pyqtSignal(str)
    erro_captura = pyqtSignal(str)
    
    def __init__(self, sfreq: float = 250.0, buffer_size: int = 500, intervalo_atualizar: float = 0.1):
        """
        Args:
            sfreq: Frequência de amostragem (Hz)
            buffer_size: Tamanho do buffer (amostras) - default 10 segundos a 250 Hz
            intervalo_atualizar: Intervalo mínimo entre emissões de sinais (segundos)
        """
        super().__init__()
        self.sfreq = sfreq
        self.buffer_size = buffer_size
        self.intervalo_atualizar = intervalo_atualizar
        self._running = False
        self._pause = False
        self.n_canais = 2  # Padrão: 2 canais EMG
        
    def run(self):
        import time as _time
        self._running = True
        last_update = _time.time()
        
        try:
            import pylsl
        except ImportError:
            self.erro_captura.emit("pylsl não disponível. LSL em tempo real desativado.")
            self._running = False
            return
        
        emg_inlet = None
        emg_proc_inlet = None
        timeout_busca = 5.0
        start_time = _time.time()
        
        while (_time.time() - start_time) < timeout_busca and self._running:
            available_streams = pylsl.resolve_streams(wait_time=0.5)
            for stream_info in available_streams:
                stream_name = stream_info.name()
                if stream_name == "EMG" and emg_inlet is None:
                    emg_inlet = pylsl.StreamInlet(stream_info, max_buflen=360)
                    self.n_canais = stream_info.channel_count()
                    nominal = float(stream_info.nominal_srate())
                    if nominal > 0: 
                        self.sfreq = nominal
                    self.status_atualizado.emit(f"Conectado ao stream EMG ({self.n_canais} canais)")
                elif stream_name == "EMG_Processado" and emg_proc_inlet is None:
                    emg_proc_inlet = pylsl.StreamInlet(stream_info, max_buflen=360)
                    self.status_atualizado.emit("Conectado ao stream EMG_Processado")
            if emg_inlet is not None and emg_proc_inlet is not None:
                break
        
        if emg_inlet is None or emg_proc_inlet is None:
            self.erro_captura.emit("Streams LSL necessários não encontrados.")
            self._running = False
            return

        # ALTERAÇÃO AQUI: Calculamos o tamanho ideal baseado na frequência REAL do LSL
        # Queremos armazenar exatamente 5 segundos de histórico para preencher o MNE Browser por completo
        tamanho_historico = int(5.0 * self.sfreq)
        
        # Usamos deques circulares para gerenciar o stream sem problemas de índices
        fila_bruto = deque(maxlen=tamanho_historico)
        fila_filt = deque(maxlen=tamanho_historico)
        
        self.status_atualizado.emit("Capturando dados em tempo real...")
        
        while self._running:
            try:
                if self._pause:
                    _time.sleep(0.05)
                    continue
                
                sample, timestamp = emg_inlet.pull_sample(timeout=0.1)
                if sample is not None:
                    fila_bruto.append(sample)
                    
                    sample_proc, _ = emg_proc_inlet.pull_sample(timeout=0.01)
                    if sample_proc is not None:
                        fila_filt.append(sample_proc)
                    else:
                        fila_filt.append(sample) # Fallback caso o filtrado falhe
                    
                    if (_time.time() - last_update) >= self.intervalo_atualizar:
                        # Convertemos a fila atual diretamente em matrizes para os gráficos
                        bruto_sorted = np.array(fila_bruto, dtype=float).T
                        filt_sorted = np.array(fila_filt, dtype=float).T
                        
                        # Se a fila ainda estiver no início (poucas amostras), o sinal se moverá
                        # livremente desde o início da tela sem gerar linhas retas fantasmas
                        self.dados_atualizados.emit(bruto_sorted, filt_sorted)
                        last_update = _time.time()
                
            except Exception as e:
                LOGGER.debug(f"Erro na captura LSL realtime: {e}")
                _time.sleep(0.01)
        
        self.status_atualizado.emit("Captura em tempo real parada.")
    
    def parar(self):
        """Para a captura de dados."""
        self._running = False
    
    def pausar(self, pausado: bool = True):
        """Pausa/retoma a captura sem encerrar a thread."""
        self._pause = pausado


class JanelaNeuro(QtWidgets.QMainWindow):
    def __init__(self, raw_bruto, raw_filt):
        super().__init__()
        self.setWindowTitle("Análise Neurofisiológica")
        self.setWindowFlag(QtCore.Qt.WindowType.WindowSystemMenuHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowState(self.windowState() | QtCore.Qt.WindowState.WindowMaximized)
        self.setStyleSheet(ESTILO_PREMIUM)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout_main = QtWidgets.QHBoxLayout(central)
        layout_main.setContentsMargins(0, 0, 0, 0)
        layout_main.setSpacing(0)

        # --- SIDEBAR (HTML5 UP STYLE) ---
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(280)
        layout_side = QtWidgets.QVBoxLayout(sidebar)
        
        lbl_logo = QtWidgets.QLabel("Análise Miográfrica")
        lbl_logo.setObjectName("Logo")
        lbl_logo.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        
        btn1 = QtWidgets.QPushButton("📊 DASHBOARD PRINCIPAL")
        btn2 = QtWidgets.QPushButton("🔍 INSPEÇÃO DE CANAIS")
        btn3 = QtWidgets.QPushButton("💾 EXPORTAR RELATÓRIO")
        btn_toggle_metricas = QtWidgets.QPushButton("🧮 ALTERNAR VISUALIZAÇÃO")
        btn_reset = QtWidgets.QPushButton("🔄 RESETAR ZOOM")
        btn_reload_from_lsl = QtWidgets.QPushButton("⬇️ Atualizar dados")
        btn1.clicked.connect(lambda: self.mostrar_em_desenvolvimento("Dashboard principal"))
        btn2.clicked.connect(self.abrir_mne_browser)
        btn3.clicked.connect(self.exportar_relatorio)
        btn_toggle_metricas.clicked.connect(self.alternar_visualizacao_analise)
        btn_reset.clicked.connect(self.reset_views)
        btn_reload_from_lsl.clicked.connect(self.recarregar_de_lsl)

        layout_side.addWidget(lbl_logo)
        layout_side.addSpacing(40)
        layout_side.addWidget(btn1)
        layout_side.addWidget(btn2)
        layout_side.addWidget(btn3)
        layout_side.addWidget(btn_toggle_metricas)
        layout_side.addWidget(btn_reset)
        layout_side.addWidget(btn_reload_from_lsl)
        layout_side.addStretch()
        
        lbl_footer = QtWidgets.QLabel("ELEX20 - 2026/1")
        lbl_footer.setStyleSheet("color: #7f8c8d; font-size: 10px; margin: 20px;")
        layout_side.addWidget(lbl_footer)

        # --- ÁREA DE CONTEÚDO (Grid de Gráficos) ---
        area_conteudo = QtWidgets.QWidget()
        layout_grid = QtWidgets.QGridLayout(area_conteudo)
        layout_grid.setContentsMargins(30, 30, 30, 30)
        layout_grid.setSpacing(20)

        # Estado interno precisa existir antes de chamar carregar_r().
        self._tmp_dir_r_atual = None
        self._ultimo_bruto = None
        self._ultimo_filt = None
        self._graficos_ja_plotados = False
        self.window_seconds = 1.0
        self.mne_browser = None
        self._mne_browser_aberto = False
        # Evita reaberturas em loop do MNE Browser
        self._mne_browser_reopen_pending = False
        # Normalizar sinais para visualização no MNE Browser
        self.mne_normalize = True
        # Ganho visual aplicado ao sinal antes de renderizar no MNE Browser
        self.mne_gain = 1.0
        self._mne_browser_refresh_pending = False
        self._mne_browser_last_refresh = 0.0
        self._mne_browser_refresh_interval = 0.8

        gain_box = QtWidgets.QFrame()
        gain_box.setObjectName("MneGainBox")
        gain_layout = QtWidgets.QVBoxLayout(gain_box)
        gain_layout.setContentsMargins(12, 8, 12, 8)
        gain_layout.setSpacing(6)

        gain_box.setStyleSheet(
            """
            QFrame#MneGainBox {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 10px;
            }
            QFrame#MneGainBox QLabel {
                color: #ecf0f1;
            }
            QFrame#MneGainBox QSlider::groove:horizontal {
                height: 6px;
                background: rgba(255, 255, 255, 0.18);
                border-radius: 3px;
            }
            QFrame#MneGainBox QSlider::sub-page:horizontal {
                background: #3498db;
                border-radius: 3px;
            }
            QFrame#MneGainBox QSlider::handle:horizontal {
                background: #ecf0f1;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
                border: 1px solid rgba(0, 0, 0, 0.2);
            }
            """
        )

        lbl_gain_title = QtWidgets.QLabel("Ganho do MNE Browser")
        lbl_gain_title.setStyleSheet("color: #000000; font-weight: bold; margin-left: 15px;")

        gain_row = QtWidgets.QHBoxLayout()
        gain_row.setContentsMargins(0, 0, 0, 0)
        lbl_gain_min = QtWidgets.QLabel("0.05x")
        lbl_gain_min.setStyleSheet("color: #000000; font-size: 11px;")
        self.slider_mne_gain = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_mne_gain.setRange(1, 200)
        self.slider_mne_gain.setValue(20)
        self.slider_mne_gain.setSingleStep(1)
        self.slider_mne_gain.setPageStep(5)
        self.lbl_mne_gain_val = QtWidgets.QLabel("1.00x")
        self.lbl_mne_gain_val.setStyleSheet("color: #000000; font-size: 11px; min-width: 44px; font-weight: bold;")
        lbl_gain_max = QtWidgets.QLabel("10.0x")
        lbl_gain_max.setStyleSheet("color: #000000; font-size: 11px;")

        gain_row.addWidget(lbl_gain_min)
        gain_row.addWidget(self.slider_mne_gain)
        gain_row.addWidget(self.lbl_mne_gain_val)
        gain_row.addWidget(lbl_gain_max)

        gain_layout.addWidget(lbl_gain_title)
        gain_layout.addLayout(gain_row)
        layout_side.addWidget(gain_box)

        try:
            self.slider_mne_gain.valueChanged.connect(getattr(self, 'on_mne_gain_changed', lambda: None))
        except Exception:
            pass
        
        # Caixa única para sinal (permite alternar entre Bruto e Processado)
        box_signal = QtWidgets.QGroupBox("EMG (Bruto / Processado)")
        self.layout_signal = QtWidgets.QVBoxLayout(box_signal)
        box_signal.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

        # Controle para escolher qual sinal exibir
        signal_ctrl = QtWidgets.QWidget()
        signal_ctrl_layout = QtWidgets.QHBoxLayout(signal_ctrl)
        signal_ctrl_layout.setContentsMargins(6, 6, 6, 6)
        lbl_signal = QtWidgets.QLabel("Mostrar:")
        self.signal_source_combo = QtWidgets.QComboBox()
        self.signal_source_combo.addItems(["EMG Processado", "EMG Bruto"])
        self.signal_source_combo.setCurrentIndex(0)
        signal_ctrl_layout.addWidget(lbl_signal)
        signal_ctrl_layout.addWidget(self.signal_source_combo)
        signal_ctrl_layout.addStretch()

        # Cria o plot único (inicializa com o sinal processado por padrão)
        default_raw = raw_filt if raw_filt is not None else raw_bruto
        self.plot_signal = self.criar_pyqtgraph(default_raw, "#2ecc71")
        self.layout_signal.addWidget(signal_ctrl)
        self.layout_signal.addWidget(self.plot_signal)

        # Conecta mudança do combo para atualizar o plot imediatamente
        try:
            self.signal_source_combo.currentIndexChanged.connect(getattr(self, 'on_signal_controls_changed', lambda: None))
        except Exception:
            pass

        box_fft = QtWidgets.QGroupBox("FFT (Amplitude x Frequência)")
        self.layout_fft = QtWidgets.QVBoxLayout(box_fft)
        box_fft.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        # Controles da FFT: escolha de fonte e limite de frequência
        self.plot_fft = self.criar_plot_fft()

        fft_ctrl_widget = QtWidgets.QWidget()
        fft_ctrl_layout = QtWidgets.QHBoxLayout(fft_ctrl_widget)
        fft_ctrl_layout.setContentsMargins(6, 6, 6, 6)

        lbl_source = QtWidgets.QLabel("Fonte FFT:")
        self.fft_source_combo = QtWidgets.QComboBox()
        # Ordem: preferir Processado por padrão
        self.fft_source_combo.addItems(["EMG Processado", "EMG Bruto"])
        self.fft_source_combo.setCurrentIndex(0)

        lbl_max = QtWidgets.QLabel("Freq. máx. (Hz):")
        self.fft_max_spin = QtWidgets.QSpinBox()
        self.fft_max_spin.setRange(1, 2000)
        self.fft_max_spin.setValue(10)
        self.fft_max_spin.setSingleStep(1)

        fft_ctrl_layout.addWidget(lbl_source)
        fft_ctrl_layout.addWidget(self.fft_source_combo)
        fft_ctrl_layout.addStretch()
        fft_ctrl_layout.addWidget(lbl_max)
        fft_ctrl_layout.addWidget(self.fft_max_spin)

        # Adiciona controles acima do gráfico
        self.layout_fft.addWidget(fft_ctrl_widget)
        self.layout_fft.addWidget(self.plot_fft)

        # Conecta sinais de controle para atualização imediata
        try:
            # Use getattr to avoid static analyzer complaining if the method
            # is not yet resolved in some analysis contexts.
            self.fft_source_combo.currentIndexChanged.connect(getattr(self, 'on_fft_controls_changed', lambda: None))
            self.fft_max_spin.valueChanged.connect(getattr(self, 'on_fft_controls_changed', lambda: None))
        except Exception:
            # Em situações de inicialização precoce, ignorar falhas aqui
            pass

        # Box do R
        box_r = QtWidgets.QGroupBox("Análise Estatística")
        layout_r = QtWidgets.QVBoxLayout(box_r)
        box_r.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.lbl_modo_analise = QtWidgets.QLabel("Modo atual: Gráfico (R + ggplot2)")
        self.lbl_modo_analise.setStyleSheet("font-weight: normal; color: #34495e;")
        layout_r.addWidget(self.lbl_modo_analise)


        self.metricas_por_canal, self.metricas_medias = calcular_parametros_sinal(raw_filt)

        self.painel_analise = QtWidgets.QStackedWidget()
        self.widget_graficos = self.criar_widget_graficos()
        self.widget_metricas = self.criar_widget_metricas()
        self.painel_analise.addWidget(self.widget_graficos)
        self.painel_analise.addWidget(self.widget_metricas)
        layout_r.addWidget(self.painel_analise)

        # Organizando no Grid
        # Organiza: sinal único e FFT em sequência na coluna 0
        layout_grid.addWidget(box_signal, 0, 0)
        layout_grid.addWidget(box_fft, 1, 0)
        layout_grid.addWidget(box_r, 0, 1, 2, 1) # Ocupa duas linhas na coluna 1

        # Dá mais largura à coluna de análise (R) para evitar cortes/scroll horizontal
        layout_grid.setColumnStretch(0, 1)
        layout_grid.setColumnStretch(1, 2)

        layout_main.addWidget(sidebar)
        layout_main.addWidget(area_conteudo)

        # --- Inicializa thread de captura LSL em tempo real ---
        # buffer_size=1250 = 5 segundos de histórico a 250 Hz (escala menor no eixo X)
        self.lsl_worker = LSLRealtimeWorker(sfreq=250.0, buffer_size=1, intervalo_atualizar=0.10)
        self.lsl_worker.dados_atualizados.connect(self.on_dados_lsl_recebidos)
        self.lsl_worker.status_atualizado.connect(self.on_status_lsl_atualizado)
        self.lsl_worker.erro_captura.connect(self.on_erro_lsl)
        self.lsl_worker.start()
        
        # Armazena referência ao plot único para atualização suave
        self.plot_items_signal = []
        self.raw_browser = raw_filt.copy()
        self._plot_buffer_bruto = None
        self._plot_buffer_filt = None

        # Mantido apenas para inspeção manual via botão.

    def criar_pyqtgraph(self, raw, cor_sinal):
        pw = pg.PlotWidget()
        pw.setBackground('#ffffff')
        pw.showGrid(x=True, y=True, alpha=0.1)
        
        # Configurar eixo X com escala pequena mas SEM mostrar números
        axis_x = pw.getAxis('bottom')
        axis_x.setTickSpacing(major=0.05, minor=0.01)
        axis_x.setLabel(text='Tempo', units='s')
        axis_x.setStyle(showValues=False)  # Esconde os números (reduz poluição visual)
        
        times = raw.times
        data = raw.get_data()
        
        # Plotando 2 canais com espessura premium
        plot_items = []
        for i in range(min(2, data.shape[0])):
            pen = pg.mkPen(color=cor_sinal, width=2, style=QtCore.Qt.PenStyle.SolidLine if i==0 else QtCore.Qt.PenStyle.DashLine)
            item = pw.plot(times, data[i, :], pen=pen)
            plot_items.append((item, times))
        
        # Remove bordas padrão para visual mais limpo
        pw.hideAxis('left')
        pw.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        
        # Armazena referência aos items para atualização posterior
        setattr(pw, '_plot_items', plot_items)
        window_samples = max(1, int(self.window_seconds * 250.0))
        setattr(pw, '_plot_display', np.asarray(data[:min(2, data.shape[0]), -window_samples:], dtype=float).copy())
        return pw

    def criar_plot_fft(self):
        pw = pg.PlotWidget()
        pw.setBackground('#ffffff')
        pw.showGrid(x=True, y=True, alpha=0.1)
        pw.setLabel('bottom', 'Frequência', units='Hz')
        pw.setLabel('left', 'Amplitude')
        pen = pg.mkPen(color="#f39c12", width=2)
        self.fft_curve = pw.plot([], [], pen=pen)
        return pw

    def atualizar_plot_fft(self, dados_novos: np.ndarray) -> None:
        try:
            if dados_novos is None or dados_novos.size == 0:
                return

            sfreq = float(getattr(self.lsl_worker, "sfreq", 250.0))
            if sfreq <= 0:
                sfreq = 250.0

            canal = np.asarray(dados_novos[0, :], dtype=float)
            if canal.size < 8:
                return

            # Janela para suavizar leakage espectral.
            janela = np.hanning(canal.size)
            sinal = (canal - np.mean(canal)) * janela

            fft_vals = np.fft.rfft(sinal)
            freqs = np.fft.rfftfreq(sinal.size, d=1.0 / sfreq)
            amp = np.abs(fft_vals)

            # Aplica limite de frequência definido pelo usuário
            try:
                max_freq = int(getattr(self, 'fft_max_spin').value())
            except Exception:
                max_freq = 20

            if np.isfinite(max_freq) and max_freq > 0:
                mask = freqs <= float(max_freq)
                if np.any(mask):
                    freqs_plot = freqs[mask]
                    amp_plot = amp[mask]
                else:
                    freqs_plot = freqs
                    amp_plot = amp
            else:
                freqs_plot = freqs
                amp_plot = amp

            self.fft_curve.setData(freqs_plot, amp_plot)
        except Exception as e:
            LOGGER.debug(f"Erro ao atualizar FFT: {e}")
    
    def atualizar_plot_dados(self, plot_widget, dados_novos: np.ndarray) -> None:
        """Atualiza os dados dos plots existentes sem remover/recriar.
        
        Args:
            plot_widget: O PlotWidget já existente
            dados_novos: Array numpy com dados (n_canais x n_amostras)
        """
        try:
            plot_items = getattr(plot_widget, '_plot_items', None)
            if plot_items is None or len(plot_items) == 0:
                return

            sfreq = 250.0
            window_samples = max(1, int(self.window_seconds * sfreq))

            n_canais_plot = min(len(plot_items), dados_novos.shape[0])
            if n_canais_plot <= 0:
                return

            dados_window = np.asarray(dados_novos[:n_canais_plot, -window_samples:], dtype=float)
            if dados_window.shape[1] == 0:
                return

            display_anterior = getattr(plot_widget, '_plot_display', None)
            if (
                display_anterior is not None
                and isinstance(display_anterior, np.ndarray)
                and display_anterior.shape == dados_window.shape
            ):
                # Smoothing temporal leve para reduzir tremulação sem perder dinâmica.
                alpha = 0.72
                dados_display = (alpha * dados_window) + ((1.0 - alpha) * display_anterior)
            else:
                dados_display = dados_window.copy()

            setattr(plot_widget, '_plot_display', dados_display)
            times = np.linspace(-self.window_seconds, 0.0, dados_display.shape[1], endpoint=False)
            
            # Atualiza cada plot item com os novos dados
            for idx, (plot_item, _) in enumerate(plot_items):
                if idx < dados_display.shape[0]:
                    plot_item.setData(times, dados_display[idx, :], connect="finite")

            plot_widget.setXRange(-self.window_seconds, 0.0, padding=0.0)
            y_min = float(np.nanmin(dados_display)) if dados_display.size else -1.0
            y_max = float(np.nanmax(dados_display)) if dados_display.size else 1.0
            if not np.isfinite(y_min) or not np.isfinite(y_max) or abs(y_max - y_min) < 1e-12:
                y_min, y_max = -1.0, 1.0
            margem = max((y_max - y_min) * 0.15, 1e-6)
            plot_widget.setYRange(y_min - margem, y_max + margem, padding=0.0)
                    
        except Exception as e:
            LOGGER.debug(f"Erro ao atualizar dados do plot: {e}")

    def on_dados_lsl_recebidos(self, dados_bruto: np.ndarray, dados_filt: np.ndarray) -> None:
        """Slot chamado quando novos dados LSL chegam.
        
        Args:
            dados_bruto: Array com dados brutos (n_canais x n_amostras)
            dados_filt: Array com dados filtrados (n_canais x n_amostras)
        """
        try:
            # Guarda ultimo buffer para recarregar o R sem travar a UI
            self._ultimo_bruto = dados_bruto
            self._ultimo_filt = dados_filt

            # Escolhe qual buffer mostrar no plot unico (controle do usuário)
            try:
                sel = getattr(self, 'signal_source_combo', None)
                if sel is not None and sel.currentText().startswith("EMG Bruto"):
                    display_buf = dados_bruto
                else:
                    display_buf = dados_filt if dados_filt is not None else dados_bruto
            except Exception:
                display_buf = dados_filt if dados_filt is not None else dados_bruto

            # Atualiza o plot unico com o buffer selecionado
            try:
                self.atualizar_plot_dados(self.plot_signal, display_buf)
            except Exception:
                pass

            # Atualiza FFT usando a fonte selecionada pelo usuário para FFT
            try:
                combo = getattr(self, 'fft_source_combo', None)
                if combo is not None and combo.currentText().startswith("EMG Bruto"):
                    fft_buf = dados_bruto
                else:
                    fft_buf = dados_filt if dados_filt is not None else dados_bruto
                self.atualizar_plot_fft(fft_buf)
            except Exception:
                self.atualizar_plot_fft(dados_filt if dados_filt is not None else dados_bruto)

            self.atualizar_mne_browser(dados_filt)
        except Exception as e:
            LOGGER.debug(f"Erro ao processar dados LSL: {e}")

    def on_fft_controls_changed(self) -> None:
        """Handler chamado quando os controles da FFT mudam (fonte ou limite de frequência)."""
        try:
            # Atualiza imediatamente a plotagem com o ultimo buffer conhecido
            sel = getattr(self, 'fft_source_combo', None)
            if sel is not None and sel.currentText().startswith("EMG Bruto"):
                buf = self._ultimo_bruto
            else:
                buf = self._ultimo_filt if self._ultimo_filt is not None else self._ultimo_bruto

            if buf is not None:
                self.atualizar_plot_fft(buf)
        except Exception as e:
            LOGGER.debug(f"Erro ao aplicar controles FFT: {e}")

    def on_signal_controls_changed(self) -> None:
        """Handler chamado quando o controle de sinal muda (bruto/processado)."""
        try:
            sel = getattr(self, 'signal_source_combo', None)
            if sel is not None and sel.currentText().startswith("EMG Bruto"):
                buf = self._ultimo_bruto
            else:
                buf = self._ultimo_filt if self._ultimo_filt is not None else self._ultimo_bruto

            if buf is not None:
                try:
                    self.atualizar_plot_dados(self.plot_signal, buf)
                except Exception:
                    pass
        except Exception as e:
            LOGGER.debug(f"Erro ao aplicar controle de sinal: {e}")

    def on_mne_gain_changed(self, valor: int) -> None:
        """Atualiza o ganho visual do MNE Browser a partir do slider."""
        try:
            ganho = max(0.05, float(valor) / 20.0)
            self.mne_gain = ganho
            if hasattr(self, 'lbl_mne_gain_val') and self.lbl_mne_gain_val is not None:
                self.lbl_mne_gain_val.setText(f"{ganho:.2f}x")

            ultimo_filt = getattr(self, '_ultimo_filt', None)
            if isinstance(ultimo_filt, np.ndarray):
                self.atualizar_mne_browser(ultimo_filt)
        except Exception as e:
            LOGGER.debug(f"Erro ao ajustar ganho do MNE Browser: {e}")

    def on_status_lsl_atualizado(self, mensagem: str) -> None:
        """Slot para atualizar a barra de status com mensagens do LSL worker."""
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage(mensagem)
        LOGGER.info(f"LSL Status: {mensagem}")

    def on_erro_lsl(self, mensagem_erro: str) -> None:
        """Slot para tratar erros de captura LSL."""
        LOGGER.warning(f"Erro LSL: {mensagem_erro}")
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage(f"Erro: {mensagem_erro}")

    def atualizar_plots_pyqtgraph(self, raw_bruto, raw_filt) -> None:
        """Atualiza os gráficos pyqtgraph com novos dados.
        
        Args:
            raw_bruto: Dados brutos em formato MNE Raw
            raw_filt: Dados filtrados em formato MNE Raw
        """
        try:
            # Remove widget antigo do plot unico
            if getattr(self, 'plot_signal', None) is not None:
                try:
                    self.layout_signal.removeWidget(self.plot_signal)
                    self.plot_signal.deleteLater()
                except Exception:
                    pass

            # Decide qual raw usar para inicialização do widget
            default_raw = raw_filt if raw_filt is not None else raw_bruto
            self.plot_signal = self.criar_pyqtgraph(default_raw, "#2ecc71")
            self.layout_signal.addWidget(self.plot_signal)

            LOGGER.info("Gráfico pyqtgraph único atualizado com sucesso")
        except Exception as e:
            LOGGER.exception(f"Erro ao atualizar gráficos pyqtgraph: {e}")

    def criar_widget_graficos(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        self.lbl_status_graficos = QtWidgets.QLabel("Atualize para plotar os gráficos.")
        self.lbl_status_graficos.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        layout.addWidget(self.lbl_status_graficos)

        scroll = QtWidgets.QScrollArea()
        self.scroll_graficos = scroll
        scroll.setWidgetResizable(True)
        # Evita barra de rolagem horizontal indesejada
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QtWidgets.QWidget()
        # Layout interno sem margens para ocupar todo o espaço do scroll
        self.layout_graficos = QtWidgets.QVBoxLayout(scroll_content)
        self.layout_graficos.setContentsMargins(0, 0, 0, 0)
        self.layout_graficos.setSpacing(12)

        self.lbl_r_box = QtWidgets.QLabel("Violino")
        self.lbl_r_pairs = QtWidgets.QLabel("Matriz de Dispersão")
        self.lbl_r_biplot = QtWidgets.QLabel("Biplot")

        for lbl in (self.lbl_r_box, self.lbl_r_pairs, self.lbl_r_biplot):
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            # Permite que o label expanda horizontalmente dentro do layout
            lbl.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            lbl.setFixedHeight(620)
            lbl.setStyleSheet("background: #ffffff; border: 1px solid #dcdde1; padding: 20px;")
            lbl.setText("Atualize para plotar os gráficos")
            # Evita zoom/estiramento do pixmap a cada atualização
            lbl.setScaledContents(False)
            self.layout_graficos.addWidget(lbl)

        scroll.setWidget(scroll_content)
        # Garante que o scroll ocupe todo o espaço disponível no container
        layout.addWidget(scroll)
        return container

    def _mostrar_pixmap_em_label(self, label: QtWidgets.QLabel, caminho: Path) -> None:
        pix = QPixmap(str(caminho))
        if pix.isNull():
            label.setText("Falha ao carregar imagem")
            return

        # Calcula largura a partir do container de scroll para evitar crescimento cumulativo.
        largura_base = 0
        if hasattr(self, "scroll_graficos") and self.scroll_graficos is not None:
            largura_base = max(largura_base, self.scroll_graficos.contentsRect().width())
        if largura_base <= 0:
            parent = label.parentWidget()
            largura_base = max(1, parent.width()) if parent else 0
        if largura_base < 20:
            # aguarda o layout ser aplicado e tenta novamente
            QtCore.QTimer.singleShot(80, lambda: self._mostrar_pixmap_em_label(label, caminho))
            return

        # Escalona sem distorcer e sem zoom cumulativo
        alvo_largura = max(100, largura_base - 36)
        altura_maxima = 560
        scaled = pix.scaled(
            alvo_largura,
            altura_maxima,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)
        label.setText("")

    def _limpar_tmp_r_anterior(self) -> None:
        tmp_dir = getattr(self, "_tmp_dir_r_atual", None)
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        self._tmp_dir_r_atual = None

    def abrir_mne_browser(self) -> None:
        if self.mne_browser is not None:
            try:
                self._mne_browser_aberto = True
                if hasattr(self.mne_browser, "show"):
                    self.mne_browser.show()
                if hasattr(self.mne_browser, "raise_"):
                    self.mne_browser.raise_()
                if hasattr(self.mne_browser, "activateWindow"):
                    self.mne_browser.activateWindow()
                self._processar_refresh_mne_browser()
                return
            except Exception:
                self.mne_browser = None

        try:
            self._mne_browser_aberto = True
            self._renderizar_mne_browser(force=True)
        except Exception as e:
            LOGGER.warning(f"Nao foi possivel abrir MNE Browser: {e}")

    def atualizar_mne_browser(self, dados_filt: np.ndarray) -> None:
        # Recria um Raw temporário a partir do último buffer filtrado e atualiza o browser
        if dados_filt is None:
            return

        try:
            sfreq = float(getattr(self.lsl_worker, 'sfreq', 250.0))
        except Exception:
            sfreq = 250.0

        # Usa a janela inteira (os 5 segundos) para rolar a tela como num EMG.
        try:
            # Limita a janela para o buffer configurado (ex: buffer_size)
            max_dur = 5.0
            max_samples = min(int(max_dur * sfreq), dados_filt.shape[1])
            n_canais = min(dados_filt.shape[0], getattr(self.raw_browser, '_data', np.zeros((4,1))).shape[0])

            segmento = dados_filt[:n_canais, -max_samples:].copy()
            # Evita valores NaN/Inf que quebram o renderer
            segmento = np.nan_to_num(segmento, copy=False)

            # Normaliza canais para visualização se solicitado
            try:
                if getattr(self, 'mne_normalize', True):
                    absmax = np.max(np.abs(segmento), axis=1)
                    absmax[~np.isfinite(absmax) | (absmax == 0.0)] = 1.0
                    segmento = (segmento.T / absmax).T
            except Exception:
                # Se falhar a normalização, continua com os dados brutos
                pass

            try:
                ganho = float(getattr(self, 'mne_gain', 1.0))
                if np.isfinite(ganho) and ganho > 0.0:
                    segmento = segmento * ganho
            except Exception:
                pass

            # Reusa o mesmo Raw do browser para evitar recriação/loop de janelas
            if self.raw_browser is None:
                self.raw_browser = self._criar_raw_mne(segmento, sfreq, desc="EMG (LSL - realtime)")
                if self.raw_browser is None:
                    return
            else:
                alvo = getattr(self.raw_browser, "_data", None)
                if isinstance(alvo, np.ndarray) and alvo.ndim == 2:
                    n_canais_raw = min(alvo.shape[0], segmento.shape[0])
                    n_amostras_copia = min(alvo.shape[1], segmento.shape[1])
                    if n_amostras_copia < alvo.shape[1]:
                        alvo[:n_canais_raw, :alvo.shape[1] - n_amostras_copia] = \
                            alvo[:n_canais_raw, n_amostras_copia:]
                    alvo[:n_canais_raw, -n_amostras_copia:] = segmento[:n_canais_raw, -n_amostras_copia:]
                else:
                    self.raw_browser = self._criar_raw_mne(segmento, sfreq, desc="EMG (LSL - realtime)")
                    if self.raw_browser is None:
                        return

            # Se o browser já estiver aberto, atualiza o mesmo objeto em tempo real
            if self._mne_browser_aberto and self.mne_browser is not None:
                try:
                    browser = self.mne_browser
                    browser_any = cast(Any, browser)
                    browser_dict = getattr(browser_any, "__dict__", None)
                    if isinstance(browser_dict, dict):
                        browser_dict["_data"] = self.raw_browser._data
                    if hasattr(browser, "_load_data"):
                        browser._load_data()
                    if hasattr(browser, "_redraw"):
                        browser._redraw(update_data=True)
                except Exception as e:
                    LOGGER.debug(f"Falha ao atualizar MNE Browser existente: {e}")
            elif not getattr(self, '_mne_browser_reopen_pending', False):
                # Se ainda não aberto, abre uma única vez
                self._mne_browser_reopen_pending = True

                def _open_once():
                    try:
                        # Se já houver algo agendado, ignora; mas não chama aqui ainda
                        pass
                    finally:
                        self._mne_browser_reopen_pending = False

                QtCore.QTimer.singleShot(10, _open_once)
        except Exception as e:
            LOGGER.debug(f"Falha ao atualizar MNE Browser: {e}")

    def _processar_refresh_mne_browser(self) -> None:
        self._mne_browser_refresh_pending = False
        if not self._mne_browser_aberto or self.mne_browser is None:
            return

        try:
            browser = self.mne_browser
            # Use cast to Any to avoid static type checker errors
            browser_any = cast(Any, browser)
            if hasattr(browser, "_redraw"):
                try:
                    browser._redraw(update_data=True)
                except TypeError:
                    browser._redraw()
            elif hasattr(browser, "redraw"):
                backend = getattr(browser_any, "backend", None)
                if backend is not None and hasattr(backend, "update_plot"):
                    backend.update_plot()
            else:
                canvas = getattr(browser_any, "canvas", None)
                if canvas is not None:
                    draw = getattr(canvas, "draw_idle", None)
                    if callable(draw):
                        draw()

            self._mne_browser_last_refresh = time.time()
        except Exception as e:
            LOGGER.debug(f"Falha ao atualizar UI do MNE Browser: {e}")

    def _renderizar_mne_browser(self, force: bool = False) -> None:
        browser = self.mne_browser
        if browser is not None:
            self._processar_refresh_mne_browser()
            return

        if self.raw_browser is None:
            return

        n_canais_browser = min(1, max(1, int(self.raw_browser.info.get("nchan", 1))))
        duracao = min(5.0, max(self.raw_browser.times[-1] if self.raw_browser.n_times > 1 else 1.0, 0.5))

        try:
            browser = mne.viz.plot_raw(
                self.raw_browser,
                title="MNE Inspector - Tempo Real",
                block=False,
                n_channels=n_canais_browser,
                duration=duracao,
                show_options=True,
                bgcolor="white",
                theme="light",
                scalings={"emg": 1.0},
            )
            self.mne_browser = browser
            if hasattr(browser, "show"):
                browser.show()
            if hasattr(browser, "raise_"):
                browser.raise_()
            if hasattr(browser, "activateWindow"):
                browser.activateWindow()
            self._mne_browser_last_refresh = time.time()
            self._mne_browser_aberto = True
        except Exception as e:
            LOGGER.debug(f"Falha ao renderizar MNE Browser: {e}")


    def carregar_r(self):
        # R alimenta a janela; versão científica (Python) vai somente para output/.
        paths_r = gerar_grafico_r(self.metricas_por_canal)

        if paths_r:
            self._limpar_tmp_r_anterior()
            self._tmp_dir_r_atual = paths_r.get("tmp_dir")
            self._mostrar_pixmap_em_label(self.lbl_r_box, paths_r["violin"])
            self._mostrar_pixmap_em_label(self.lbl_r_pairs, paths_r["pares"])
            self._mostrar_pixmap_em_label(self.lbl_r_biplot, paths_r["biplot"])
            self.lbl_status_graficos.setText("Gráficos R atualizados.")
            self._graficos_ja_plotados = True
            LOGGER.info("Gráficos R atualizados na janela.")
        else:
            self.lbl_status_graficos.setText("Falha ao gerar gráficos R.")
            LOGGER.warning("R não disponível para renderização na janela.")

        # Sempre gera a versão científica em arquivos PNG no output.
        paths_py = gerar_grafico_python(self.metricas_por_canal)
        if paths_py:
            LOGGER.info("Versões científicas salvas em output/: %s", paths_py)
        else:
            LOGGER.warning("Não foi possível gerar gráficos científicos no output.")

        # Gera o gráfico comparativo bruto vs processado (últimos 5 s)
        try:
            bruto = self._ultimo_bruto
            
            if bruto is not None:
                # O analisador de tipo agora sabe que 'bruto' não é None,
                # logo 'filtrado' também nunca será None.
                filtrado = self._ultimo_filt if self._ultimo_filt is not None else bruto
                
                sfreq = float(getattr(self.lsl_worker, "sfreq", 1500.0))
                png_comp = gerar_grafico_comparacao_r(bruto, filtrado, sfreq)
                
                if png_comp:
                    LOGGER.info("Gráfico comparativo salvo em: %s", png_comp)
                else:
                    LOGGER.warning("Gráfico comparativo não gerado (R indisponível ou erro).")
                    
        except Exception as e:
            LOGGER.warning("Erro ao gerar gráfico comparativo: %s", e)



    def criar_widget_metricas(self):
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)

        tabela = QtWidgets.QTableWidget()
        tabela.setColumnCount(5)
        tabela.setHorizontalHeaderLabels(
            ["Canal", "RMS", "Freq. Mediana (Hz)", "Zero Crossing Rate", "Waveform Length"]
        )
        tabela.setRowCount(len(self.metricas_por_canal) + 1)

        tabela.setItem(0, 0, QtWidgets.QTableWidgetItem("Média (todos)"))
        tabela.setItem(0, 1, QtWidgets.QTableWidgetItem(f"{self.metricas_medias['rms']:.6f}"))
        tabela.setItem(0, 2, QtWidgets.QTableWidgetItem(f"{self.metricas_medias['freq_mediana']:.3f}"))
        tabela.setItem(0, 3, QtWidgets.QTableWidgetItem(f"{self.metricas_medias['zcr']:.6f}"))
        tabela.setItem(0, 4, QtWidgets.QTableWidgetItem(f"{self.metricas_medias['waveform_length']:.6f}"))

        for i, metrica in enumerate(self.metricas_por_canal, start=1):
            tabela.setItem(i, 0, QtWidgets.QTableWidgetItem(metrica["canal"]))
            tabela.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{metrica['rms']:.6f}"))
            tabela.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{metrica['freq_mediana']:.3f}"))
            tabela.setItem(i, 3, QtWidgets.QTableWidgetItem(f"{metrica['zcr']:.6f}"))
            tabela.setItem(i, 4, QtWidgets.QTableWidgetItem(f"{metrica['waveform_length']:.6f}"))

        header = tabela.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
            header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(tabela)
        return container

    def alternar_visualizacao_analise(self):
        indice_atual = self.painel_analise.currentIndex()
        novo_indice = 1 if indice_atual == 0 else 0
        self.painel_analise.setCurrentIndex(novo_indice)
        if novo_indice == 0:
            self.lbl_modo_analise.setText("Modo atual: Gráfico (R + ggplot2)")
        else:
            self.lbl_modo_analise.setText("Modo atual: Tabela de parâmetros")

    def reset_views(self):
        try:
            self.plot_signal.autoRange()
        except Exception:
            pass

    def exportar_relatorio(self) -> None:
        """Agrupa todos os PNGs da pasta output/ em um único PDF, um por página."""
        from PIL import Image as PilImage

        output_dir = caminho_saida_dir()
        pngs = sorted(output_dir.glob("*.png"))

        if not pngs:
            QtWidgets.QMessageBox.warning(
                self,
                "Exportar Relatório",
                "Nenhuma imagem PNG encontrada na pasta output/.\n"
                "Gere os gráficos antes de exportar.",
            )
            return

        destino, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar Relatório PDF",
            str(output_dir / "relatorio.pdf"),
            "PDF (*.pdf)",
        )
        if not destino:
            return

        try:
            imagens = [PilImage.open(p).convert("RGB") for p in pngs]
            imagens[0].save(
                destino,
                format="PDF",
                save_all=True,
                append_images=imagens[1:],
            )
            QtWidgets.QMessageBox.information(
                self,
                "Exportar Relatório",
                f"PDF gerado com sucesso:\n{destino}",
            )
            LOGGER.info("Relatório PDF exportado: %s (%d imagens)", destino, len(imagens))
        except Exception as e:
            LOGGER.exception("Erro ao exportar relatório PDF: %s", e)
            QtWidgets.QMessageBox.critical(
                self,
                "Erro ao exportar",
                f"Não foi possível gerar o PDF:\n{e}",
            )

    def mostrar_em_desenvolvimento(self, recurso: str):
        QtWidgets.QMessageBox.information(
            self,
            "Recurso em desenvolvimento",
            f"{recurso} ainda não foi implementado.",
        )

    def closeEvent(self, a0) -> None:
        """Encerramento seguro da aplicação com limpeza de threads."""
        LOGGER.info("Encerrando aplicação...")
        
        # Para a thread LSL worker
        if hasattr(self, 'lsl_worker') and self.lsl_worker is not None:
            self.lsl_worker.parar()
            self.lsl_worker.wait(2000)  # Aguarda até 2 segundos
            if self.lsl_worker.isRunning():
                self.lsl_worker.terminate()
                self.lsl_worker.wait()

        self._limpar_tmp_r_anterior()

        if self.mne_browser is not None:
            try:
                self.mne_browser.close()
            except Exception:
                pass
        self._mne_browser_aberto = False
        
        if a0 is not None:
            a0.accept()

    def capturar_dados_lsl(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Captura dados de streams LSL: EMG e EMG_Processado.
        
        Returns:
            Tupla (emg_data, emg_proc_data) onde cada elemento pode ser ndarray ou None
        """
        try:
            import pylsl
        except ImportError:
            LOGGER.error("pylsl não disponível. Instale: pip install pylsl")
            QtWidgets.QMessageBox.critical(self, "Erro", "pylsl não instalado. Execute: pip install pylsl")
            return None, None

        try:
            LOGGER.info("Procurando por streams LSL...")
            streams = pylsl.resolve_streams(wait_time=3.0)
            if not streams:
                LOGGER.warning("Nenhum stream LSL encontrado.")
                QtWidgets.QMessageBox.warning(self, "Aviso", "Nenhum stream LSL encontrado.")
                return None, None

            emg_stream = None
            emg_proc_stream = None

            for stream_info in streams:
                if stream_info.name() == "EMG":
                    emg_stream = pylsl.StreamInlet(stream_info)
                    LOGGER.info("Stream EMG encontrado")
                elif stream_info.name() == "EMG_Processado":
                    emg_proc_stream = pylsl.StreamInlet(stream_info)
                    LOGGER.info("Stream EMG_Processado encontrado")

            if emg_stream is None:
                LOGGER.warning("Stream EMG não encontrado")
                QtWidgets.QMessageBox.warning(self, "Aviso", "Stream 'EMG' não encontrado.")
                return None, None

            # Captura dados por 5 segundos
            emg_data = []
            emg_proc_data = []
            timeout = 5.0
            import time
            start_time = time.time()

            while (time.time() - start_time) < timeout:
                if emg_stream:
                    sample, timestamp = emg_stream.pull_sample(timeout=0.1)
                    if sample is not None:
                        emg_data.append(sample)
                if emg_proc_stream:
                    sample, timestamp = emg_proc_stream.pull_sample(timeout=0.1)
                    if sample is not None:
                        emg_proc_data.append(sample)

            if not emg_data:
                LOGGER.warning("Nenhum dado capturado do EMG")
                QtWidgets.QMessageBox.warning(self, "Aviso", "Nenhum dado capturado.")
                return None, None

            LOGGER.info(f"Capturados {len(emg_data)} amostras de EMG")
            return np.array(emg_data), np.array(emg_proc_data) if emg_proc_data else None

        except Exception as e:
            LOGGER.exception(f"Erro ao capturar dados LSL: {e}")
            QtWidgets.QMessageBox.critical(self, "Erro", f"Erro ao capturar dados: {str(e)}")
            return None, None

    def recarregar_de_lsl(self):
        """Recarrega gráficos usando o ultimo buffer do LSL (sem travar UI)."""
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage("Atualizando gráficos com ultimo buffer...")

        if self._ultimo_bruto is None:
            if status_bar:
                status_bar.showMessage("Sem dados recentes do LSL")
            return

        try:
            sfreq = 430.0
            bruto = self._ultimo_bruto
            filt = self._ultimo_filt if self._ultimo_filt is not None else bruto

            raw_bruto_new = self._criar_raw_mne(bruto, sfreq, "EMG (LSL)")
            if raw_bruto_new is None:
                raise ValueError("Falha ao criar Raw MNE")

            raw_filt_new = self._criar_raw_mne(filt, sfreq, "EMG Proc (LSL)")
            if raw_filt_new is None:
                raw_filt_new = raw_bruto_new.copy().filter(1, 40)

            self.metricas_por_canal, self.metricas_medias = calcular_parametros_sinal(raw_filt_new)
            self.carregar_r()

            old_widget = self.painel_analise.widget(1)
            if old_widget is not None:
                self.painel_analise.removeWidget(old_widget)
                old_widget.deleteLater()
            self.widget_metricas = self.criar_widget_metricas()
            self.painel_analise.addWidget(self.widget_metricas)

            if status_bar:
                status_bar.showMessage("Recarregado!")
            LOGGER.info("Gráficos recarregados com buffer LSL")
        except Exception as e:
            LOGGER.exception(f"Erro: {e}")
            if status_bar:
                status_bar.showMessage(f"Erro: {str(e)}")

    def _criar_raw_mne(self, data: np.ndarray, sfreq: float, desc: str = "Dados LSL") -> mne.io.RawArray | None:
        """Cria objeto MNE Raw a partir de dados numpy.
        
        Args:
            data: Array numpy com dados (n_canais x n_amostras) ou (n_amostras,)
            sfreq: Frequência de amostragem em Hz
            desc: Descrição dos dados
            
        Returns:
            Objeto mne.io.RawArray ou None se houver erro
        """
        try:
            if data is None or len(data) == 0:
                LOGGER.error("Dados vazios ou None")
                return None
                
            # Garantir formato correto
            if len(data.shape) == 1:
                data = data.reshape(1, -1)
            
            # Converter para float se necessário
            data = np.asarray(data, dtype=float)
            
            # Cria info do MNE
            n_canais = int(data.shape[0])
            ch_names = [f"EMG_{i+1}" for i in range(n_canais)]
            info = mne.create_info(ch_names, int(sfreq), ch_types="emg")

            # Cria objeto Raw
            raw = mne.io.RawArray(data, info)
            LOGGER.info(f"Raw MNE criado: {n_canais} canais, {raw.n_times} amostras")
            return raw
            
        except Exception as e:
            LOGGER.exception(f"Erro ao criar Raw MNE: {e}")
            return None

def inferir_modo_sinal(metricas_por_canal: list[dict]) -> list[dict]:
    """Classifica canais em modos de energia com base no RMS.
    
    Args:
        metricas_por_canal: Lista de dicts com métricas por canal
        
    Returns:
        Lista de dicts com métricas classificadas em modos
    """
    if not metricas_por_canal or len(metricas_por_canal) == 0:
        return []

    try:
        rms_vals = np.array([m.get("rms", 0.0) for m in metricas_por_canal], dtype=float)
        if rms_vals.size == 0:
            return []
            
        q1, q2 = np.quantile(rms_vals, [0.33, 0.66])

        linhas = []
        for metrica in metricas_por_canal:
            rms = float(metrica.get("rms", 0.0))
            if rms <= q1:
                modo = "Baixa energia"
            elif rms <= q2:
                modo = "Media energia"
            else:
                modo = "Alta energia"

            linhas.append(
                {
                    "canal": str(metrica.get("canal", "Canal")),
                    "modo": modo,
                    "rms": float(metrica.get("rms", 0.0)),
                    "freq_mediana": float(metrica.get("freq_mediana", 0.0)),
                    "zcr": float(metrica.get("zcr", 0.0)),
                    "waveform_length": float(metrica.get("waveform_length", 0.0)),
                }
            )
        return linhas
    except Exception as e:
        LOGGER.exception(f"Erro ao inferir modo de sinal: {e}")
        return []


def salvar_metricas_csv(metricas_por_canal: list[dict], csv_path: Path) -> bool:
    """Salva métricas em arquivo CSV.
    
    Args:
        metricas_por_canal: Lista de dicts com métricas
        csv_path: Caminho do arquivo CSV de saída
        
    Returns:
        True se bem-sucedido, False caso contrário
    """
    try:
        linhas = inferir_modo_sinal(metricas_por_canal)
        if not linhas:
            LOGGER.warning("Nenhuma métrica para salvar")
            return False
            
        campos = ["canal", "modo", "rms", "freq_mediana", "zcr", "waveform_length"]
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()
            writer.writerows(linhas)
        LOGGER.info(f"Métricas salvas em: {csv_path}")
        return True
    except Exception as e:
        LOGGER.exception(f"Erro ao salvar métricas CSV: {e}")
        return False


def _configurar_r_sistema() -> Path | None:
    """Configura o ambiente do R para o processo atual antes de chamar Rscript."""
    candidatos: list[Path] = []

    r_home_env = os.environ.get("R_HOME")
    if r_home_env:
        candidatos.append(Path(r_home_env))

    for nome in ("Rscript", "R"):
        encontrado = shutil.which(nome)
        if encontrado:
            candidatos.append(Path(encontrado).resolve().parent.parent)

    for raiz in (Path("C:/Program Files/R"), Path("C:/Program Files (x86)/R")):
        if raiz.exists():
            candidatos.extend(sorted([p for p in raiz.glob("R-*") if p.is_dir()], reverse=True))

    for r_home in candidatos:
        bin_root = r_home / "bin"
        bin_x64 = bin_root / "x64"
        rscript = bin_root / "Rscript.exe"
        rexec = bin_root / "R.exe"

        if not r_home.exists() or not (rscript.exists() or rexec.exists()):
            continue

        os.environ["R_HOME"] = str(r_home)
        path_atual = os.environ.get("PATH", "")
        entradas = [str(p) for p in (bin_x64, bin_root) if p.exists()]
        if entradas:
            os.environ["PATH"] = os.pathsep.join(entradas + [path_atual])

        if os.name == "nt":
            for dll_dir in (bin_x64, bin_root):
                if dll_dir.exists():
                    try:
                        os.add_dll_directory(str(dll_dir))
                    except (AttributeError, FileNotFoundError):
                        pass

        LOGGER.info("R configurado a partir de: %s", r_home)
        return r_home

    return None


def gerar_grafico_r(metricas_por_canal: list[dict] | None = None) -> dict[str, Path] | None:
    """Gera gráficos estatísticos usando R e ggplot2 para exibição nativa em Qt.
    
    Args:
        metricas_por_canal: Lista de dicts com métricas por canal
        
    Returns:
        Dicionário com caminhos dos PNGs temporários ou None se falhar
    """
    import tempfile as _tempfile

    temp_dir = Path(_tempfile.mkdtemp(prefix="neuro_r_"))
    output_csv = temp_dir / "metricas_canais.csv"
    
    # Usar diretório temporário para gráficos (não salva em output/)
    temp_png_violin = temp_dir / "grafico_violin_facet_temp.png"
    temp_png_pairs = temp_dir / "grafico_matriz_dispersao_temp.png"
    temp_png_biplot = temp_dir / "grafico_biplot_temp.png"

    if not metricas_por_canal:
        LOGGER.warning("Sem metricas para gerar analise R.")
        return None

    salvar_metricas_csv(metricas_por_canal, output_csv)

    # Se o R não estiver disponível no sistema, cai diretamente no fallback Python.
    rscript = _configurar_r_sistema()
    if rscript is None:
        LOGGER.warning("R não encontrado ou não configurável neste processo. Usando fallback Python.")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    try:
        script_r = f'''
        options(warn = 1)
        args <- commandArgs(trailingOnly = TRUE)
        output_r_csv <- args[[1]]
        output_r_png_box <- args[[2]]
        output_r_png_pairs <- args[[3]]
        output_r_png_biplot <- args[[4]]

        suppressPackageStartupMessages({{
            library(ggplot2)
            library(tidyr)
            library(dplyr)
            library(scales)
        }})

        df <- read.csv(output_r_csv, stringsAsFactors = FALSE)
        df$modo <- factor(df$modo, levels = c("Baixa energia", "Media energia", "Alta energia"))

        nomes_features <- c(
            rms = "RMS",
            freq_mediana = "Freq. Mediana",
            zcr = "Zero Crossing Rate",
            waveform_length = "Waveform Length"
        )

        long_df <- df %>%
            pivot_longer(
                cols = c(rms, freq_mediana, zcr, waveform_length),
                names_to = "feature",
                values_to = "valor"
            ) %>%
            mutate(feature = factor(feature, levels = names(nomes_features), labels = unname(nomes_features)))

        p_violin <- ggplot(long_df, aes(x = modo, y = valor, color = modo, fill = modo)) +
            geom_violin(trim = FALSE, alpha = 0.35, linewidth = 0.5) +
            geom_boxplot(width = 0.12, alpha = 0.0, outlier.shape = NA, linewidth = 0.6, color = "#1F2937") +
            geom_jitter(width = 0.08, alpha = 0.70, size = 1.8) +
            stat_summary(fun = mean, geom = "point", shape = 23, size = 3, fill = "white", color = "black") +
            facet_wrap(~feature, scales = "free_y", ncol = 2) +
            scale_color_manual(values = c("Baixa energia" = "#1f78b4", "Media energia" = "#33a02c", "Alta energia" = "#e31a1c")) +
            scale_fill_manual(values = c("Baixa energia" = "#a6cee3", "Media energia" = "#b2df8a", "Alta energia" = "#fb9a99")) +
            labs(x = "Modo inferido a partir do RMS", y = "Valor da feature") +
            theme_minimal(base_size = 12) +
            theme(
                legend.position = "bottom",
                legend.box.spacing = grid::unit(0.5, "cm"),
                legend.margin = ggplot2::margin(t = 10, b = 5, l = 5, r = 5),
                plot.margin = ggplot2::margin(b = 60, t = 20, l = 20, r = 20),
                panel.grid.minor = element_blank(),
                axis.title.x = element_text(margin = ggplot2::margin(t = 20)),
                axis.title.y = element_text(margin = ggplot2::margin(r = 20))
            )

        ggsave(output_r_png_box, plot = p_violin, width = 12, height = 9, dpi = 120)

        pair_df <- df %>% select(modo, rms, freq_mediana, zcr, waveform_length)
        cols_to_rename <- c("rms", "freq_mediana", "zcr", "waveform_length")
        colnames(pair_df)[colnames(pair_df) %in% cols_to_rename] <- unname(nomes_features[cols_to_rename])

        pair_df_jittered <- pair_df %>%
            mutate(across(where(is.numeric), ~ {{
                rng <- diff(range(.x, na.rm = TRUE))
                amt <- if (!is.finite(rng) || rng == 0) 0.002 else max(rng * 0.03, 0.001)
                jitter(.x, amount = amt)
            }}))

        if (!requireNamespace("GGally", quietly = TRUE)) {{
            stop("Pacote GGally nao encontrado. Instale com: install.packages('GGally')")
        }}

        p_pairs <- GGally::ggpairs(
            pair_df_jittered,
            columns = 2:5,
            mapping = aes(color = modo, fill = modo),
            upper = list(continuous = GGally::wrap("cor", size = 4, family = "serif", stars = FALSE)),
            lower = list(continuous = GGally::wrap("points", alpha = 0.4, size = 1.0)),
            diag = list(continuous = GGally::wrap("densityDiag", alpha = 0.5))
        ) +
        scale_color_manual(values = c("Baixa energia" = "#1f78b4", "Media energia" = "#33a02c", "Alta energia" = "#e31a1c")) +
        scale_fill_manual(values = c("Baixa energia" = "#1f78b4", "Media energia" = "#33a02c", "Alta energia" = "#e31a1c")) +
        labs(color = "Modo", fill = "Modo") +
        theme_minimal(base_size = 11) +
        theme(
            panel.grid = element_blank(),
            panel.border = element_rect(color = "#CBD5E1", fill = NA, linewidth = 0.7),
            strip.background = element_rect(fill = "#F8FAFC", color = "#CBD5E1", linewidth = 0.6),
            strip.text = element_text(face = "bold", size = 10, color = "#1F2937"),
            panel.spacing = grid::unit(0.18, "lines"),
            text = element_text(family = "serif"),
            legend.position = "bottom",
            legend.title = element_text(face = "bold"),
            legend.key = element_rect(fill = "white", color = NA)
        )

        ggsave(output_r_png_pairs, plot = p_pairs, width = 13, height = 11, dpi = 130)

        matriz_features <- df %>% dplyr::select(rms, freq_mediana, zcr, waveform_length)
        matriz_scaled <- as.data.frame(lapply(matriz_features, function(x) as.numeric(scale(x))))
        matriz_scaled[is.na(matriz_scaled)] <- 0

        pca <- prcomp(matriz_scaled, center = FALSE, scale. = FALSE)
        scores <- as.data.frame(pca$x[, 1:2, drop = FALSE])
        scores$modo <- df$modo
        names(scores)[1:2] <- c("PC1", "PC2")

        loadings <- as.data.frame(pca$rotation[, 1:2, drop = FALSE])
        names(loadings)[1:2] <- c("PC1", "PC2")
        loadings$feature <- c("RMS", "Freq. Mediana", "Zero Crossing Rate", "Waveform Length")

        var_exp <- (pca$sdev^2) / sum(pca$sdev^2)
        p_1 <- round(var_exp[1] * 100, 1)
        p_2 <- round(var_exp[2] * 100, 1)

        max_scores <- max(abs(c(scores$PC1, scores$PC2)), na.rm = TRUE)
        max_loadings <- max(abs(c(loadings$PC1, loadings$PC2)), na.rm = TRUE)
        escala_setas <- max_scores * 0.72 / max(max_loadings, 1e-9)
        if (!is.finite(escala_setas) || escala_setas == 0) {{
            escala_setas <- 1
        }}

        loadings$x_end <- loadings$PC1 * escala_setas
        loadings$y_end <- loadings$PC2 * escala_setas

        cores_paleta <- c(
            "Baixa energia" = "#1f78b4",
            "Media energia" = "#33a02c",
            "Alta energia" = "#e31a1c",
            "RMS" = "#8E44AD",
            "Freq. Mediana" = "#2980B9",
            "Zero Crossing Rate" = "#E67E22",
            "Waveform Length" = "#16A085"
        )

        p_biplot <- ggplot() +
            geom_hline(yintercept = 0, linewidth = 0.4, color = "gray80") +
            geom_vline(xintercept = 0, linewidth = 0.4, color = "gray80") +
            geom_point(data = scores, aes(x = PC1, y = PC2, color = modo), size = 2.6, alpha = 0.85) +
            geom_segment(data = loadings, aes(x = 0, y = 0, xend = x_end, yend = y_end, color = feature), linewidth = 1.0, arrow = grid::arrow(length = grid::unit(0.20, "cm"))) +
            scale_color_manual(values = cores_paleta) +
            labs(x = paste0("PC1 (", p_1, " % da variancia)"), y = paste0("PC2 (", p_2, " % da variancia)"), color = "Legenda") +
            coord_equal() +
            theme_minimal(base_size = 12) +
            theme(text = element_text(family = "serif"), legend.position = "right", panel.grid.minor = element_blank(), plot.title = element_blank())

        ggsave(output_r_png_biplot, plot = p_biplot, width = 10, height = 8, dpi = 130)
        '''

        script_path = temp_dir / "gerar_graficos.R"
        script_path.write_text(script_r, encoding="utf-8")

        comando = [
            str(rscript / "bin" / "Rscript.exe"),
            "--vanilla",
            str(script_path),
            str(output_csv),
            str(temp_png_violin),
            str(temp_png_pairs),
            str(temp_png_biplot),
        ]
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if resultado.returncode != 0:
            LOGGER.warning("Falha no Rscript; usando fallback Python. Saida: %s", resultado.stderr.strip())
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        LOGGER.info("Gráficos R gerados em PNG temporário.")
        return {
            "violin": temp_png_violin,
            "pares": temp_png_pairs,
            "biplot": temp_png_biplot,
            "tmp_dir": temp_dir,
        }
        
    except subprocess.TimeoutExpired:
        LOGGER.warning("Rscript excedeu o tempo limite; usando fallback Python.")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None
    except Exception as e:
        LOGGER.warning("Falha no caminho R; usando fallback Python. Detalhe: %s", e)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None  # Falha


def gerar_grafico_python(metricas_por_canal: list[dict] | None = None) -> dict[str, Path] | None:
    """Gera gráficos estatísticos usando matplotlib (fallback).
    
    Args:
        metricas_por_canal: Lista de dicts com métricas por canal
        
    Returns:
        Caminhos dos PNGs científicos no output ou None se falhar
    """
    if not metricas_por_canal:
        return None

    try:
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.markers import MarkerStyle
    except ImportError as e:
        LOGGER.error("Matplotlib nao disponivel para fallback Python: %s", e)
        return None

    linhas = inferir_modo_sinal(metricas_por_canal)
    if not linhas:
        return None

    np.random.seed(42)

    output_dir = caminho_saida_dir()
    output_png_violin = output_dir / "grafico_violin_facet.png"
    output_png_pairs = output_dir / "grafico_matriz_dispersao.png"
    output_png_biplot = output_dir / "grafico_biplot_py.png"

    features = ["rms", "freq_mediana", "zcr", "waveform_length"]
    nomes_features = {
        "rms": "RMS",
        "freq_mediana": "Freq. Mediana",
        "zcr": "Zero Crossing Rate",
        "waveform_length": "Waveform Length",
    }
    modos = ["Baixa energia", "Media energia", "Alta energia"]
    # Paleta com alto contraste 
    cores = {
        "Baixa energia": "#0072B2",
        "Media energia": "#D55E00",
        "Alta energia": "#009E73",
    }
    marcadores = {
        "Baixa energia": "o",
        "Media energia": "s",
        "Alta energia": "^",
    }

    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams["font.family"] = "serif"
    plt.rcParams["font.serif"] = ["Cambria", "Georgia", "DejaVu Serif", "serif"]

    # 1) Violin facetado + jitter + media
    if not features: return 

    fig, axes = plt.subplots(2, 2, figsize=(13.2, 9.8), constrained_layout=False, dpi=150)
    fig.set_facecolor("#FFFFFF")
    
    ax = None
    axes_list = axes.flatten() 

    for idx, feature in enumerate(features):
        ax = axes_list[idx]
        dados_modo = [
            [l[feature] for l in linhas if l["modo"] == modo]
            for modo in modos
        ]

        # 1. Alterado para violinplot e removidos os argumentos inválidos de boxplot
        vp = ax.violinplot(
            dados_modo,
            showmedians=True,  # Mostra a linha da mediana (substitui o medianprops)
            widths=0.58,
        )

        # 2. Ajustado para colorir os corpos ("bodies") do violinplot
        for patch, modo in zip(vp["bodies"], modos):
            patch.set_facecolor(cores[modo])
            patch.set_alpha(0.25)
            patch.set_edgecolor(cores[modo])
            patch.set_linewidth(1.5)

        # Estilização opcional das linhas de suporte do violino (médias, extremidades, etc.)
        # Se quiser mudar a cor das linhas centrais geradas pelo Matplotlib:
        for cb in ['cmaxes', 'cmins', 'cmeans', 'cmedians']:
            if cb in vp:
                vp[cb].set_edgecolor("#4B5563")
                vp[cb].set_linewidth(1.5)

        # 3. Adiciona as labels no eixo X manualmente (já que violinplot não aceita o parâmetro labels)
        ax.set_xticks(range(1, len(modos) + 1))
        ax.set_xticklabels(modos)

        # O restante do seu código (Jitter/Scatter e Estilização de eixos) continua igual
        for pos, (modo, valores) in enumerate(zip(modos, dados_modo), start=1):
            if not valores:
                continue
            jitter_x = np.random.normal(loc=pos, scale=0.045, size=len(valores))
            ax.scatter(
                jitter_x,
                valores,
                color=cores[modo],
                alpha=0.85,
                s=28,
                linewidths=0.8,
                edgecolors="#111111",
                marker=str(marcadores[modo]),
            )
            media = float(np.mean(valores))
            ax.scatter([pos], [media], marker="D", s=64, color="#1F2937", zorder=3, edgecolors="#000000", linewidth=0.8)

        ax.set_title(nomes_features[feature], fontsize=12, fontweight="bold", color="#1F2937", family="serif")
        ax.grid(True, axis="y", alpha=0.3, linestyle="-", linewidth=0.6, color="#D1D5DB")
        ax.grid(False, axis="x")
        ax.tick_params(axis="x", rotation=35, labelsize=9, pad=6)
        ax.tick_params(axis="y", labelsize=9, pad=5)
        ax.set_facecolor("#FFFFFF")

    fig.suptitle("Distribuição das Features de EMG por Nível de Energia", 
                 fontsize=15, fontweight="bold", family="serif", y=0.98)
    
    handles_modo = [
        Line2D([0], [0], marker=str(marcadores[m]), color='w', markerfacecolor=cores[m], 
               markeredgecolor="#111111", markersize=8, label=m)
        for m in modos
    ]
    
    fig.legend(
        handles=handles_modo, 
        title="Níveis de Energia", 
        loc="center left", 
        bbox_to_anchor=(0.93, 0.5), 
        frameon=False, 
        prop={"family": "serif", "size": 9}
    )
    
    fig.subplots_adjust(top=0.90, 
        bottom=0.12, 
        left=0.08, 
        right=0.92,  
        hspace=0.45,
        wspace=0.35  
    )
    fig.savefig(str(output_png_violin), dpi=300, bbox_inches="tight", facecolor="#FFFFFF", edgecolor="none")
    plt.close(fig)

    # 2) Matriz de dispersao e correlacao
    dados_feature = {feature: np.array([l[feature] for l in linhas], dtype=float) for feature in features}

    n = len(features)
    fig, axes = plt.subplots(n, n, figsize=(12.8, 12.8), constrained_layout=False, dpi=150)
    fig.set_facecolor("#FFFFFF")

    for i in range(n):
        for j in range(n):
            ax = axes[i, j]
            fi = features[i]
            fj = features[j]

            if i == j:
                ax.text(
                    0.5,
                    0.5,
                    nomes_features[fi],
                    ha="center",
                    va="center",
                    fontsize=12,
                    fontweight="bold",
                    color="#111827",
                    family="serif",
                )
                ax.set_xticks([])
                ax.set_yticks([])
                ax.grid(False)
            elif i > j:
                for modo in modos:
                    xs = [l[fj] for l in linhas if l["modo"] == modo]
                    ys = [l[fi] for l in linhas if l["modo"] == modo]
                    if xs and ys:
                        ax.scatter(
                            xs,
                            ys,
                            s=28,
                            alpha=0.85,
                            color=cores[modo],
                            marker=str(marcadores[modo]),
                            edgecolors="#111111",
                            linewidths=0.45,
                        )
            else:
                x = dados_feature[fj]
                y = dados_feature[fi]
                if x.size > 1 and y.size > 1 and float(np.std(x)) > 1e-12 and float(np.std(y)) > 1e-12:
                    with np.errstate(invalid="ignore", divide="ignore"):
                        corr = float(np.corrcoef(x, y)[0, 1])
                    if not np.isfinite(corr):
                        corr = 0.0
                else:
                    corr = 0.0
                cor_corr = "#374151" if abs(corr) < 0.4 else "#1F2937" if abs(corr) >= 0.4 else "#4B5563"
                ax.text(0.5, 0.56, f"r = {corr:.2f}", ha="center", va="center", fontsize=12, color=cor_corr, fontweight="bold", family="serif")
                ax.text(0.5, 0.38, "correlação", ha="center", va="center", fontsize=9, color="#6B7280", family="serif")
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)

            if i == n - 1:
                ax.set_xlabel(nomes_features[fj], fontsize=10, family="serif", labelpad=8)
                ax.tick_params(axis="x", labelsize=8, pad=4)
            else:
                ax.set_xticklabels([])
            if j == 0:
                ax.set_ylabel(nomes_features[fi], fontsize=10, family="serif", labelpad=8)
                ax.tick_params(axis="y", labelsize=8, pad=4)
            else:
                ax.set_yticklabels([])

            ax.grid(True, alpha=0.2, linestyle=":", color="#D1D5DB", linewidth=0.6)
            ax.set_facecolor("#FFFFFF")
            for spine in ax.spines.values():
                spine.set_edgecolor("#D1D5DB")
                spine.set_linewidth(0.8)

    handles = [
        Line2D(
            [0],
            [0],
            marker=str(marcadores[m]),
            linestyle="",
            color=cores[m],
            markerfacecolor=cores[m],
            markeredgecolor="#111111",
            markeredgewidth=0.8,
            label=m,
            markersize=8,
        )
        for m in modos
    ]
    fig.subplots_adjust(top=0.86, bottom=0.07, left=0.07, right=0.98, wspace=0.07, hspace=0.07)
    fig.legend(
        handles=handles_modo, 
        title="Modo de sinal:", 
        loc="center left", 
        bbox_to_anchor=(1, 0.5), 
        frameon=False, 
        prop={"family": "serif", "size": 9}
    )
    fig.suptitle(
        "Matriz de Dispersão e Correlação entre Features",
        fontsize=16,
        fontweight="bold",
        color="#0F172A",
        family="serif",
        y=0.885,
    )
    fig.savefig(str(output_png_pairs), dpi=300, bbox_inches="tight", pad_inches=0.28, facecolor="#FFFFFF", edgecolor="none")
    plt.close(fig)

    # 3) Biplot PCA: padroniza features, projeta em PC1/PC2, mostra pontos por modo e vetores das features
    X = np.array([[float(l[f]) for f in features] for l in linhas], dtype=float)
    if X.size == 0 or X.shape[0] < 2:
        return None

    means = np.nanmean(X, axis=0)
    stds = np.nanstd(X, axis=0)
    stds[~np.isfinite(stds) | (stds == 0.0)] = 1.0
    Xz = (X - means) / stds
    Xz[~np.isfinite(Xz)] = 0.0

    U, S, Vt = np.linalg.svd(Xz, full_matrices=False)
    if Vt.shape[0] < 2:
        return None

    scores = U[:, :2] * S[:2]
    loadings = Vt[:2, :].T
    var_exp = (S ** 2) / max(Xz.shape[0] - 1, 1)
    total_var = float(np.sum(var_exp)) if np.isfinite(np.sum(var_exp)) else 0.0
    pct1 = round(float(var_exp[0] / total_var * 100.0), 1) if total_var > 0 else 0.0
    pct2 = round(float(var_exp[1] / total_var * 100.0), 1) if total_var > 0 and len(var_exp) > 1 else 0.0

    max_score = max(float(np.max(np.abs(scores[:, 0]))), float(np.max(np.abs(scores[:, 1]))), 1e-9)
    max_loading = max(float(np.max(np.abs(loadings[:, 0]))), float(np.max(np.abs(loadings[:, 1]))), 1e-9)
    arrow_scale = max_score * 0.72 / max_loading
    loadings_scaled = loadings * arrow_scale

    fig = plt.figure(figsize=(12.6, 8.8), constrained_layout=False, dpi=150)
    fig.set_facecolor("#FFFFFF")
    ax = fig.add_subplot(111)

    cores_vetores = {
        "rms": "#8E44AD",
        "freq_mediana": "#2980B9",
        "zcr": "#E67E22",
        "waveform_length": "#16A085",
    }

    for modo in modos:
        idxs = [i for i, l in enumerate(linhas) if l["modo"] == modo]
        if not idxs:
            continue
        ax.scatter(
            scores[idxs, 0],
            scores[idxs, 1],
            s=34,
            alpha=0.85,
            color=cores[modo],
            edgecolors="#111111",
            linewidths=0.6,
            label=modo,
            marker=MarkerStyle(str(marcadores[modo])),
        )

    ax.axhline(0, color="#D1D5DB", linewidth=0.8)
    ax.axvline(0, color="#D1D5DB", linewidth=0.8)

    for i, feature in enumerate(features):
        x_end = float(loadings_scaled[i, 0])
        y_end = float(loadings_scaled[i, 1])
        ax.arrow(
            0.0,
            0.0,
            x_end,
            y_end,
            color=cores_vetores[feature],
            width=0.0,
            head_width=max_score * 0.035,
            length_includes_head=True,
            linewidth=1.1,
        )

    ax.set_xlabel(f"PC1 ({pct1}% da variância)", fontsize=11, family="serif")
    ax.set_ylabel(f"PC2 ({pct2}% da variância)", fontsize=11, family="serif")
    ax.set_title("Biplot PCA das Features", fontsize=15, fontweight="bold", color="#0F172A", family="serif")
    ax.grid(True, alpha=0.22, linestyle=":", color="#D1D5DB", linewidth=0.7)
    ax.set_aspect("equal", adjustable="datalim")
    handles_modo = [
        Line2D(
            [0],
            [0],
            marker=str(marcadores[m]),
            linestyle="",
            markerfacecolor=cores[m],
            markeredgecolor="#111111",
            markeredgewidth=0.8,
            color=cores[m],
            label=m,
            markersize=8,
        )
        for m in modos
    ]
    handles_vetores = [
        Line2D([0], [0], color=cores_vetores[f], lw=2.2, label=nomes_features[f])
        for f in features
    ]

    fig.subplots_adjust(top=0.90, bottom=0.12, left=0.08, right=0.75)
    leg_modos = ax.legend(
        handles=handles_modo,
        title="Modos",
        loc="upper left",
        bbox_to_anchor=(1.1, 1.0),
        frameon=False,
        prop={"family": "serif", "size": 9},
        fontsize=10,
        title_fontsize=11,
    )
    ax.add_artist(leg_modos)
    ax.legend(
        handles=handles_vetores,
        title="Vetores das Features",
        loc="lower left",
        bbox_to_anchor=(1.1, 0.0),
        frameon=False,
        prop={"family": "serif", "size": 9},
        fontsize=9,
        title_fontsize=10,
    )

    fig.savefig(str(output_png_biplot), dpi=300, bbox_inches="tight", pad_inches=0.25, facecolor="#FFFFFF", edgecolor="none")
    plt.close(fig)

    LOGGER.info("Gráficos científicos salvos em output/")
    return {
        "violin": output_png_violin,
        "pares": output_png_pairs,
        "biplot": output_png_biplot,
    }


def criar_raw_vazio(n_canais: int = 1, duracao: float = 0.01, sfreq: float = 250.0) -> mne.io.RawArray:
    """Cria um RawArray vazio para inicialização.
    
    Args:
        n_canais: Número de canais
        duracao: Duração em segundos
        sfreq: Frequência de amostragem
        
    Returns:
        Objeto mne.io.RawArray vazio (será preenchido com dados do LSL)
    """
    n_amostras = int(duracao * sfreq)
    data = np.zeros((n_canais, n_amostras))
    ch_names = [f"EMG_{i+1}" for i in range(n_canais)]
    info = mne.create_info(ch_names, int(sfreq), ch_types="emg")
    raw = mne.io.RawArray(data, info)
    LOGGER.info(f"RawArray vazio criado: {n_canais} canais, {duracao}s")
    return raw

def gerar_grafico_comparacao_r(
    bruto: np.ndarray,
    filtrado: np.ndarray,
    sfreq: float,
) -> Path | None:
    """Gera um gráfico comparativo (tempo e espectro) entre sinal bruto e processado.

    Produz 4 painéis em um único PNG salvo em output/:
      - Linha superior: Voltagem × Tempo  (bruto | processado)
      - Linha inferior: Amplitude × Frequência via FFT  (bruto | processado)

    Args:
        bruto:    Array (n_canais × n_amostras) com sinal bruto dos últimos 5 s.
        filtrado: Array (n_canais × n_amostras) com sinal processado dos últimos 5 s.
        sfreq:    Frequência de amostragem em Hz.

    Returns:
        Path do PNG gerado ou None em caso de falha.
    """
    import tempfile as _tempfile

    if bruto is None or filtrado is None:
        LOGGER.warning("gerar_grafico_comparacao_r: dados None recebidos.")
        return None

    bruto   = np.asarray(bruto,   dtype=float)
    filtrado = np.asarray(filtrado, dtype=float)

    # Garante formato (n_canais × n_amostras)
    if bruto.ndim == 1:
        bruto = bruto.reshape(1, -1)
    if filtrado.ndim == 1:
        filtrado = filtrado.reshape(1, -1)

    # Usa apenas o primeiro canal para a comparação
    sig_bruto = bruto[0, :]
    sig_filt  = filtrado[0, :]

    # Limita aos últimos 5 segundos
    n_max = int(5.0 * sfreq)
    sig_bruto = sig_bruto[-n_max:]
    sig_filt  = sig_filt[-n_max:]
    n = len(sig_bruto)

    # Eixo de tempo
    t = np.linspace(-min(n / sfreq, 5.0), 0.0, n, endpoint=False)

    # FFT (magnitude normalizada)
    freqs    = np.fft.rfftfreq(n, d=1.0 / sfreq)
    amp_bruto = np.abs(np.fft.rfft(sig_bruto - sig_bruto.mean()))
    amp_filt  = np.abs(np.fft.rfft(sig_filt  - sig_filt.mean()))

    # Salva CSVs em diretório temporário para o R consumir
    temp_dir = Path(_tempfile.mkdtemp(prefix="neuro_comp_"))
    csv_tempo   = temp_dir / "comp_tempo.csv"
    csv_espectro = temp_dir / "comp_espectro.csv"
    output_png  = caminho_saida_dir() / "grafico_comparacao_bruto_processado.png"

    # CSV temporal
    with csv_tempo.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["tempo", "bruto", "filtrado"])
        for i in range(n):
            writer.writerow([f"{t[i]:.6f}", f"{sig_bruto[i]:.8f}", f"{sig_filt[i]:.8f}"])

    # CSV espectral
    with csv_espectro.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["freq", "bruto", "filtrado"])
        for i in range(len(freqs)):
            writer.writerow([f"{freqs[i]:.4f}", f"{amp_bruto[i]:.8f}", f"{amp_filt[i]:.8f}"])

    rscript_home = _configurar_r_sistema()
    if rscript_home is None:
        LOGGER.warning("R não encontrado; gráfico de comparação não gerado.")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    script_r = r"""
options(warn = 1)
args <- commandArgs(trailingOnly = TRUE)
csv_tempo    <- args[[1]]
csv_espectro <- args[[2]]
output_png   <- args[[3]]

suppressPackageStartupMessages({
    library(ggplot2)
    library(tidyr)
    library(dplyr)
    library(gridExtra)
})

df_t <- read.csv(csv_tempo,    stringsAsFactors = FALSE)
df_f <- read.csv(csv_espectro, stringsAsFactors = FALSE)

# Paleta
cor_bruto <- "#2980B9"
cor_filt  <- "#E74C3C"

# --- Painel 1: Tempo × Voltagem — Bruto ---
p1 <- ggplot(df_t, aes(x = tempo, y = bruto)) +
    geom_line(color = cor_bruto, linewidth = 0.55, alpha = 0.9) +
    labs(title = "Sinal Bruto", x = "Tempo (s)", y = "Amplitude") +
    theme_minimal(base_size = 11) +
    theme(plot.title = element_text(face = "bold", hjust = 0.5, size = 12),
          panel.grid.minor = element_blank())

# --- Painel 2: Tempo × Voltagem — Processado ---
p2 <- ggplot(df_t, aes(x = tempo, y = filtrado)) +
    geom_line(color = cor_filt, linewidth = 0.55, alpha = 0.9) +
    labs(title = "Sinal Processado", x = "Tempo (s)", y = "Amplitude") +
    theme_minimal(base_size = 11) +
    theme(plot.title = element_text(face = "bold", hjust = 0.5, size = 12),
          panel.grid.minor = element_blank())

# --- Painel 3: Frequência × Amplitude — Bruto ---
p3 <- ggplot(df_f, aes(x = freq, y = bruto)) +
    geom_line(color = cor_bruto, linewidth = 0.55, alpha = 0.9) +
    labs(title = "Espectro Bruto", x = "Frequência (Hz)", y = "Amplitude") +
    theme_minimal(base_size = 11) +
    theme(plot.title = element_text(face = "bold", hjust = 0.5, size = 12),
          panel.grid.minor = element_blank())

# --- Painel 4: Frequência × Amplitude — Processado ---
p4 <- ggplot(df_f, aes(x = freq, y = filtrado)) +
    geom_line(color = cor_filt, linewidth = 0.55, alpha = 0.9) +
    labs(title = "Espectro Processado", x = "Frequência (Hz)", y = "Amplitude") +
    theme_minimal(base_size = 11) +
    theme(plot.title = element_text(face = "bold", hjust = 0.5, size = 12),
          panel.grid.minor = element_blank())

png(output_png, width = 2400, height = 1600, res = 150)
grid.arrange(p1, p2, p3, p4, nrow = 2,
    top = grid::textGrob("Comparação: Sinal Bruto vs Processado (últimos 5 s)",
                         gp = grid::gpar(fontsize = 14, fontface = "bold")))
dev.off()
"""

    script_path = temp_dir / "comparacao.R"
    script_path.write_text(script_r, encoding="utf-8")

    try:
        resultado = subprocess.run(
            [
                str(rscript_home / "bin" / "Rscript.exe"),
                "--vanilla",
                str(script_path),
                str(csv_tempo),
                str(csv_espectro),
                str(output_png),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if resultado.returncode != 0:
            LOGGER.warning("Falha ao gerar comparação R: %s", resultado.stderr.strip())
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        LOGGER.info("Gráfico de comparação salvo em: %s", output_png)
        return output_png

    except Exception as e:
        LOGGER.warning("Erro em gerar_grafico_comparacao_r: %s", e)
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    configurar_logging()

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")

    try:
        sfreq = 1500.0
        n_canais = 2
        raw = criar_raw_vazio(n_canais=n_canais, duracao=5.0, sfreq=sfreq)
        raw_filt = raw.copy()

        win = JanelaNeuro(raw, raw_filt)
        win.showMaximized()
        sys.exit(app.exec())
        
    except Exception as e:
        LOGGER.exception("Erro: %s", e)