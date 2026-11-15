#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""02 — Convergência de malha (GCI) para Q10, Q35 e Q60 nas malhas M0, M1 e M2.

Lê ``dados_extraidos/series_temporais.csv`` (gerado pelo script 01) e grava em
``resultados/gci/``:

    tabela_gci.csv               resumo no formato das Tabelas 2, 3, A.1 e B.1
    relatorio_gci_completo.csv   todos os indicadores (R, p, GCI, CV, deriva...)
    medias_por_malha.csv         média temporal de cada grandeza em cada malha
    taxas_de_variacao.csv        taxa de variação no intervalo final (Tabela C.1)
    figuras/Q10_atrito_total.png ... históricos temporais (Figura C.1)

Método (igual ao do TCC):
  * média temporal trapezoidal na janela (padrão 3 a 6 s);
  * GCI de Celik et al. (2008), Fs = 1,25, três malhas;
  * GCI só é reportado para convergência monotônica com p >= 0,5.

Uso:
    python 02_analise_gci.py
    python 02_analise_gci.py --janela 4 5 --saida resultados/gci_4a5s
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from duto_anular.casos import (JANELA_BALANCO, JANELA_MEDIA, MALHAS, N_CELULAS,
                               VAZOES_BASE, nome_caso)
from duto_anular.dados import carregar_casos, carregar_series, salvar_csv, serie
from duto_anular.estatistica import (calcular_gci, media_na_janela,
                                     taxa_de_variacao)
from duto_anular.funcoes_openfoam import AREA_MOLHADA_MINIMA_M2

# Diferença M1->M2 menor que este múltiplo do CV temporal é sinalizada.
FATOR_RUIDO = 2.0

# (rótulo, coluna de series_temporais.csv, coluna de área para testar parede seca)
GRANDEZAS = (
    ("Atrito interno (N)", "integral_tau_ponderada_interna_N", "area_ponderada_oleo_interna_m2"),
    ("Atrito externo (N)", "integral_tau_ponderada_externa_N", "area_ponderada_oleo_externa_m2"),
    ("Atrito total (N)", "integral_tau_ponderada_total_N", None),
    ("Área ponderada (m2)", "area_ponderada_oleo_total_m2", None),
    ("Vazão central (L/min)", "Q_meio_L_min", None),
    ("Velocidade média (m/s)", "V_meio_m_s", None),
    ("Volume de óleo (m3)", "volume_oleo_m3", None),
)

# Históricos temporais (Figura C.1): coluna, nome do arquivo, rótulo do eixo.
HISTORICOS = (
    ("tau_media_global_Pa", "atrito_total", "Tensão de cisalhamento (Pa)"),
    ("V_meio_m_s", "velocidade", "Velocidade axial (m/s)"),
    ("volume_oleo_m3", "volume_oleo", "Volume de óleo (m³)"),
)
# Grandezas da tabela de taxas de variação (Tabela C.1).
TAXAS = (
    ("Tensão média na parede (Pa)", "tau_media_global_Pa"),
    ("Volume de óleo (m3)", "volume_oleo_m3"),
    ("Altura central (mm)", "h_meio_mm"),
    ("Vazão central (L/min)", "Q_meio_L_min"),
)


def celulas_por_malha(casos: pd.DataFrame) -> dict:
    """Número de células de cada malha (lido dos casos; senão, valor padrão)."""
    n = dict(N_CELULAS)
    if "n_celulas" in casos.columns:
        for malha, grupo in casos.dropna(subset=["n_celulas"]).groupby("malha"):
            valores = set(grupo["n_celulas"].astype(int))
            if len(valores) == 1:
                n[malha] = valores.pop()
    return n


def analisar(df, n_celulas, janela):
    relatorio, medias = [], []
    for vazao in VAZOES_BASE:
        print(f"\n{'=' * 20} {vazao} {'=' * 20}")
        for rotulo, coluna, coluna_area in GRANDEZAS:
            est = {m: media_na_janela(*serie(df, nome_caso(m, vazao), coluna), janela)
                   for m in MALHAS}
            for m in MALHAS:
                if est[m]:
                    medias.append({"caso": vazao, "malha": m, "grandeza": rotulo,
                                   "coluna": coluna,
                                   "janela_s": f"{est[m]['t_inicial']:.4g}-{est[m]['t_final']:.4g}",
                                   **{k: est[m][k] for k in ("media", "n", "cv_pct", "deriva_pct")}})

            base = {"caso": vazao, "grandeza": rotulo, "coluna": coluna,
                    "janela_s": f"{janela[0]:g}-{janela[1]:g}"}

            # Parede praticamente seca: a força individual não tem significado.
            if coluna_area:
                secas = []
                for m in MALHAS:
                    area = media_na_janela(*serie(df, nome_caso(m, vazao), coluna_area), janela)
                    if area and area["media"] < AREA_MOLHADA_MINIMA_M2:
                        secas.append(m)
                if secas:
                    print(f"  {rotulo}: parede praticamente seca em {', '.join(secas)}")
                    relatorio.append({**base, "diagnostico": "Parede praticamente seca",
                                      "status": "Não aplicável: parede seca em " + ", ".join(secas)})
                    continue

            faltam = [m for m in MALHAS if est[m] is None]
            if faltam:
                print(f"  {rotulo}: SEM DADOS na janela para {', '.join(faltam)}")
                relatorio.append({**base, "diagnostico": "Sem dados",
                                  "status": "Sem cobertura da janela em " + ", ".join(faltam)})
                continue

            phi = {m: est[m]["media"] for m in MALHAS}
            res = calcular_gci(phi["M2"], phi["M1"], phi["M0"],
                               n_celulas["M2"], n_celulas["M1"], n_celulas["M0"])
            cv_max = max(est[m]["cv_pct"] for m in MALHAS)
            if (math.isfinite(res["ea21_pct"]) and math.isfinite(cv_max)
                    and res["ea21_pct"] < FATOR_RUIDO * cv_max):
                res["status"] += " | diferença M1→M2 comparável ao CV temporal (heurístico)"

            relatorio.append({
                **base,
                "media_M0": phi["M0"], "media_M1": phi["M1"], "media_M2": phi["M2"],
                **res,
                **{f"n_{m}": est[m]["n"] for m in MALHAS},
                **{f"cv_{m}_pct": est[m]["cv_pct"] for m in MALHAS},
                "cv_max_pct": cv_max,
                **{f"deriva_{m}_pct": est[m]["deriva_pct"] for m in MALHAS},
                "deriva_max_pct": max(est[m]["deriva_pct"] for m in MALHAS),
            })
            p = f"{res['p']:.3f}" if res["p"] is not None else "—"
            gci = f"{res['GCI21_pct']:.3f}%" if res["gci_reportado"] else "—"
            print(f"  {rotulo:<24} M0={phi['M0']:.6g}  M1={phi['M1']:.6g}  M2={phi['M2']:.6g}"
                  f"  | p={p}  M1–M2={res['ea21_pct']:.3f}%  GCI21={gci}  {res['diagnostico']}")
    return pd.DataFrame(relatorio), pd.DataFrame(medias)


def tabela_resumo(relatorio: pd.DataFrame) -> pd.DataFrame:
    """Formato das tabelas do TCC: p, diferença M1–M2, GCI21, GCI32, diagnóstico."""
    colunas = {"caso": "Caso", "grandeza": "Grandeza", "p": "Ordem p",
               "ea21_pct": "Diferença M1–M2 (%)", "GCI21_pct": "GCI21 (%)",
               "GCI32_pct": "GCI32 (%)", "diagnostico": "Diagnóstico"}
    relatorio = relatorio.copy()
    for c in colunas:
        if c not in relatorio.columns:
            relatorio[c] = float("nan")
    tabela = relatorio[list(colunas)].rename(columns=colunas).copy()
    for c in ("Ordem p", "Diferença M1–M2 (%)", "GCI21 (%)", "GCI32 (%)"):
        tabela[c] = pd.to_numeric(tabela[c], errors="coerce").round(3)
    return tabela


def taxas(df, janela):
    linhas = []
    for vazao in VAZOES_BASE:
        for m in MALHAS:
            for rotulo, coluna in TAXAS:
                r = taxa_de_variacao(*serie(df, nome_caso(m, vazao), coluna), janela)
                if r:
                    linhas.append({"caso": vazao, "malha": m, "grandeza": rotulo,
                                   "t_inicial_s": r["t_inicial"], "t_final_s": r["t_final"],
                                   "n": r["n"], "media": r["media"],
                                   "taxa_por_s": r["taxa"],
                                   "taxa_pct_por_s": r["taxa_pct_por_s"]})
    return pd.DataFrame(linhas)


def graficos(df, pasta: Path, t_final=6.05):
    pasta.mkdir(parents=True, exist_ok=True)
    feitos = 0
    for vazao in VAZOES_BASE:
        for coluna, arquivo, _ in HISTORICOS:
            fig, ax = plt.subplots(figsize=(6.0, 4.0))
            tem_dados = False
            for m in MALHAS:
                t, v = serie(df, nome_caso(m, vazao), coluna)
                ok = t <= t_final
                if ok.any():
                    ax.plot(t[ok], v[ok], marker="o", markersize=3.0, linewidth=1.7, label=m)
                    tem_dados = True
            if tem_dados:
                ax.set_xlim(left=0, right=t_final)
                ax.tick_params(axis="both", labelsize=9, pad=2)
                ax.grid(True, alpha=0.28, linewidth=0.6)
                ax.legend(fontsize=8, loc="best", frameon=True, framealpha=0.85,
                          borderpad=0.25, labelspacing=0.2, handlelength=1.5,
                          handletextpad=0.4)
                fig.subplots_adjust(left=0.13, right=0.985, bottom=0.11, top=0.985)
                fig.savefig(pasta / f"{vazao}_{arquivo}.png", dpi=300,
                            bbox_inches="tight", pad_inches=0.03)
                feitos += 1
            plt.close(fig)
    return feitos


def main() -> int:
    ap = argparse.ArgumentParser(description="GCI das malhas M0, M1 e M2 (Celik et al., 2008).")
    ap.add_argument("--dados", type=Path, default=Path("dados_extraidos"))
    ap.add_argument("--saida", type=Path, default=Path("resultados/gci"))
    ap.add_argument("--janela", type=float, nargs=2, default=JANELA_MEDIA,
                    metavar=("T0", "T1"), help="janela das médias temporais [s]")
    ap.add_argument("--janela-taxas", type=float, nargs=2, default=JANELA_BALANCO,
                    metavar=("T0", "T1"), help="janela das taxas de variação [s]")
    ap.add_argument("--sem-graficos", action="store_true")
    args = ap.parse_args()
    janela = tuple(args.janela)

    df = carregar_series(args.dados)
    n_celulas = celulas_por_malha(carregar_casos(args.dados))
    print(f"GCI — janela {janela[0]:g} a {janela[1]:g} s | células: "
          + ", ".join(f"{m}={n_celulas[m]:,}".replace(",", ".") for m in MALHAS))

    relatorio, medias = analisar(df, n_celulas, janela)
    if relatorio.empty or "media_M1" not in relatorio.columns:
        print("\n[ERRO] Nenhuma grandeza com as três malhas na janela. "
              "Confira dados_extraidos/auditoria/cobertura.csv.")
        return 2

    salvar_csv(tabela_resumo(relatorio), args.saida / "tabela_gci.csv")
    salvar_csv(relatorio, args.saida / "relatorio_gci_completo.csv")
    salvar_csv(medias, args.saida / "medias_por_malha.csv")
    salvar_csv(taxas(df, tuple(args.janela_taxas)), args.saida / "taxas_de_variacao.csv")
    n_fig = 0 if args.sem_graficos else graficos(df, args.saida / "figuras")

    print("\n" + tabela_resumo(relatorio).to_string(index=False, na_rep="—"))
    print(f"\nResultados em: {args.saida.resolve()}  ({n_fig} figuras)")
    print("O GCI só é reportado para convergência monotônica com p >= 0,5; "
          "nos demais casos use a diferença M1–M2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
