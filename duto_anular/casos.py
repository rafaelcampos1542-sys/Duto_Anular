"""Nomes dos casos, malhas e constantes usadas em todo o pós-processamento.

Um caso é uma pasta chamada  M<malha>_Q<vazão>[_R<raiz>], por exemplo:
    M1_Q35      malha M1, vazão nominal de 35 L/min        (caso base)
    M1_Q20_R2   malha M1, 20 L/min, inicializado na raiz 2  (multiplicidade)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .modelo_anular import G, RHO as RHO_OLEO   # noqa: F401 — 9,81 m/s² e 900 kg/m³ (fonte única)

L_MIN = 60000.0           # 1 m³/s = 60000 L/min

# --- Estudo de malha ----------------------------------------------------------
MALHAS = ("M0", "M1", "M2")                 # grossa, intermediária, fina
N_CELULAS = {"M0": 480_000, "M1": 1_620_000, "M2": 5_491_800}
VAZOES_BASE = ("Q10", "Q35", "Q60")         # fora da região de multiplicidade
MALHA_REFERENCIA = "M1"

# --- Estudo de multiplicidade -------------------------------------------------
VAZOES_MULTIPLICIDADE = ("Q20", "Q55")
RAIZES = (1, 2, 3)

# --- Janelas temporais padrão [s] ----------------------------------------------
JANELA_MEDIA = (3.0, 6.0)      # médias temporais (GCI, vazão central, Tabela 7)
JANELA_BALANCO = (5.0, 6.0)    # balanço volumétrico e taxas de variação
T_REFERENCIA = 5.0             # instante das Tabelas 4 e 6

CASO_RE = re.compile(r"^(M[0-9]+)_Q([0-9]+)(?:_(R[0-9]+))?$", re.I)
TEMPO_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")

# Pastas que nunca contêm casos válidos.
PASTAS_IGNORADAS = {".git", ".venv", "venv", "__pycache__", "constant", "system",
                    "postprocessing", "dynamiccode", "legado"}
PREFIXOS_IGNORADOS = ("backup", "resultados", "dados_extraidos", "processor")


def info_caso(caso_id: str) -> dict:
    """Separa o nome do caso em malha, vazão nominal e raiz."""
    m = CASO_RE.fullmatch(caso_id)
    if not m:
        return {"caso_id": caso_id, "grupo": "nao_classificado", "malha": "",
                "vazao": "", "Q_nominal_L_min": float("nan"), "raiz": ""}
    malha, vazao, raiz = m.groups()
    return {
        "caso_id": caso_id,
        "grupo": "multiplicidade" if raiz else "base",
        "malha": malha.upper(),
        "vazao": f"Q{vazao}",
        "Q_nominal_L_min": float(vazao),
        "raiz": raiz.upper() if raiz else "",
    }


def nome_caso(malha: str, vazao: str, raiz: int | str | None = None) -> str:
    """Monta o nome do caso: nome_caso('M1', 'Q20', 2) -> 'M1_Q20_R2'."""
    if raiz in (None, ""):
        return f"{malha}_{vazao}"
    raiz = str(raiz).upper().lstrip("R")
    return f"{malha}_{vazao}_R{raiz}"


def _ignorar(nome: str) -> bool:
    baixo = nome.lower()
    return baixo in PASTAS_IGNORADAS or baixo.startswith(PREFIXOS_IGNORADOS)


def descobrir_casos(raiz: Path, ignorar: Path | None = None):
    """Procura pastas de caso abaixo de ``raiz``.

    Retorna (casos, duplicados):
      casos       {caso_id: Path} — uma pasta por caso;
      duplicados  {caso_id: [Path, ...]} — casos achados em mais de um lugar.

    Quando o mesmo caso aparece em dois lugares (ex.: na raiz e dentro de M1/),
    vale a pasta mais próxima da raiz; as outras são listadas em ``duplicados``.
    Não desce em pastas de backup, de resultados, processor*, nem dentro de um
    caso já encontrado.
    """
    raiz = raiz.resolve()
    ignorar = ignorar.resolve() if ignorar else None
    achados: dict[str, list[Path]] = {}

    # A própria raiz pode ser um caso (ex.: --raiz M1/M1_Q35).
    if CASO_RE.fullmatch(raiz.name):
        return {raiz.name.upper(): raiz}, {}

    for atual, pastas, _ in os.walk(raiz):
        atual_p = Path(atual)
        manter = []
        for nome in sorted(pastas):
            caminho = atual_p / nome
            if ignorar and (caminho == ignorar or ignorar in caminho.parents):
                continue
            if _ignorar(nome) or TEMPO_RE.fullmatch(nome):
                continue
            if CASO_RE.fullmatch(nome):
                achados.setdefault(nome.upper(), []).append(caminho)
                continue                      # não desce dentro do caso
            manter.append(nome)
        pastas[:] = manter

    casos, duplicados = {}, {}
    for caso_id, caminhos in sorted(achados.items()):
        caminhos.sort(key=lambda p: (len(p.relative_to(raiz).parts), str(p)))
        casos[caso_id] = caminhos[0]
        if len(caminhos) > 1:
            duplicados[caso_id] = caminhos
    return casos, duplicados
