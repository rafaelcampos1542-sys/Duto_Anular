#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Procura automaticamente casos OpenFOAM abaixo da pasta raiz e compara os planos.

Coloque este arquivo na raiz do projeto (junto de modelo_anular.py) e execute:
    python comparar_planos_axiais.py

Cada caso encontrado deve conter postProcessing/<functionObject>/.../*.dat
para areaOleoProximo, areaOleoMeio, QOleoProximo e QOleoMeio.
Gera CSV e PNG dentro de cada caso, além de um resumo consolidado na raiz.
"""
from pathlib import Path
import argparse
import re

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import brentq

try:
    from modelo_anular import geometria, D_O, D_I
except ImportError as exc:
    raise SystemExit("Deixe comparar_planos_axiais.py na mesma pasta de modelo_anular.py.") from exc

OBJETOS = {
    "A_proximo": "areaOleoProximo",
    "A_meio": "areaOleoMeio",
    "Q_proximo": "QOleoProximo",
    "Q_meio": "QOleoMeio",
}
EXCLUIR_PASTAS = {".git", ".venv", "venv", "__pycache__", "processor0"}


def hL_por_area(area_m2):
    if not np.isfinite(area_m2):
        return np.nan
    if area_m2 <= 0:
        return 0.0
    area_max = geometria(D_O, D_O, D_I)[0]
    if area_m2 >= area_max:
        return D_O * 1000.0
    try:
        h = brentq(lambda x: geometria(x, D_O, D_I)[0] - area_m2,
                   0.0, D_O, xtol=1e-12, rtol=1e-12)
        return h * 1000.0
    except ValueError:
        return np.nan


def ler_dat(caso, nome, componente=None):
    """
    Lê todos os arquivos surfaceFieldValue*.dat de um functionObject.

    componente=None: lê valores escalares, como areaIntegrate.
    componente=0, 1 ou 2: lê componentes de vetores, como U.

    Consolida todos os tempos e ignora arquivos vazios.
    """

    base = caso / "postProcessing" / nome

    arquivos = (
        sorted(base.rglob("surfaceFieldValue*.dat"))
        if base.exists() else []
    )

    registros = {}

    # Número inteiro, decimal ou notação científica
    padrao_numero = (
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    )

    for arquivo in arquivos:

        if not arquivo.is_file() or arquivo.stat().st_size == 0:
            continue

        with arquivo.open(errors="ignore") as f:

            for linha in f:

                linha = linha.strip()

                if not linha or linha.startswith("#"):
                    continue

                partes = linha.split(maxsplit=1)

                if len(partes) != 2:
                    continue

                try:
                    tempo = float(partes[0])
                except ValueError:
                    continue

                nums = re.findall(padrao_numero, partes[1])

                if componente is None:
                    if len(nums) < 1:
                        continue
                    valor = float(nums[0])

                else:
                    if len(nums) <= componente:
                        continue
                    valor = float(nums[componente])

                # Consolidação por tempo.
                # Arquivos vazios não interferem nos resultados.
                registros[tempo] = valor

    if not registros:
        return pd.DataFrame(columns=["time", nome])

    df = pd.DataFrame(
        [(t, v) for t, v in registros.items()],
        columns=["time", nome]
    )

    return df.sort_values("time").reset_index(drop=True)

def descobrir_casos(raiz, incluir_backups=False):
    casos = []
    for pasta in raiz.rglob("postProcessing"):
        if not pasta.is_dir():
            continue
        relativo = pasta.relative_to(raiz)
        partes = relativo.parts[:-1]
        if any(p in EXCLUIR_PASTAS or p.lower().startswith("processor") for p in partes):
            continue
        if not incluir_backups and any(any(x in p.lower() for x in ("backup", "archive", "arquiv")) for p in partes):
            continue
        caso = pasta.parent
        if all((pasta / nome).exists() for nome in OBJETOS.values()):
            casos.append(caso)
    return sorted(set(casos))


def combinar(series, tolerancia):
    base = series["A_proximo"]

    if base.empty:
        raise RuntimeError("areaOleoProximo não contém dados")

    # Renomeia a coluna original para o nome padronizado de saída
    out = base.rename(columns={
        "time": "tempo_s",
        OBJETOS["A_proximo"]: "A_oleo_proximo_m2"
    }).copy()

    mapa = {
        "A_meio": "A_oleo_meio_m2",
        "Q_proximo": "Uy_proximo_m3_s",
        "Q_meio": "Uy_meio_m3_s"
    }

    for chave, coluna_saida in mapa.items():
        df = series[chave].sort_values("time").reset_index(drop=True)

        valores = []
        deltas = []
        tempos_usados = set()

        for t in out["tempo_s"]:
            if df.empty:
                valores.append(np.nan)
                deltas.append(np.nan)
                continue

            diferencas = np.abs(df["time"].to_numpy() - t)
            idx = int(np.argmin(diferencas))

            dt = float(df.iloc[idx]["time"] - t)

            if abs(dt) <= tolerancia and idx not in tempos_usados:
                # A segunda coluna contém o valor lido do arquivo .dat
                valores.append(float(df.iloc[idx, 1]))
                deltas.append(dt)
                tempos_usados.add(idx)
            else:
                valores.append(np.nan)
                deltas.append(np.nan)

        out[coluna_saida] = valores
        out[f"delta_t_{chave}_s"] = deltas

    return out


def processar(caso, args):
    series = {
        "A_proximo": ler_dat(caso, OBJETOS["A_proximo"]),
        "A_meio": ler_dat(caso, OBJETOS["A_meio"]),
        "Q_proximo": ler_dat(caso, OBJETOS["Q_proximo"], 1),
        "Q_meio": ler_dat(caso, OBJETOS["Q_meio"], 1),
    }
    df = combinar(series, args.tolerancia)
    if args.inicio is not None: df = df[df.tempo_s >= args.inicio]
    if args.fim is not None: df = df[df.tempo_s <= args.fim]
    if df.empty: raise RuntimeError("nenhum ponto no intervalo selecionado")
    df["hL_proximo_mm"] = df.A_oleo_proximo_m2.map(hL_por_area)
    df["hL_meio_mm"] = df.A_oleo_meio_m2.map(hL_por_area)
    df["Q_proximo_L_min"] = df.Uy_proximo_m3_s * 60000
    df["Q_meio_L_min"] = df.Uy_meio_m3_s * 60000
    df["delta_h_meio_menos_proximo_mm"] = df.hL_meio_mm - df.hL_proximo_mm
    df["delta_Q_meio_menos_proximo_L_min"] = df.Q_meio_L_min - df.Q_proximo_L_min
    df.insert(0, "caso", str(caso.relative_to(args.raiz)))

    prefixo = caso / args.prefixo
    df.to_csv(prefixo.with_suffix(".csv"), index=False, float_format="%.10g")
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(df.tempo_s, df.hL_proximo_mm, label="Próximo (Y=-0,15 m)")
    axes[0].plot(df.tempo_s, df.hL_meio_mm, label="Meio (Y=0)")
    axes[0].set_ylabel("Altura equivalente [mm]"); axes[0].grid(True, alpha=.3); axes[0].legend()
    axes[1].plot(df.tempo_s, df.Q_proximo_L_min, label="Próximo")
    axes[1].plot(df.tempo_s, df.Q_meio_L_min, label="Meio")
    axes[1].set_xlabel("Tempo [s]"); axes[1].set_ylabel("Uy integrado [L/min]")
    axes[1].grid(True, alpha=.3); axes[1].legend()
    fig.suptitle(str(caso.relative_to(args.raiz))); fig.tight_layout()
    fig.savefig(prefixo.with_suffix(".png"), dpi=180); plt.close(fig)

    resumo = {"caso": str(caso.relative_to(args.raiz)), "n_pontos": len(df),
              "tempo_inicial_s": df.tempo_s.min(), "tempo_final_s": df.tempo_s.max()}
    for c in ["hL_proximo_mm", "hL_meio_mm", "Q_proximo_L_min", "Q_meio_L_min"]:
        resumo[f"{c}_media"] = df[c].mean()
        resumo[f"{c}_desvio"] = df[c].std()
    print(f"[OK] {resumo['caso']}: {len(df)} pontos")
    return df, resumo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz", type=Path, default=Path(__file__).resolve().parent,
                        help="Raiz onde procurar os casos (padrão: pasta do script).")
    parser.add_argument("--tolerancia", type=float, default=1e-4)
    parser.add_argument("--inicio", type=float, default=None)
    parser.add_argument("--fim", type=float, default=None)
    parser.add_argument("--prefixo", default="comparacao_planos_axiais")
    parser.add_argument("--incluir-backups", action="store_true",
                        help="Também procura dentro de pastas de backup/arquivo.")
    args = parser.parse_args()
    args.raiz = args.raiz.resolve()
    casos = descobrir_casos(args.raiz, args.incluir_backups)
    if not casos:
        raise SystemExit(f"Nenhum caso encontrado em {args.raiz}. Confira se cada caso possui postProcessing e os quatro objetos esperados.")
    print(f"Raiz: {args.raiz}\nCasos encontrados: {len(casos)}")
    resumos, tabelas = [], []
    for caso in casos:
        try:
            df, resumo = processar(caso, args)
            tabelas.append(df); resumos.append(resumo)
        except Exception as exc:
            print(f"[ERRO] {caso.relative_to(args.raiz)}: {exc}")
    if resumos:
        pd.DataFrame(resumos).to_csv(args.raiz / "resumo_comparacao_planos.csv", index=False)
        pd.concat(tabelas, ignore_index=True).to_csv(args.raiz / "todos_casos_comparacao_planos.csv", index=False)
        print(f"\nConcluído: {len(resumos)}/{len(casos)} casos processados.")
        print(f"Resumo: {args.raiz / 'resumo_comparacao_planos.csv'}")
        print(f"Dados consolidados: {args.raiz / 'todos_casos_comparacao_planos.csv'}")
    else:
        raise SystemExit("Nenhum caso foi processado com sucesso.")
    print("Alturas são equivalentes geométricas; vazões mantêm o sinal de Uy.")

if __name__ == "__main__":
    main()
