"""Médias temporais e índice de convergência de malha (GCI).

As contas são as mesmas dos scripts usados no TCC:

* ``media_na_janela``  — média trapezoidal em uma janela exata, com os extremos
  interpolados (era ``window_stats`` em analise_gci_celik_atrito_total.py);
* ``media_dos_registros`` — média e desvio trapezoidais sobre os próprios
  registros (era ``estatistica_temporal`` em comparar_analitico_cfd_R.py);
* ``calcular_gci`` — procedimento de Celik et al. (2008).
"""
from __future__ import annotations

import math

import numpy as np

_trapezio = getattr(np, "trapezoid", None) or np.trapz   # numpy 1.x e 2.x

# --- Parâmetros do GCI --------------------------------------------------------
FS = 1.25                 # fator de segurança (três malhas)
DIMENSAO = 3
ORDEM_MINIMA = 0.5        # abaixo disso o GCI não é reportado
TOLERANCIA_ASSINTOTICA = 0.10
TOLERANCIA_JANELA = 0.01  # folga para tempos gravados como 2,9998 ou 5,9997 s
MINIMO_DE_PONTOS = 4


def _limpar(tempos, valores):
    """Ordena, remove NaN e tempos repetidos (fica o último)."""
    t = np.asarray(tempos, dtype=float)
    v = np.asarray(valores, dtype=float)
    ok = np.isfinite(t) & np.isfinite(v)
    unicos = {}
    for ti, vi in sorted(zip(t[ok], v[ok]), key=lambda par: par[0]):
        unicos[ti] = vi
    t = np.array(sorted(unicos))
    return t, np.array([unicos[x] for x in t])


def media_na_janela(tempos, valores, janela, tolerancia=TOLERANCIA_JANELA,
                    minimo_de_pontos=MINIMO_DE_PONTOS):
    """Média trapezoidal na janela [t0, t1].

    Os valores em t0 e t1 são interpolados linearmente. Se a série começa até
    ``tolerancia`` depois de t0 (ou termina até ``tolerancia`` antes de t1),
    a janela é encurtada para o tempo disponível. Devolve None se a série não
    cobre a janela ou tem menos de ``minimo_de_pontos`` registros dentro dela.

    cv_pct     desvio padrão amostral / média das amostras da janela
    deriva_pct |valor final - valor inicial| / |média|
    """
    t, v = _limpar(tempos, valores)
    if t.size == 0:
        return None
    t0, t1 = janela
    if t[0] > t0 + tolerancia or t[-1] < t1 - tolerancia:
        return None
    t0 = t0 if t[0] <= t0 else t[0]
    t1 = t1 if t[-1] >= t1 else t[-1]

    dentro = (t >= t0) & (t <= t1)
    if dentro.sum() < minimo_de_pontos:
        return None

    v0 = float(np.interp(t0, t, v))
    v1 = float(np.interp(t1, t, v))
    miolo = (t > t0) & (t < t1)
    tw = np.concatenate(([t0], t[miolo], [t1]))
    vw = np.concatenate(([v0], v[miolo], [v1]))
    media = float(_trapezio(vw, tw) / (t1 - t0))

    amostras = v[dentro]
    if amostras.size > 1 and amostras.mean() != 0:
        cv = abs(float(amostras.std(ddof=1) / amostras.mean())) * 100
    else:
        cv = float("nan")
    deriva = abs(v1 - v0) / abs(media) * 100 if media != 0 else float("nan")
    return {"media": media, "n": int(dentro.sum()), "cv_pct": cv,
            "deriva_pct": deriva, "t_inicial": float(t0), "t_final": float(t1),
            "valor_inicial": v0, "valor_final": v1}


def media_dos_registros(tempos, valores):
    """Média e desvio padrão temporais (trapézio) entre o primeiro e o último
    registro fornecidos. Usada nas estatísticas de Q20 e Q55."""
    t, v = _limpar(tempos, valores)
    if t.size < 2 or t[-1] <= t[0]:
        return None
    duracao = float(t[-1] - t[0])
    media = float(_trapezio(v, t) / duracao)
    variancia = float(_trapezio((v - media) ** 2, t) / duracao)
    desvio = math.sqrt(max(variancia, 0.0))
    return {"media": media, "desvio": desvio,
            "cv_pct": abs(desvio / media) * 100 if media != 0 else float("nan"),
            "minimo": float(v.min()), "maximo": float(v.max()), "n": int(t.size),
            "t_inicial": float(t[0]), "t_final": float(t[-1]), "duracao": duracao}


def taxa_de_variacao(tempos, valores, janela, tolerancia=TOLERANCIA_JANELA):
    """Inclinação da reta ajustada (mínimos quadrados) na janela.

    Devolve {"taxa", "taxa_pct_por_s", "media", "n"} ou None.
    """
    t, v = _limpar(tempos, valores)
    dentro = (t >= janela[0] - tolerancia) & (t <= janela[1] + tolerancia)
    if dentro.sum() < 2:
        return None
    t, v = t[dentro], v[dentro]
    taxa = float(np.polyfit(t - t[0], v, 1)[0])
    media = float(v.mean())
    return {"taxa": taxa, "media": media, "n": int(t.size),
            "taxa_pct_por_s": taxa / abs(media) * 100 if media != 0 else float("nan"),
            "t_inicial": float(t[0]), "t_final": float(t[-1])}


# ---------------------------------------------------------------------------
# GCI — Celik et al. (2008)
# ---------------------------------------------------------------------------
def ordem_aparente(phi1, phi2, phi3, r21, r32, tol=1e-8, itmax=200):
    """Ordem aparente p. phi1 = malha fina, phi2 = média, phi3 = grossa.

    Devolve (p, regime, R), com R = e21/e32.
    """
    if not all(math.isfinite(x) for x in (phi1, phi2, phi3, r21, r32)):
        return None, "dados não finitos", None
    if r21 <= 1.0 or r32 <= 1.0:
        return None, "razão de refinamento inválida", None

    e21 = phi2 - phi1
    e32 = phi3 - phi2
    escala = max(abs(phi1), abs(phi2), abs(phi3), 1.0)
    if abs(e21) <= 1e-14 * escala or abs(e32) <= 1e-14 * escala:
        return None, "diferença entre malhas muito pequena", None

    R = e21 / e32
    if R > 0:
        regime = "convergência monotônica" if R < 1 else "divergência monotônica"
    else:
        regime = "convergência oscilatória" if abs(R) < 1 else "divergência oscilatória"
    if abs(R) >= 1:
        return None, regime, R

    s = 1.0 if e21 * e32 > 0 else -1.0
    log_razao = math.log(abs(e32 / e21))
    log_r21 = math.log(r21)
    p = max(0.1, abs(log_razao) / log_r21)

    def residuo(p_teste):
        try:
            a = r21 ** p_teste - s
            b = r32 ** p_teste - s
            if a <= 0 or b <= 0:
                return None
            return p_teste * log_r21 - abs(log_razao + math.log(a / b))
        except (ValueError, OverflowError, ZeroDivisionError):
            return None

    for _ in range(itmax):
        try:
            numerador = r21 ** p - s
            denominador = r32 ** p - s
            if numerador <= 0 or denominador <= 0:
                return None, regime, R
            q = math.log(numerador / denominador)
            p_novo = abs(log_razao + q) / log_r21
        except (ValueError, OverflowError, ZeroDivisionError):
            return None, regime, R
        if not math.isfinite(p_novo) or p_novo <= 0:
            return None, regime, R
        res = residuo(p_novo)
        if res is not None and abs(res) < tol:
            return p_novo, regime, R
        if abs(p_novo - p) < tol:
            if res is not None and abs(res) < 10 * tol:
                return p_novo, regime, R
            return None, "iteração estabilizou sem resolver a equação", R
        p = p_novo
    return None, "ordem aparente não convergiu", R


def calcular_gci(phi1, phi2, phi3, n1, n2, n3, fs=FS, dimensao=DIMENSAO,
                 ordem_minima=ORDEM_MINIMA):
    """GCI para três malhas. Índice 1 = fina, 2 = média, 3 = grossa.

    O GCI só é reportado para convergência monotônica com p >= ordem_minima.
    """
    r21 = (n1 / n2) ** (1.0 / dimensao)
    r32 = (n2 / n3) ** (1.0 / dimensao)
    ea21 = abs((phi1 - phi2) / phi1) if abs(phi1) > 1e-30 else None
    ea32 = abs((phi2 - phi3) / phi2) if abs(phi2) > 1e-30 else None

    res = {
        "r21": r21, "r32": r32, "R": None, "p": None,
        "ea21_pct": ea21 * 100 if ea21 is not None else float("nan"),
        "ea32_pct": ea32 * 100 if ea32 is not None else float("nan"),
        "GCI21_pct": None, "GCI32_pct": None, "phi_ext21": None,
        "razao_assintotica": None, "regime": "", "status": "",
        "diagnostico": "", "gci_reportado": False,
    }

    p, regime, R = ordem_aparente(phi1, phi2, phi3, r21, r32)
    res["regime"], res["R"] = regime, R
    if p is None:
        res["status"] = "GCI não calculado: " + regime
        res["diagnostico"] = _diagnostico(regime)
        return res
    res["p"] = p

    if "oscilatória" in regime:
        res["status"] = ("GCI não reportado: sequência oscilatória; "
                         "reportar diferença entre M1 e M2")
        res["diagnostico"] = "Oscilatória"
        return res
    if "divergência" in regime:
        res["status"] = "GCI não reportado: sequência divergente"
        res["diagnostico"] = _diagnostico(regime)
        return res
    if p < ordem_minima:
        res["status"] = (f"GCI não reportado: ordem aparente baixa "
                         f"(p={p:.3g} < {ordem_minima})")
        res["diagnostico"] = "Ordem baixa"
        return res

    denom21 = r21 ** p - 1.0
    denom32 = r32 ** p - 1.0
    if denom21 <= 1e-30 or denom32 <= 1e-30:
        res["status"] = "GCI não calculado: denominador inválido"
        res["diagnostico"] = "Não calculado"
        return res

    gci21 = fs * ea21 / denom21 if ea21 is not None else None
    gci32 = fs * ea32 / denom32 if ea32 is not None else None
    phi_ext = (r21 ** p * phi1 - phi2) / denom21
    razao = (gci32 / (r21 ** p * gci21)
             if gci21 is not None and gci32 is not None
             and abs(r21 ** p * gci21) > 1e-30 else None)

    if razao is None or not math.isfinite(razao):
        status = "GCI calculado com ressalvas: razão assintótica indisponível"
        diagnostico = "Favorável, com ressalva"
    elif abs(razao - 1.0) > TOLERANCIA_ASSINTOTICA:
        status = "GCI calculado com ressalvas: fora da tolerância assintótica"
        diagnostico = "Favorável, com ressalva"
    else:
        status = "GCI calculado: sequência monotônica e razão assintótica próxima de 1"
        diagnostico = "Favorável"

    res.update({
        "GCI21_pct": gci21 * 100 if gci21 is not None else float("nan"),
        "GCI32_pct": gci32 * 100 if gci32 is not None else float("nan"),
        "phi_ext21": phi_ext, "razao_assintotica": razao,
        "status": status, "diagnostico": diagnostico, "gci_reportado": True,
    })
    return res


def _diagnostico(regime: str) -> str:
    if "oscilatória" in regime:
        return "Oscilatória"
    if "divergência monotônica" in regime:
        return "Divergência monotônica"
    if "convergência" in regime:
        return "Não calculado"
    return regime.capitalize()
