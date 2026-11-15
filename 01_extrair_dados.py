#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""01 — Extração e tratamento inicial dos dados do OpenFOAM (Duto Anular).

Lê os casos (M0/M1/M2 x Q10/Q35/Q60 e M1_Q20/Q55_R1..R3), sem alterar nada
dentro deles, e grava uma pasta de dados pronta para os scripts 02 e 03:

    dados_extraidos/
        series_temporais.csv     tabela principal: 1 linha por caso e por tempo
        casos.csv                casos encontrados e seus metadados
        atrito_paredes.csv       atrito calculado a partir dos campos (completo)
        perfis_resumo.csv        diagnóstico das linhas de amostragem
        brutos/                  registros exatamente como lidos
        auditoria/               o que foi usado, descartado ou está faltando

Tratamento inicial feito aqui:
  1. seleção das function objects (ver duto_anular/funcoes_openfoam.py);
  2. união dos trechos de reinício e remoção de cópias idênticas;
  3. conferência do cabeçalho de cada .dat (patch, operação, campo de peso);
  4. unidades e sinais: vazões em L/min (positivo = entra por inlet_oil,
     sai por outlet/inlet_air), tensões em Pa;
  5. altura equivalente h_L pela inversão da área de óleo de cada seção;
  6. atrito nas paredes a partir de alpha.oil e wallShearStress.

Não calcula médias, janelas temporais nem GCI: isso fica nos scripts 02 e 03.

Uso:
    python 01_extrair_dados.py --raiz /caminho/dos/casos
    python 01_extrair_dados.py --raiz . --sem-atrito
    python 01_extrair_dados.py --raiz . --atrito-csv atrito_temporal.csv
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from duto_anular import atrito, funcoes_openfoam as fo
from duto_anular.casos import (L_MIN, MALHAS, MALHA_REFERENCIA, RAIZES, VAZOES_BASE,
                               VAZOES_MULTIPLICIDADE, descobrir_casos, info_caso,
                               nome_caso)
from duto_anular.dados import ARQUIVO_CASOS, ARQUIVO_SERIES, altura_por_area, salvar_csv
from duto_anular.leitura_openfoam import (chave_tempo, ler_funcao, ler_perfil,
                                          resumir_perfil, valor_da_funcao)

VERSAO = "2.0.0"

COLUNAS_ID = ["caso_id", "grupo", "malha", "vazao", "Q_nominal_L_min", "raiz", "tempo_s"]
ALTURAS = {                      # área de óleo -> altura equivalente
    "A_oleo_entrada_m2": "h_entrada_mm",
    "A_oleo_meio_m2": "h_meio_mm",
    "A_oleo_saida_m2": "h_saida_mm",
    "A_oleo_proximo_m2": "h_proximo_mm",
}
COLUNAS_SERIES = (
    COLUNAS_ID
    + ["Q_in_L_min", "Q_out_L_min", "Q_inlet_air_L_min", "Q_meio_L_min", "Q_proximo_L_min"]
    + list(ALTURAS) + list(ALTURAS.values())
    + ["V_meio_m_s", "volume_oleo_m3",
       "A_molhada_externa_fo_m2", "A_molhada_interna_fo_m2",
       "tau_fo_externa_Pa", "tau_fo_interna_Pa"]
    + list(atrito.COLUNAS_USADAS_NO_TCC)
)
# Colunas que os scripts 02 e 03 precisam em cada grupo de casos.
ESSENCIAIS_GCI = ["Q_meio_L_min", "V_meio_m_s", "volume_oleo_m3",
                  "integral_tau_ponderada_total_N", "area_ponderada_oleo_total_m2"]
ESSENCIAIS_BASE = ["Q_in_L_min", "Q_out_L_min", "Q_inlet_air_L_min", "Q_meio_L_min",
                   "h_entrada_mm", "h_meio_mm", "h_saida_mm", "volume_oleo_m3"]
ESSENCIAIS_MULTIPLICIDADE = ["Q_meio_L_min", "h_meio_mm"]


class Registro:
    """Junta tudo o que será gravado."""

    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.casos, self.series, self.brutos = [], [], []
        self.atrito, self.perfis, self.perfis_pontos = [], [], []
        self.inventario, self.ocorrencias, self.cobertura = [], [], []

    def rel(self, caminho) -> str:
        try:
            return Path(caminho).resolve().relative_to(self.raiz).as_posix()
        except ValueError:
            return str(caminho)

    def ocorrencia(self, tipo, caso_id, origem, detalhe, severidade):
        self.ocorrencias.append({
            "severidade": severidade, "tipo": tipo, "caso_id": caso_id,
            "origem": self.rel(origem) if origem else "", "detalhe": detalhe})


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Function objects
# ---------------------------------------------------------------------------
def extrair_funcoes(caso_id, pasta_pp, info, reg: Registro):
    """Lê as function objects do caso. Devolve ({tempo: {coluna: valor}}, meta)."""
    por_tempo: dict[float, dict] = {}
    meta = {}
    presentes = set()

    for pasta in sorted(p for p in pasta_pp.iterdir() if p.is_dir()):
        if pasta.name.lower() in fo.PASTAS_PERFIS:
            continue
        funcao = fo.buscar(pasta.name)
        serie, arquivos, conflitos = ler_funcao(pasta)

        if funcao is None:
            situacao = "nao_cadastrada"
            reg.ocorrencia("funcao_nao_cadastrada", caso_id, pasta,
                           "Pasta de postProcessing sem cadastro em funcoes_openfoam.py; "
                           "guardada só nos dados brutos.", "revisar")
        elif not funcao.usada:
            situacao = "descartada"
        else:
            situacao = "usada"
            presentes.add(funcao.nome)

        # Confere o cabeçalho de cada arquivo com dados.
        arquivos_ruins = {}
        for item in arquivos:
            arquivo, cab, n = item["arquivo"], item["cabecalho"], item["n_registros"]
            status, detalhe = situacao, ""
            if n == 0:
                status = "vazio" if arquivo.stat().st_size == 0 else "sem_registros"
            elif funcao is not None and funcao.usada:
                problemas = fo.conferir_cabecalho(funcao, cab)
                if problemas:
                    status = "cabecalho_divergente"
                    detalhe = "; ".join(problemas)
                    arquivos_ruins[arquivo] = detalhe
                    reg.ocorrencia("cabecalho_divergente", caso_id, arquivo,
                                   f"{funcao.nome}: {detalhe}. Arquivo fora dos dados tratados.",
                                   "erro")
            reg.inventario.append({
                "caso_id": caso_id, "funcao": pasta.name, "arquivo": reg.rel(arquivo),
                "bytes": arquivo.stat().st_size, "n_registros": n, "status": status,
                "regiao": cab["regiao"], "operacao": cab["operacao"], "peso": cab["peso"],
                "detalhe": detalhe, "sha256": sha256(arquivo)})

        for c in conflitos:
            reg.ocorrencia("valores_conflitantes_no_mesmo_tempo", caso_id, c["arquivo_mantido"],
                           f"{pasta.name}, t={c['tempo_s']:.6g} s: mantido {c['mantido']} "
                           f"(reinício mais recente); descartado {c['descartado']} de "
                           f"{reg.rel(c['arquivo_descartado'])}.", "revisar")

        for (chave, patch), r in sorted(serie.items()):
            usado = situacao == "usada" and r["arquivo"] not in arquivos_ruins
            valor = (valor_da_funcao(r["valores"], funcao.componente, funcao.fator)
                     if usado else float("nan"))
            reg.brutos.append({
                "caso_id": caso_id, "funcao": pasta.name, "tempo_s": r["tempo_s"],
                "patch": patch,
                "valor_bruto": " ".join(f"{v:.10g}" for v in r["valores"]),
                "situacao": situacao if (usado or situacao != "usada") else "cabecalho_divergente",
                "coluna": funcao.coluna if usado else "",
                "valor_tratado": valor if usado else "",
                "unidade": funcao.unidade if usado else "",
                "arquivo": reg.rel(r["arquivo"]), "linha": r["linha"]})
            if not usado or not math.isfinite(valor):
                continue
            linha = por_tempo.setdefault(chave, {"tempo_s": r["tempo_s"]})
            anterior = linha.get(funcao.coluna)
            if anterior is not None and not math.isclose(anterior, valor, rel_tol=1e-9, abs_tol=1e-15):
                reg.ocorrencia("duas_pastas_para_a_mesma_grandeza", caso_id, pasta,
                               f"{funcao.coluna}, t={r['tempo_s']:.6g} s: {anterior} x {valor}; "
                               "mantido o primeiro.", "revisar")
                continue
            linha[funcao.coluna] = valor

        # Metadados do domínio (cabeçalho de volumeOleo).
        if funcao is not None and funcao.nome == "volumeOleo":
            for item in arquivos:
                cab = item["cabecalho"]
                if cab["celulas"]:
                    meta["n_celulas"] = int(float(cab["celulas"]))
                    meta["volume_dominio_m3"] = float(cab["volume_m3"]) if cab["volume_m3"] else ""

    faltam = [f.nome for f in fo.FUNCOES if f.usada and f.nome not in presentes]
    if faltam:
        reg.ocorrencia("funcoes_ausentes", caso_id, pasta_pp,
                       "Sem dados de: " + ", ".join(faltam), "revisar")
    return por_tempo, meta


def completar_com_log(caso_id, pasta_caso: Path, por_tempo: dict, reg: Registro):
    """Reserva: se não há .dat de QOleoMeio, lê a vazão central de log.QOleoMeio."""
    if any("Q_meio_L_min" in linha for linha in por_tempo.values()):
        return
    padrao = re.compile(r"weightedAreaIntegrate\(plano_meio\) of U\s*=\s*"
                        r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)")
    for log in sorted(pasta_caso.glob("log.QOleoMeio*")):
        tempo, n = None, 0
        for texto in log.read_text(encoding="utf-8", errors="replace").splitlines():
            m_tempo = re.match(r"\s*Time\s*=\s*([-+0-9.eE]+)", texto)
            if m_tempo:
                tempo = float(m_tempo.group(1))
            m = padrao.search(texto)
            if m and tempo is not None:
                linha = por_tempo.setdefault(chave_tempo(tempo), {"tempo_s": tempo})
                linha["Q_meio_L_min"] = float(m.group(2)) * L_MIN
                n += 1
        if n:
            reg.ocorrencia("vazao_central_lida_do_log", caso_id, log,
                           f"Sem .dat de QOleoMeio; {n} registros lidos do log.", "revisar")
            return


def tratar_linhas(por_tempo: dict, caso_id, reg: Registro):
    """Alturas equivalentes e parede seca."""
    secos = 0
    for linha in por_tempo.values():
        for col_area, col_altura in ALTURAS.items():
            if col_area in linha:
                linha[col_altura] = altura_por_area(linha[col_area])
        # Tensão média em parede seca é 0/0: não tem significado.
        for parede in ("interna", "externa"):
            area = linha.get(f"A_molhada_{parede}_fo_m2")
            if area is not None and area < fo.AREA_MOLHADA_MINIMA_M2 \
                    and f"tau_fo_{parede}_Pa" in linha:
                del linha[f"tau_fo_{parede}_Pa"]
                secos += 1
    if secos:
        reg.ocorrencia("parede_seca", caso_id, "",
                       f"{secos} registros de tensão média (function object) apagados: "
                       f"área molhada < {fo.AREA_MOLHADA_MINIMA_M2:g} m².", "informativo")


# ---------------------------------------------------------------------------
# Perfis de linha
# ---------------------------------------------------------------------------
def extrair_perfis(caso_id, pasta_pp, reg: Registro, completos: bool):
    for nome in fo.PASTAS_PERFIS:
        pasta = pasta_pp / nome
        if not pasta.is_dir():
            continue
        for arquivo in sorted(pasta.rglob("*.csv")):
            try:
                tempo = float(arquivo.parent.name)
            except ValueError:
                continue
            perfil = arquivo.name.replace("_alpha.oil_U.csv", "").replace(".csv", "")
            try:
                pontos = ler_perfil(arquivo)
            except OSError as exc:
                reg.ocorrencia("erro_leitura_perfil", caso_id, arquivo, str(exc), "erro")
                continue
            for resumo in resumir_perfil(pontos):
                reg.perfis.append({"caso_id": caso_id, "tempo_s": tempo,
                                   "perfil": perfil, **resumo})
            if completos:
                for z, alpha, ux, uy, uz in pontos:
                    reg.perfis_pontos.append({
                        "caso_id": caso_id, "tempo_s": tempo, "perfil": perfil,
                        "z_m": z, "alpha_oil": alpha, "Ux_m_s": ux, "Uy_m_s": uy,
                        "Uz_m_s": uz})


# ---------------------------------------------------------------------------
# Atrito
# ---------------------------------------------------------------------------
def carregar_atrito_csv(arquivo: Path) -> dict[str, list[dict]]:
    """Lê um atrito já calculado (atrito_paredes.csv deste script ou
    atrito_temporal.csv dos consolidadores antigos)."""
    df = pd.read_csv(arquivo, encoding="utf-8-sig")
    if "caso_id" not in df.columns:
        if {"malha", "caso"} <= set(df.columns):
            df["caso_id"] = [c if str(c).upper().startswith("M") else f"{m}_{c}"
                             for m, c in zip(df["malha"], df["caso"])]
        else:
            sys.exit(f"[ERRO] {arquivo}: precisa da coluna caso_id (ou malha + caso).")
    df["caso_id"] = df["caso_id"].astype(str).str.upper()
    colunas = ["tempo_s"] + [c for c in df.columns
                             if c.endswith(("_m2", "_Pa", "_N")) or c.startswith("faces_oleo")]
    saida = {}
    for caso_id, grupo in df.groupby("caso_id"):
        grupo = grupo.dropna(subset=["tempo_s"]).drop_duplicates("tempo_s", keep="last")
        saida[caso_id] = grupo[colunas].to_dict("records")
    return saida


def juntar_atrito(caso_id, linhas_atrito, por_tempo, info, reg: Registro, fonte: str):
    for linha in linhas_atrito:
        reg.atrito.append({"caso_id": caso_id, "malha": info["malha"],
                           "vazao": info["vazao"], "raiz": info["raiz"],
                           **linha, "fonte": fonte})
        destino = por_tempo.setdefault(chave_tempo(linha["tempo_s"]),
                                       {"tempo_s": linha["tempo_s"]})
        for coluna in atrito.COLUNAS_USADAS_NO_TCC:
            valor = linha.get(coluna)
            if valor is not None and not (isinstance(valor, float) and math.isnan(valor)):
                destino[coluna] = valor


# ---------------------------------------------------------------------------
# Conferência do que foi extraído
# ---------------------------------------------------------------------------
def conferir_cobertura(series: pd.DataFrame, reg: Registro):
    """Lista, por caso, quantos registros há de cada grandeza e o que falta."""
    esperados = [nome_caso(m, q) for m in MALHAS for q in VAZOES_BASE]
    esperados += [nome_caso(MALHA_REFERENCIA, q, r)
                  for q in VAZOES_MULTIPLICIDADE for r in RAIZES]
    achados = set(series["caso_id"]) if len(series) else set()
    for caso_id in esperados:
        if caso_id not in achados:
            reg.ocorrencia("caso_esperado_ausente", caso_id, "",
                           "Caso do TCC não encontrado na raiz informada.", "revisar")

    grandezas = [c for c in COLUNAS_SERIES if c not in COLUNAS_ID]
    for caso_id, grupo in series.groupby("caso_id"):
        info = info_caso(caso_id)
        if info["grupo"] == "multiplicidade":
            essenciais = ESSENCIAIS_MULTIPLICIDADE
        else:
            essenciais = list(ESSENCIAIS_GCI)
            if info["malha"] == MALHA_REFERENCIA:
                essenciais += [c for c in ESSENCIAIS_BASE if c not in essenciais]
        for coluna in grandezas:
            validos = grupo.loc[grupo[coluna].notna(), "tempo_s"]
            essencial = coluna in essenciais
            reg.cobertura.append({
                "caso_id": caso_id, "grandeza": coluna,
                "n_registros": len(validos),
                "t_inicial_s": validos.min() if len(validos) else "",
                "t_final_s": validos.max() if len(validos) else "",
                "necessaria_para_o_tcc": "sim" if essencial else "",
                "situacao": "ok" if len(validos) else ("FALTA" if essencial else "sem dados")})
            if essencial and not len(validos):
                reg.ocorrencia("grandeza_necessaria_ausente", caso_id, "",
                               f"{coluna} não tem nenhum registro.", "erro")


def imprimir_resumo(series: pd.DataFrame, reg: Registro, saida: Path):
    print("\n" + "=" * 78)
    print(" RESUMO DA EXTRAÇÃO")
    print("=" * 78)
    if len(series):
        chaves = ["Q_meio_L_min", "h_meio_mm", "Q_out_L_min", "Q_inlet_air_L_min",
                  "V_meio_m_s", "volume_oleo_m3", "integral_tau_ponderada_total_N"]
        rotulos = ["Qmeio", "hmeio", "Qout", "QinAr", "Vmeio", "volume", "atrito"]
        print(f" {'caso':<12}{'tempos':>7}{'t final':>9}  "
              + "".join(f"{r:>8}" for r in rotulos))
        for caso_id, grupo in series.groupby("caso_id"):
            marcas = "".join(f"{int(grupo[c].notna().sum()):>8}" for c in chaves)
            print(f" {caso_id:<12}{len(grupo):>7}{grupo['tempo_s'].max():>9.3f}  {marcas}")
        print(" (números = quantidade de registros de cada grandeza; 0 = faltando)")
    cont = pd.Series([o["severidade"] for o in reg.ocorrencias]).value_counts()
    print(f"\n Ocorrências: {int(cont.get('erro', 0))} erro(s), "
          f"{int(cont.get('revisar', 0))} para revisar, "
          f"{int(cont.get('informativo', 0))} informativa(s)"
          f"  ->  {saida / 'auditoria' / 'ocorrencias.csv'}")
    for o in reg.ocorrencias:
        if o["severidade"] == "erro":
            print(f"   [ERRO] {o['caso_id']}: {o['tipo']} — {o['detalhe']}")
    print(f"\n Dados gravados em: {saida}")


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Extrai e trata os dados dos casos OpenFOAM do Duto Anular.")
    ap.add_argument("--raiz", type=Path, default=Path("."),
                    help="pasta que contém os casos (procura em subpastas)")
    ap.add_argument("--saida", type=Path, default=Path("dados_extraidos"),
                    help="pasta de saída (padrão: dados_extraidos)")
    ap.add_argument("--sem-atrito", action="store_true",
                    help="não calcula o atrito a partir dos campos")
    ap.add_argument("--atrito-csv", type=Path, default=None,
                    help="usa um atrito já calculado em vez de ler os campos "
                         "(ex.: dados_extraidos/atrito_paredes.csv de uma extração anterior)")
    ap.add_argument("--perfis-completos", action="store_true",
                    help="grava também todos os pontos dos perfis de linha "
                         "(brutos/perfis_pontos.csv; arquivo grande)")
    args = ap.parse_args()

    raiz = args.raiz.resolve()
    saida = args.saida.resolve()
    if not raiz.is_dir():
        print(f"[ERRO] Pasta não encontrada: {raiz}", file=sys.stderr)
        return 2

    atrito_importado = None
    if args.atrito_csv:
        if not args.atrito_csv.is_file():
            print(f"[ERRO] Arquivo não encontrado: {args.atrito_csv}", file=sys.stderr)
            return 2
        atrito_importado = carregar_atrito_csv(args.atrito_csv)

    casos, duplicados = descobrir_casos(raiz, ignorar=saida)
    if not casos:
        print(f"[ERRO] Nenhum caso (pastas M?_Q??) encontrado em {raiz}", file=sys.stderr)
        return 2

    reg = Registro(raiz)
    for caso_id, caminhos in duplicados.items():
        reg.ocorrencia("caso_em_mais_de_uma_pasta", caso_id, caminhos[0],
                       "Usada a pasta mais próxima da raiz. Outras: "
                       + " | ".join(reg.rel(p) for p in caminhos[1:]), "revisar")

    print(f"Raiz: {raiz}\nCasos encontrados: {len(casos)}")
    for i, (caso_id, pasta) in enumerate(casos.items(), 1):
        info = info_caso(caso_id)
        print(f"[{i}/{len(casos)}] {caso_id}  ({reg.rel(pasta)})")
        pasta_pp = pasta / "postProcessing"
        por_tempo, meta = {}, {}

        if pasta_pp.is_dir():
            por_tempo, meta = extrair_funcoes(caso_id, pasta_pp, info, reg)
            extrair_perfis(caso_id, pasta_pp, reg, args.perfis_completos)
        else:
            reg.ocorrencia("sem_postProcessing", caso_id, pasta,
                           "Pasta postProcessing não encontrada.", "erro")
        completar_com_log(caso_id, pasta, por_tempo, reg)
        tratar_linhas(por_tempo, caso_id, reg)

        fonte_atrito = "nao_calculado"
        if atrito_importado is not None:
            if caso_id in atrito_importado:
                fonte_atrito = f"importado de {args.atrito_csv.name}"
                juntar_atrito(caso_id, atrito_importado[caso_id], por_tempo, info, reg,
                              fonte_atrito)
            else:
                reg.ocorrencia("atrito_ausente_no_csv", caso_id, args.atrito_csv,
                               "Caso sem linhas no CSV de atrito informado.", "revisar")
        elif not args.sem_atrito:
            linhas, ocorrencias = atrito.atrito_do_caso(pasta)
            for tipo, origem, detalhe, severidade in ocorrencias:
                reg.ocorrencia(tipo, caso_id, origem, detalhe, severidade)
            if linhas:
                fonte_atrito = "calculado dos campos"
                juntar_atrito(caso_id, linhas, por_tempo, info, reg, fonte_atrito)
                print(f"      atrito calculado em {len(linhas)} tempos")

        for chave in sorted(por_tempo):
            reg.series.append({**{k: info[k] for k in COLUNAS_ID if k in info},
                               **por_tempo[chave]})
        tempos = sorted(l["tempo_s"] for l in por_tempo.values())
        reg.casos.append({
            **info, "pasta": reg.rel(pasta),
            "n_celulas": meta.get("n_celulas", ""),
            "volume_dominio_m3": meta.get("volume_dominio_m3", ""),
            "n_tempos": len(tempos),
            "t_inicial_s": tempos[0] if tempos else "",
            "t_final_s": tempos[-1] if tempos else "",
            "atrito": fonte_atrito})

    series = pd.DataFrame(reg.series, columns=COLUNAS_SERIES)
    conferir_cobertura(series, reg)

    # ----------------------------------------------------------------- gravação
    salvar_csv(series, saida / ARQUIVO_SERIES)
    salvar_csv(pd.DataFrame(reg.casos), saida / ARQUIVO_CASOS)
    salvar_csv(pd.DataFrame(reg.atrito), saida / "atrito_paredes.csv")
    salvar_csv(pd.DataFrame(reg.perfis), saida / "perfis_resumo.csv")
    salvar_csv(pd.DataFrame(reg.brutos), saida / "brutos" / "functionObjects.csv")
    if args.perfis_completos:
        salvar_csv(pd.DataFrame(reg.perfis_pontos), saida / "brutos" / "perfis_pontos.csv")
    pasta_auditoria = saida / "auditoria"
    salvar_csv(pd.DataFrame(fo.tabela_selecao()), pasta_auditoria / "selecao_funcoes.csv")
    salvar_csv(pd.DataFrame(reg.inventario), pasta_auditoria / "inventario_arquivos.csv")
    salvar_csv(pd.DataFrame(reg.cobertura), pasta_auditoria / "cobertura.csv")
    ordem = {"erro": 0, "revisar": 1, "informativo": 2}
    reg.ocorrencias.sort(key=lambda o: (ordem.get(o["severidade"], 9), o["caso_id"], o["tipo"]))
    salvar_csv(pd.DataFrame(reg.ocorrencias,
                            columns=["severidade", "tipo", "caso_id", "origem", "detalhe"]),
               pasta_auditoria / "ocorrencias.csv")
    manifesto = {
        "versao_extrator": VERSAO,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "raiz": str(raiz),
        "casos": sorted(casos),
        "atrito": ("importado de " + str(args.atrito_csv) if args.atrito_csv
                   else "não calculado (--sem-atrito)" if args.sem_atrito
                   else "calculado dos campos alpha.oil e wallShearStress"),
        "registros": {"series_temporais": len(series), "atrito_paredes": len(reg.atrito),
                      "perfis_resumo": len(reg.perfis), "brutos": len(reg.brutos)},
        "arquivos_lidos": len(reg.inventario),
        "ocorrencias": len(reg.ocorrencias),
        "convencoes": {
            "vazao": "L/min; positivo = entra por inlet_oil, sai por outlet e inlet_air",
            "tensao": "Pa (wallShearStress cinemático x 900 kg/m³)",
            "altura": "mm; inversão de A_L(h_L) do modelo analítico",
            "conflitos": "mesmo tempo com valores diferentes: vale o reinício mais recente",
        },
    }
    (pasta_auditoria / "manifest.json").write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8")

    imprimir_resumo(series, reg, saida)
    return 1 if any(o["severidade"] == "erro" for o in reg.ocorrencias) else 0


if __name__ == "__main__":
    raise SystemExit(main())
