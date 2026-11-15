
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import re

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from modelo_anular import gerar_curva


# ============================================================
# CONFIGURAÇÃO
# ============================================================

MESH = "M1"
CASES = ("Q10", "Q35", "Q60")

TOLERANCIA_TEMPO = 0.13

VAZOES_TEORICAS = {
    "Q10": 10.0,
    "Q35": 35.0,
    "Q60": 60.0,
}

CORES = {
    "Q10": "tab:blue",
    "Q35": "tab:orange",
    "Q60": "tab:green",
}

OUTPUT = Path(MESH) / "comparacao_analitico_cfd_M1.png"

NUM = re.compile(
    r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
)


# ============================================================
# LEITURA DO HISTÓRICO QOleoMeio
# ============================================================

def ler_qoleo_meio(pasta_caso):

    pasta = pasta_caso / "postProcessing" / "QOleoMeio"

    if not pasta.exists():
        raise FileNotFoundError(
            f"Diretório QOleoMeio não encontrado: {pasta}"
        )

    # Seleciona o diretório temporal mais recente.
    diretorios = []

    for d in pasta.iterdir():
        if d.is_dir():
            try:
                diretorios.append((float(d.name), d))
            except ValueError:
                pass

    if not diretorios:
        raise FileNotFoundError(
            f"Nenhum diretório temporal válido em {pasta}"
        )

    _, ultimo = max(diretorios, key=lambda x: x[0])

    # Prioriza o arquivo com sufixo temporal.
    sufixado = ultimo / f"surfaceFieldValue_{ultimo.name}.dat"

    if sufixado.exists() and sufixado.stat().st_size > 0:
        arquivo = sufixado
    else:
        # Procura outro arquivo sufixado não vazio.
        alternativas = sorted(
            p for p in ultimo.glob("surfaceFieldValue_*.dat")
            if p.stat().st_size > 0
        )

        if alternativas:
            arquivo = alternativas[0]
        else:
            arquivo = ultimo / "surfaceFieldValue.dat"

    if not arquivo.exists() or arquivo.stat().st_size == 0:
        raise ValueError(
            f"Nenhum histórico válido encontrado em {ultimo}"
        )

    registros = []

    with arquivo.open(errors="replace") as f:

        for linha in f:

            linha = linha.strip()

            if not linha or linha.startswith("#"):
                continue

            valores = NUM.findall(linha)

            # Formato: tempo (Ux Uy Uz)
            if len(valores) < 4:
                continue

            tempo = float(valores[0])
            uy = float(valores[2])

            if np.isfinite(tempo) and np.isfinite(uy):

                # weightedAreaIntegrate(U), ponderado por alpha.oil.
                # Componente Y: direção axial.
                # Conversão de m³/s para L/min.
                q_l_min = uy * 60000.0

                registros.append((tempo, q_l_min))

    if not registros:
        raise ValueError(
            f"Nenhum registro vetorial válido em {arquivo}"
        )

    df = pd.DataFrame(
        registros,
        columns=["tempo_s", "Q_meio_L_min"]
    )

    df = df.sort_values("tempo_s")

    # Não aceita tempos duplicados com valores conflitantes.
    duplicados = df[df.duplicated("tempo_s", keep=False)]

    if not duplicados.empty:
        conflitos = duplicados.groupby("tempo_s")[
            "Q_meio_L_min"
        ].nunique()

        if (conflitos > 1).any():
            raise ValueError(
                f"Valores conflitantes em {arquivo}"
            )

        df = df.drop_duplicates("tempo_s", keep="first")

    print(
        f"[QOleoMeio] {arquivo.name}: "
        f"{len(df)} registros | "
        f"Q = {df['Q_meio_L_min'].min():.2f}–"
        f"{df['Q_meio_L_min'].max():.2f} L/min"
    )

    return df.reset_index(drop=True)


# ============================================================
# SINCRONIZAÇÃO DA ALTURA E VAZÃO
# ============================================================

def carregar_caso(case):

    nome = f"{MESH}_{case}"
    pasta_caso = Path(MESH) / nome

    arquivo_h = pasta_caso / "resultados_hL.csv"

    if not arquivo_h.exists():
        raise FileNotFoundError(arquivo_h)

    h = pd.read_csv(arquivo_h)

    colunas = {"tempo_s", "h_L_meio_mm"}

    if not colunas.issubset(h.columns):
        raise ValueError(
            f"Colunas necessárias ausentes em {arquivo_h}"
        )

    h = h[["tempo_s", "h_L_meio_mm"]].copy()
    h = h.dropna().sort_values("tempo_s")

    q = ler_qoleo_meio(pasta_caso)

    # Sincronização pelo tempo mais próximo.
    dados = pd.merge_asof(
        h,
        q,
        on="tempo_s",
        direction="nearest",
        tolerance=TOLERANCIA_TEMPO
    )

    dados = dados.dropna()

    if dados.empty:
        raise ValueError(
            f"Nenhum ponto sincronizado para {case}. "
            f"Verifique a tolerância temporal."
        )

    print(
        f"[OK] {case}: {len(dados)} pontos sincronizados | "
        f"h = {dados['h_L_meio_mm'].min():.2f}–"
        f"{dados['h_L_meio_mm'].max():.2f} mm | "
        f"Q = {dados['Q_meio_L_min'].min():.2f}–"
        f"{dados['Q_meio_L_min'].max():.2f} L/min"
    )

    return dados


# ============================================================
# GRÁFICO
# ============================================================

def main():

    h_analitico, q_analitico, _, _ = gerar_curva(
        n_pontos=1000
    )

    fig, ax = plt.subplots(figsize=(10, 7))

    # Curva analítica.
    ax.plot(
        q_analitico * 60000.0,
        h_analitico * 1000.0,
        linewidth=2.0,
        color="black",
        label="Modelo analítico",
        zorder=3
    )

    # Resultados CFD.
    for case in CASES:

        dados = carregar_caso(case)

        ax.plot(
            dados["Q_meio_L_min"],
            dados["h_L_meio_mm"],
            color=CORES[case],
            marker="o",
            markersize=3,
            linewidth=1.2,
            label=f"CFD {case}",
            zorder=4
        )

    # Referências das vazões nominais.
    for vazao in VAZOES_TEORICAS.values():

        ax.axvline(
            x=vazao,
            color="0.55",
            linestyle=":",
            linewidth=1.6,
            alpha=0.9,
            zorder=1
        )

    # Eixos.
    ax.set_xlabel(
        "Vazão volumétrica de óleo no plano central (L/min)",
        fontsize=11
    )

    ax.set_ylabel(
        r"Altura equivalente de líquido $h_L$ (mm)",
        fontsize=11
    )

    ax.tick_params(axis="both", labelsize=10)
    ax.grid(True, alpha=0.25)

    # Legenda lateral: resultados.
    handles, labels = ax.get_legend_handles_labels()

    fig.legend(
        handles,
        labels,
        loc="center left",
        bbox_to_anchor=(0.79, 0.62),
        fontsize=9,
        frameon=True,
        title="Resultados",
        title_fontsize=10
    )

    # Legenda inferior: vazões nominais.
    handles_referencias = [
        Line2D(
            [0], [0],
            color="0.55",
            linestyle=":",
            linewidth=1.6
        )
        for _ in VAZOES_TEORICAS
    ]

    labels_referencias = [
        f"Vazão nominal: {v:g} L/min"
        for v in VAZOES_TEORICAS.values()
    ]

    fig.legend(
        handles_referencias,
        labels_referencias,
        loc="lower center",
        bbox_to_anchor=(0.43, 0.025),
        ncol=3,
        fontsize=9,
        frameon=False,
        handlelength=2.2,
        columnspacing=1.5
    )

    # Espaçamento.
    fig.subplots_adjust(
        left=0.10,
        right=0.77,
        top=0.97,
        bottom=0.19
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(
        OUTPUT,
        dpi=400,
        bbox_inches="tight",
        pad_inches=0.08
    )

    plt.close(fig)

    print(f"\n[OK] Gráfico salvo: {OUTPUT.resolve()}")


if __name__ == "__main__":
    main()
