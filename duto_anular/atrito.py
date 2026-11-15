"""Atrito nas paredes a partir dos campos gravados e da malha.

Mesmo cálculo de ``calcular_atrito_paredes.py`` / ``consolidar_brutos_final_v1.4.0.py``
(as forças de atrito e a área ponderada do TCC vêm daqui), reescrito com numpy
para ler as malhas grandes mais rápido. Para cada face das paredes:

    alpha_face = alpha.oil da célula dona da face, limitado a [0, 1]
    tau_face   = |wallShearStress| da face   (cinemático, m²/s²)

    área ponderada   = soma(alpha_face x área)
    força de atrito  = rho x soma(alpha_face x área x tau_face)        [N]
    tensão média     = força / área ponderada                          [Pa]

A força é a integral do MÓDULO da tensão; não é a resultante vetorial axial.
O segundo método (só faces com alpha.oil >= 0,99) é mantido para comparação.

Precisa, em cada caso, de:
    constant/polyMesh/{boundary, points, faces, owner}
    <tempo>/alpha.oil   e   <tempo>/wallShearStress        (formato ascii)
"""
from __future__ import annotations

import re
import time
import warnings
from pathlib import Path

import numpy as np

from .casos import RHO_OLEO, TEMPO_RE

PAREDES = ("interna", "externa")
ALPHA_MINIMO_FILTRO = 0.99

COLUNAS_USADAS_NO_TCC = (
    "integral_tau_ponderada_interna_N",
    "integral_tau_ponderada_externa_N",
    "integral_tau_ponderada_total_N",
    "area_ponderada_oleo_interna_m2",
    "area_ponderada_oleo_externa_m2",
    "area_ponderada_oleo_total_m2",
    "tau_media_interna_Pa",
    "tau_media_externa_Pa",
    "tau_media_global_Pa",
)


class ErroLeitura(RuntimeError):
    pass


def _texto(caminho: Path) -> str:
    if not caminho.is_file():
        if caminho.with_name(caminho.name + ".gz").is_file():
            raise ErroLeitura(f"{caminho.name} está compactado (.gz); descompacte antes.")
        raise ErroLeitura(f"Arquivo não encontrado: {caminho}")
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    if re.search(r"\bformat\s+binary\s*;", texto[:2000]):
        raise ErroLeitura(f"{caminho.name} está em formato binário; converta para ascii "
                          "(foamFormatConvert).")
    return texto


def _numeros(texto: str, esperado: int, nome: str) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        valores = np.fromstring(texto, sep=" ")
    if valores.size != esperado:
        raise ErroLeitura(f"{nome}: esperados {esperado} números, lidos {valores.size}")
    return valores


# ---------------------------------------------------------------------------
# Malha
# ---------------------------------------------------------------------------
def ler_patches(caminho: Path) -> dict:
    texto = _texto(caminho)
    patches = {}
    for nome in PAREDES:
        bloco = re.search(rf"\bparede_{nome}\s*\{{(.*?)\}}", texto, re.S)
        if not bloco:
            raise ErroLeitura(f"Patch parede_{nome} não encontrado em {caminho}")
        n_faces = re.search(r"\bnFaces\s+(\d+)\s*;", bloco.group(1))
        inicio = re.search(r"\bstartFace\s+(\d+)\s*;", bloco.group(1))
        if not n_faces or not inicio:
            raise ErroLeitura(f"nFaces/startFace ausentes em parede_{nome}")
        patches[nome] = {"nFaces": int(n_faces.group(1)),
                         "startFace": int(inicio.group(1))}
    return patches


def ler_pontos(caminho: Path) -> np.ndarray:
    texto = _texto(caminho)
    # Pula o cabeçalho FoamFile para não confundir com números dele.
    fim_cabecalho = texto.find("}") + 1 if "FoamFile" in texto[:2000] else 0
    inicio = re.compile(r"\b(\d+)\s*\(").search(texto, fim_cabecalho)
    if not inicio:
        raise ErroLeitura(f"Lista de pontos não encontrada: {caminho}")
    n = int(inicio.group(1))
    fim = texto.rfind(")")
    conteudo = texto[inicio.end():fim].replace("(", " ").replace(")", " ")
    return _numeros(conteudo, 3 * n, "points").reshape(n, 3)


def _linhas_da_lista(caminho: Path, primeiro: int, ultimo: int):
    """Percorre uma lista 'um item por linha' e devolve os itens do intervalo."""
    if not caminho.is_file():
        raise ErroLeitura(f"Arquivo não encontrado: {caminho}")
    aberto = False
    indice = 0
    with caminho.open(encoding="utf-8", errors="replace") as f:
        for linha in f:
            s = linha.strip()
            if not aberto:
                aberto = (s == "(")
                continue
            if indice > ultimo:
                break
            if indice >= primeiro:
                yield indice, s
            indice += 1


def ler_donos(caminho: Path, primeiro: int, ultimo: int) -> np.ndarray:
    try:
        donos = [int(s) for _, s in _linhas_da_lista(caminho, primeiro, ultimo)]
    except ValueError as exc:
        raise ErroLeitura(f"owner: linha inválida ({exc})") from exc
    if len(donos) != ultimo - primeiro + 1:
        raise ErroLeitura("owner: quantidade de faces diferente do esperado")
    return np.asarray(donos, dtype=np.int64)


def ler_faces(caminho: Path, primeiro: int, ultimo: int) -> list[list[int]]:
    faces = []
    padrao = re.compile(r"\d+\(([^()]*)\)")
    for indice, s in _linhas_da_lista(caminho, primeiro, ultimo):
        m = padrao.search(s)
        if not m:
            raise ErroLeitura(f"faces: face {indice} inválida")
        faces.append([int(x) for x in m.group(1).split()])
    if len(faces) != ultimo - primeiro + 1:
        raise ErroLeitura("faces: quantidade de faces diferente do esperado")
    return faces


def areas_das_faces(pontos: np.ndarray, faces: list[list[int]]) -> np.ndarray:
    """Área de cada face: 0,5 x |soma dos produtos vetoriais dos vértices|."""
    areas = np.empty(len(faces))
    por_tamanho: dict[int, list[int]] = {}
    for i, face in enumerate(faces):
        por_tamanho.setdefault(len(face), []).append(i)
    for _, indices in por_tamanho.items():
        vertices = pontos[np.asarray([faces[i] for i in indices], dtype=np.int64)]
        soma = np.cross(vertices, np.roll(vertices, -1, axis=1)).sum(axis=1)
        areas[indices] = 0.5 * np.linalg.norm(soma, axis=1)
    return areas


def preparar_malha(pasta_malha: Path) -> dict:
    """Lê a malha uma vez por caso: dono e área de cada face das paredes."""
    patches = ler_patches(pasta_malha / "boundary")
    pontos = ler_pontos(pasta_malha / "points")
    primeiro = min(p["startFace"] for p in patches.values())
    ultimo = max(p["startFace"] + p["nFaces"] for p in patches.values()) - 1
    donos = ler_donos(pasta_malha / "owner", primeiro, ultimo)
    areas = areas_das_faces(pontos, ler_faces(pasta_malha / "faces", primeiro, ultimo))
    malha = {}
    for nome, patch in patches.items():
        fatia = slice(patch["startFace"] - primeiro,
                      patch["startFace"] - primeiro + patch["nFaces"])
        malha[nome] = {"dono": donos[fatia], "area": areas[fatia],
                       "nFaces": patch["nFaces"]}
    return malha


# ---------------------------------------------------------------------------
# Campos
# ---------------------------------------------------------------------------
def ler_campo_escalar(caminho: Path):
    """internalField de um campo escalar: array (nonuniform) ou float (uniform)."""
    texto = _texto(caminho)
    pos = texto.find("internalField")
    if pos < 0:
        raise ErroLeitura(f"internalField não encontrado em {caminho.name}")
    uniforme = re.compile(r"internalField\s+uniform\s+([-+0-9.eE]+)\s*;").match(texto, pos)
    if uniforme:
        return float(uniforme.group(1))
    lista = re.compile(r"\b(\d+)\s*\(").search(texto, pos)
    if not lista:
        raise ErroLeitura(f"Lista de valores não encontrada em {caminho.name}")
    n = int(lista.group(1))
    fim = texto.find(")", lista.end())
    return _numeros(texto[lista.end():fim], n, caminho.name)


def ler_vetores_do_patch(caminho: Path, patch: str, n_faces: int) -> np.ndarray:
    """Valores vetoriais de um patch em boundaryField: array (n_faces, 3)."""
    texto = _texto(caminho)
    inicio = texto.find("boundaryField")
    bloco = re.compile(rf"\b{re.escape(patch)}\s*\{{").search(texto, max(inicio, 0))
    if not bloco:
        raise ErroLeitura(f"Patch {patch} não encontrado em {caminho.name}")
    fim_bloco = texto.find("}", bloco.end())      # não invade o patch seguinte
    if fim_bloco < 0:
        fim_bloco = len(texto)
    valor = re.compile(r"\bvalue\s+(uniform|nonuniform)\b").search(
        texto, bloco.end(), fim_bloco)
    if not valor:
        raise ErroLeitura(f"'value' não encontrado para {patch} em {caminho.name}")
    if valor.group(1) == "uniform":
        vetor = re.compile(r"\s*\(([^()]*)\)").match(texto, valor.end())
        if not vetor:
            raise ErroLeitura(f"Vetor uniforme inválido para {patch}")
        return np.tile(_numeros(vetor.group(1), 3, patch), (n_faces, 1))
    lista = re.compile(r"List<vector>\s+(\d+)\s*\(").match(
        texto, re.compile(r"\s*").match(texto, valor.end()).end())
    if not lista:
        raise ErroLeitura(f"Lista vetorial não encontrada para {patch}")
    n = int(lista.group(1))
    if n != n_faces:
        raise ErroLeitura(f"{patch}: {n} vetores para {n_faces} faces")
    fim = re.compile(r"\)\s*\)").search(texto, lista.end())
    if not fim:
        raise ErroLeitura(f"Fim da lista vetorial não encontrado para {patch}")
    conteudo = texto[lista.end():fim.start() + 1].replace("(", " ").replace(")", " ")
    return _numeros(conteudo, 3 * n, patch).reshape(n, 3)


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------
def atrito_no_tempo(pasta_tempo: Path, malha: dict) -> dict:
    """Atrito nas duas paredes em um instante (dois métodos)."""
    alpha = ler_campo_escalar(pasta_tempo / "alpha.oil")
    linha = {}
    area_total = 0.0
    integral_total = 0.0

    for nome in PAREDES:
        parede = malha[nome]
        tau = ler_vetores_do_patch(pasta_tempo / "wallShearStress",
                                   f"parede_{nome}", parede["nFaces"])
        tau_modulo = np.linalg.norm(tau, axis=1)

        if isinstance(alpha, float):
            alpha_face = np.full(parede["nFaces"], alpha)
        else:
            if parede["dono"].max() >= alpha.size:
                raise ErroLeitura(f"parede_{nome}: célula dona fora do campo alpha.oil")
            alpha_face = alpha[parede["dono"]]
        alpha_face = np.clip(alpha_face, 0.0, 1.0)
        area = parede["area"]

        # Método do TCC: ponderação por alpha.oil x área.
        peso = alpha_face * area
        area_molhada = float(peso.sum())
        integral = float((peso * tau_modulo).sum())

        linha[f"area_geometrica_{nome}_m2"] = float(area.sum())
        linha[f"area_ponderada_oleo_{nome}_m2"] = area_molhada
        linha[f"tau_media_{nome}_Pa"] = (
            integral / area_molhada * RHO_OLEO if area_molhada > 0 else float("nan"))
        linha[f"integral_tau_ponderada_{nome}_N"] = integral * RHO_OLEO

        # Método comparativo: só faces com alpha.oil >= 0,99.
        oleo = alpha_face >= ALPHA_MINIMO_FILTRO
        area_oleo = float(area[oleo].sum())
        integral_oleo = float((area[oleo] * tau_modulo[oleo]).sum())
        linha[f"faces_oleo_{nome}"] = int(oleo.sum())
        linha[f"area_filtrada_oleo_{nome}_m2"] = area_oleo
        linha[f"tau_media_filtrada_{nome}_Pa"] = (
            integral_oleo / area_oleo * RHO_OLEO if area_oleo > 0 else float("nan"))
        linha[f"integral_tau_filtrada_{nome}_N"] = integral_oleo * RHO_OLEO

        area_total += area_molhada
        integral_total += integral * RHO_OLEO

    linha["area_ponderada_oleo_total_m2"] = area_total
    linha["integral_tau_ponderada_total_N"] = integral_total
    linha["tau_media_global_Pa"] = (
        integral_total / area_total if area_total > 0 else float("nan"))
    return linha


def pastas_de_tempo(pasta_caso: Path) -> list[tuple[float, Path]]:
    tempos = [(float(p.name), p) for p in pasta_caso.iterdir()
              if p.is_dir() and TEMPO_RE.fullmatch(p.name)]
    return sorted(tempos, key=lambda x: x[0])


def atrito_do_caso(pasta_caso: Path, avisar=print):
    """Calcula o atrito em todos os tempos do caso.

    Devolve (linhas, ocorrencias). ``linhas`` é uma lista de dicionários com
    ``tempo_s`` e as colunas de atrito; ``ocorrencias`` lista o que faltou.
    """
    ocorrencias = []
    pasta_malha = pasta_caso / "constant" / "polyMesh"
    if not pasta_malha.is_dir():
        ocorrencias.append(("atrito_sem_malha", str(pasta_malha),
                            "constant/polyMesh não encontrado; atrito não calculado.",
                            "revisar"))
        return [], ocorrencias
    try:
        malha = preparar_malha(pasta_malha)
    except (ErroLeitura, OSError, ValueError) as exc:
        ocorrencias.append(("atrito_falha_malha", str(pasta_malha), str(exc), "erro"))
        return [], ocorrencias

    linhas = []
    ultimo_aviso = time.monotonic()
    tempos = pastas_de_tempo(pasta_caso)
    for i, (t, pasta_tempo) in enumerate(tempos, 1):
        faltam = [n for n in ("alpha.oil", "wallShearStress")
                  if not (pasta_tempo / n).is_file()]
        if faltam:
            # t = 0 nunca tem wallShearStress: não é problema.
            if t > 0:
                ocorrencias.append(("atrito_tempo_sem_campos", str(pasta_tempo),
                                    f"faltam: {', '.join(faltam)}", "revisar"))
            continue
        try:
            linhas.append({"tempo_s": t, **atrito_no_tempo(pasta_tempo, malha)})
        except (ErroLeitura, OSError, ValueError) as exc:
            ocorrencias.append(("atrito_falha_calculo", str(pasta_tempo), str(exc), "erro"))
        # Malhas grandes demoram: avisa o andamento a cada 20 s.
        if avisar and time.monotonic() - ultimo_aviso > 20:
            avisar(f"      atrito: {i}/{len(tempos)} tempos lidos")
            ultimo_aviso = time.monotonic()
    return linhas, ocorrencias
