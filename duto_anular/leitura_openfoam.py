"""Leitura dos arquivos de ``postProcessing/`` do OpenFOAM.

Pontos tratados aqui (eram fonte de erro nos scripts antigos):

* Reinícios da simulação: o OpenFOAM abre uma pasta nova a cada reinício
  (``0/``, ``0.249825/``, ``4.9997.../``). TODOS os trechos são lidos e unidos.
* ``surfaceFieldValue.dat`` vazio com os dados em ``surfaceFieldValue_<t>.dat``.
* Cópias idênticas do mesmo registro (comum nas funções rodadas com
  ``postProcess``): contam uma vez só.
* Mesmo tempo com valores diferentes em dois trechos: vale o trecho do
  reinício mais recente, e o conflito é registrado para revisão.
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path

NUM_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
CASAS_TEMPO = 9      # tempos iguais até 1e-9 s são o mesmo instante


def chave_tempo(t: float) -> float:
    return round(float(t), CASAS_TEMPO)


# ---------------------------------------------------------------------------
# Arquivos .dat das function objects
# ---------------------------------------------------------------------------
def ler_dat(caminho: Path) -> tuple[dict, list[dict]]:
    """Lê um .dat. Devolve (cabecalho, registros).

    cabecalho: regiao, faces, area_m2, celulas, volume_m3, peso, operacao.
    registros: {"linha", "tempo_s", "valores", "patch"} — ``valores`` tem
    1 número (escalar), 3 (vetor) ou 6 (mínimo e máximo de wallShear).
    """
    cabecalho = {"regiao": "", "faces": "", "area_m2": "", "celulas": "",
                 "volume_m3": "", "peso": "", "operacao": ""}
    registros = []
    texto = caminho.read_text(encoding="utf-8", errors="replace")

    for n_linha, linha in enumerate(texto.splitlines(), 1):
        s = linha.strip()
        if not s or s.startswith("//"):
            continue

        if s.startswith("#"):
            h = s[1:].strip()
            baixo = h.lower()
            valor = h.split(":", 1)[-1].strip()
            if baixo.startswith("region"):
                cabecalho["regiao"] = valor
            elif baixo.startswith("faces"):
                cabecalho["faces"] = valor
            elif baixo.startswith("area"):
                cabecalho["area_m2"] = valor
            elif baixo.startswith("cells"):
                cabecalho["celulas"] = valor
            elif baixo.startswith("volume"):
                cabecalho["volume_m3"] = valor
            elif baixo.startswith("weight field"):
                cabecalho["peso"] = valor
            elif baixo.startswith("time"):
                partes = h.split(None, 1)
                cabecalho["operacao"] = partes[1].strip() if len(partes) > 1 else ""
            continue

        partes = s.split(None, 1)
        if len(partes) != 2:
            continue
        try:
            tempo = float(partes[0])
        except ValueError:
            continue

        resto = partes[1]
        patch = ""
        # wallShear: "tempo  patch  (min)  (max)"
        if not resto.lstrip().startswith(("(", "-", "+", ".")) and \
                not resto.lstrip()[:1].isdigit():
            pedacos = resto.split(None, 1)
            patch = pedacos[0]
            resto = pedacos[1] if len(pedacos) > 1 else ""

        try:
            valores = [float(x) for x in NUM_RE.findall(resto)]
        except ValueError:
            continue
        if len(valores) not in (1, 3, 6) or not math.isfinite(tempo):
            continue
        if not all(math.isfinite(v) for v in valores):
            continue
        registros.append({"linha": n_linha, "tempo_s": tempo,
                          "valores": valores, "patch": patch})
    return cabecalho, registros


def _inicio_trecho(arquivo: Path, pasta_funcao: Path) -> float:
    """Tempo de início do trecho = nome da pasta logo abaixo da função."""
    try:
        return float(arquivo.relative_to(pasta_funcao).parts[0])
    except (ValueError, IndexError):
        return -1.0


def ler_funcao(pasta_funcao: Path):
    """Lê todos os .dat de uma function object e une os trechos.

    Devolve (serie, arquivos, conflitos):
      serie      {chave_tempo: registro} com 1 registro por instante; cada
                 registro ganha "arquivo" e "cabecalho";
      arquivos   lista de {"arquivo", "cabecalho", "n_registros"};
      conflitos  lista de {"tempo_s", "mantido", "descartado", ...}.
    """
    arquivos_dat = sorted(
        (p for p in pasta_funcao.rglob("*.dat") if p.is_file()),
        key=lambda p: (_inicio_trecho(p, pasta_funcao), p.name),
    )
    serie: dict[float, dict] = {}
    arquivos, conflitos = [], []

    for arquivo in arquivos_dat:
        cabecalho, registros = ler_dat(arquivo)
        arquivos.append({"arquivo": arquivo, "cabecalho": cabecalho,
                         "n_registros": len(registros)})
        inicio = _inicio_trecho(arquivo, pasta_funcao)
        for reg in registros:
            reg = {**reg, "arquivo": arquivo, "cabecalho": cabecalho,
                   "inicio_trecho": inicio}
            chave = (chave_tempo(reg["tempo_s"]), reg["patch"])
            anterior = serie.get(chave)
            if anterior is None:
                serie[chave] = reg
                continue
            if anterior["valores"] == reg["valores"]:
                continue                       # cópia idêntica
            # Conflito: vale o reinício mais recente (trecho de maior início).
            if reg["inicio_trecho"] >= anterior["inicio_trecho"]:
                mantido, descartado = reg, anterior
                serie[chave] = reg
            else:
                mantido, descartado = anterior, reg
            conflitos.append({
                "tempo_s": reg["tempo_s"],
                "mantido": mantido["valores"], "arquivo_mantido": mantido["arquivo"],
                "descartado": descartado["valores"],
                "arquivo_descartado": descartado["arquivo"],
            })
    return serie, arquivos, conflitos


def valor_da_funcao(valores: list[float], componente: int | None, fator: float) -> float:
    """Converte o registro bruto no valor tratado (componente/módulo x fator)."""
    if len(valores) == 1:
        return valores[0] * fator
    if len(valores) == 3:
        if componente is None:
            return math.sqrt(sum(v * v for v in valores)) * fator
        return valores[componente] * fator
    return float("nan")


# ---------------------------------------------------------------------------
# Perfis de linha (function object "sets", formato csv)
# ---------------------------------------------------------------------------
def _numero(texto):
    try:
        v = float(texto)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def ler_perfil(caminho: Path) -> list[tuple]:
    """Lê um perfil csv: lista de (z, alpha, Ux, Uy, Uz), ordenada em z."""
    pontos = []
    with caminho.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        for linha in csv.DictReader(f):
            z = _numero(linha.get("z"))
            alpha = _numero(linha.get("alpha.oil"))
            if z is None or alpha is None:
                continue
            pontos.append((z, alpha, _numero(linha.get("U_0")),
                           _numero(linha.get("U_1")), _numero(linha.get("U_2"))))
    return sorted(pontos, key=lambda p: p[0])


def _media_trapezio(x, y):
    if len(x) < 2 or x[-1] <= x[0]:
        return sum(y) / len(y) if y else None
    integral = sum((y[i] + y[i + 1]) * 0.5 * (x[i + 1] - x[i])
                   for i in range(len(x) - 1))
    return integral / (x[-1] - x[0])


def _ramos(pontos, salto=0.01):
    """Separa a linha em ramos quando ela atravessa o tubo interno."""
    ramos, atual = [], []
    for p in pontos:
        if atual and p[0] - atual[-1][0] > salto:
            ramos.append(atual)
            atual = []
        atual.append(p)
    if atual:
        ramos.append(atual)
    return ramos


def _cruzamentos(ramo, nivel=0.5):
    saida = []
    for (z0, a0, *_), (z1, a1, *_) in zip(ramo, ramo[1:]):
        if a0 == nivel:
            saida.append(z0)
        if (a0 - nivel) * (a1 - nivel) < 0:
            saida.append(z0 + (nivel - a0) * (z1 - z0) / (a1 - a0))
    if ramo and ramo[-1][1] == nivel:
        saida.append(ramo[-1][0])
    limpo = []
    for z in sorted(saida):
        if not limpo or abs(z - limpo[-1]) > 1e-10:
            limpo.append(z)
    return limpo


def _medias_por_fase(ramo, nivel=0.5):
    """Média de Uy em cada fase ao longo da linha, cortando em alpha = nivel."""
    acum = {"oleo": [0.0, 0.0], "ar": [0.0, 0.0]}
    validos = [(z, a, uy) for z, a, _, uy, _ in ramo if uy is not None]
    for (z0, a0, u0), (z1, a1, u1) in zip(validos, validos[1:]):
        dz = abs(z1 - z0)
        if dz <= 0:
            continue
        cortes = [(0.0, a0, u0), (1.0, a1, u1)]
        if (a0 - nivel) * (a1 - nivel) < 0:
            f = (nivel - a0) / (a1 - a0)
            cortes.insert(1, (f, nivel, u0 + f * (u1 - u0)))
        for (f0, aa0, uu0), (f1, aa1, uu1) in zip(cortes, cortes[1:]):
            meio = (aa0 + aa1) * 0.5
            if meio == nivel:
                continue
            fase = "oleo" if meio > nivel else "ar"
            comprimento = dz * (f1 - f0)
            acum[fase][0] += 0.5 * (uu0 + uu1) * comprimento
            acum[fase][1] += comprimento
    return {fase: (soma / comp if comp > 0 else None, comp)
            for fase, (soma, comp) in acum.items()}


def resumir_perfil(pontos: list[tuple]) -> list[dict]:
    """Resume um perfil: interface (alpha = 0,5) e Uy médio por fase, por ramo.

    São amostras de UMA linha: servem de diagnóstico e não representam médias
    de seção transversal.
    """
    saida = []
    for i, ramo in enumerate(_ramos(pontos), 1):
        z = [p[0] for p in ramo]
        alpha = [p[1] for p in ramo]
        cruz = _cruzamentos(ramo)
        fases = _medias_por_fase(ramo)
        com_u = [(p[0], p[3]) for p in ramo if p[3] is not None]
        saida.append({
            "ramo": i,
            "n_pontos": len(ramo),
            "z_min_m": min(z),
            "z_max_m": max(z),
            "alpha_medio_linha": _media_trapezio(z, alpha),
            "z_interface_m": cruz[0] if cruz else None,
            "n_cruzamentos_interface": len(cruz),
            "Uy_medio_linha_m_s": _media_trapezio([p[0] for p in com_u],
                                                  [p[1] for p in com_u]) if com_u else None,
            "Uy_medio_oleo_m_s": fases["oleo"][0],
            "Uy_medio_ar_m_s": fases["ar"][0],
            "comprimento_oleo_m": fases["oleo"][1],
            "comprimento_ar_m": fases["ar"][1],
        })
    return saida
