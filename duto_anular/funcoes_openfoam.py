"""Seleção das function objects do OpenFOAM.

Esta é a ÚNICA lista que decide o que entra nos dados tratados.
Cada pasta de ``postProcessing/`` cai em um destes grupos:

  usada        vira uma coluna de ``series_temporais.csv``;
  descartada   é lida e guardada só em ``brutos/functionObjects.csv``,
               com o motivo do descarte;
  perfil       linhas de amostragem (sampling) — vão para ``perfis_resumo.csv``.

Além do nome da pasta, o cabeçalho de cada .dat é conferido (patch, operação
e campo de peso). Um arquivo com cabeçalho diferente do esperado NÃO entra nos
dados tratados: isso pega, por exemplo, um atrito gravado sem ``weightField``.

Para acrescentar uma função nova, basta incluir uma linha em ``FUNCOES``.
"""
from __future__ import annotations

from dataclasses import dataclass

from .casos import L_MIN, RHO_OLEO


@dataclass(frozen=True)
class Funcao:
    nome: str                    # nome da pasta em postProcessing/
    usada: bool
    descricao: str
    coluna: str = ""             # coluna em series_temporais.csv
    unidade: str = ""
    componente: int | None = None   # vetores: 0=x, 1=y (axial), 2=z; None = módulo
    fator: float = 1.0           # conversão de unidade (e de sinal)
    operacao: str = ""           # operação esperada no cabeçalho do .dat
    peso: str = ""               # campo de peso esperado ("" = sem peso)
    patch: str = ""              # patch esperado ("" = plano de corte ou volume)
    apelidos: tuple = ()         # outros nomes de pasta para a mesma função
    origem: str = "execucao"     # "execucao" (controlDict) ou "pos" (postProcess -func)
    motivo_descarte: str = ""


FUNCOES = (
    # --- Vazões de óleo -------------------------------------------------------
    Funcao("QOleoInlet", True, "Vazão de óleo que entra por inlet_oil",
           coluna="Q_in_L_min", unidade="L/min", fator=-L_MIN,
           operacao="weightedSum(phi)", peso="alpha.oil", patch="inlet_oil"),
    Funcao("QOleoOutlet", True, "Vazão de óleo que sai por outlet",
           coluna="Q_out_L_min", unidade="L/min", fator=L_MIN,
           operacao="weightedSum(phi)", peso="alpha.oil", patch="outlet"),
    Funcao("QOleoInletAir", True, "Vazão de óleo que sai por inlet_air",
           coluna="Q_inlet_air_L_min", unidade="L/min", fator=L_MIN,
           operacao="weightedSum(phi)", peso="alpha.oil", patch="inlet_air",
           origem="pos"),
    Funcao("QOleoMeio", True, "Vazão de óleo no plano central (y = 0)",
           coluna="Q_meio_L_min", unidade="L/min", componente=1, fator=L_MIN,
           operacao="weightedAreaIntegrate(U)", peso="alpha.oil", origem="pos"),
    Funcao("QOleoProximo", True, "Vazão de óleo no plano y = -0,15 m",
           coluna="Q_proximo_L_min", unidade="L/min", componente=1, fator=L_MIN,
           operacao="weightedAreaIntegrate(U)", peso="alpha.oil", origem="pos"),

    # --- Áreas de óleo nas seções (viram altura equivalente h_L) --------------
    Funcao("areaOleoInlet", True, "Área de óleo na entrada (constante)",
           coluna="A_oleo_entrada_m2", unidade="m2",
           operacao="areaIntegrate(alpha.oil)", patch="inlet_oil"),
    Funcao("areaOleoMeio", True, "Área de óleo no plano central",
           coluna="A_oleo_meio_m2", unidade="m2",
           operacao="areaIntegrate(alpha.oil)"),
    Funcao("areaOleoSaida", True, "Área de óleo no plano de saída (y = 0,3 m)",
           coluna="A_oleo_saida_m2", unidade="m2",
           operacao="areaIntegrate(alpha.oil)"),
    Funcao("areaOleoProximo", True, "Área de óleo no plano y = -0,15 m",
           coluna="A_oleo_proximo_m2", unidade="m2",
           operacao="areaIntegrate(alpha.oil)", origem="pos"),

    # --- Velocidade e volume --------------------------------------------------
    Funcao("velocidadePonderada", True,
           "Velocidade axial média do óleo no plano central (ponderada por alpha.oil)",
           coluna="V_meio_m_s", unidade="m/s", componente=1,
           operacao="weightedAreaAverage(U)", peso="alpha.oil", origem="pos"),
    Funcao("volumeOleo", True, "Volume total de óleo no domínio",
           coluna="volume_oleo_m3", unidade="m3",
           operacao="volIntegrate(alpha.oil)"),

    # --- Paredes: área molhada e tensão média (function objects) --------------
    Funcao("areaOleoExterna", True, "Área molhada da parede externa",
           coluna="A_molhada_externa_fo_m2", unidade="m2",
           operacao="areaIntegrate(alpha.oil)", patch="parede_externa",
           origem="pos"),
    Funcao("areaOleoInterna", True, "Área molhada da parede interna",
           coluna="A_molhada_interna_fo_m2", unidade="m2",
           operacao="areaIntegrate(alpha.oil)", patch="parede_interna",
           apelidos=("areaOleoInterno",), origem="pos"),
    Funcao("atritoExterno", True,
           "Tensão média na parede externa, ponderada por alpha.oil (módulo do vetor médio)",
           coluna="tau_fo_externa_Pa", unidade="Pa", fator=RHO_OLEO,
           operacao="weightedAreaAverage(wallShearStress)", peso="alpha.oil",
           patch="parede_externa", origem="pos"),
    Funcao("atritoInterno", True,
           "Tensão média na parede interna, ponderada por alpha.oil (módulo do vetor médio)",
           coluna="tau_fo_interna_Pa", unidade="Pa", fator=RHO_OLEO,
           operacao="weightedAreaAverage(wallShearStress)", peso="alpha.oil",
           patch="parede_interna", origem="pos"),

    # --- Descartadas ----------------------------------------------------------
    Funcao("atritoPonderado", False, "Tensão média ponderada na parede externa",
           origem="pos",
           motivo_descarte="Duplicata exata de atritoExterno (mesmo patch e mesma operação)."),
    Funcao("atritoParedeExterna", False, "Tensão média na parede externa sem ponderação",
           motivo_descarte="areaAverage sem peso: mistura parede molhada e parede seca; "
                           "o valor muda de sinal ao longo do tempo. Use atritoExterno."),
    Funcao("velocidadeMediaMeio", False, "Velocidade média no plano central sem ponderação",
           motivo_descarte="areaAverage(U) sem peso: dominada pelo ar em contracorrente "
                           "(cerca de -5,9 m/s em M1_Q10). Use velocidadePonderada."),
    Funcao("wallShear", False, "Mínimo e máximo de wallShearStress por patch",
           motivo_descarte="Guarda só mínimo e máximo, não média nem integral. O campo "
                           "wallShearStress gravado em cada tempo é usado no cálculo de atrito."),
    Funcao("alphaStats", False, "Média volumétrica de alpha.oil",
           origem="pos",
           motivo_descarte="Redundante com volumeOleo (volume = média x volume do domínio)."),
    Funcao("TauParedeInterna", False, "Nome antigo citado em analise.py",
           motivo_descarte="Função que não existe no controlDict final; substituída pelo "
                           "cálculo de atrito a partir dos campos."),
    Funcao("TauParedeExterna", False, "Nome antigo citado em analise.py",
           motivo_descarte="Função que não existe no controlDict final; substituída pelo "
                           "cálculo de atrito a partir dos campos."),
)

# Pastas de postProcessing com perfis de linha (function object ``sets``).
PASTAS_PERFIS = ("sampling", "perfil_lateral")

# Parede com área molhada abaixo disso é tratada como seca.
AREA_MOLHADA_MINIMA_M2 = 1e-8

_POR_NOME = {}
for _f in FUNCOES:
    _POR_NOME[_f.nome.lower()] = _f
    for _apelido in _f.apelidos:
        _POR_NOME[_apelido.lower()] = _f


def buscar(nome_pasta: str) -> Funcao | None:
    """Função cadastrada para uma pasta de postProcessing (ou None)."""
    return _POR_NOME.get(nome_pasta.lower())


def colunas_usadas() -> list[str]:
    return [f.coluna for f in FUNCOES if f.usada]


def conferir_cabecalho(funcao: Funcao, cabecalho: dict) -> list[str]:
    """Compara o cabeçalho de um .dat com o esperado. Devolve os problemas."""
    problemas = []
    operacao = cabecalho.get("operacao", "")
    if funcao.operacao and operacao and operacao != funcao.operacao:
        problemas.append(f"operação '{operacao}' (esperado '{funcao.operacao}')")
    peso = cabecalho.get("peso", "")
    if funcao.peso != peso and operacao:
        problemas.append(f"campo de peso '{peso or 'nenhum'}' "
                         f"(esperado '{funcao.peso or 'nenhum'}')")
    if funcao.patch:
        regiao = cabecalho.get("regiao", "")
        if regiao and regiao != f"patch {funcao.patch}":
            problemas.append(f"região '{regiao}' (esperado 'patch {funcao.patch}')")
    return problemas


def tabela_selecao() -> list[dict]:
    """Tabela legível da seleção (gravada em auditoria/selecao_funcoes.csv)."""
    linhas = []
    for f in FUNCOES:
        linhas.append({
            "funcao": f.nome,
            "situacao": "usada" if f.usada else "descartada",
            "coluna_gerada": f.coluna,
            "unidade": f.unidade,
            "descricao": f.descricao,
            "operacao_esperada": f.operacao,
            "campo_de_peso": f.peso,
            "patch": f.patch,
            "componente": {None: "", 0: "x", 1: "y (axial)", 2: "z"}[f.componente]
                          if f.usada else "",
            "fator_conversao": f.fator if f.usada else "",
            "gerada_em": "execução (controlDict)" if f.origem == "execucao"
                         else "pós-processamento (postProcess -func)",
            "motivo_descarte": f.motivo_descarte,
        })
    for pasta in PASTAS_PERFIS:
        linhas.append({"funcao": pasta, "situacao": "perfil",
                       "coluna_gerada": "perfis_resumo.csv",
                       "descricao": "Perfis de alpha.oil e U em linhas de amostragem "
                                    "(diagnóstico; não representam médias de seção)."})
    return linhas
