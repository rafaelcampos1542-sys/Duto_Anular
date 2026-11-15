#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analise.py
Pós-processamento, diagnóstico VOF e comparação analítico x CFD.

Consolida:
  - analisar_resultados.py
  - compare_analytic.sh
  - debug_perfil_meio.py
  - diagnostico_vof_perfil_meio.py
  - diagnostico_vof_perfil_meio_v2.py

Uso:
  python3 analise.py resultados
  python3 analise.py diagnostico
  python3 analise.py comparar
  python3 analise.py tudo
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import subprocess
import shutil
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scipy.optimize import brentq

from modelo_anular import gerar_curva, encontrar_raizes_Q, geometria, calcular_V_Q, D_O, D_I


R_OUT = 0.0575
ALPHA_COL = "alpha.oil"


# ---------------------------------------------------------------------------
# UTILITÁRIOS
# ---------------------------------------------------------------------------
def perimetro_molhado_cfd(h_mm):
    if not np.isfinite(h_mm):
        return np.nan

    h = h_mm / 1000.0

    _, S_L, _ = geometria(h)

    return S_L

def get_time_dirs():
    dirs = []
    for d in os.listdir("."):
        if os.path.isdir(d) and re.match(r"^\d+(\.\d+)?$", d):
            if d not in {"0", "0.orig"}:
                try:
                    dirs.append((float(d), d))
                except ValueError:
                    pass
    dirs.sort(key=lambda x: x[0])
    return [d[1] for d in dirs]


def find_latest_time_from_sampling():
    sampling_dir = Path("postProcessing/sampling")
    if not sampling_dir.is_dir():
        raise FileNotFoundError(f"Diretório não encontrado: {sampling_dir}")

    times = []
    for d in sampling_dir.iterdir():
        try:
            times.append((float(d.name), d.name))
        except ValueError:
            continue

    if not times:
        raise FileNotFoundError("Nenhum tempo em postProcessing/sampling.")

    return max(times)[1]


def run_postprocess():
    """Executa os functionObjects configurados no ``controlDict``.

    Não usamos ``-latestTime`` aqui: a análise temporal precisa reconstruir
    também os functionObjects dos tempos já gravados. Isso é especialmente
    importante para QOleoInlet/QOleoOutlet e areaOleo*, que alimentam
    ``resultados_hL.csv``.
    """
    cmds = [
        [
            "postProcess",
            "-fields", "(U alpha.oil phi)"
        ],
        ["postProcess"],
    ]

    for cmd in cmds:
        try:
            subprocess.run(cmd, check=True)
            print(f"[OK] FunctionObjects: {' '.join(cmd)}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    print("[AVISO] Não foi possível executar os functionObjects automaticamente.")
    return False

def find_postprocessing_base(t_dir: str):
    candidates = ["sampling", "sample", "sets"]
    for name in candidates:
        path = Path("postProcessing") / name / t_dir
        if path.is_dir():
            return path

    pp = Path("postProcessing")
    if pp.exists():
        for root, dirs, _ in os.walk(pp):
            if t_dir in dirs:
                return Path(root) / t_dir

    return Path("postProcessing/sampling") / t_dir


def find_profile_csv(base_dir: Path, prefix: str):
    if not base_dir.exists():
        return None
    matches = sorted(base_dir.glob(f"{prefix}*.csv"))
    if not matches:
        return None

    exact = base_dir / f"{prefix}.csv"
    return exact if exact in matches else matches[0]


def read_csv_data(path):
    try:
        import pandas as pd
        return pd.read_csv(path)
    except ImportError:
        with open(path, newline="") as f:
            reader = csv.reader(f)
            headers = [x.strip() for x in next(reader)]
            rows = list(reader)

        data = {h: [] for h in headers}
        for row in rows:
            if len(row) != len(headers):
                continue
            for i, value in enumerate(row):
                try:
                    data[headers[i]].append(float(value))
                except ValueError:
                    data[headers[i]].append(value)

        class Fallback:
            def __init__(self, d):
                self.d = d
                self.columns = list(d)

            def __getitem__(self, key):
                return np.array(self.d[key])

        return Fallback(data)


def extract_profile_arrays(csv_path):
    if not csv_path or not Path(csv_path).exists():
        return None, None, None

    df = read_csv_data(csv_path)
    cols = list(df.columns)
    lower = [str(c).lower() for c in cols]

    alpha_idx = next(
        (i for i, c in enumerate(lower) if "alpha" in c and "oil" in c),
        None,
    )
    if alpha_idx is None:
        alpha_idx = next(
            (i for i, c in enumerate(lower) if "alpha" in c),
            None,
        )
    if alpha_idx is None:
        return None, None, None

    coord_candidates = ["distance", "z", "y", "x", "coordz", "points:2"]
    coord_idx = None
    for candidate in coord_candidates:
        for i, c in enumerate(lower):
            if candidate in c and i != alpha_idx:
                coord_idx = i
                break
        if coord_idx is not None:
            break

    if coord_idx is None:
        coord_idx = next(
            (i for i in range(len(cols)) if i != alpha_idx),
            None,
        )

    if coord_idx is None:
        return None, None, None

    alpha = np.asarray(df[cols[alpha_idx]], dtype=float)
    coord = np.asarray(df[cols[coord_idx]], dtype=float)

    valid = np.isfinite(alpha) & np.isfinite(coord)
    coord = coord[valid]
    alpha = alpha[valid]

    idx = np.argsort(coord)
    return coord[idx], alpha[idx], str(cols[coord_idx])


def extract_hL_from_csv(csv_path):
    coord, alpha, coord_name = extract_profile_arrays(csv_path)
    if coord is None or len(coord) < 2:
        return np.nan

    for i in range(len(alpha) - 1):
        a0, a1 = alpha[i], alpha[i + 1]
        if (a0 - 0.5) * (a1 - 0.5) <= 0 and abs(a1 - a0) > 1e-12:
            t = (0.5 - a0) / (a1 - a0)
            z = coord[i] + t * (coord[i + 1] - coord[i])
            if "distance" in coord_name.lower():
                h = z
            else:
                h = z + R_OUT
            return h * 1000.0

    return np.nan

def read_area_integrate(path):
    """Lê surfaceFieldValue/areaIntegrate: tempo [s] e área [m²]."""
    if not path or not Path(path).exists():
        return np.array([]), np.array([])

    times = []
    areas = []
    with open(path, errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"\s+", line)
            if len(parts) < 2:
                continue
            try:
                times.append(float(parts[0]))
                areas.append(float(parts[1]))
            except ValueError:
                continue
    return np.asarray(times), np.asarray(areas)


def encontrar_arquivo_area(nome):
    """
    Procura o arquivo de resultado do surfaceFieldValue.

    No OpenFOAM v2312, quando o arquivo principal está vazio,
    os dados podem estar em surfaceFieldValue_0.dat.
    """

    base = Path("postProcessing") / nome

    if not base.exists():
        return None

    arquivos = list(base.rglob("surfaceFieldValue*.dat"))

    if not arquivos:
        return None

    # Primeiro procura o arquivo principal que realmente tenha dados.
    for p in arquivos:
        try:
            if p.stat().st_size == 0:
                continue

            with open(p, errors="ignore") as f:
                for line in f:
                    line = line.strip()

                    if not line or line.startswith("#"):
                        continue

                    parts = re.split(r"\s+", line)

                    if len(parts) >= 2:
                        try:
                            float(parts[0])
                            float(parts[1])
                            return p
                        except ValueError:
                            continue

        except OSError:
            continue

    return None

def carregar_serie_area(tipo):
    """Carrega uma série inteira de areaIntegrate uma única vez."""
    arquivo = encontrar_arquivo_area(tipo)
    if arquivo is None:
        print(f"[AVISO] Arquivo de área não encontrado: postProcessing/{tipo}")
        return np.array([]), np.array([])

    tempos, areas = read_area_integrate(arquivo)
    if len(tempos) == 0:
        print(f"[AVISO] Arquivo de área vazio: {arquivo}")
    else:
        print(f"[OK] Área {tipo}: {arquivo} ({len(tempos)} pontos)")
    return tempos, areas


def area_no_tempo(tempos, areas, time_value):
    """Retorna a área no tempo disponível mais próximo."""
    if len(tempos) == 0 or len(areas) == 0:
        return np.nan
    idx = int(np.argmin(np.abs(tempos - float(time_value))))
    return float(areas[idx])


def hL_por_area(A_oleo):
    """
    Inverte A_L = geometria(h_L), usando a mesma geometria do modelo analítico.
    Entrada: A_oleo [m²]. Saída: h_L [mm].
    """
    if not np.isfinite(A_oleo):
        return np.nan
    if A_oleo <= 0.0:
        return 0.0

    A_max = geometria(D_O, D_O, D_I)[0]
    if A_oleo >= A_max:
        return D_O * 1000.0

    def residual(h):
        return geometria(h, D_O, D_I)[0] - A_oleo

    try:
        h = brentq(residual, 0.0, D_O, xtol=1e-12, rtol=1e-12)
    except ValueError:
        return np.nan

    return h * 1000.0

def calcular_vazao_teorica():
    for path in [Path("0/U"), Path("0.orig/U")]:
        if path.exists():
            content = path.read_text(errors="ignore")
            m = re.search(r"Q\s*=\s*([0-9.]+)\s*L/min", content)
            if m:
                return float(m.group(1))

            m = re.search(
                r"const\s+scalar\s+uOleo\s*=\s*([0-9.eE+-]+);",
                content,
            )
            if m:
                u = float(m.group(1))
                h = 0.016559
                theta = np.arccos(1 - 2*h/(2*R_OUT))
                area = ((2*R_OUT)**2/4) * (
                    theta - (1 - 2*h/(2*R_OUT))
                    * np.sqrt(1 - (1 - 2*h/(2*R_OUT))**2)
                )
                return area * u * 60000.0

    return 35.0

def integrar_vazao_numerica(csv_path):
    """Integra a vazão de óleo a partir de um perfil vertical no plano x=0.

    O eixo do duto é Y. Para uma seção circular/anular, cada ponto z representa
    uma corda na direção X. Assim:

        Q = integral[ alpha(z) * U_y(z) * b(z) dz ]

    onde b(z) é a largura da seção anular na coordenada z.
    Retorna Q em L/min.
    """
    if not csv_path or not Path(csv_path).exists():
        return np.nan

    df = read_csv_data(csv_path)
    cols = list(df.columns)
    lower = [str(c).lower() for c in cols]

    alpha_idx = next((i for i, c in enumerate(lower)
                      if "alpha" in c and "oil" in c), None)
    if alpha_idx is None:
        alpha_idx = next((i for i, c in enumerate(lower) if "alpha" in c), None)

    coord_idx = next((i for i, c in enumerate(lower)
                      if i != alpha_idx and (c == "z" or c.endswith(":2")
                                             or "coordz" in c or "distance" in c)), None)
    if coord_idx is None:
        coord_idx = next((i for i, c in enumerate(lower)
                          if i != alpha_idx and c.startswith("z")), None)

    if alpha_idx is None or coord_idx is None:
        return np.nan

    # Primeiro tenta encontrar diretamente a componente axial U_y.
    u_idx = next((i for i, c in enumerate(lower)
                  if i not in (alpha_idx, coord_idx)
                  and (c in ("u:1", "u_1", "uy", "u_y", "u.y", "u[1]")
                       or c.endswith(":1"))), None)

    # Alguns CSVs gravam U como uma única coluna textual/vectorial.
    if u_idx is None:
        u_idx = next((i for i, c in enumerate(lower)
                      if i not in (alpha_idx, coord_idx) and c == "u"), None)

    if alpha_idx is None or coord_idx is None or u_idx is None:
        return np.nan

    alpha = np.asarray(df[cols[alpha_idx]], dtype=float)
    z = np.asarray(df[cols[coord_idx]], dtype=float)
    raw_u = df[cols[u_idx]]

    try:
        uy = np.asarray(raw_u, dtype=float)
    except (TypeError, ValueError):
        # Vetor no formato "(Ux Uy Uz)".
        uy = np.array([
            float(re.sub(r'[()]', '', str(v)).split()[1])
            if len(re.sub(r'[()]', '', str(v)).split()) >= 3 else np.nan
            for v in raw_u
        ])

    valid = np.isfinite(alpha) & np.isfinite(z) & np.isfinite(uy)
    alpha, z, uy = alpha[valid], z[valid], uy[valid]
    if len(z) < 2:
        return np.nan

    idx = np.argsort(z)
    z, alpha, uy = z[idx], alpha[idx], uy[idx]

    # Remove pontos repetidos para evitar problemas na integração.
    z_unique, inv = np.unique(z, return_inverse=True)
    if len(z_unique) != len(z):
        w = np.zeros(len(z_unique))
        a = np.zeros(len(z_unique))
        u = np.zeros(len(z_unique))
        n = np.zeros(len(z_unique))
        for j, k in enumerate(inv):
            a[k] += alpha[j]; u[k] += uy[j]; n[k] += 1
        alpha, uy = a/n, u/n
        z = z_unique

    # Largura da seção anular na coordenada z.
    ro, ri = float(D_O)/2.0, float(D_I)/2.0
    zz = np.abs(z)
    b = np.zeros_like(z)
    outside = zz < ro
    b[outside] = 2.0*np.sqrt(np.maximum(ro**2 - z[outside]**2, 0.0))
    inside = zz < ri
    b[inside] -= 2.0*np.sqrt(np.maximum(ri**2 - z[inside]**2, 0.0))
    b = np.maximum(b, 0.0)

    integrand = alpha * uy * b
    q = np.trapezoid(integrand, z) if hasattr(np, "trapezoid") else np.trapz(integrand, z)
    q_lmin = abs(float(q)) * 60000.0
    return q_lmin if q_lmin > 1e-8 else np.nan


def ler_surface_field_value(nome):
    """Lê todos os ``surfaceFieldValue*.dat`` válidos de um functionObject.

    O OpenFOAM 2312 pode manter ``surfaceFieldValue.dat`` vazio e escrever os
    dados em ``surfaceFieldValue_0.dat``. Também pode haver mais de um arquivo
    de saída. Por isso não usamos simplesmente o primeiro arquivo encontrado:
    varremos todos os .dat não vazios, extraímos as linhas numéricas e
    consolidamos por tempo.
    """
    base = Path("postProcessing") / nome

    if not base.exists():
        print(f"[AVISO] Não encontrado: {base}")
        return np.array([]), np.array([])

    arquivos = sorted(base.rglob("surfaceFieldValue*.dat"))
    arquivos = [p for p in arquivos if p.is_file() and p.stat().st_size > 0]

    if not arquivos:
        print(f"[AVISO] Nenhum surfaceFieldValue*.dat com dados em {base}")
        return np.array([]), np.array([])

    registros = []

    for path in arquivos:
        try:
            with open(path, errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    parts = line.split()
                    if len(parts) < 2:
                        continue

                    try:
                        t = float(parts[0])
                        value = float(parts[1])
                    except ValueError:
                        continue

                    registros.append((t, value, path))
        except OSError as exc:
            print(f"[AVISO] Não foi possível ler {path}: {exc}")

    if not registros:
        print(f"[AVISO] Nenhuma linha numérica encontrada em {base}")
        return np.array([]), np.array([])

    # Se vários arquivos repetirem o mesmo instante, mantém o último registro
    # encontrado. Isso evita duplicar pontos quando o OpenFOAM deixa cópias.
    por_tempo = {}
    for t, value, path in registros:
        por_tempo[float(t)] = float(value)

    tempos = np.array(sorted(por_tempo), dtype=float)
    valores = np.array([por_tempo[t] for t in tempos], dtype=float)

    print(
        f"[OK] {nome}: {len(tempos)} pontos "
        f"({', '.join(p.name for p in arquivos)})"
    )
    return tempos, valores

def valor_no_tempo(tempos, valores, t):
    """
    Obtém o valor no instante mais próximo.
    """
    if len(tempos) == 0:
        return np.nan

    idx = int(np.argmin(np.abs(tempos - float(t))))

    return float(valores[idx])

def churchill_cfd(h_mm):
    if not np.isfinite(h_mm):
        return np.nan, np.nan, np.nan, np.nan

    h = h_mm / 1000.0

    V, Q, Re, f = calcular_V_Q(h)

    tau = f * 900.0 * V**2 / 8.0

    return V, Q * 60000.0, Re, tau

# ---------------------------------------------------------------------------
# RESULTADOS
# ---------------------------------------------------------------------------
def resultados():
    print("=" * 72)
    print(" ANÁLISE DE RESULTADOS — CANAL ANULAR")
    print("=" * 72)

    time_dirs = get_time_dirs()
    if not time_dirs:
        print("[ERRO] Nenhum diretório de tempo encontrado.")
        return False

    print(f"[INFO] {len(time_dirs)} tempos: {time_dirs[0]} -> {time_dirs[-1]}")

    run_postprocess()
    q_teorica = calcular_vazao_teorica()
    rows = []
    # ---------------------------------------------------------
    # VAZÃO REAL DE ÓLEO
    # ---------------------------------------------------------

    t_qin, qin_raw = ler_surface_field_value("QOleoInlet")
    t_qout, qout_raw = ler_surface_field_value("QOleoOutlet")

    # inlet: fluxo entrando é negativo
    qin = -qin_raw * 60000.0

    # outlet: fluxo saindo é positivo
    qout = qout_raw * 60000.0

    print(
        f"[OK] Qin:  {len(qin)} pontos"
    )

    print(
        f"[OK] Qout: {len(qout)} pontos"
    )
    t_tau_i, tau_i_kin = ler_surface_field_value(
        "TauParedeInterna"
    )

    t_tau_o, tau_o_kin = ler_surface_field_value(
        "TauParedeExterna"
    )
    RHO = 900.0

    tau_i = tau_i_kin * RHO
    tau_o = tau_o_kin * RHO

    # Resultado oficial de h_L: integração de alpha.oil na seção inteira.
    # O perfil_meio continua sendo usado apenas para diagnóstico.
    tempos_area_meio, areas_meio = carregar_serie_area("areaOleoMeio")
    tempos_area_saida, areas_saida = carregar_serie_area("areaOleoSaida")

    for t_dir in time_dirs:
        base = find_postprocessing_base(t_dir)

        meio = find_profile_csv(base, "perfil_meio")
        saida = find_profile_csv(base, "perfil_saida")
        vertical = find_profile_csv(base, "perfil_vertical_debug")

        area_meio = area_no_tempo(tempos_area_meio, areas_meio, float(t_dir))
        area_saida = area_no_tempo(tempos_area_saida, areas_saida, float(t_dir))

        h_meio = hL_por_area(area_meio)
        h_saida = hL_por_area(area_saida)

        # Mantido somente como diagnóstico do método antigo.
        h_vertical = extract_hL_from_csv(vertical)

        # A vazão usada na comparação analítico x CFD deve vir do balanço
        # de fase nos patches, e não da integração de uma linha 1D. A linha
        # x=0 atravessa o tubo interno e, além disso, não representa por si só
        # a integral de área completa da seção. Mantemos a integração de perfil
        # apenas como diagnóstico independente.
        q_perfil_meio = integrar_vazao_numerica(meio)
        q_perfil_saida = integrar_vazao_numerica(saida)

        q_in_t = valor_no_tempo(t_qin, qin, float(t_dir))
        q_out_t = valor_no_tempo(t_qout, qout, float(t_dir))
        q_cfd_t = q_out_t if np.isfinite(q_out_t) else q_in_t

        rows.append({
            "tempo_s": float(t_dir),

            # Geometria
            "A_oleo_meio_m2": area_meio,
            "A_oleo_saida_m2": area_saida,

            "h_L_meio_mm": hL_por_area(area_meio),
            "h_L_saida_mm": hL_por_area(area_saida),

            # Vazão real de fase
            "Qin_oleo_Lmin": q_in_t,

            "Qout_oleo_Lmin": q_out_t,

            "Q_CFD_Lmin": q_cfd_t,
            "Q_teorica_Lmin": q_teorica,

            # Integrações 1D mantidas apenas para diagnóstico. Não são usadas
            # como vazão CFD oficial.
            "Q_perfil_meio_Lmin": q_perfil_meio,
            "Q_perfil_saida_Lmin": q_perfil_saida,

            # Cisalhamento integrado
            "F_tau_interna_N": valor_no_tempo(
                t_tau_i, tau_i, float(t_dir)
            ),

            "F_tau_externa_N": valor_no_tempo(
                t_tau_o, tau_o, float(t_dir)
            ),
        })

    import pandas as pd
    df = pd.DataFrame(rows)

    df["DeltaQ_Lmin"] = (
        df["Qin_oleo_Lmin"]
        - df["Qout_oleo_Lmin"]
    )
    
    df["DeltaQ_rel_pct"] = (
        100.0
        * df["DeltaQ_Lmin"].abs()
        / df["Qin_oleo_Lmin"].abs().replace(0, np.nan)
    )

    dados_churchill = df["h_L_meio_mm"].apply(
        churchill_cfd
    )

    df[
        [
            "V_Churchill_mps",
            "Q_Churchill_Lmin",
            "Re_Churchill",
            "tau_Churchill_Pa",
        ]
    ] = pd.DataFrame(
        dados_churchill.tolist(),
        index=df.index,
    )
    
    df["F_tau_total_N"] = (
        df["F_tau_interna_N"]
        + df["F_tau_externa_N"]
    ).abs()
    df["S_L_m"] = df["h_L_meio_mm"].apply(
        perimetro_molhado_cfd
    )

    L_CASE = 3.0

    df["tau_CFD_eq_Pa"] = (
        df["F_tau_total_N"]
        / (df["S_L_m"] * L_CASE)
    )

    df["erro_tau_pct"] = (
        100.0
        * (
            df["tau_CFD_eq_Pa"]
            - df["tau_Churchill_Pa"]
        )
        / df["tau_Churchill_Pa"]
    )

    df.to_csv("resultados_hL.csv", index=False, float_format="%.6f")

    print(f"[OK] resultados_hL.csv: {len(df)} registros")
    if len(df):
        h0 = df["h_L_meio_mm"].iloc[0]
        hf = df["h_L_meio_mm"].iloc[-1]
        print(f"h_L meio inicial: {h0:.3f} mm")
        print(f"h_L meio final:   {hf:.3f} mm")
        print(f"Q teórica:        {q_teorica:.3f} L/min")

    return True


# ---------------------------------------------------------------------------
# DIAGNÓSTICO VOF
# ---------------------------------------------------------------------------
def read_raw_csv(path):
    with open(path) as f:
        header = f.readline().strip().split(",")
    data = np.genfromtxt(path, delimiter=",", skip_header=1)
    if data is None or np.size(data) == 0:
        return header, np.empty((0, len(header)))
    if data.ndim == 1:
        data = data.reshape(1, -1)
    return header, data


def detect_gap(z, alpha, label=""):
    if len(z) < 3:
        return False, None, None, 0.0

    dz = np.diff(z)
    median_dz = np.median(dz)
    gap_idx = np.where(dz > 3.0 * median_dz)[0]

    if len(gap_idx) == 0:
        return False, None, None, 0.0

    idx = gap_idx[np.argmax(dz[gap_idx])]
    z0, z1 = z[idx], z[idx + 1]
    width_mm = (z1 - z0) * 1000.0

    print(f"[GAP] {label}: {width_mm:.2f} mm")
    return True, z0, z1, width_mm


def analyze_interface(z, alpha, label=""):
    """Analisa a interface no perfil, separando perfil bruto e região anular.

    A linha x=0 atravessa o tubo interno. Portanto um cruzamento alpha=0.5
    em |z| < R_IN não pode ser interpretado como interface do canal anular.
    """
    if len(z) < 2:
        return [], [], [], np.array([]), np.array([])

    dz = np.diff(z)
    median_dz = np.median(dz)

    if len(z) >= 3:
        d_alpha = np.gradient(alpha, z)
    else:
        d_alpha = np.array([])

    # ---------------------------------------------------------------
    # Cruzamentos no perfil bruto
    # ---------------------------------------------------------------
    crossings_raw = []
    for i in range(len(alpha) - 1):
        a0, a1 = alpha[i], alpha[i + 1]
        if (a0 - 0.5) * (a1 - 0.5) <= 0 and abs(a1 - a0) > 1e-12:
            t = (0.5 - a0) / (a1 - a0)
            crossings_raw.append(z[i] + t * (z[i + 1] - z[i]))

    # ---------------------------------------------------------------
    # Cruzamentos somente no canal anular
    # ---------------------------------------------------------------
    r_in = float(D_I) / 2.0
    r_out = float(D_O) / 2.0
    tol = max(1e-12, 0.25 * median_dz)

    crossings_annulus = []
    for i in range(len(alpha) - 1):
        z0, z1 = z[i], z[i + 1]
        a0, a1 = alpha[i], alpha[i + 1]

        # O segmento inteiro deve estar na região do anular.
        # Não aceitamos um segmento que atravesse o tubo interno.
        if min(abs(z0), abs(z1)) < r_in - tol:
            continue
        if max(abs(z0), abs(z1)) > r_out + tol:
            continue

        if (a0 - 0.5) * (a1 - 0.5) <= 0 and abs(a1 - a0) > 1e-12:
            t = (0.5 - a0) / (a1 - a0)
            zc = z0 + t * (z1 - z0)
            if r_in - tol <= abs(zc) <= r_out + tol:
                crossings_annulus.append(zc)

    h_raw = [(zc + R_OUT) * 1000.0 for zc in crossings_raw]
    h_annulus = [(zc + R_OUT) * 1000.0 for zc in crossings_annulus]

    print(f"\n=== {label} ===")
    print(f"Pontos: {len(z)}")
    print(f"z: [{z.min():.6f}, {z.max():.6f}] m")
    print(f"alpha: [{alpha.min():.3e}, {alpha.max():.6f}]")
    print(f"dz mediano: {median_dz*1000:.4f} mm")
    print(f"R_IN: {r_in*1000:.2f} mm | R_OUT: {r_out*1000:.2f} mm")

    if len(d_alpha):
        max_idx = int(np.argmax(np.abs(d_alpha)))
        print(f"max |dalpha/dz|: {abs(d_alpha[max_idx]):.3f}")
    else:
        print("max |dalpha/dz|: n/d")

    print(f"cruzamentos alpha=0.5 no perfil bruto: {len(crossings_raw)}")
    for zc, h in zip(crossings_raw, h_raw):
        print(f"  z={zc:.6f} m -> h_L={h:.4f} mm")

    print(f"cruzamentos alpha=0.5 no anular: {len(crossings_annulus)}")
    for zc, h in zip(crossings_annulus, h_annulus):
        print(f"  z={zc:.6f} m -> h_L={h:.4f} mm")

    if crossings_raw and not crossings_annulus:
        inside = [zc for zc in crossings_raw if abs(zc) < r_in]
        if inside:
            print("[AVISO] Cruzamento encontrado apenas dentro/na região do tubo interno;")
            print("ele não será interpretado como interface do canal anular.")

    if not crossings_annulus:
        print("[AVISO] Sem cruzamento alpha=0.5 na região anular.")

        if alpha.mean() > 0.95:
            print("[INFO] Perfil saturado em óleo.")
        elif alpha.mean() < 0.05:
            print("[INFO] Perfil saturado em gás.")

    return crossings_raw, crossings_annulus, d_alpha, h_raw, h_annulus

def diagnostico():
    latest = find_latest_time_from_sampling()
    path = Path("postProcessing/sampling") / latest

    print("=" * 72)
    print(" DIAGNÓSTICO VOF — PERFIS")
    print("=" * 72)
    print(f"Último tempo: {latest}")
    print(f"Pasta: {path}")
    print(f"R_OUT: {R_OUT*1000:.1f} mm")

    files = {
        "meio": find_profile_csv(path, "perfil_meio"),
        "saida": find_profile_csv(path, "perfil_saida"),
        "vertical_debug": find_profile_csv(path, "perfil_vertical_debug"),
    }

    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    all_data = {}
    gaps = {}
    interfaces = {}

    for key, csv_path in files.items():
        if not csv_path:
            print(f"[AVISO] perfil '{key}' não encontrado.")
            continue

        z, alpha, coord_name = extract_profile_arrays(csv_path)
        if z is None:
            print(f"[AVISO] Não foi possível ler {csv_path}")
            continue

        all_data[key] = (z, alpha)
        crossings_raw, crossings_annulus, d_alpha, h_raw, h_annulus = analyze_interface(
            z, alpha, label=str(csv_path)
        )
        interfaces[key] = h_annulus

        has_gap, zg0, zg1, gw = detect_gap(z, alpha, str(csv_path))
        gaps[key] = (has_gap, zg0, zg1, gw)

        axes[0, 0].plot(z*1000, alpha, "o-", markersize=3, label=key)

        # Um perfil pode conter apenas 1 ponto (ou dados insuficientes).
        # Nesse caso analyze_interface() devolve d_alpha vazio e não há
        # uma curva de derivada que possa ser desenhada. Não deixe esse
        # perfil inválido interromper todo o diagnóstico dos demais perfis.
        if len(z) >= 2 and len(d_alpha) == len(z):
            axes[0, 1].plot(z*1000, np.abs(d_alpha), "-", label=key)
        else:
            print(f"[AVISO] {csv_path}: pontos insuficientes para calcular d(alpha)/dz; derivada ignorada.")

        trans = (alpha > 0.01) & (alpha < 0.99)
        if np.any(trans):
            idx = np.where(trans)[0]
            margin = max(3, len(idx))
            i0 = max(0, idx[0] - margin)
            i1 = min(len(z), idx[-1] + margin + 1)
            axes[1, 0].plot(
                z[i0:i1]*1000, alpha[i0:i1], "o-",
                markersize=4, label=key
            )
        else:
            axes[1, 0].plot(z*1000, alpha, "o-", label=f"{key} (sem transição)")

    axes[0, 0].axhline(0.5, linestyle=":")
    axes[0, 0].set(xlabel="z [mm]", ylabel="alpha.oil", title="Perfis VOF")
    axes[0, 0].grid(True, alpha=0.3)
    axes[0, 0].legend()

    axes[0, 1].set(xlabel="z [mm]", ylabel="|dalpha/dz| [1/m]", title="Derivada")
    axes[0, 1].set_yscale("log")
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].legend()

    axes[1, 0].axhline(0.5, linestyle=":")
    axes[1, 0].set(xlabel="z [mm]", ylabel="alpha.oil", title="Zoom da transição")
    axes[1, 0].grid(True, alpha=0.3)
    axes[1, 0].legend()

    if "meio" in all_data and "saida" in all_data:
        zm, am = all_data["meio"]
        zs, a_s = all_data["saida"]
        axes[1, 1].plot(zm*1000, am, "o-", label="meio")
        axes[1, 1].plot(zs*1000, a_s, "s-", label="saída")
        axes[1, 1].axhline(0.5, linestyle=":")
        axes[1, 1].set_title("Comparação meio vs saída")
        axes[1, 1].set_xlabel("z [mm]")
        axes[1, 1].set_ylabel("alpha.oil")
        axes[1, 1].grid(True, alpha=0.3)
        axes[1, 1].legend()
    else:
        axes[1, 1].text(
            0.5, 0.5, "Dados insuficientes\npara comparação",
            ha="center", va="center", transform=axes[1, 1].transAxes
        )

    plt.tight_layout()
    out = "diagnostico_vof_perfil_meio.png"
    plt.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"\n[OK] Gráfico: {out}")

    if gaps.get("meio", (False,))[0]:
        _, z0, z1, width = gaps["meio"]
        ri = abs(z0) * 1000
        print("\n[ATENÇÃO] Gap detectado em perfil_meio.")
        print(f"  largura: {width:.2f} mm")
        print(f"  z: [{z0*1000:.2f}, {z1*1000:.2f}] mm")
        print(f"  raio interno estimado: {ri:.1f} mm")
        print("  A linha pode estar atravessando o tubo interno.")

    hm_list = interfaces.get("meio", [])
    hs_list = interfaces.get("saida", [])

    if hm_list and hs_list:
        hm = hm_list[0]
        hs = hs_list[0]
        diff = abs(hm - hs)
        print(f"\nh_L interface meio : {hm:.2f} mm")
        print(f"h_L interface saída: {hs:.2f} mm")
        print(f"diferença          : {diff:.2f} mm")
    else:
        if not hm_list:
            print("\n[INFO] Perfil_meio não forneceu cruzamento válido no anular.")
            print("Isso é aceitável quando a interface não cruza a linha x=0.")
        if not hs_list:
            print("[INFO] Perfil_saida não forneceu cruzamento válido no anular.")
            print("Isso é aceitável quando a interface não cruza a linha x=0.")

    # O resultado oficial de h_L vem da área integrada de alpha.oil.
    tempos_area_meio, areas_meio = carregar_serie_area("areaOleoMeio")
    tempos_area_saida, areas_saida = carregar_serie_area("areaOleoSaida")
    if len(tempos_area_meio) and len(tempos_area_saida):
        a_m = area_no_tempo(tempos_area_meio, areas_meio, float(latest))
        a_s = area_no_tempo(tempos_area_saida, areas_saida, float(latest))
        h_m = hL_por_area(a_m)
        h_s = hL_por_area(a_s)
        print("\n=== ALTURA DE LÍQUIDO — MÉTODO OFICIAL ===")
        print("Área integrada de alpha.oil + inversão da geometria hidráulica")
        print(f"Área óleo meio : {a_m:.8f} m²")
        print(f"h_L meio       : {h_m:.3f} mm")
        print(f"Área óleo saída: {a_s:.8f} m²")
        print(f"h_L saída      : {h_s:.3f} mm")
        print(f"diferença      : {abs(h_m-h_s):.3f} mm")

    return True


# ---------------------------------------------------------------------------
# EXTRAÇÃO DE PERFIS DE BACKUP
# ---------------------------------------------------------------------------
def extrair_perfis(backup_dir, times_solicitados, output_dir=None, tolerance=None):
    """
    Extrai snapshots de perfis de um backup de simulação.

    Versão da funcionalidade: 1.0
    Entrada:
      - pasta do backup;
      - tempos solicitados;
      - tolerância opcional em segundos.
    Saída:
      - uma pasta por tempo solicitado;
      - cópias dos arquivos de perfil;
      - manifest.tsv com rastreabilidade.
    Finalidade:
      - selecionar o snapshot REAL mais próximo sem alterar o backup,
        a simulação ou os resultados originais.

    A tolerância, quando informada, é uma tolerância máxima: se o snapshot
    mais próximo estiver além dela, os arquivos daquele tempo não são
    copiados e o manifest registra a ocorrência.
    """
    backup = Path(backup_dir).expanduser().resolve()

    if not backup.is_dir():
        print(f"[ERRO] Pasta de backup não encontrada: {backup}")
        return False

    sampling = backup / "postProcessing" / "sampling"
    if not sampling.is_dir():
        print(f"[ERRO] Diretório não encontrado: {sampling}")
        return False

    # Tempos reais disponíveis no backup.
    available = []
    for item in sampling.iterdir():
        if not item.is_dir():
            continue
        try:
            available.append((float(item.name), item))
        except ValueError:
            continue

    available.sort(key=lambda x: x[0])

    if not available:
        print(f"[ERRO] Nenhum diretório temporal encontrado em {sampling}")
        return False

    if output_dir is None:
        output = Path("analise_perfis")
    else:
        output = Path(output_dir).expanduser()

    # Saída da análise é independente do backup e nunca é escrita dentro dele.
    output = output.resolve()

    try:
        output.relative_to(backup)
        output_inside_backup = True
    except ValueError:
        output_inside_backup = False

    if output_inside_backup:
        print(
            "[ERRO] A pasta de saída não pode ficar dentro do backup. "
            "Isso garante que os resultados originais permaneçam intocados."
        )
        return False

    output.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print(" EXTRAÇÃO DE PERFIS — BACKUP")
    print("=" * 72)
    print(f"Backup : {backup}")
    print(f"Sampling: {sampling}")
    print(f"Saída  : {output}")
    print(f"Tempos disponíveis: {len(available)}")
    print(f"Faixa real: {available[0][0]:.15g} -> {available[-1][0]:.15g} s")

    if tolerance is not None:
        print(f"Tolerância máxima: {tolerance:.12g} s")

    # Normaliza tempos solicitados e elimina duplicatas preservando a ordem.
    requested = []
    seen = set()
    for value in times_solicitados:
        try:
            t = float(value)
        except ValueError:
            print(f"[AVISO] Tempo inválido ignorado: {value}")
            continue

        key = repr(t)
        if key not in seen:
            requested.append(t)
            seen.add(key)

    if not requested:
        print("[ERRO] Nenhum tempo solicitado válido.")
        return False

    manifest_path = output / "manifest.tsv"
    manifest_rows = []

    patterns = (
        "perfil_meio*.csv",
        "perfil_saida*.csv",
        "perfil_vertical_debug*.csv",
    )

    total_copied = 0
    successful_times = 0

    with manifest_path.open("w", encoding="utf-8", newline="") as manifest:
        manifest.write(
            "tempo_solicitado\ttempo_real\terro_tempo\tarquivo\tstatus\n"
        )

        for requested_time in requested:
            real_time, real_dir = min(
                available,
                key=lambda item: abs(item[0] - requested_time)
            )
            error = abs(real_time - requested_time)

            time_label = f"{requested_time:.6f}".rstrip("0").rstrip(".")
            destination = output / time_label

            exceeds_tolerance = (
                tolerance is not None and error > tolerance
            )

            files = []
            for pattern in patterns:
                files.extend(
                    sorted(
                        p for p in real_dir.glob(pattern)
                        if p.is_file()
                    )
                )

            # Deduplica por caminho.
            files = list(dict.fromkeys(files))

            if exceeds_tolerance:
                print(
                    f"[AVISO] {requested_time:.15g} s -> "
                    f"{real_time:.15g} s | erro={error:.9g} s "
                    f"> tolerância={tolerance:.9g} s"
                )

                if files:
                    for source in files:
                        manifest.write(
                            f"{requested_time:.15g}\t"
                            f"{real_time:.15g}\t"
                            f"{error:.15g}\t"
                            f"\tFORA_TOLERANCIA\n"
                        )
                else:
                    manifest.write(
                        f"{requested_time:.15g}\t"
                        f"{real_time:.15g}\t"
                        f"{error:.15g}\t"
                        f"\tFORA_TOLERANCIA_SEM_ARQUIVOS\n"
                    )
                continue

            if error > 0.001:
                print(
                    f"[ATENÇÃO] {requested_time:.15g} s -> "
                    f"{real_time:.15g} s | erro={error:.9g} s"
                )
            else:
                print(
                    f"[OK] {requested_time:.15g} s -> "
                    f"{real_time:.15g} s | erro={error:.9g} s"
                )

            if not files:
                print(
                    f"[AVISO] Nenhum perfil encontrado em "
                    f"{real_dir}"
                )
                manifest.write(
                    f"{requested_time:.15g}\t"
                    f"{real_time:.15g}\t"
                    f"{error:.15g}\t"
                    f"\tSEM_ARQUIVOS\n"
                )
                continue

            destination.mkdir(parents=True, exist_ok=True)
            copied_for_time = 0

            for source in files:
                target = destination / source.name

                # copy2 preserva metadados básicos, mas cria uma cópia
                # independente; o original permanece intocado.
                shutil.copy2(source, target)

                rel_target = target.relative_to(output)
                manifest.write(
                    f"{requested_time:.15g}\t"
                    f"{real_time:.15g}\t"
                    f"{error:.15g}\t"
                    f"{rel_target.as_posix()}\tCOPIADO\n"
                )

                copied_for_time += 1
                total_copied += 1

            successful_times += 1
            print(
                f"      {copied_for_time} arquivo(s) copiado(s) "
                f"-> {destination}"
            )

    print("-" * 72)
    print(f"[OK] Manifest: {manifest_path}")
    print(f"[OK] Tempos com arquivos copiados: {successful_times}/{len(requested)}")
    print(f"[OK] Arquivos copiados: {total_copied}")
    print("[OK] Backup e resultados originais não foram modificados.")

    return total_copied > 0


# ---------------------------------------------------------------------------
# COMPARAÇÃO ANALÍTICO x CFD
# ---------------------------------------------------------------------------
def comparar():
    import pandas as pd

    if not Path("resultados_hL.csv").exists():
        print("[ERRO] resultados_hL.csv não existe. Rode 'resultados' primeiro.")
        return False

    df = pd.read_csv("resultados_hL.csv")
    h_a, q_a, _, _ = gerar_curva(n_pontos=500)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    axes[0].plot(df["tempo_s"], df["h_L_meio_mm"], "o-", label="CFD (meio)")
    if "h_L_saida_mm" in df.columns:
        axes[0].plot(df["tempo_s"], df["h_L_saida_mm"], "s-", label="CFD (saída)")
    axes[0].set(xlabel="Tempo [s]", ylabel="h_L [mm]", title="Evolução temporal")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    axes[1].plot(
        q_a * 60000.0, h_a * 1000.0,
        "-", linewidth=2, label="Analítico"
    )
    if "Q_CFD_Lmin" in df.columns:
        data = df[["Q_CFD_Lmin", "h_L_meio_mm", "tempo_s"]].dropna()
        if len(data):
            sc = axes[1].scatter(
                data["Q_CFD_Lmin"],
                data["h_L_meio_mm"],
                c=data["tempo_s"],
                cmap="viridis",
                s=50,
                edgecolors="black",
                label="CFD — vazão de fase",
            )
            fig.colorbar(sc, ax=axes[1], label="Tempo [s]")

    if "Q_teorica_Lmin" in df.columns and len(df):
        qref = df["Q_teorica_Lmin"].iloc[0]
        if np.isfinite(qref):
            axes[1].axvline(
                qref, linestyle=":", linewidth=1.5,
                label=f"Q teórica = {qref:.1f} L/min"
            )

    axes[1].set(xlabel="Q [L/min]", ylabel="h_L [mm]",
                title="Analítico vs CFD")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()

    plt.tight_layout()
    out = "comparacao_analitico_cfd.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)

    print(f"[OK] Gráfico: {out}")

    fig, ax = plt.subplots(figsize=(9, 6))

    ax.plot(
        df["tempo_s"],
        df["tau_CFD_eq_Pa"],
        label="CFD"
    )

    ax.plot(
        df["tempo_s"],
        df["tau_Churchill_Pa"],
        "--",
        label="Churchill"
    )

    ax.set_xlabel("Tempo [s]")
    ax.set_ylabel(r"$\tau_w$ equivalente [Pa]")
    ax.set_title("Cisalhamento na parede — CFD × Churchill")

    ax.grid(True, alpha=0.3)
    ax.legend()

    plt.tight_layout()

    plt.savefig(
        "comparacao_cisalhamento_churchill.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close()


    fig, ax = plt.subplots(figsize=(9, 6))

    ax.plot(
        df["tempo_s"],
        df["Qin_oleo_Lmin"],
        label="Qin óleo"
    )

    ax.plot(
        df["tempo_s"],
        df["Qout_oleo_Lmin"],
        label="Qout óleo"
    )

    ax.axhline(
        df["Q_teorica_Lmin"].iloc[0],
        linestyle="--",
        label="Q teórica"
    )

    ax.set_xlabel("Tempo [s]")
    ax.set_ylabel("Vazão de óleo [L/min]")
    ax.set_title("Balanço de vazão — entrada × saída")

    ax.grid(True, alpha=0.3)
    ax.legend()

    plt.tight_layout()

    plt.savefig(
        "balanco_vazao_oleo.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close()

    if len(df):
        h_ini = df["h_L_meio_mm"].iloc[0]
        h_fim = df["h_L_meio_mm"].iloc[-1]
        print(f"h_L inicial: {h_ini:.3f} mm")
        print(f"h_L final:   {h_fim:.3f} mm")

        q_series = df.get("Q_CFD_Lmin", pd.Series(dtype=float)).dropna()
        if len(q_series):
            q_target_lmin = float(q_series.iloc[-1])
            q_target = q_target_lmin / 60000.0
            roots = encontrar_raizes_Q(q_target)
            print(f"Q CFD usada para as raízes: {q_target_lmin:.3f} L/min")
            if not roots:
                print("[AVISO] Nenhuma raiz analítica encontrada para a vazão CFD.")
            for i, root in enumerate(roots, 1):
                h, v, q, re, f, reg = root
                print(
                    f"Raiz {i}: h_L={h*1000:.3f} mm | "
                    f"V={v:.5f} m/s | Re={re:.2f} | região={reg}"
                )

    return True


def main():
    parser = argparse.ArgumentParser(description="Pós-processamento do Canal Anular.")
    parser.add_argument(
        "comando",
        choices=["resultados", "diagnostico", "comparar", "extrair-perfis", "tudo"],
        help="operação a executar",
    )

    # Opções exclusivas do comando extrair-perfis.
    parser.add_argument(
        "backup",
        nargs="?",
        help="pasta do backup contendo postProcessing/sampling",
    )
    parser.add_argument(
        "--times",
        nargs="+",
        type=float,
        help="tempos solicitados [s] para extração dos perfis",
    )
    parser.add_argument(
        "--output",
        default="analise_perfis",
        help="pasta de saída da análise (padrão: analise_perfis)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=None,
        help="erro máximo permitido entre tempo solicitado e snapshot real [s]",
    )

    args = parser.parse_args()

    if args.comando == "extrair-perfis":
        if not args.backup:
            parser.error("extrair-perfis requer a pasta do backup.")
        if not args.times:
            parser.error("extrair-perfis requer --times com pelo menos um tempo.")
        if args.tolerance is not None and args.tolerance < 0:
            parser.error("--tolerance não pode ser negativa.")

        ok = extrair_perfis(
            args.backup,
            args.times,
            output_dir=args.output,
            tolerance=args.tolerance,
        )
    elif args.comando == "resultados":
        ok = resultados()
    elif args.comando == "diagnostico":
        ok = diagnostico()
    elif args.comando == "comparar":
        ok = comparar()
    else:
        ok = resultados()
        if ok:
            ok = diagnostico()
        if ok:
            ok = comparar()

    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
