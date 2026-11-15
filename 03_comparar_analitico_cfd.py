#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""03 — Comparação entre o modelo analítico e o CFD.

Lê ``dados_extraidos/series_temporais.csv`` (script 01) e trata as duas partes:

  base            Q10, Q35 e Q60 (fora da região de multiplicidade)
                  Tabelas 4, 5 e 6 e Figura 7 do TCC
  multiplicidade  Q20 e Q55, raízes R1, R2 e R3
                  Tabela 7, Figura 8 e figuras do Apêndice 9

Saída em ``resultados/analitico_cfd/``:

    base/
        tabela4_parametros.csv        vazões, alturas, V, Re e Fr em t ≈ 5 s
        tabela5_balanco.csv           balanço volumétrico de óleo entre 5 e 6 s
        tabela6_analitico_cfd.csv     h_L do CFD x h_L analítica (Q central e nominal)
        altura_central_por_malha.csv  h_L central em M0, M1 e M2
        diagnostico_perfil_central.csv  velocidade do ar/óleo na linha de amostragem
        figuras/comparacao_analitico_cfd_M1.png
    multiplicidade/
        tabela7_estatisticas.csv      média ± desvio temporal e CV_t
        analitico_cfd.csv             h_L do CFD x h_L analítica na vazão central
        repetibilidade.csv            CV_r entre R1, R2 e R3 no intervalo comum
        estabilidade.csv              estável/transiente no trecho final da janela
        registros_na_janela.csv       registros usados nas estatísticas
        figuras/evolucao_temporal_M1.png, comparacao_analitico_cfd_M1.png,
                repetibilidade_M1_Q20.png, repetibilidade_M1_Q55.png

Uso:
    python 03_comparar_analitico_cfd.py
    python 03_comparar_analitico_cfd.py --parte multiplicidade
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from duto_anular.casos import (JANELA_BALANCO, JANELA_MEDIA, L_MIN, MALHAS,
                               MALHA_REFERENCIA, RAIZES, T_REFERENCIA,
                               VAZOES_BASE, VAZOES_MULTIPLICIDADE, info_caso,
                               nome_caso)
from duto_anular.dados import (carregar_series, reynolds_froude, salvar_csv,
                               serie, valor_no_tempo)
from duto_anular.estatistica import media_dos_registros, media_na_janela
from duto_anular.modelo_anular import D_O, encontrar_raizes_Q, gerar_curva

# Folga aceita nos limites da janela para as estatísticas de Q20/Q55: os tempos
# gravados são 2,9998 s, 6,00005 s etc. (13 registros entre 3 e 6 s).
TOLERANCIA_TEMPO = 0.13
MINIMO_DE_PONTOS = 3

CORES_BASE = {"Q10": "tab:blue", "Q35": "tab:orange", "Q60": "tab:green"}
MARCADORES_RAIZ = {1: "s", 2: "o", 3: "*"}


# ---------------------------------------------------------------------------
# Modelo analítico
# ---------------------------------------------------------------------------
def raizes_analiticas(q_l_min: float) -> list[float]:
    """Alturas h_L [mm] que o modelo analítico dá para a vazão (ordem crescente)."""
    return [r[0] * 1000.0 for r in encontrar_raizes_Q(q_l_min / L_MIN)]


def altura_analitica_na_vazao(q_l_min, h_referencia_mm, h_curva_m, q_curva_m3s):
    """Altura na curva analítica para a vazão dada.

    Se a vazão cruza mais de um ramo da curva, vale o ramo mais próximo de
    ``h_referencia_mm`` (a raiz analítica na vazão nominal do caso).
    """
    q_curva = np.asarray(q_curva_m3s) * L_MIN
    h_curva = np.asarray(h_curva_m) * 1000.0
    candidatos = []
    for i in range(len(q_curva) - 1):
        q1, q2 = q_curva[i], q_curva[i + 1]
        if q1 == q2:
            continue
        if min(q1, q2) <= q_l_min <= max(q1, q2):
            fracao = (q_l_min - q1) / (q2 - q1)
            candidatos.append(h_curva[i] + fracao * (h_curva[i + 1] - h_curva[i]))
    if not candidatos:
        return float("nan")
    candidatos = np.asarray(candidatos)
    return float(candidatos[np.argmin(np.abs(candidatos - h_referencia_mm))])


def desvio_pct(valor, referencia):
    if not np.isfinite(valor) or not np.isfinite(referencia) or referencia == 0:
        return float("nan")
    return (valor - referencia) / referencia * 100.0


# ---------------------------------------------------------------------------
# PARTE 1 — casos base (Q10, Q35, Q60)
# ---------------------------------------------------------------------------
def parte_base(df, args, saida: Path) -> bool:
    malha = args.malha
    janela, janela_bal, t_ref = tuple(args.janela), tuple(args.janela_balanco), args.t_ref
    h_curva, q_curva, _, _ = gerar_curva(n_pontos=5000)
    tab4, tab5, tab6 = [], [], []

    print("\n" + "=" * 78)
    print(f" CASOS BASE — malha {malha} | t_ref ≈ {t_ref:g} s | média {janela[0]:g}–{janela[1]:g} s"
          f" | balanço {janela_bal[0]:g}–{janela_bal[1]:g} s")
    print("=" * 78)

    for vazao in VAZOES_BASE:
        caso = nome_caso(malha, vazao)
        sub = df[df["caso_id"] == caso]
        if sub.empty:
            print(f"[AVISO] {caso}: sem dados extraídos.")
            continue
        q_nom = info_caso(caso)["Q_nominal_L_min"]

        # ---- Tabela 4: valores no instante de referência -------------------
        def em_tref(coluna):
            return valor_no_tempo(*serie(df, caso, coluna), t_ref)

        t_usado, q_in = em_tref("Q_in_L_min")
        _, q_out = em_tref("Q_out_L_min")
        _, q_meio_t = em_tref("Q_meio_L_min")
        _, h_meio = em_tref("h_meio_mm")
        _, h_saida = em_tref("h_saida_mm")
        _, h_entrada = em_tref("h_entrada_mm")
        _, a_entrada = em_tref("A_oleo_entrada_m2")
        _, a_meio = em_tref("A_oleo_meio_m2")
        _, a_saida = em_tref("A_oleo_saida_m2")

        v_entrada = q_nom / L_MIN / a_entrada if a_entrada > 0 else float("nan")
        v_meio = q_meio_t / L_MIN / a_meio if a_meio > 0 else float("nan")
        v_saida = q_out / L_MIN / a_saida if a_saida > 0 else float("nan")
        reynolds, froude = reynolds_froude(h_meio, v_meio)
        tab4.append({
            "caso": vazao, "tempo_s": t_usado,
            "Q_in_L_min": q_in, "Q_out_L_min": q_out,
            "diferenca_in_out_pct": (q_in - q_out) / q_in * 100.0 if q_in else float("nan"),
            "h_entrada_mm": h_entrada, "h_meio_mm": h_meio, "h_saida_mm": h_saida,
            "reducao_meio_saida_pct": -desvio_pct(h_saida, h_meio),
            "V_entrada_m_s": v_entrada, "V_meio_m_s": v_meio, "V_saida_m_s": v_saida,
            "Re_meio": reynolds, "Fr_meio": froude,
            "folga_ate_o_topo_mm": D_O * 1000.0 - h_meio,
        })

        # ---- Tabela 5: balanço volumétrico de óleo -------------------------
        def media(coluna, jan, minimo=2):
            r = media_na_janela(*serie(df, caso, coluna), jan, minimo_de_pontos=minimo)
            return r if r else {"media": float("nan"), "valor_inicial": float("nan"),
                                "valor_final": float("nan"), "t_inicial": float("nan"),
                                "t_final": float("nan")}

        m_in, m_out = media("Q_in_L_min", janela_bal), media("Q_out_L_min", janela_bal)
        m_ar, m_vol = media("Q_inlet_air_L_min", janela_bal), media("volume_oleo_m3", janela_bal)
        duracao = m_vol["t_final"] - m_vol["t_inicial"]
        dv_dt = ((m_vol["valor_final"] - m_vol["valor_inicial"]) / duracao * L_MIN
                 if duracao and np.isfinite(duracao) else float("nan"))
        saida_total = m_out["media"] + m_ar["media"]
        residuo = m_in["media"] - saida_total - dv_dt
        q_meio = media("Q_meio_L_min", janela, minimo=4)["media"]
        tab5.append({
            "caso": vazao, "janela_s": f"{janela_bal[0]:g}-{janela_bal[1]:g}",
            "entrada_L_min": m_in["media"],
            "saida_outlet_L_min": m_out["media"],
            "saida_inlet_air_L_min": m_ar["media"],
            "saida_total_L_min": saida_total,
            "dV_dt_L_min": dv_dt,
            "residuo_L_min": residuo,
            "residuo_relativo_pct": abs(residuo) / m_in["media"] * 100
            if m_in["media"] else float("nan"),
            "entrada_menos_inlet_air_L_min": m_in["media"] - m_ar["media"],
            "Q_meio_medio_L_min": q_meio,
        })

        # ---- Tabela 6: altura do CFD x altura analítica --------------------
        raizes_nom = raizes_analiticas(q_nom)
        h_nominal = (min(raizes_nom, key=lambda h: abs(h - h_entrada))
                     if raizes_nom else float("nan"))
        h_analitica_meio = altura_analitica_na_vazao(q_meio, h_nominal, h_curva, q_curva)
        tab6.append({
            "caso": vazao, "Q_nominal_L_min": q_nom, "Q_meio_L_min": q_meio,
            "h_meio_CFD_mm": h_meio,
            "h_analitica_em_Q_meio_mm": h_analitica_meio,
            "desvio_em_Q_meio_pct": desvio_pct(h_meio, h_analitica_meio),
            "h_analitica_em_Q_nominal_mm": h_nominal,
            "desvio_em_Q_nominal_pct": desvio_pct(h_meio, h_nominal),
        })

    if not tab4:
        print("[AVISO] Nenhum caso base com dados; parte ignorada.")
        return False

    tab4, tab5, tab6 = pd.DataFrame(tab4), pd.DataFrame(tab5), pd.DataFrame(tab6)
    salvar_csv(tab4, saida / "tabela4_parametros.csv")
    salvar_csv(tab5, saida / "tabela5_balanco.csv")
    salvar_csv(tab6, saida / "tabela6_analitico_cfd.csv")

    # Altura central em cada malha (variação citada no texto, sem GCI).
    por_malha = []
    for vazao in VAZOES_BASE:
        for m in MALHAS:
            t, h = valor_no_tempo(*serie(df, nome_caso(m, vazao), "h_meio_mm"), t_ref)
            if np.isfinite(h):
                por_malha.append({"caso": vazao, "malha": m, "tempo_s": t, "h_meio_mm": h})
    salvar_csv(pd.DataFrame(por_malha), saida / "altura_central_por_malha.csv")

    diag = diagnostico_perfil_central(args.dados, malha, janela)
    salvar_csv(diag, saida / "diagnostico_perfil_central.csv")

    figura_base(df, malha, saida / "figuras" / f"comparacao_analitico_cfd_{malha}.png")

    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print("\nTabela 4 — parâmetros em t_ref\n" + tab4.to_string(index=False))
        print("\nTabela 5 — balanço volumétrico\n" + tab5.to_string(index=False))
        print("\nTabela 6 — analítico x CFD\n" + tab6.to_string(index=False))
        if not diag.empty:
            print("\nPerfil central (linha de amostragem; não é média de seção)\n"
                  + diag.to_string(index=False))
    if tab5["saida_inlet_air_L_min"].isna().any():
        print("\n[AVISO] Falta QOleoInletAir em algum caso: o balanço ficou incompleto. "
              "Rode postProcess -func fluxoOleoInletAir e extraia de novo.")
    return True


def diagnostico_perfil_central(pasta_dados: Path, malha, janela) -> pd.DataFrame:
    """Velocidade axial média do ar e do óleo na linha vertical do plano central.

    Ramo 1 = abaixo do tubo interno; ramo 2 = acima. É o diagnóstico do ar em
    contracorrente citado na Seção 4.3; são amostras de uma linha, não médias
    de seção.
    """
    arquivo = Path(pasta_dados) / "perfis_resumo.csv"
    if not arquivo.is_file():
        return pd.DataFrame()
    perfis = pd.read_csv(arquivo)
    perfis = perfis[(perfis["perfil"] == "perfil_meio")
                    & (perfis["tempo_s"] >= janela[0] - TOLERANCIA_TEMPO)
                    & (perfis["tempo_s"] <= janela[1] + TOLERANCIA_TEMPO)]
    linhas = []
    for vazao in VAZOES_BASE:
        sub = perfis[perfis["caso_id"] == nome_caso(malha, vazao)]
        for ramo, g in sub.groupby("ramo"):
            linhas.append({"caso": vazao, "ramo": int(ramo), "n_registros": len(g),
                           "Uy_medio_ar_m_s": g["Uy_medio_ar_m_s"].mean(),
                           "Uy_medio_oleo_m_s": g["Uy_medio_oleo_m_s"].mean()})
    return pd.DataFrame(linhas)


def figura_base(df, malha, arquivo: Path):
    """Figura 7: curva analítica h_L(Q) e registros temporais do CFD."""
    h_analitico, q_analitico, _, _ = gerar_curva(n_pontos=1000)
    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    ax.plot(q_analitico * L_MIN, h_analitico * 1000.0, linewidth=2.0, color="black",
            label="Modelo analítico", zorder=3)

    nominais = []
    for vazao in VAZOES_BASE:
        caso = nome_caso(malha, vazao)
        sub = df.loc[df["caso_id"] == caso, ["tempo_s", "Q_meio_L_min", "h_meio_mm"]].dropna()
        if sub.empty:
            continue
        nominais.append(info_caso(caso)["Q_nominal_L_min"])
        ax.plot(sub["Q_meio_L_min"], sub["h_meio_mm"], color=CORES_BASE[vazao],
                marker="o", markersize=3, linewidth=1.2, label=f"CFD {vazao}", zorder=4)

    # posição vertical (mm) dos rótulos, escolhida em regiões livres da curva
    y_rotulo = {10: 75, 35: 90, 60: 40}
    for q in nominais:
        ax.axvline(x=q, color="0.55", linestyle=":", linewidth=1.6, alpha=0.9, zorder=1)
        ax.text(q - 0.8, y_rotulo.get(int(round(q)), 60), f"Vazão teórica: {q:g} L/min",
                rotation=90, ha="right", va="center", fontsize=10, color="dimgray",
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.5), zorder=2)

    ax.set_xlabel("Vazão volumétrica de óleo no plano central (L/min)", fontsize=12)
    ax.set_ylabel(r"Altura equivalente de líquido $h_L$ (mm)", fontsize=12)
    ax.tick_params(axis="both", labelsize=11)
    ax.grid(True, alpha=0.25)
    # legenda com apenas 4 entradas (analítico + 3 casos CFD), na região livre
    ax.legend(loc="lower right", fontsize=10, frameon=True, framealpha=0.9)

    arquivo.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(arquivo, dpi=400, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)

# ---------------------------------------------------------------------------
# PARTE 2 — multiplicidade (Q20 e Q55, raízes R1 a R3)
# ---------------------------------------------------------------------------
def parte_multiplicidade(df, args, saida: Path) -> bool:
    malha = args.malha
    t0, t1 = args.janela
    h_curva, q_curva, _, _ = gerar_curva(n_pontos=5000)

    print("\n" + "=" * 78)
    print(f" MULTIPLICIDADE — malha {malha} | janela {t0:g}–{t1:g} s")
    print("=" * 78)

    registros, tab7, comparacao = [], [], []
    for vazao in VAZOES_MULTIPLICIDADE:
        q_nom = float(vazao[1:])
        raizes_nom = raizes_analiticas(q_nom)
        for raiz in RAIZES:
            caso = nome_caso(malha, vazao, raiz)
            sub = df.loc[df["caso_id"] == caso, ["tempo_s", "Q_meio_L_min", "h_meio_mm"]].dropna()
            sub = sub[(sub["tempo_s"] >= t0 - TOLERANCIA_TEMPO)
                      & (sub["tempo_s"] <= t1 + TOLERANCIA_TEMPO)]
            if len(sub) < MINIMO_DE_PONTOS:
                print(f"[AVISO] {caso}: {len(sub)} registros na janela; caso ignorado.")
                continue
            if len(raizes_nom) < raiz:
                print(f"[AVISO] {caso}: o modelo analítico não tem raiz {raiz} em {q_nom:g} L/min.")
                continue
            h_nominal = raizes_nom[raiz - 1]

            sub = sub.assign(caso_id=caso, vazao=vazao, raiz=raiz)
            registros.append(sub)
            est_q = media_dos_registros(sub["tempo_s"], sub["Q_meio_L_min"])
            est_h = media_dos_registros(sub["tempo_s"], sub["h_meio_mm"])
            tab7.append({
                "caso": f"{vazao}_R{raiz}", "h_L0_mm": h_nominal,
                "Q_meio_media_L_min": est_q["media"], "Q_meio_desvio_L_min": est_q["desvio"],
                "CVt_Q_pct": est_q["cv_pct"],
                "h_meio_media_mm": est_h["media"], "h_meio_desvio_mm": est_h["desvio"],
                "CVt_h_pct": est_h["cv_pct"],
                "n_registros": est_q["n"], "t_inicial_s": est_q["t_inicial"],
                "t_final_s": est_q["t_final"],
                "Q_min_L_min": est_q["minimo"], "Q_max_L_min": est_q["maximo"],
                "h_min_mm": est_h["minimo"], "h_max_mm": est_h["maximo"],
            })
            h_analitica = altura_analitica_na_vazao(est_q["media"], h_nominal, h_curva, q_curva)
            comparacao.append({
                "caso": f"{vazao}_R{raiz}", "vazao": vazao, "raiz": raiz,
                "Q_nominal_L_min": q_nom, "Q_meio_media_L_min": est_q["media"],
                "Q_meio_desvio_L_min": est_q["desvio"],
                "erro_Q_pct": desvio_pct(est_q["media"], q_nom),
                "h_nominal_analitica_mm": h_nominal,
                "h_meio_media_mm": est_h["media"], "h_meio_desvio_mm": est_h["desvio"],
                "h_analitica_em_Q_meio_mm": h_analitica,
                "erro_h_pct": desvio_pct(est_h["media"], h_analitica),
            })
            print(f"[OK] {caso}: {est_q['n']} registros em {est_q['t_inicial']:.3f}–"
                  f"{est_q['t_final']:.3f} s | Q = {est_q['media']:.3f} ± {est_q['desvio']:.3f} L/min"
                  f" | h = {est_h['media']:.3f} ± {est_h['desvio']:.3f} mm")

    if not tab7:
        print("[AVISO] Nenhum caso de multiplicidade com dados; parte ignorada.")
        return False

    registros = pd.concat(registros, ignore_index=True)
    tab7, comparacao = pd.DataFrame(tab7), pd.DataFrame(comparacao)
    rep = repetibilidade(df, malha, (t0, t1))
    estab = estabilidade(df, malha, (t0, t1))
    salvar_csv(estab, saida / "estabilidade.csv")
    salvar_csv(registros[["caso_id", "vazao", "raiz", "tempo_s", "Q_meio_L_min", "h_meio_mm"]],
               saida / "registros_na_janela.csv")
    salvar_csv(tab7, saida / "tabela7_estatisticas.csv")
    salvar_csv(comparacao, saida / "analitico_cfd.csv")
    salvar_csv(rep, saida / "repetibilidade.csv")

    figuras = saida / "figuras"
    figuras.mkdir(parents=True, exist_ok=True)
    figura_evolucao(registros, malha, (t0, t1), figuras / f"evolucao_temporal_{malha}.png")
    figura_comparacao(comparacao, h_curva, q_curva, figuras / f"comparacao_analitico_cfd_{malha}.png")
    for vazao in VAZOES_MULTIPLICIDADE:
        figura_repetibilidade(df, malha, vazao, (t0, t1), args.plano,
                              figuras / f"repetibilidade_{malha}_{vazao}.png")

    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print("\nTabela 7 — estatísticas temporais\n" + tab7.iloc[:, :8].to_string(index=False))
        print("\nAnalítico x CFD\n" + comparacao.drop(columns=["vazao", "raiz"]).to_string(index=False))
        if not rep.empty:
            print("\nRepetibilidade entre inicializações (CV_r)\n" + rep.to_string(index=False))
        if not estab.empty:
            resumo = estab.groupby("caso")["classificacao"].agg(
                lambda c: "estável nos indicadores avaliados" if (c == "estável").all()
                else "transiente em pelo menos um indicador" if (c == "transiente").any()
                else "inconclusivo")
            print("\nEstabilidade no trecho final da janela (exploratória)\n" + resumo.to_string())
    return True


def _series_comuns(df, malha, vazao, coluna, janela):
    """Séries das raízes R1–R3 no intervalo comum, interpoladas nos mesmos tempos."""
    series = {}
    for raiz in RAIZES:
        t, v = serie(df, nome_caso(malha, vazao, raiz), coluna)
        dentro = (t >= janela[0]) & (t <= janela[1])       # limites exatos, sem folga
        if dentro.sum() >= 2:
            series[raiz] = (t[dentro], v[dentro])
    if len(series) < 2:
        return None
    inicio = max(t.min() for t, _ in series.values())
    fim = min(t.max() for t, _ in series.values())
    if fim <= inicio:
        return None
    tempos = np.unique(np.concatenate(
        [t[(t >= inicio) & (t <= fim)] for t, _ in series.values()]))
    return tempos, {raiz: np.interp(tempos, t, v) for raiz, (t, v) in series.items()}


def repetibilidade(df, malha, janela, minimo_de_tempos=4) -> pd.DataFrame:
    """CV_r: dispersão entre as médias de R1, R2 e R3 no intervalo comum."""
    linhas = []
    for vazao in VAZOES_MULTIPLICIDADE:
        for coluna in ("h_meio_mm", "Q_meio_L_min", "h_proximo_mm", "Q_proximo_L_min"):
            comum = _series_comuns(df, malha, vazao, coluna, janela)
            if comum is None or len(comum[0]) < minimo_de_tempos:
                continue
            tempos, valores = comum
            medias = np.array([v.mean() for v in valores.values()])
            desvio = float(medias.std(ddof=1)) if len(medias) > 1 else float("nan")
            linhas.append({
                "grupo": f"{malha}_{vazao}", "grandeza": coluna,
                "n_inicializacoes": len(medias), "n_tempos_comuns": len(tempos),
                "inicio_comum_s": tempos[0], "fim_comum_s": tempos[-1],
                "media_das_medias": float(medias.mean()),
                "desvio_entre_inicializacoes": desvio,
                "CVr_pct": abs(desvio / medias.mean()) * 100 if medias.mean() else float("nan"),
            })
    return pd.DataFrame(linhas)


def estabilidade(df, malha, janela, fracao_final=0.30, minimo_de_pontos=6,
                 limite_cv_pct=1.0, limite_deriva_pct=1.0) -> pd.DataFrame:
    """Classifica cada série como estável ou transiente no trecho final da janela.

    Usa os últimos 30 % dos registros (no mínimo 6): CV amostral e deriva da
    reta ajustada, ambos com limite de 1 %. É uma classificação estatística
    exploratória; não comprova regime permanente.
    """
    linhas = []
    for vazao in VAZOES_MULTIPLICIDADE:
        for raiz in RAIZES:
            caso = nome_caso(malha, vazao, raiz)
            for coluna in ("h_meio_mm", "Q_meio_L_min", "h_proximo_mm", "Q_proximo_L_min"):
                t, v = serie(df, caso, coluna)
                dentro = (t >= janela[0]) & (t <= janela[1])
                t, v = t[dentro], v[dentro]
                if len(t) == 0:
                    continue
                base = {"caso": f"{vazao}_R{raiz}", "grandeza": coluna}
                if len(t) < minimo_de_pontos:
                    linhas.append({**base, "n_trecho": len(t), "classificacao": "inconclusivo"})
                    continue
                n = max(minimo_de_pontos, int(np.ceil(len(t) * fracao_final)))
                tt, vv = t[-n:], v[-n:]
                media = float(vv.mean())
                cv = abs(float(vv.std(ddof=1)) / media) * 100 if media else float("inf")
                inclinacao = np.polyfit(tt - tt[0], vv, 1)[0]
                deriva = abs(inclinacao * (tt[-1] - tt[0]) / media) * 100 if media else float("inf")
                estavel = cv <= limite_cv_pct and deriva <= limite_deriva_pct
                linhas.append({**base, "n_trecho": n, "t_inicial_s": tt[0], "t_final_s": tt[-1],
                               "media": media, "cv_pct": cv, "deriva_pct": deriva,
                               "classificacao": "estável" if estavel else "transiente"})
    return pd.DataFrame(linhas)


def figura_evolucao(registros, malha, janela, arquivo: Path):
    """Figura 8: vazão e altura no plano central ao longo do tempo."""
    fig, (ax_q, ax_h) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    for vazao in VAZOES_MULTIPLICIDADE:
        for raiz in RAIZES:
            g = registros[registros["caso_id"] == nome_caso(malha, vazao, raiz)]
            if g.empty:
                continue
            estilo = {"marker": MARCADORES_RAIZ[raiz], "markersize": 5, "markevery": 3,
                      "linewidth": 1.7, "label": f"{vazao} – R{raiz}"}
            ax_q.plot(g["tempo_s"], g["Q_meio_L_min"], **estilo)
            ax_h.plot(g["tempo_s"], g["h_meio_mm"], **estilo)
    ax_q.set_ylabel("Vazão de óleo (L/min)", fontsize=11)
    ax_h.set_ylabel(r"Altura equivalente, $h_L$ (mm)", fontsize=11)
    ax_h.set_xlabel("Tempo (s)", fontsize=11)
    for ax in (ax_q, ax_h):
        ax.set_xlim(*janela)
        ax.tick_params(axis="both", labelsize=9, pad=3)
        ax.grid(True, alpha=0.25, linewidth=0.7)
    handles, labels = ax_q.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.015), ncol=3,
               fontsize=9, frameon=False, handlelength=2, columnspacing=1.8)
    fig.subplots_adjust(left=0.14, right=0.97, top=0.97, bottom=0.20, hspace=0.30)
    fig.savefig(arquivo, dpi=400, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)


def figura_comparacao(comparacao, h_curva, q_curva, arquivo: Path):
    """Curva analítica com as médias do CFD (barras = desvio temporal)."""
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.plot(q_curva * L_MIN, h_curva * 1000.0, color="black", linewidth=2,
            label="Modelo analítico", zorder=2)
    for _, linha in comparacao.iterrows():
        raiz = int(linha["raiz"])
        ax.errorbar(linha["Q_meio_media_L_min"], linha["h_meio_media_mm"],
                    xerr=linha["Q_meio_desvio_L_min"], yerr=linha["h_meio_desvio_mm"],
                    fmt=MARCADORES_RAIZ[raiz], markeredgecolor="black", markeredgewidth=0.7,
                    markersize=9 if raiz != 3 else 12, capsize=4, elinewidth=1.2,
                    label=f"CFD {linha['vazao']} - R{raiz}", zorder=5)
        if np.isfinite(linha["h_analitica_em_Q_meio_mm"]):
            ax.scatter(linha["Q_meio_media_L_min"], linha["h_analitica_em_Q_meio_mm"],
                       marker="x", s=75, linewidths=2, zorder=6)
    for vazao in sorted(set(comparacao["vazao"])):
        q = float(vazao[1:])
        ax.axvline(x=q, linestyle=":", linewidth=1.5, alpha=0.8,
                   label=f"Vazão nominal {vazao}: {q:g} L/min")
    ax.set_xlabel("Vazão volumétrica de óleo no plano central (L/min)")
    ax.set_ylabel("Altura equivalente de líquido $h_L$ (mm)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(arquivo, dpi=300, bbox_inches="tight")
    plt.close(fig)


def figura_repetibilidade(df, malha, vazao, janela, plano, arquivo: Path):
    """Apêndice 9: altura e vazão das três inicializações no intervalo comum."""
    comum_h = _series_comuns(df, malha, vazao, f"h_{plano}_mm", janela)
    comum_q = _series_comuns(df, malha, vazao, f"Q_{plano}_L_min", janela)
    if comum_h is None or comum_q is None:
        return
    fig, axs = plt.subplots(2, 1, figsize=(5.2, 3.8), sharex=True)
    for ax, (tempos, valores) in zip(axs, (comum_h, comum_q)):
        for raiz, v in valores.items():
            ax.plot(tempos, v, marker="o", linewidth=1.6, markersize=4,
                    label=nome_caso(malha, vazao, raiz))
    axs[0].set_ylabel(r"$h_L$ (mm)", fontsize=11)
    axs[1].set_ylabel(r"$Q$ (L/min)", fontsize=11)
    axs[1].set_xlabel("Tempo (s)", fontsize=11)
    inicio, fim = comum_h[0][0], comum_h[0][-1]
    margem = 0.03 * (fim - inicio)
    for ax in axs:
        ax.set_xlim(inicio - margem, fim + margem)
        ax.tick_params(axis="both", labelsize=9, pad=3)
        ax.grid(True, alpha=0.25, linewidth=0.6)
    handles, labels = axs[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=3,
               fontsize=9, frameon=False, handlelength=1.8, columnspacing=1.5)
    fig.subplots_adjust(left=0.17, right=0.97, top=0.97, bottom=0.24, hspace=0.35)
    fig.savefig(arquivo, dpi=400, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Comparação modelo analítico x CFD.")
    ap.add_argument("--dados", type=Path, default=Path("dados_extraidos"))
    ap.add_argument("--saida", type=Path, default=Path("resultados/analitico_cfd"))
    ap.add_argument("--parte", choices=("base", "multiplicidade", "tudo"), default="tudo")
    ap.add_argument("--malha", default=MALHA_REFERENCIA)
    ap.add_argument("--janela", type=float, nargs=2, default=JANELA_MEDIA,
                    metavar=("T0", "T1"), help="janela das médias temporais [s]")
    ap.add_argument("--janela-balanco", type=float, nargs=2, default=JANELA_BALANCO,
                    metavar=("T0", "T1"), help="janela do balanço volumétrico [s]")
    ap.add_argument("--t-ref", type=float, default=T_REFERENCIA,
                    help="instante das Tabelas 4 e 6 [s] (usa o registro mais próximo)")
    ap.add_argument("--plano", choices=("meio", "proximo"), default="meio",
                    help="plano usado nas figuras de repetibilidade (Apêndice 9)")
    args = ap.parse_args()

    df = carregar_series(args.dados)
    feito = False
    if args.parte in ("base", "tudo"):
        feito |= parte_base(df, args, args.saida / "base")
    if args.parte in ("multiplicidade", "tudo"):
        feito |= parte_multiplicidade(df, args, args.saida / "multiplicidade")
    if not feito:
        print("\n[ERRO] Nada foi calculado. Confira dados_extraidos/auditoria/cobertura.csv.")
        return 2
    print(f"\nResultados em: {args.saida.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
