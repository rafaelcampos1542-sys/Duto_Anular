
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import re
import math

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from modelo_anular import gerar_curva


# ============================================================
# CONFIGURAÇÃO
# ============================================================

MESH = "M1"
CASES = ("Q20", "Q55")
RAIZES = (1, 2, 3)

PASTA_RAIZ = Path(".")

# Janela temporal de análise
TEMPO_INICIAL = 3
TEMPO_FINAL = 6

# Tolerância para sincronizar altura e vazão
TOLERANCIA_TEMPO = 0.13

# Mínimo de pontos sincronizados
MIN_PONTOS = 3

# Vazões nominais
VAZOES_TEORICAS = {
    "Q20": 20.0,
    "Q55": 55.0,
}

# Alturas analíticas conhecidas para as vazões nominais.
# Utilizadas para identificar o ramo analítico correspondente.
ALTURAS_NOMINAIS = {
    ("Q20", 1): 19.345,
    ("Q20", 2): 20.152,
    ("Q20", 3): 25.416,
    ("Q55", 1): 92.428,
    ("Q55", 2): 94.693,
    ("Q55", 3): 95.607,
}

# Identificação visual das raízes
MARCADORES = {
    1: "s",
    2: "o",
    3: "*",
}

# Identificação visual das vazões
CORES = {
    "Q20": "tab:blue",
    "Q55": "tab:orange",
}

# Arquivos de saída
ARQ_DADOS = "dados_comparacao_multiplas_alturas_M1.csv"
ARQ_ESTATISTICAS = "estatisticas_temporais_M1.csv"
ARQ_COMPARACAO = "comparacao_analitica_cfd_M1.csv"

ARQ_GRAFICO_TEMPORAL = "evolucao_temporal_M1.png"
ARQ_GRAFICO_COMPARACAO = "comparacao_analitico_cfd_M1.png"


# ============================================================
# EXPRESSÃO REGULAR
# ============================================================

NUM = re.compile(
    r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
)


# ============================================================
# LEITURA DA VAZÃO CENTRAL
# ============================================================

def ler_qoleo_meio(pasta_caso):

    pasta = pasta_caso / "postProcessing" / "QOleoMeio"

    if not pasta.exists():
        raise FileNotFoundError(
            f"Diretório QOleoMeio não encontrado: {pasta}"
        )

    # Seleciona somente o diretório de maior tempo.
    diretorios = [
        d for d in pasta.iterdir()
        if d.is_dir()
    ]

    diretorios_validos = []

    for d in diretorios:
        try:
            tempo_diretorio = float(d.name)
            diretorios_validos.append(
                (tempo_diretorio, d)
            )
        except ValueError:
            continue

    if not diretorios_validos:
        raise FileNotFoundError(
            f"Nenhum diretório temporal válido em {pasta}"
        )

    _, ultimo_diretorio = max(
        diretorios_validos,
        key=lambda item: item[0]
    )

    arquivos = sorted(
        ultimo_diretorio.glob("surfaceFieldValue*.dat")
    )

    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum arquivo surfaceFieldValue em "
            f"{ultimo_diretorio}"
        )
    registros = []

    for arquivo in arquivos:

        with arquivo.open(errors="replace") as f:

            for linha in f:

                linha = linha.strip()

                if not linha or linha.startswith("#"):
                    continue

                valores = NUM.findall(linha)

                # Formato:
                # tempo (Ux Uy Uz)
                if len(valores) < 4:
                    continue

                tempo = float(valores[0])
                q_y = float(valores[2])

                if math.isfinite(tempo) and math.isfinite(q_y):

                    # weightedAreaIntegrate(U) com alpha.oil
                    # já fornece vazão volumétrica em m3/s.
                    # Componente Y: direção axial.
                    # Conversão para L/min.
                    q_l_min = q_y * 60000.0

                    registros.append(
                        (tempo, q_l_min)
                    )

    if not registros:
        raise ValueError(
            f"Nenhum dado vetorial válido em {pasta}"
        )

    df = pd.DataFrame(
        registros,
        columns=[
            "tempo_s",
            "QOleoMeio_L_min"
        ]
    )

    df = df.drop_duplicates(
        subset=["tempo_s", "QOleoMeio_L_min"]
    )

    conflitos = df.groupby("tempo_s").size()
    conflitos = conflitos[conflitos > 1]

    if not conflitos.empty:
        raise ValueError(
            f"Valores conflitantes em QOleoMeio: "
            f"{conflitos.index.tolist()[:10]}"
        )

    return df.sort_values("tempo_s").reset_index(drop=True)


# ============================================================
# LEITURA DA ALTURA E SINCRONIZAÇÃO
# ============================================================

def carregar_caso(case, raiz):

    nome = f"{MESH}_{case}_R{raiz}"
    pasta_caso = PASTA_RAIZ / nome

    arquivo_h = pasta_caso / "resultados_hL.csv"

    if not pasta_caso.exists():
        print(f"[AVISO] Pasta não encontrada: {pasta_caso}")
        return None

    if not arquivo_h.exists():
        print(f"[AVISO] Arquivo não encontrado: {arquivo_h}")
        return None

    h = pd.read_csv(arquivo_h)

    colunas = {"tempo_s", "h_L_meio_mm"}

    if not colunas.issubset(h.columns):
        raise ValueError(
            f"Colunas esperadas ausentes em {arquivo_h}"
        )

    h = h[
        ["tempo_s", "h_L_meio_mm"]
    ].copy()

    q = ler_qoleo_meio(pasta_caso)

    h = h.dropna().sort_values("tempo_s")
    q = q.dropna().sort_values("tempo_s")

    dados = pd.merge_asof(
        h,
        q,
        on="tempo_s",
        direction="nearest",
        tolerance=TOLERANCIA_TEMPO,
    ).dropna()

    if dados.empty:
        print(f"[AVISO] Sem dados sincronizados: {nome}")
        return None

    # Recorte da janela temporal com tolerância nos dois limites
    tempo_inicio_aceito = TEMPO_INICIAL - TOLERANCIA_TEMPO
    tempo_final_aceito = TEMPO_FINAL + TOLERANCIA_TEMPO

    dados = dados[
        (dados["tempo_s"] >= tempo_inicio_aceito) &
        (dados["tempo_s"] <= tempo_final_aceito)
    ].copy()

    if len(dados) < MIN_PONTOS:
        print(
            f"[AVISO] {nome}: apenas {len(dados)} pontos "
            f"na janela temporal."
        )
        return None

    dados["caso"] = case
    dados["raiz"] = raiz
    dados["identificacao"] = nome

    tempo_min = dados["tempo_s"].min()
    tempo_max = dados["tempo_s"].max()

    print(
        f"[OK] {nome}: {len(dados)} pontos | "
        f"janela efetiva = {tempo_min:.3f}–{tempo_max:.3f} s | "
        f"Q = "
        f"{dados['QOleoMeio_L_min'].min():.2f}–"
        f"{dados['QOleoMeio_L_min'].max():.2f} L/min | "
        f"h = "
        f"{dados['h_L_meio_mm'].min():.2f}–"
        f"{dados['h_L_meio_mm'].max():.2f} mm"
    )

    inicio_ok = (
        TEMPO_INICIAL - TOLERANCIA_TEMPO
        <= tempo_min
        <= TEMPO_INICIAL + TOLERANCIA_TEMPO
    )

    fim_ok = (
        TEMPO_FINAL - TOLERANCIA_TEMPO
        <= tempo_max
        <= TEMPO_FINAL + TOLERANCIA_TEMPO
    )

    if not (inicio_ok and fim_ok):
        print(
            f"[AVISO] Janela fora da tolerância: "
            f"{tempo_min:.3f}–{tempo_max:.3f} s"
        )

    return dados.reset_index(drop=True)


# ============================================================
# ESTATÍSTICAS TEMPORAIS
# ============================================================

def estatistica_temporal(tempo, valores):

    tempo = np.asarray(tempo, dtype=float)
    valores = np.asarray(valores, dtype=float)

    ordem = np.argsort(tempo)
    tempo = tempo[ordem]
    valores = valores[ordem]

    # Remove tempos duplicados, caso existam
    df = pd.DataFrame({
        "tempo": tempo,
        "valor": valores
    }).drop_duplicates(
        subset="tempo",
        keep="first"
    )

    tempo = df["tempo"].to_numpy()
    valores = df["valor"].to_numpy()

    if len(tempo) < 2:
        raise ValueError(
            "Pontos insuficientes para integração temporal."
        )

    duracao = tempo[-1] - tempo[0]

    if duracao <= 0:
        raise ValueError("Intervalo temporal inválido.")

    # Média temporal pela integração trapezoidal
    media = np.trapezoid(valores, tempo) / duracao

    variancia = (
        np.trapezoid((valores - media) ** 2, tempo)
        / duracao
    )

    desvio = np.sqrt(max(variancia, 0.0))

    return {
        "media": media,
        "desvio": desvio,
        "minimo": valores.min(),
        "maximo": valores.max(),
        "n": len(valores),
        "duracao": duracao,
        "tempo_inicial": tempo[0],
        "tempo_final": tempo[-1],
    }


def calcular_estatisticas(dados):

    resultados = []

    for identificacao, grupo in dados.groupby("identificacao"):

        estat_q = estatistica_temporal(
            grupo["tempo_s"],
            grupo["QOleoMeio_L_min"]
        )

        estat_h = estatistica_temporal(
            grupo["tempo_s"],
            grupo["h_L_meio_mm"]
        )

        primeira = grupo.iloc[0]

        resultados.append({
            "caso": primeira["caso"],
            "raiz": int(primeira["raiz"]),
            "identificacao": identificacao,

            "tempo_inicial_s": estat_q["tempo_inicial"],
            "tempo_final_s": estat_q["tempo_final"],
            "duracao_s": estat_q["duracao"],
            "numero_pontos": estat_q["n"],

            "Q_media_L_min": estat_q["media"],
            "Q_desvio_L_min": estat_q["desvio"],
            "Q_min_L_min": estat_q["minimo"],
            "Q_max_L_min": estat_q["maximo"],

            "h_media_mm": estat_h["media"],
            "h_desvio_mm": estat_h["desvio"],
            "h_min_mm": estat_h["minimo"],
            "h_max_mm": estat_h["maximo"],
        })

    return pd.DataFrame(resultados)


# ============================================================
# ALTURA ANALÍTICA PARA A VAZÃO MÉDIA
# ============================================================

def altura_analitica_na_vazao(
    q_alvo_l_min,
    h_referencia_mm,
    h_curva_m,
    q_curva_m3s
):
    """
    Interpola a altura na curva analítica.

    Quando houver mais de um ramo para a mesma vazão,
    escolhe o segmento que passa mais próximo da altura
    analítica de referência da raiz na vazão nominal.

    Não força uma raiz inexistente.
    """

    q_curva = np.asarray(q_curva_m3s) * 60000.0
    h_curva = np.asarray(h_curva_m) * 1000.0

    candidatos = []

    for i in range(len(q_curva) - 1):

        q1 = q_curva[i]
        q2 = q_curva[i + 1]

        if q1 == q2:
            continue

        # Verifica se o segmento contém a vazão desejada
        if min(q1, q2) <= q_alvo_l_min <= max(q1, q2):

            fracao = (
                (q_alvo_l_min - q1) / (q2 - q1)
            )

            h_interp = (
                h_curva[i] +
                fracao * (h_curva[i + 1] - h_curva[i])
            )

            candidatos.append(h_interp)

    if not candidatos:
        return np.nan

    # Seleciona o ramo mais próximo da raiz nominal
    candidatos = np.asarray(candidatos)

    indice = np.argmin(
        np.abs(candidatos - h_referencia_mm)
    )

    return float(candidatos[indice])


# ============================================================
# COMPARAÇÃO ANALÍTICA × CFD
# ============================================================

def calcular_comparacao(estatisticas, h_analitico, q_analitico):

    resultados = []

    for _, linha in estatisticas.iterrows():

        case = linha["caso"]
        raiz = int(linha["raiz"])

        q_nominal = VAZOES_TEORICAS[case]
        h_nominal = ALTURAS_NOMINAIS[(case, raiz)]

        q_media = linha["Q_media_L_min"]
        h_media = linha["h_media_mm"]

        h_analitica_media = altura_analitica_na_vazao(
            q_media,
            h_nominal,
            h_analitico,
            q_analitico
        )

        erro_q = (
            (q_media - q_nominal) / q_nominal
        ) * 100.0

        if np.isfinite(h_analitica_media):
            erro_h = (
                (h_media - h_analitica_media)
                / h_analitica_media
            ) * 100.0
        else:
            erro_h = np.nan

        resultados.append({
            "caso": case,
            "raiz": raiz,

            "Q_nominal_L_min": q_nominal,
            "Q_media_CFD_L_min": q_media,
            "Q_desvio_CFD_L_min": linha["Q_desvio_L_min"],
            "erro_Q_percentual": erro_q,

            "h_nominal_analitica_mm": h_nominal,
            "h_media_CFD_mm": h_media,
            "h_desvio_CFD_mm": linha["h_desvio_mm"],

            "h_analitica_na_Q_media_mm": h_analitica_media,
            "erro_h_percentual": erro_h,
        })

    return pd.DataFrame(resultados)


# ============================================================
# GRÁFICO 1 — EVOLUÇÃO TEMPORAL
# ============================================================


def gerar_grafico_temporal(dados):

    fig, (ax_q, ax_h) = plt.subplots(
        2, 1,
        figsize=(9, 6),
        sharex=True
    )

    for case in CASES:
        for raiz in RAIZES:

            nome = f"{MESH}_{case}_R{raiz}"

            grupo = dados[
                dados["identificacao"] == nome
            ]

            if grupo.empty:
                continue

            cor = CORES[case]
            marcador = MARCADORES[raiz]

            estilo = {
                #"color": cor,
                "marker": marcador,
                "markersize": 5,
                "markevery": 3,
                "linewidth": 1.7,
                "label": f"{case} – R{raiz}"
            }

            ax_q.plot(
                grupo["tempo_s"],
                grupo["QOleoMeio_L_min"],
                **estilo
            )

            ax_h.plot(
                grupo["tempo_s"],
                grupo["h_L_meio_mm"],
                **estilo
            )

    # Identificação dos eixos
    ax_q.set_ylabel(
        "Vazão de óleo (L/min)",
        fontsize=11
    )

    ax_h.set_ylabel(
        r"Altura equivalente, $h_L$ (mm)",
        fontsize=11
    )

    ax_h.set_xlabel(
        "Tempo (s)",
        fontsize=11
    )

    # Configuração visual dos painéis
    for ax in (ax_q, ax_h):

        ax.set_xlim(TEMPO_INICIAL, TEMPO_FINAL)

        ax.tick_params(
            axis="both",
            labelsize=9,
            pad=3
        )

        ax.grid(
            True,
            alpha=0.25,
            linewidth=0.7
        )

    # Legenda única compartilhada
    handles, labels = ax_q.get_legend_handles_labels()

    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.015),
        ncol=3,
        fontsize=9,
        frameon=False,
        handlelength=2,
        columnspacing=1.8
    )

    # Espaçamento
    fig.subplots_adjust(
        left=0.14,
        right=0.97,
        top=0.97,
        bottom=0.20,
        hspace=0.30
    )

    fig.savefig(
        ARQ_GRAFICO_TEMPORAL,
        dpi=400,
        bbox_inches="tight",
        pad_inches=0.06
    )

    plt.close(fig)


# ============================================================
# GRÁFICO 2 — MODELO ANALÍTICO × CFD
# ============================================================

def gerar_grafico_comparacao(
    comparacao,
    h_analitico,
    q_analitico
):

    fig, ax = plt.subplots(figsize=(12, 8))

    # Curva analítica completa
    ax.plot(
        q_analitico * 60000.0,
        h_analitico * 1000.0,
        color="black",
        linewidth=2,
        label="Modelo analítico",
        zorder=2
    )

    for _, linha in comparacao.iterrows():

        case = linha["caso"]
        raiz = int(linha["raiz"])

        #cor = CORES[case]
        marcador = MARCADORES[raiz]

        q_media = linha["Q_media_CFD_L_min"]
        h_media = linha["h_media_CFD_mm"]

        q_desvio = linha["Q_desvio_CFD_L_min"]
        h_desvio = linha["h_desvio_CFD_mm"]

        # Média CFD com barras de dispersão temporal
        ax.errorbar(
            q_media,
            h_media,
            xerr=q_desvio,
            yerr=h_desvio,
            fmt=marcador,
            #color=cor,
            markeredgecolor="black",
            markeredgewidth=0.7,
            markersize=9 if raiz != 3 else 12,
            capsize=4,
            elinewidth=1.2,
            label=f"CFD {case} - R{raiz}",
            zorder=5
        )

        # Previsão analítica para a vazão média do CFD
        h_a = linha["h_analitica_na_Q_media_mm"]

        if np.isfinite(h_a):

            ax.scatter(
                q_media,
                h_a,
                marker="x",
                #color=cor,
                s=75,
                linewidths=2,
                zorder=6
            )

    # Referências de vazão nominal
    for case, vazao in VAZOES_TEORICAS.items():

        ax.axvline(
            x=vazao,
            #color=CORES[case],
            linestyle=":",
            linewidth=1.5,
            alpha=0.8,
            label=f"Vazão nominal {case}: {vazao} L/min"
        )

    ax.set_xlabel(
        "Vazão volumétrica de óleo no plano central (L/min)"
    )

    ax.set_ylabel(
        "Altura equivalente de líquido $h_L$ (mm)"
    )



    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, ncol=2)

    fig.tight_layout()

    fig.savefig(
        ARQ_GRAFICO_COMPARACAO,
        dpi=300,
        bbox_inches="tight"
    )

    plt.close(fig)


# ============================================================
# RELATÓRIO NO TERMINAL
# ============================================================

def imprimir_resultados(estatisticas, comparacao):

    print("\n")
    print("=" * 76)
    print(" ESTATÍSTICAS TEMPORAIS — CFD")
    print("=" * 76)

    for _, linha in estatisticas.iterrows():

        print(
            f"\n{linha['identificacao']}"
        )

        print(
            f"Q média = {linha['Q_media_L_min']:.3f} "
            f"+/- {linha['Q_desvio_L_min']:.3f} L/min"
        )

        print(
            f"h média = {linha['h_media_mm']:.3f} "
            f"+/- {linha['h_desvio_mm']:.3f} mm"
        )

        print(
            f"Pontos = {int(linha['numero_pontos'])} | "
            f"Janela = {linha['tempo_inicial_s']:.3f}–"
            f"{linha['tempo_final_s']:.3f} s"
        )

    print("\n")
    print("=" * 76)
    print(" COMPARAÇÃO ANALÍTICA × CFD")
    print("=" * 76)

    for _, linha in comparacao.iterrows():

        print(
            f"\n{linha['caso']} R{int(linha['raiz'])}"
        )

        print(
            f"Erro de vazão = "
            f"{linha['erro_Q_percentual']:+.2f}%"
        )

        print(
            f"h CFD = {linha['h_media_CFD_mm']:.3f} mm"
        )

        print(
            f"h analítica na Q média = "
            f"{linha['h_analitica_na_Q_media_mm']:.3f} mm"
        )

        print(
            f"Erro de altura = "
            f"{linha['erro_h_percentual']:+.2f}%"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 76)
    print(" COMPARAÇÃO ANALÍTICA × CFD — MÚLTIPLAS ALTURAS")
    print("=" * 76)

    print(
        f"Malha: {MESH} | "
        f"Janela: {TEMPO_INICIAL}–{TEMPO_FINAL} s"
    )

    todos_dados = []

    # --------------------------------------------------------
    # Carrega as seis simulações
    # --------------------------------------------------------

    for case in CASES:

        for raiz in RAIZES:

            dados = carregar_caso(case, raiz)

            if dados is not None:
                todos_dados.append(dados)

    if not todos_dados:
        raise RuntimeError(
            "Nenhum caso apresentou dados suficientes."
        )

    consolidado = pd.concat(
        todos_dados,
        ignore_index=True
    )

    consolidado.to_csv(
        ARQ_DADOS,
        index=False
    )

    # --------------------------------------------------------
    # Estatísticas temporais
    # --------------------------------------------------------

    estatisticas = calcular_estatisticas(consolidado)

    estatisticas.to_csv(
        ARQ_ESTATISTICAS,
        index=False
    )

    # --------------------------------------------------------
    # Curva analítica
    # --------------------------------------------------------

    h_analitico, q_analitico, _, _ = gerar_curva(
        n_pontos=5000
    )

    # --------------------------------------------------------
    # Comparação
    # --------------------------------------------------------

    comparacao = calcular_comparacao(
        estatisticas,
        h_analitico,
        q_analitico
    )

    comparacao.to_csv(
        ARQ_COMPARACAO,
        index=False
    )

    # --------------------------------------------------------
    # Gráficos
    # --------------------------------------------------------

    gerar_grafico_temporal(consolidado)

    gerar_grafico_comparacao(
        comparacao,
        h_analitico,
        q_analitico
    )

    # --------------------------------------------------------
    # Relatório
    # --------------------------------------------------------

    imprimir_resultados(
        estatisticas,
        comparacao
    )

    print("\n")
    print("=" * 76)
    print(" ARQUIVOS GERADOS")
    print("=" * 76)

    arquivos = [
        ARQ_DADOS,
        ARQ_ESTATISTICAS,
        ARQ_COMPARACAO,
        ARQ_GRAFICO_TEMPORAL,
        ARQ_GRAFICO_COMPARACAO,
    ]

    for arquivo in arquivos:
        print(f"[OK] {Path(arquivo).resolve()}")

    print("=" * 76)


if __name__ == "__main__":
    main()
