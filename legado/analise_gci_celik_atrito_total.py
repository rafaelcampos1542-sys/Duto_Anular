#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Análise de independência de malha / GCI para OpenFOAM.

Executar na pasta principal do caso, que contém:
    M0/M0_Q10, M0/M0_Q35, ...
e os CSVs:
    atrito_M0_Q10.csv ... atrito_M2_Q60.csv

O script:
- Lê forças e áreas de atrito do CSV consolidado auditado;
  calcula a força total como soma das magnitudes das duas contribuições.
- Lê vazão de óleo no plano central do functionObjects_temporais.csv.
- Lê velocidade média no plano central e volume de óleo dos functionObjects.
- Calcula médias temporais por integração trapezoidal na janela comum.
- Calcula CV amostral e deriva temporal na janela.
- Calcula ordem aparente, extrapolação de Richardson e GCI quando aplicável.
- Mantém diferenças relativas entre malhas mesmo quando não reporta GCI.
- Gera relatorio_gci_3malhas_atualizado.csv.

ATENÇÃO:
Os CSVs de atrito devem conter tensões já convertidas para Pa e integrais
já convertidas para N. O script NÃO multiplica esses dados novamente por rho.
"""

from __future__ import annotations

import glob
import math
import os
import re
import sys
from dataclasses import dataclass
from typing import Optional

try:
    import pandas as pd
except ImportError:
    print("ERRO: pandas não está instalado.")
    print("Instale com: ./venv/bin/pip install pandas")
    sys.exit(1)


# ------------------------- CONFIGURAÇÃO --------------------------------------

CELL_COUNTS = {
    "M0": 480_000,       # malha grossa
    "M1": 1_620_000,     # malha intermediária
    "M2": 5_491_800,     # malha fina
}
MESHES = ("M0", "M1", "M2")
CASES = ("Q10", "Q35", "Q60")

# Janela comum a todos os casos e malhas.
WINDOW = (3.0, 6.0)
WINDOW_TOL = 0.01       # tolerância apenas para pequenas diferenças nos tempos gravados
MIN_POINTS = 4
MIN_WET_AREA_M2 = 1e-8  # abaixo disso, a tensão média da parede não é representativa

# Parâmetros do GCI (Celik et al., 2008).
FS = 1.25
DIM = 3
LOW_ORDER_P = 0.5
ASYMPTOTIC_TOL = 0.10

# Diagnóstico heurístico: diferença M1->M2 menor que este múltiplo
# do CV temporal máximo será sinalizada como comparável à variação temporal.
NOISE_FACTOR = 2.0

# Arquivos gerados por consolidar_resultados_auditado.py.
CONSOLIDATED_DIR = "resultados_consolidados"
FRICTION_DATA = os.path.join(CONSOLIDATED_DIR, "atrito_temporal_nove_casos_reconstruido.csv")
FUNCTION_DATA = os.path.join(CONSOLIDATED_DIR, "functionObjects_temporais.csv")

# FunctionObjects mantidos do script anterior.
# O atrito foi removido daqui porque agora vem dos CSVs corrigidos.
FUNCTIONS_MAP = {
    "Velocidade média no plano central (m/s)": {
        "folder": "velocidadePonderada",
        "component": 1,  # componente Y
    },
    "Volume de óleo (m³)": {
        "folder": "volumeOleo",
        "component": None,
    },
}

# O GCI do atrito utiliza diretamente a força total já calculada
# no CSV: integral_tau_ponderada_total_N.
FRICTION_METRICS = {
    "Força de atrito parede interna (N)": "integral_tau_ponderada_interna_N",
    "Força de atrito parede externa (N)": "integral_tau_ponderada_externa_N",
    "Força total de atrito — soma das duas paredes (N)": "__forca_atrito_total_paredes_N",
    "Área ponderada total pelo óleo (m²)": "area_ponderada_oleo_total_m2",
}

OUTPUT_CSV = "relatorio_gci_3malhas_atualizado.csv"
FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


@dataclass
class Record:
    time: float
    value: float
    source: str = ""


def fmt(value, unit=""):
    if value is None:
        return "—"
    try:
        if not math.isfinite(float(value)):
            return "—"
    except (TypeError, ValueError):
        return "—"
    return f"{float(value):.5g}{unit}"


# ------------------------- MÉDIA TEMPORAL ------------------------------------

def interpolate_at(times, values, target):
    """Interpolação linear em target; exige dados dos dois lados ou ponto exato."""
    for i, t in enumerate(times):
        if math.isclose(t, target, rel_tol=0.0, abs_tol=1e-10):
            return values[i]
    for i in range(len(times) - 1):
        t0, t1 = times[i], times[i + 1]
        if t0 < target < t1:
            f = (target - t0) / (t1 - t0)
            return values[i] + f * (values[i + 1] - values[i])
    raise ValueError(f"Não há dados suficientes para interpolar t={target:g} s.")


def window_stats(records):
    """
    Média temporal trapezoidal na janela exata.
    CV calculado sobre as amostras contidas na janela; deriva usa os extremos
    interpolados da própria janela.
    """
    if not records:
        return None

    records = sorted(records, key=lambda r: r.time)
    # Remove tempos duplicados: conserva o último registro para aquele tempo.
    unique = {}
    for rec in records:
        unique[rec.time] = rec.value
    times = sorted(unique)
    values = [unique[t] for t in times]

    t0, t1 = WINDOW
    if times[0] > t0 + WINDOW_TOL or times[-1] < t1 - WINDOW_TOL:
        return None

    # Ajusta diferenças minúsculas de arredondamento/gravação nos extremos.
    t0_eff = t0 if times[0] <= t0 else times[0]
    t1_eff = t1 if times[-1] >= t1 else times[-1]
    inside = [(t, v) for t, v in zip(times, values)
              if t0_eff <= t <= t1_eff]
    if len(inside) < MIN_POINTS:
        return None

    v0 = interpolate_at(times, values, t0_eff)
    v1 = interpolate_at(times, values, t1_eff)
    tw = [t0_eff] + [t for t, _ in inside if t0_eff < t < t1_eff] + [t1_eff]
    vw = [v0] + [v for t, v in inside if t0_eff < t < t1_eff] + [v1]

    duration = t1_eff - t0_eff
    mean = sum(
        (vw[i] + vw[i + 1]) * 0.5 * (tw[i + 1] - tw[i])
        for i in range(len(tw) - 1)
    ) / duration

    sample_values = [v for _, v in inside]
    if len(sample_values) > 1:
        avg_sample = sum(sample_values) / len(sample_values)
        variance = sum((v - avg_sample) ** 2 for v in sample_values) / (len(sample_values) - 1)
        std = math.sqrt(variance)
        cv = abs(std / avg_sample) * 100 if avg_sample != 0 else float("nan")
    else:
        cv = float("nan")

    drift = abs(v1 - v0) / abs(mean) * 100 if mean != 0 else float("nan")

    return {
        "mean": mean,
        "n": len(inside),
        "cv_pct": cv,
        "drift_pct": drift,
        "t_min": t0_eff,
        "t_max": t1_eff,
    }


# ------------------------- LEITURA DOS CSVs DE ATRITO -------------------------

def load_consolidated_friction(mesh, case):
    """Carrega os registros de atrito da malha/caso no CSV consolidado."""
    if not os.path.isfile(FRICTION_DATA):
        print(f"  [ERRO] CSV consolidado não encontrado: {FRICTION_DATA}")
        return None
    try:
        df = pd.read_csv(FRICTION_DATA)
    except Exception as exc:
        print(f"  [ERRO] Não consegui ler {FRICTION_DATA}: {exc}")
        return None

    required = {"malha", "caso", "tempo_s"}
    missing = required - set(df.columns)
    if missing:
        print(f"  [ERRO] {FRICTION_DATA}: colunas ausentes: {sorted(missing)}")
        return None

    df = df[(df["malha"] == mesh) & (df["caso"] == case)].copy()
    for col in df.columns:
        if col not in ("malha", "caso"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["tempo_s"]).sort_values("tempo_s")
    return df.drop_duplicates(subset="tempo_s", keep="last")


def load_friction_records(mesh, case, column):
    df = load_consolidated_friction(mesh, case)
    if df is None or column not in df.columns:
        if df is not None:
            print(f"  [ERRO] Coluna ausente em {FRICTION_DATA}: {column}")
        return []
    df = df.dropna(subset=[column])
    return [Record(float(r["tempo_s"]), float(r[column]), FRICTION_DATA)
            for _, r in df.iterrows()]


def load_total_friction_records(mesh, case):
    return load_friction_records(
        mesh, case, "integral_tau_ponderada_total_N"
    )


# ------------------------- LEITURA DOS FUNCTIONOBJECTS ------------------------

def parse_foam_line(line, component=None):
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    nums = FLOAT_RE.findall(s)
    if len(nums) not in (2, 4):
        return None
    try:
        vals = [float(x) for x in nums]
    except ValueError:
        return None
    t, data = vals[0], vals[1:]
    if not math.isfinite(t) or not all(math.isfinite(x) for x in data):
        return None
    if len(data) == 1:
        return t, data[0]
    if component is None:
        return t, math.sqrt(sum(x * x for x in data))
    return t, data[component]


def extract_function_records(case_dir, func_folder, component=None):
    pattern = os.path.join(case_dir, "postProcessing", func_folder, "**", "*.dat")
    paths = sorted(glob.glob(pattern, recursive=True))
    if not paths:
        print(f"  [AVISO] Nenhum .dat encontrado: {pattern}")
        return []

    by_time = {}
    for path in paths:
        priority = 1 if os.path.basename(os.path.dirname(path)) == "0" else 0
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parsed = parse_foam_line(line, component)
                    if parsed is None:
                        continue
                    t, value = parsed
                    old = by_time.get(t)
                    if old is None or priority >= old[0]:
                        by_time[t] = (priority, Record(t, value, path))
        except OSError as exc:
            print(f"  [AVISO] Não consegui ler {path}: {exc}")

    return sorted((item[1] for item in by_time.values()), key=lambda r: r.time)


def extract_qoleo_meio_records(mesh, case):
    """Lê QOleoMeio consolidado; valor_bruto é componente Y em m³/s."""
    if not os.path.isfile(FUNCTION_DATA):
        print(f"  [ERRO] CSV de functionObjects não encontrado: {FUNCTION_DATA}")
        return []
    try:
        df = pd.read_csv(FUNCTION_DATA)
    except Exception as exc:
        print(f"  [ERRO] Não consegui ler {FUNCTION_DATA}: {exc}")
        return []

    required = {"caso", "funcao", "tempo_s", "valor_bruto"}
    missing = required - set(df.columns)
    if missing:
        print(f"  [ERRO] {FUNCTION_DATA}: colunas ausentes: {sorted(missing)}")
        return []

    names = df["funcao"].astype(str).str.lower().str.replace("_", "", regex=False)
    df = df[(df["caso"] == f"{mesh}_{case}") & (names == "qoleomeio")].copy()
    df["tempo_s"] = pd.to_numeric(df["tempo_s"], errors="coerce")
    df["valor_bruto"] = pd.to_numeric(df["valor_bruto"], errors="coerce")
    df = df.dropna(subset=["tempo_s", "valor_bruto"]).sort_values("tempo_s")
    df = df.drop_duplicates(subset="tempo_s", keep="last")

    return [Record(float(r["tempo_s"]), float(r["valor_bruto"]) * 60000.0,
                   FUNCTION_DATA) for _, r in df.iterrows()]


# ------------------------- GCI (CELIK ET AL., 2008) --------------------------

def apparent_order(phi1, phi2, phi3, r21, r32, tol=1e-8, itmax=200):
    """
    phi1=M2 (fina), phi2=M1 (média), phi3=M0 (grossa).
    Retorna ordem aparente p, regime e R=e21/e32.
    """
    values = (phi1, phi2, phi3, r21, r32)
    if not all(math.isfinite(x) for x in values):
        return None, "dados não finitos", None
    if r21 <= 1.0 or r32 <= 1.0:
        return None, "razão de refinamento inválida", None

    e21 = phi2 - phi1
    e32 = phi3 - phi2
    scale = max(abs(phi1), abs(phi2), abs(phi3), 1.0)
    if abs(e21) <= 1e-14 * scale or abs(e32) <= 1e-14 * scale:
        return None, "diferença entre malhas muito pequena", None

    R = e21 / e32
    if R > 0:
        regime = "convergência monotônica" if R < 1 else "divergência monotônica"
    else:
        regime = "convergência oscilatória" if abs(R) < 1 else "divergência oscilatória"

    if abs(R) >= 1:
        return None, regime, R

    s = 1.0 if e21 * e32 > 0 else -1.0
    log_ratio = math.log(abs(e32 / e21))
    log_r21 = math.log(r21)
    p = max(0.1, abs(log_ratio) / log_r21)

    def residual(p_test):
        try:
            a = r21 ** p_test - s
            b = r32 ** p_test - s
            if a <= 0 or b <= 0:
                return None
            return p_test * log_r21 - abs(log_ratio + math.log(a / b))
        except (ValueError, OverflowError, ZeroDivisionError):
            return None

    for _ in range(itmax):
        try:
            numerator = r21 ** p - s
            denominator = r32 ** p - s
            if numerator <= 0 or denominator <= 0:
                return None, regime, R
            q = math.log(numerator / denominator)
            p_new = abs(log_ratio + q) / log_r21
        except (ValueError, OverflowError, ZeroDivisionError):
            return None, regime, R

        if not math.isfinite(p_new) or p_new <= 0:
            return None, regime, R
        res = residual(p_new)
        if res is not None and abs(res) < tol:
            return p_new, regime, R
        if abs(p_new - p) < tol:
            if res is not None and abs(res) < 10 * tol:
                return p_new, regime, R
            return None, "iteração estabilizou sem resolver a equação", R
        p = p_new

    return None, "ordem aparente não convergiu", R


def calculate_gci(phi1, phi2, phi3, N1, N2, N3, Fs=FS, dim=DIM):
    r21 = (N1 / N2) ** (1.0 / dim)
    r32 = (N2 / N3) ** (1.0 / dim)
    ea21 = abs((phi1 - phi2) / phi1) if abs(phi1) > 1e-30 else None
    ea32 = abs((phi2 - phi3) / phi2) if abs(phi2) > 1e-30 else None

    result = {
        "phi3_M0": phi3, "phi2_M1": phi2, "phi1_M2": phi1,
        "r21": r21, "r32": r32, "R": None, "p": None,
        "ea21_pct": ea21 * 100 if ea21 is not None else float("nan"),
        "ea32_pct": ea32 * 100 if ea32 is not None else float("nan"),
        "GCI21_pct": None, "GCI32_pct": None,
        "phi_ext21": None, "asymptotic_ratio": None,
        "regime": "", "status": "", "gci_ok": False,
    }

    p, regime, R = apparent_order(phi1, phi2, phi3, r21, r32)
    result["regime"], result["R"] = regime, R
    if p is None:
        result["status"] = "GCI não calculado: " + regime
        return result

    result["p"] = p

    # Para este relatório, GCI será reportado apenas
    # para sequências de convergência monotônica.
    if "oscilatória" in regime:
        result["status"] = (
            "GCI não reportado: sequência oscilatória; "
            "reportar diferença entre M1 e M2"
        )
        return result

    if "divergência" in regime:
        result["status"] = (
            "GCI não reportado: sequência divergente"
        )
        return result

    if p < LOW_ORDER_P:
        result["status"] = (
            f"GCI não reportado: ordem aparente baixa (p={p:.3g} < {LOW_ORDER_P})"
        )
        return result

    s = 1.0 if "monotônica" in regime else -1.0
    denom21 = r21 ** p - s
    denom32 = r32 ** p - s
    if denom21 <= 1e-30 or denom32 <= 1e-30:
        result["status"] = "GCI não calculado: denominador inválido"
        return result

    gci21 = Fs * ea21 / denom21 if ea21 is not None else None
    gci32 = Fs * ea32 / denom32 if ea32 is not None else None
    phi_ext = (r21 ** p * phi1 - s * phi2) / denom21
    ar = (
        gci32 / (r21 ** p * gci21)
        if gci21 is not None and gci32 is not None
        and abs(r21 ** p * gci21) > 1e-30 else None
    )

    if "oscilatória" in regime:
        status = "GCI calculado com ressalvas: sequência oscilatória"
    elif ar is None or not math.isfinite(ar):
        status = "GCI calculado com ressalvas: razão assintótica indisponível"
    elif abs(ar - 1.0) > ASYMPTOTIC_TOL:
        status = "GCI calculado com ressalvas: fora da tolerância assintótica"
    else:
        status = "GCI calculado: sequência monotônica e razão assintótica próxima de 1"

    result.update({
        "GCI21_pct": gci21 * 100 if gci21 is not None else float("nan"),
        "GCI32_pct": gci32 * 100 if gci32 is not None else float("nan"),
        "phi_ext21": phi_ext,
        "asymptotic_ratio": ar,
        "status": status,
        "gci_ok": True,
    })
    return result


# ------------------------- ORQUESTRAÇÃO ---------------------------------------

def add_result(all_results, case, variable, records_by_mesh):
    stats = {m: window_stats(records_by_mesh[m]) for m in MESHES}
    if any(stats[m] is None for m in MESHES):
        counts = {m: (stats[m]["n"] if stats[m] else 0) for m in MESHES}
        print(f"  [SEM JANELA COMPLETA {WINDOW}] {variable}: amostras={counts}")
        return

    vals = {m: stats[m]["mean"] for m in MESHES}
    res = calculate_gci(
        phi1=vals["M2"], phi2=vals["M1"], phi3=vals["M0"],
        N1=CELL_COUNTS["M2"], N2=CELL_COUNTS["M1"], N3=CELL_COUNTS["M0"],
    )

    cv_max = max(stats[m]["cv_pct"] for m in MESHES)
    drift_max = max(stats[m]["drift_pct"] for m in MESHES)
    ea = res["ea21_pct"]
    if (ea is not None and math.isfinite(ea) and math.isfinite(cv_max)
            and ea < NOISE_FACTOR * cv_max):
        res["status"] += " | diferença M1→M2 comparável ao CV temporal (heurístico)"

    res.update({
        "Caso": case,
        "Variável": variable,
        "janela_s": f"{WINDOW[0]}-{WINDOW[1]}",
        "media_M0": vals["M0"],
        "media_M1": vals["M1"],
        "media_M2": vals["M2"],
        "n_M0": stats["M0"]["n"],
        "n_M1": stats["M1"]["n"],
        "n_M2": stats["M2"]["n"],
        "cv_M0_pct": stats["M0"]["cv_pct"],
        "cv_M1_pct": stats["M1"]["cv_pct"],
        "cv_M2_pct": stats["M2"]["cv_pct"],
        "cv_max_pct": cv_max,
        "deriva_M0_pct": stats["M0"]["drift_pct"],
        "deriva_M1_pct": stats["M1"]["drift_pct"],
        "deriva_M2_pct": stats["M2"]["drift_pct"],
        "deriva_max_pct": drift_max,
    })
    all_results.append(res)

    print(
        f"  {variable}: M0={vals['M0']:.8g}; M1={vals['M1']:.8g}; "
        f"M2={vals['M2']:.8g} | R={fmt(res['R'])}; p={fmt(res['p'])}; "
        f"M1→M2={fmt(res['ea21_pct'], '%')}"
    )
    if res["gci_ok"]:
        print(
            f"    GCI21={fmt(res['GCI21_pct'], '%')}; "
            f"GCI32={fmt(res['GCI32_pct'], '%')}; "
            f"razão assintótica={fmt(res['asymptotic_ratio'])} | {res['status']}"
        )
    else:
        print(f"    [GCI NÃO REPORTADO] {res['status']}")


def main():
    all_results = []

    print(f"ANÁLISE GCI — janela temporal {WINDOW[0]} a {WINDOW[1]} s")
    print("M0=grossa | M1=intermediária | M2=fina")
    print("Médias temporais calculadas por integração trapezoidal.\n")

    for case in CASES:
        print(f"\n{'=' * 18} {case} {'=' * 18}")

        # Atrito: forças integradas de cada parede, soma total das duas
        # paredes e área ponderada total. O GCI principal é o da força total.
        for label, column in FRICTION_METRICS.items():
            if column == "__forca_atrito_total_paredes_N":
                records = {
                    mesh: load_total_friction_records(mesh, case)
                    for mesh in MESHES
                }
            else:
                records = {
                    mesh: load_friction_records(mesh, case, column)
                    for mesh in MESHES
                }

            # Para as forças individuais, evita GCI quando a respectiva parede
            # está praticamente seca em qualquer malha. A força total continua
            # sendo calculada, pois pode ser dominada pela outra parede.
            wall_area_column = {
                "integral_tau_ponderada_interna_N": "area_ponderada_oleo_interna_m2",
                "integral_tau_ponderada_externa_N": "area_ponderada_oleo_externa_m2",
            }.get(column)
            if wall_area_column:
                dry_meshes = []
                for mesh in MESHES:
                    area_records = load_friction_records(
                        mesh, case, wall_area_column
                    )
                    area_stats = window_stats(area_records)
                    # Cobertura incompleta não significa parede seca.
                    if area_stats is None:
                        continue
                    if area_stats["mean"] < MIN_WET_AREA_M2:
                        dry_meshes.append(mesh)
                if dry_meshes:
                    print(
                        f"  [NÃO APLICÁVEL] {label}: parede praticamente "
                        f"seca em {', '.join(dry_meshes)}; GCI individual não calculado."
                    )
                    continue

            add_result(all_results, case, label, records)

        # Vazão central: integra a componente Y de U no plano_meio,
        # conforme o analisador separado log.QOleoMeio.
        q_records = {
            mesh: extract_qoleo_meio_records(mesh, case)
            for mesh in MESHES
        }
        add_result(all_results, case, "Vazão de óleo no plano central (L/min)", q_records)

        # Velocidade média central e volume: mantidos dos functionObjects.
        for label, config in FUNCTIONS_MAP.items():
            records = {}
            for mesh in MESHES:
                case_dir = os.path.join(mesh, f"{mesh}_{case}")
                records[mesh] = extract_function_records(
                    case_dir, config["folder"], config["component"]
                )
            add_result(all_results, case, label, records)

    if not all_results:
        print("\nNenhum resultado calculado. Verifique CSVs, pastas e functionObjects.")
        return 2

    df = pd.DataFrame(all_results)
    first_cols = [
        "Caso", "Variável", "janela_s",
        "media_M0", "media_M1", "media_M2",
        "r21", "r32", "R", "p",
        "ea21_pct", "ea32_pct", "GCI21_pct", "GCI32_pct",
        "phi_ext21", "asymptotic_ratio", "regime", "status",
        "n_M0", "n_M1", "n_M2",
        "cv_M0_pct", "cv_M1_pct", "cv_M2_pct", "cv_max_pct",
        "deriva_M0_pct", "deriva_M1_pct", "deriva_M2_pct", "deriva_max_pct",
    ]
    df = df[[c for c in first_cols if c in df.columns]]
    df.to_csv(OUTPUT_CSV, index=False, float_format="%.10g")

    print("\n\nRESUMO GCI")
    display_cols = [
        "Caso", "Variável", "media_M0", "media_M1", "media_M2",
        "R", "p", "ea21_pct", "GCI21_pct", "GCI32_pct",
        "asymptotic_ratio", "status",
    ]
    print(df[[c for c in display_cols if c in df.columns]].to_string(index=False))
    print(f"\nRelatório salvo em: {OUTPUT_CSV}")
    print(
        "\nNOTAS:\n"
        "- O CSV consolidado de atrito deve conter integrais em N e áreas em m².\n"
        "- QOleoMeio é lido de functionObjects_temporais.csv e convertido de m³/s para L/min.\n"
        "- O GCI só é reportado quando a sequência e a ordem aparente atendem "
        "aos critérios implementados.\n"
        "- CV e deriva são diagnósticos temporais; a comparação com o CV é "
        "heurística, não um critério universal de independência.\n"
        "- A média temporal trapezoidal exige cobertura completa de 3 a 6 s "
        "em todas as malhas do caso."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
