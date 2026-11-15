"""Leitura dos dados gerados por ``01_extrair_dados.py`` e funções de apoio."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .casos import G, RHO_OLEO
from .modelo_anular import D_I, D_O, MU, geometria

ARQUIVO_SERIES = "series_temporais.csv"
ARQUIVO_CASOS = "casos.csv"


def carregar_series(pasta_dados: Path) -> pd.DataFrame:
    """Tabela principal: uma linha por caso e por tempo."""
    arquivo = Path(pasta_dados) / ARQUIVO_SERIES
    if not arquivo.is_file():
        sys.exit(f"[ERRO] Não achei {arquivo}.\n"
                 f"       Rode antes:  python 01_extrair_dados.py --raiz <pasta dos casos>")
    df = pd.read_csv(arquivo, dtype={"caso_id": str, "raiz": str})
    df["raiz"] = df["raiz"].fillna("")
    return df.sort_values(["caso_id", "tempo_s"]).reset_index(drop=True)


def carregar_casos(pasta_dados: Path) -> pd.DataFrame:
    arquivo = Path(pasta_dados) / ARQUIVO_CASOS
    if not arquivo.is_file():
        return pd.DataFrame(columns=["caso_id"])
    return pd.read_csv(arquivo, dtype={"caso_id": str})


def serie(df: pd.DataFrame, caso_id: str, coluna: str):
    """Tempos e valores de uma coluna para um caso (sem linhas vazias)."""
    if coluna not in df.columns:
        return np.array([]), np.array([])
    sub = df.loc[df["caso_id"] == caso_id, ["tempo_s", coluna]].dropna()
    return sub["tempo_s"].to_numpy(dtype=float), sub[coluna].to_numpy(dtype=float)


def valor_no_tempo(tempos, valores, t_alvo: float):
    """Registro mais próximo de ``t_alvo``. Devolve (tempo, valor)."""
    if len(tempos) == 0:
        return float("nan"), float("nan")
    i = int(np.argmin(np.abs(np.asarray(tempos) - t_alvo)))
    return float(tempos[i]), float(valores[i])


# ---------------------------------------------------------------------------
# Geometria da seção anular parcialmente cheia
# ---------------------------------------------------------------------------
def altura_por_area(area_m2: float) -> float:
    """Altura equivalente h_L [mm] que dá a área de óleo informada [m²].

    Inverte A_L(h_L) do modelo analítico (mesma geometria do modelo).
    """
    if area_m2 is None or not np.isfinite(area_m2):
        return float("nan")
    if area_m2 <= 0.0:
        return 0.0
    if area_m2 >= geometria(D_O, D_O, D_I)[0]:
        return D_O * 1000.0
    try:
        h = brentq(lambda x: geometria(x, D_O, D_I)[0] - area_m2,
                   0.0, D_O, xtol=1e-12, rtol=1e-12)
    except ValueError:
        return float("nan")
    return h * 1000.0


def largura_superficie_livre(h_mm: float) -> float:
    """Largura T da superfície livre [m] para a altura h_L [mm]."""
    if not np.isfinite(h_mm):
        return float("nan")
    z = h_mm / 1000.0 - D_O / 2.0            # cota da interface em relação ao eixo
    externa = 2.0 * np.sqrt(max((D_O / 2.0) ** 2 - z ** 2, 0.0))
    interna = 2.0 * np.sqrt(max((D_I / 2.0) ** 2 - z ** 2, 0.0))
    return externa - interna


def reynolds_froude(h_mm: float, velocidade: float):
    """Re = rho V D_h / mu  e  Fr = V / sqrt(g A_L / T) para a altura h_L."""
    if not (np.isfinite(h_mm) and np.isfinite(velocidade)) or h_mm <= 0:
        return float("nan"), float("nan")
    area, _, d_h = geometria(h_mm / 1000.0)
    largura = largura_superficie_livre(h_mm)
    reynolds = RHO_OLEO * abs(velocidade) * d_h / MU
    froude = (abs(velocidade) / np.sqrt(G * area / largura)
              if largura > 0 and area > 0 else float("nan"))
    return float(reynolds), float(froude)


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------
def salvar_csv(df: pd.DataFrame, caminho: Path) -> Path:
    """Grava o CSV. Tabela sem nenhuma coluna não gera arquivo (e apaga o antigo)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if len(df.columns) == 0:
        caminho.unlink(missing_ok=True)
        return caminho
    df.to_csv(caminho, index=False, float_format="%.10g", encoding="utf-8")
    return caminho
