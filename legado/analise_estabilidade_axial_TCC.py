#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analise temporal e repetibilidade dos planos axiais do caso OpenFOAM.
Entrada: CSV consolidado produzido por comparar_planos_axiais.py.
Não altera arquivos/casos OpenFOAM.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

COLUNAS = {
    "tempo": "tempo_s",
    "h_prox": "hL_proximo_mm",
    "h_meio": "hL_meio_mm",
    "q_prox": "Q_proximo_L_min",
    "q_meio": "Q_meio_L_min",
}

def nome_seguro(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s)).strip("_")

def carregar_csv(caminho: Path) -> pd.DataFrame:
    df = pd.read_csv(caminho)
    faltantes = [c for c in COLUNAS.values() if c not in df.columns]
    if faltantes:
        raise ValueError(
            "CSV não contém as colunas necessárias: " + ", ".join(faltantes)
            + "\nColunas encontradas: " + ", ".join(df.columns)
        )
    if "caso" not in df.columns:
        raise ValueError("CSV precisa conter a coluna 'caso'.")
    for c in COLUNAS.values():
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["caso", COLUNAS["tempo"]]).copy()
    return df.sort_values(["caso", COLUNAS["tempo"]]).reset_index(drop=True)

def metricas_estabilidade(t, y, janela_frac=0.30, min_pontos=6,
                          limite_cv_pct=1.0, limite_drift_pct=1.0):
    """Avalia apenas a janela final; não prova convergência física."""
    d = pd.DataFrame({"t": t, "y": y}).dropna().sort_values("t")
    n_total = len(d)
    if n_total < min_pontos:
        return {"n_janela": n_total, "media": np.nan, "desvio": np.nan,
                "cv_pct": np.nan, "drift_pct": np.nan,
                "classificacao": "inconclusivo"}
    n_janela = max(min_pontos, int(np.ceil(n_total * janela_frac)))
    w = d.tail(n_janela)
    tt = w["t"].to_numpy(dtype=float)
    yy = w["y"].to_numpy(dtype=float)
    media = float(np.mean(yy))
    desvio = float(np.std(yy, ddof=1)) if len(yy) > 1 else np.nan
    cv = abs(desvio / media) * 100 if media != 0 else np.inf
    # Variação linear ajustada ao longo da janela, normalizada pela média.
    slope = np.polyfit(tt - tt[0], yy, 1)[0] if len(np.unique(tt)) > 1 else np.nan
    duracao = float(tt[-1] - tt[0])
    drift = abs(slope * duracao / media) * 100 if media != 0 and np.isfinite(slope) else np.inf
    if cv <= limite_cv_pct and drift <= limite_drift_pct:
        classe = "estável"
    elif cv > limite_cv_pct or drift > limite_drift_pct:
        classe = "transiente"
    else:
        classe = "inconclusivo"
    return {"n_janela": n_janela, "media": media, "desvio": desvio,
            "cv_pct": cv, "drift_pct": drift, "classificacao": classe}

def gerar_graficos_casos(df, pasta, janela_frac):
    pasta.mkdir(parents=True, exist_ok=True)
    for caso, g in df.groupby("caso", sort=True):
        g = g.sort_values("tempo_s")
        fig, axs = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
        axs[0].plot(g["tempo_s"], g["hL_proximo_mm"], "o-", label="Plano próximo")
        axs[0].plot(g["tempo_s"], g["hL_meio_mm"], "s-", label="Plano médio")
        axs[0].set_ylabel("Altura equivalente (mm)")
        axs[0].grid(True, alpha=.3); axs[0].legend()
        axs[1].plot(g["tempo_s"], g["Q_proximo_L_min"], "o-", label="Plano próximo")
        axs[1].plot(g["tempo_s"], g["Q_meio_L_min"], "s-", label="Plano médio")
        axs[1].set_xlabel("Tempo (s)"); axs[1].set_ylabel("Vazão (L/min)")
        axs[1].grid(True, alpha=.3); axs[1].legend()
        #fig.suptitle(f"{caso} — evolução temporal")
        fig.tight_layout()
        fig.savefig(pasta / f"{nome_seguro(caso)}_temporal.png", dpi=160)
        plt.close(fig)

        fig, axs = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
        axs[0].plot(g["tempo_s"], g["hL_meio_mm"] - g["hL_proximo_mm"], "o-")
        axs[0].axhline(0, color="black", linewidth=.8)
        axs[0].set_ylabel("Δh = h médio − h próximo (mm)")
        axs[0].grid(True, alpha=.3)
        axs[1].plot(g["tempo_s"], g["Q_meio_L_min"] - g["Q_proximo_L_min"], "o-")
        axs[1].axhline(0, color="black", linewidth=.8)
        axs[1].set_xlabel("Tempo (s)")
        axs[1].set_ylabel("ΔQ = Q médio − Q próximo (L/min)")
        axs[1].grid(True, alpha=.3)
        #fig.suptitle(f"{caso} — diferenças entre planos")
        fig.tight_layout()
        fig.savefig(pasta / f"{nome_seguro(caso)}_diferencas.png", dpi=160)
        plt.close(fig)

def analisar(df, args, saida):
    registros = []
    variaveis = [
        ("hL_proximo_mm", "hL próximo"),
        ("hL_meio_mm", "hL médio"),
        ("Q_proximo_L_min", "Q próximo"),
        ("Q_meio_L_min", "Q médio"),
    ]
    for caso, g in df.groupby("caso", sort=True):
        for col, rotulo in variaveis:
            m = metricas_estabilidade(
                g["tempo_s"], g[col], args.janela_frac, args.min_pontos,
                args.limite_cv_pct, args.limite_drift_pct
            )
            registros.append({
                "caso": caso, "grandeza": rotulo,
                "tempo_inicial_s": g["tempo_s"].min(),
                "tempo_final_s": g["tempo_s"].max(),
                **m
            })
    met = pd.DataFrame(registros)
    # Classificação global conservadora: todos os quatro sinais devem ser estáveis.
    globais = []
    for caso, g in met.groupby("caso", sort=True):
        classes = list(g["classificacao"])
        if all(c == "estável" for c in classes):
            classe = "estável nos indicadores avaliados"
        elif "transiente" in classes:
            classe = "transiente em pelo menos um indicador"
        else:
            classe = "inconclusivo"
        globais.append({"caso": caso, "classificacao_global": classe,
                        "indicadores_estaveis": sum(c == "estável" for c in classes),
                        "indicadores_transientes": sum(c == "transiente" for c in classes),
                        "indicadores_inconclusivos": sum(c == "inconclusivo" for c in classes)})
    global_df = pd.DataFrame(globais)
    met.to_csv(saida / "metricas_estabilidade_por_grandeza.csv", index=False)
    global_df.to_csv(saida / "classificacao_estabilidade_casos.csv", index=False)
    return met, global_df

def analisar_repeticoes(df, saida, min_pontos=4):
    # Agrupa apenas os casos com padrão _R1, _R2, _R3.
    grupos = {}
    for caso in df["caso"].unique():
        m = re.match(r"^(.*)_R([0-9]+)$", str(caso))
        if m:
            grupos.setdefault(m.group(1), []).append((int(m.group(2)), caso))
    resumo = []
    for base, itens in sorted(grupos.items()):
        if len(itens) < 2:
            continue
        sub = {caso: df[df["caso"] == caso].sort_values("tempo_s") for _, caso in itens}
        inicio = max(g["tempo_s"].min() for g in sub.values())
        fim = min(g["tempo_s"].max() for g in sub.values())
        if fim <= inicio:
            continue
        # Interpola todas as repetições em uma malha comum limitada ao intervalo compartilhado.
        tempos = np.unique(np.concatenate([
            g.loc[(g["tempo_s"] >= inicio) & (g["tempo_s"] <= fim), "tempo_s"].to_numpy()
            for g in sub.values()
        ]))
        if len(tempos) < min_pontos:
            continue
        for col in ["hL_proximo_mm", "hL_meio_mm", "Q_proximo_L_min", "Q_meio_L_min"]:
            matriz = []
            for _, caso in itens:
                g = sub[caso]
                matriz.append(np.interp(tempos, g["tempo_s"], g[col]))
            arr = np.asarray(matriz)
            media_rep = np.mean(arr, axis=1)
            media_geral = float(np.mean(media_rep))
            desvio_entre = float(np.std(media_rep, ddof=1)) if len(media_rep) > 1 else np.nan
            cv_entre = abs(desvio_entre / media_geral) * 100 if media_geral else np.nan
            resumo.append({
                "grupo": base, "grandeza": col, "n_repeticoes": len(itens),
                "n_tempos_comuns": len(tempos), "inicio_comum_s": inicio,
                "fim_comum_s": fim, "media_das_medias": media_geral,
                "desvio_entre_repeticoes": desvio_entre,
                "cv_entre_repeticoes_pct": cv_entre
            })
        # Gráfico de repetibilidade no intervalo comum.
        # Todas as repetições são interpoladas na mesma malha temporal
        # usada no cálculo de CV_r, evitando comparar pontos em tempos distintos.

        # Figura compacta para inserção lado a lado no apêndice
        fig, axs = plt.subplots(
            2, 1,
            figsize=(5.2, 3.8),
            sharex=True
        )

        for _, caso in itens:
            g = sub[caso]

            h_interp = np.interp(
                tempos, g["tempo_s"], g["hL_proximo_mm"]
            )
            q_interp = np.interp(
                tempos, g["tempo_s"], g["Q_proximo_L_min"]
            )

            axs[0].plot(
                tempos, h_interp,
                marker="o", linewidth=1.6,
                markersize=4, label=caso
            )

            axs[1].plot(
                tempos, q_interp,
                marker="o", linewidth=1.6,
                markersize=4, label=caso
            )


        # Rótulos dos eixos
        axs[0].set_ylabel(r"$h_L$ (mm)", fontsize=11)
        axs[1].set_ylabel(r"$Q$ (L/min)", fontsize=11)
        axs[1].set_xlabel("Tempo (s)", fontsize=11)

        # Margem visual nas extremidades do eixo temporal
        margem_tempo = 0.03 * (fim - inicio)

        for ax in axs:
            ax.set_xlim(inicio - margem_tempo, fim + margem_tempo)
            ax.tick_params(axis="both", labelsize=9, pad=3)
            ax.grid(True, alpha=0.25, linewidth=0.6)

        # Remove as legendas individuais
        for ax in axs:
            leg = ax.get_legend()
            if leg is not None:
                leg.remove()

        # Uma única legenda compartilhada
        handles, labels = axs[0].get_legend_handles_labels()

        fig.legend(
            handles, labels,
            loc="lower center",
            bbox_to_anchor=(0.5, 0.015),
            ncol=3,
            fontsize=9,
            frameon=False,
            handlelength=1.8,
            columnspacing=1.5
        )

        # Espaçamento entre os painéis e a legenda
        fig.subplots_adjust(
            left=0.17,
            right=0.97,
            top=0.97,
            bottom=0.20,
            hspace=0.35
        )

        fig.savefig(
            saida / f"repetibilidade_{nome_seguro(base)}.png",
            dpi=400,
            bbox_inches="tight",
            pad_inches=0.06
        )

        plt.close(fig)

    rep = pd.DataFrame(resumo)
    rep.to_csv(saida / "repetibilidade_intervalo_comum.csv", index=False)
    return rep

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", type=Path, help="CSV consolidado de comparar_planos_axiais.py")
    ap.add_argument("--saida", type=Path, default=Path("analise_estabilidade"))
    ap.add_argument("--inicio", type=float, default=None, help="Início opcional do intervalo (s)")
    ap.add_argument("--fim", type=float, default=None, help="Fim opcional do intervalo (s)")
    ap.add_argument("--janela-frac", type=float, default=0.30, help="Fração final usada na avaliação (padrão: 0.30)")
    ap.add_argument("--min-pontos", type=int, default=6)
    ap.add_argument("--limite-cv-pct", type=float, default=1.0)
    ap.add_argument("--limite-drift-pct", type=float, default=1.0)
    args = ap.parse_args()

    df = carregar_csv(args.csv)
    if args.inicio is not None:
        df = df[df["tempo_s"] >= args.inicio]
    if args.fim is not None:
        df = df[df["tempo_s"] <= args.fim]
    if df.empty:
        raise SystemExit("Nenhum dado permaneceu após o filtro temporal.")
    args.saida.mkdir(parents=True, exist_ok=True)
    gerar_graficos_casos(df, args.saida / "graficos_casos", args.janela_frac)
    met, glob = analisar(df, args, args.saida)
    rep = analisar_repeticoes(df, args.saida)

    print(f"Casos analisados: {df['caso'].nunique()}")
    print(f"Linhas analisadas: {len(df)}")
    print("\nClassificação global:")
    print(glob.to_string(index=False))
    print("\nRepetibilidade:")
    if rep.empty:
        print("Não foram encontrados grupos de repetição com intervalo comum suficiente.")
    else:
        print(rep.to_string(index=False))
    print(f"\nArquivos gerados em: {args.saida.resolve()}")
    print("ATENÇÃO: classificação estatística exploratória; não comprova convergência física.")

if __name__ == "__main__":
    main()
