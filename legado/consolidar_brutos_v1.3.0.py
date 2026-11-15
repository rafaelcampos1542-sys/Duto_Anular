#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Consolidador bruto central — OpenFOAM / Duto Anular — v1.2.0

Somente leitura na árvore de origem. Calcula atrito com o algoritmo de referência; não filtra
janelas temporais, não interpola, não calcula médias/balanços/GCI e não remove
registros duplicados. A saída é gravada em diretório separado.

Uso:
  ./venv/bin/python consolidar_brutos_v1.3.0.py --root . --out resultados_consolidados_v1.3.0 --friction-script calcular_atrito_paredes.py
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, math, re, sys
from collections import defaultdict
from pathlib import Path
from typing import Any

VERSION = "1.3.0"
CASE_RE = re.compile(r"^(M[0-9]+)_Q([0-9]+)(?:_(R[0-9]+))?$", re.I)
TIME_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
NUM_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
CSV_EXT = {".csv"}
DATA_EXT = {".dat", ".qoleomeio"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "constant", "system"}


def is_num(v: Any) -> bool:
    try: return math.isfinite(float(v))
    except (TypeError, ValueError): return False


def case_meta(case_id: str) -> dict[str, Any]:
    m = CASE_RE.fullmatch(case_id)
    if not m:
        return {"caso_id": case_id, "grupo_estudo": "nao_classificado", "malha": "", "vazao_nominal_L_min": "", "condicao_inicial_id": ""}
    mesh, flow, initial = m.groups()
    return {"caso_id": case_id, "grupo_estudo": "multiplicidade" if initial else "caso_base",
            "malha": mesh.upper(), "vazao_nominal_L_min": flow,
            "condicao_inicial_id": initial.upper() if initial else ""}


def is_excluded_dir(path: Path, root: Path, out: Path) -> bool:
    try: rel = path.resolve().relative_to(root.resolve())
    except ValueError: return True
    if out.resolve() == path.resolve() or out.resolve() in path.resolve().parents: return True
    for part in rel.parts:
        low = part.lower()
        if low in SKIP_DIRS or low.startswith("backup_") or low.startswith("resultados_"):
            return True
    return False


def discover_cases(root: Path, out: Path):
    found = defaultdict(list)
    for p in root.rglob("*"):
        if p.is_dir() and not is_excluded_dir(p, root, out) and CASE_RE.fullmatch(p.name):
            found[p.name].append(p)
    cases, audit = [], []
    for cid, paths in sorted(found.items()):
        for p in sorted(paths):
            cases.append({**case_meta(cid), "caminho_caso": p.relative_to(root).as_posix(),
                          "n_localizacoes_com_mesmo_id": len(paths)})
        if len(paths) > 1:
            audit.append({"tipo_ocorrencia":"caso_com_localizacoes_duplicadas", "caso_id":cid,
                          "arquivo_origem":"", "detalhe":" | ".join(x.relative_to(root).as_posix() for x in paths), "severidade":"revisar"})
    return cases, audit


def read_csv_rows(path: Path):
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try: text = raw.decode(enc); break
        except UnicodeDecodeError: pass
    if text is None: raise UnicodeError("Falha de decodificacao")
    # CSVs de perfis podem conter campos longos; eleva o limite padrão do módulo csv.
    csv.field_size_limit(sys.maxsize)
    sample = text[:32768]
    try: dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error: dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect, restkey="__campos_extras__", restval="")
    headers = list(reader.fieldnames or [])
    rows = []
    for row in reader:
        clean = {str(k): ("" if v is None else str(v)) for k,v in row.items() if k is not None}
        if "__campos_extras__" in clean:
            clean["__campos_extras__"] = json.dumps(clean["__campos_extras__"], ensure_ascii=False)
        rows.append(clean)
    return headers, rows


def parse_dat(text: str):
    out=[]
    for line_no,line in enumerate(text.splitlines(),1):
        s=line.strip()
        if not s or s.startswith("#") or s.startswith("//"): continue
        nums=NUM_RE.findall(s)
        if len(nums) not in (2,4): continue
        try: v=[float(x) for x in nums]
        except ValueError: continue
        if not all(math.isfinite(x) for x in v): continue
        if len(v)==2:
            rec={"linha_arquivo":line_no,"tempo_s":v[0],"tipo_valor":"escalar","valor_escalar":v[1],"componente_x":"","componente_y":"","componente_z":"","valor_bruto":s}
        else:
            rec={"linha_arquivo":line_no,"tempo_s":v[0],"tipo_valor":"vetor","valor_escalar":"","componente_x":v[1],"componente_y":v[2],"componente_z":v[3],"valor_bruto":s}
        out.append(rec)
    return out


def sha256(path: Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict], fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if fields is None: fields=list(dict.fromkeys(k for row in rows for k in row))
    if not fields: fields=["sem_registros"]
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)


def add_inventory(inventory, root, path, case_id, status, n, detail=""):
    rel=path.relative_to(root).as_posix()
    try: size=path.stat().st_size; digest=sha256(path)
    except OSError: size=""; digest=""
    inventory.append({"caso_id":case_id,"arquivo_origem":rel,"extensao":path.suffix.lower(),"tamanho_bytes":size,"sha256":digest,"status":status,"n_registros":n,"detalhe":detail})


def row_time(path: Path, row: dict):
    for k,v in row.items():
        if k.strip().lower() in {"tempo_s","time","time_s","tempo"} and is_num(v): return float(v)
    for part in reversed(path.parts[:-1]):
        if TIME_RE.fullmatch(part): return float(part)
    return ""


def base_tables():
    return {k:[] for k in ["sampling_temporal","functionObjects_temporais","qoleomeio_temporal",
        "comparacao_planos_axiais","resultados_hL","atrito_temporal","demais_csv_temporais","resultados_derivados"]}


def classify_case_csv(path: Path, case_dir: Path):
    rel=path.relative_to(case_dir).as_posix().lower(); name=path.name.lower()
    if "sampling" in rel or "perfil_lateral" in rel or "perfil_" in name or "profile" in name: return "sampling_temporal"
    if name == "comparacao_planos_axiais.csv": return "comparacao_planos_axiais"
    if name in {"resultados_hl.csv","q10_resultados_hl.csv","q35_resultados_hl.csv","q60_resultados_hl.csv"}: return "resultados_hL"
    if name.startswith("relatorio_gci") or "gci" in name: return "resultados_derivados"
    if "postprocessing" in rel: return "demais_csv_temporais"
    return "resultados_derivados"


def append_csv_family(table, path, root, meta, family, inventory, audit, file_hashes):
    try:
        headers, rows=read_csv_rows(path)
        rel=path.relative_to(root).as_posix()
        for i,row in enumerate(rows,1):
            # Mantém campos originais sem conversão; tempo_s adicional é apenas metadado extraído.
            rec={**meta,"tempo_s":row_time(path,row),"arquivo_origem":rel,"linha_registro":i,
                 "colunas_originais_json":json.dumps(row,ensure_ascii=False)}
            rec.update({f"original__{k}":v for k,v in row.items()})
            table.append(rec)
        status="valido" if rows else ("vazio" if path.stat().st_size==0 else "sem_registros")
        add_inventory(inventory,root,path,meta.get("caso_id",""),status,len(rows),f"familia={family}; colunas={headers}")
        file_hashes[sha256(path)].append(rel)
    except Exception as exc:
        add_inventory(inventory,root,path,meta.get("caso_id",""),"erro_leitura",0,repr(exc))
        audit.append({"tipo_ocorrencia":"erro_leitura_csv","caso_id":meta.get("caso_id",""),"arquivo_origem":path.relative_to(root).as_posix(),"detalhe":repr(exc),"severidade":"erro"})


def ingest_friction_archives(root, tables, inventory, audit, file_hashes):
    """Importa CSVs históricos nomeados explicitamente; não calcula atrito."""
    target_names={"atrito_temporal_nove_casos.csv","atrito_paredes.csv"}
    for p in sorted(root.rglob("*.csv")):
        if p.name.lower() not in target_names and not re.fullmatch(r"atrito_m[0-9]+_q[0-9]+(?:_r[0-9]+)?\.csv",p.name.lower()): continue
        rel=p.relative_to(root)
        if any(x.lower() in SKIP_DIRS or x.lower()=="resultados_consolidados" for x in rel.parts): continue
        # Evita reimportar tabela de saída se o usuário escolher uma saída sob a raiz.
        if "resultados_consolidados" in rel.parts: continue
        try:
            headers,rows=read_csv_rows(p)
            for i,row in enumerate(rows,1):
                mesh=row.get("malha","").strip().upper()
                case=row.get("caso","").strip().upper()
                cid=case if CASE_RE.fullmatch(case) else (f"{mesh}_{case}" if mesh and re.fullmatch(r"Q\d+(?:_R\d+)?",case) else "")
                meta=case_meta(cid) if cid else {"caso_id":"","grupo_estudo":"nao_classificado","malha":mesh,"vazao_nominal_L_min":"","condicao_inicial_id":""}
                rec={**meta,"tempo_s":row_time(p,row),"arquivo_origem":rel.as_posix(),"linha_registro":i,
                     "fonte_arquivo":p.name,"colunas_originais_json":json.dumps(row,ensure_ascii=False)}
                rec.update({f"original__{k}":v for k,v in row.items()})
                tables["atrito_temporal"].append(rec)
            add_inventory(inventory,root,p,"","valido" if rows else "vazio",len(rows),f"familia=atrito_temporal; importado sem recalculo; colunas={headers}")
            file_hashes[sha256(p)].append(rel.as_posix())
        except Exception as exc:
            add_inventory(inventory,root,p,"","erro_leitura",0,repr(exc))
            audit.append({"tipo_ocorrencia":"erro_leitura_csv_atrito","caso_id":"","arquivo_origem":rel.as_posix(),"detalhe":repr(exc),"severidade":"erro"})


def load_friction_module(script_path: Path):
    import importlib.util
    script_path = script_path.expanduser().resolve()
    if not script_path.is_file():
        raise FileNotFoundError(
            f"Script de cálculo de atrito não encontrado: {script_path}. "
            "Informe --friction-script com o caminho de calcular_atrito_paredes.py."
        )
    spec = importlib.util.spec_from_file_location("calcular_atrito_paredes_ref", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Não foi possível carregar {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = ("read_patches", "read_points", "read_owner_range", "read_selected_faces", "calculate_time")
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise AttributeError(f"O script de atrito não contém as funções esperadas: {missing}")
    return module


def calculate_friction_for_cases(root, cases, friction_script, inventory, audit):
    """Reutiliza literalmente as funções do calcular_atrito_paredes.py; não grava nos casos."""
    module = load_friction_module(friction_script)
    rows = []
    for case in cases:
        cid = case["caso_id"]
        cdir = root / case["caminho_caso"]
        mesh = cdir / "constant" / "polyMesh"
        try:
            patches = module.read_patches(mesh / "boundary")
            points = module.read_points(mesh / "points")
            first = min(p["startFace"] for p in patches.values())
            last = max(p["startFace"] + p["nFaces"] for p in patches.values()) - 1
            owners = module.read_owner_range(mesh / "owner", first, last)
            faces = module.read_selected_faces(mesh / "faces", first, last)
        except Exception as exc:
            audit.append({"tipo_ocorrencia":"falha_leitura_malha_atrito", "caso_id":cid,
                          "arquivo_origem":(mesh.as_posix()), "detalhe":repr(exc), "severidade":"erro"})
            continue

        time_dirs = sorted(
            ((float(p.name), p) for p in cdir.iterdir()
             if p.is_dir() and re.fullmatch(r"\d+(?:\.\d+)?", p.name)),
            key=lambda x: x[0]
        )
        for t, time_dir in time_dirs:
            alpha_file = time_dir / "alpha.oil"
            tau_file = time_dir / "wallShearStress"
            rel_alpha = alpha_file.relative_to(root).as_posix()
            rel_tau = tau_file.relative_to(root).as_posix()
            if not alpha_file.is_file() or not tau_file.is_file():
                missing = [n for n,p in (("alpha.oil",alpha_file),("wallShearStress",tau_file)) if not p.is_file()]
                audit.append({"tipo_ocorrencia":"tempo_sem_campos_para_atrito", "caso_id":cid,
                              "arquivo_origem":time_dir.relative_to(root).as_posix(),
                              "detalhe":f"tempo_s={t}; campos ausentes={','.join(missing)}", "severidade":"revisar"})
                continue
            try:
                result = module.calculate_time(t, time_dir, patches, points, owners, faces, first)
                meta = case_meta(cid)
                row = {**meta, **result,
                       "fonte_calculo":"campos_OpenFOAM", "versao_algoritmo":"calcular_atrito_paredes.py_importado",
                       "rho_kg_m3":900, "arquivo_alpha_origem":rel_alpha,
                       "arquivo_wallShearStress_origem":rel_tau,
                       "malha_origem":(mesh.relative_to(root).as_posix()),
                       "metodo_ponderacao":"alpha.oil da celula owner x area da face",
                       "observacao_forca":"integral da magnitude do cisalhamento; nao representa resultante vetorial axial"}
                rows.append(row)
                add_inventory(inventory, root, alpha_file, cid, "usado_calculo_atrito", 1, f"tempo_s={t}; campo alpha.oil")
                add_inventory(inventory, root, tau_file, cid, "usado_calculo_atrito", 1, f"tempo_s={t}; campo wallShearStress")
            except Exception as exc:
                audit.append({"tipo_ocorrencia":"falha_calculo_atrito", "caso_id":cid,
                              "arquivo_origem":time_dir.relative_to(root).as_posix(),
                              "detalhe":f"tempo_s={t}; {repr(exc)}", "severidade":"erro"})
    return rows


def ingest_legacy_friction(root, inventory, audit):
    """Importa CSVs históricos apenas como referência; nunca mistura no atrito calculado."""
    rows=[]
    target_names={"atrito_temporal_nove_casos.csv", "atrito_paredes.csv"}
    for p in sorted(root.rglob("*.csv")):
        if p.name.lower() not in target_names and not re.fullmatch(r"atrito_m[0-9]+_q[0-9]+(?:_r[0-9]+)?\.csv",p.name.lower()):
            continue
        rel=p.relative_to(root)
        if any(x.lower() in SKIP_DIRS or x.lower().startswith("backup_") for x in rel.parts):
            continue
        if any(x.lower() in {"dados_brutos","dados_processados","auditoria","dados_referencia_legada"} or x.lower().startswith("resultados_consolidados") for x in rel.parts):
            continue
        # Não importar o próprio diretório de saída desta versão.
        if any(x.lower().startswith("resultados_consolidados_v1.3") for x in rel.parts):
            continue
        try:
            headers, data = read_csv_rows(p)
            for i, raw in enumerate(data, 1):
                mesh=raw.get("malha", "").strip().upper(); case=raw.get("caso", "").strip().upper()
                cid=case if CASE_RE.fullmatch(case) else (f"{mesh}_{case}" if mesh and re.fullmatch(r"Q\d+(?:_R\d+)?",case) else "")
                meta=case_meta(cid) if cid else case_meta("")
                rows.append({**meta,"tempo_s":row_time(p,raw),"fonte_calculo":"csv_legado_nao_recalculado",
                             "arquivo_origem":rel.as_posix(),"linha_registro":i,
                             "colunas_originais_json":json.dumps(raw,ensure_ascii=False),
                             **{f"original__{k}":v for k,v in raw.items()}})
            add_inventory(inventory,root,p,"","referencia_legada" if data else "vazio",len(data),f"CSV legado; colunas={headers}; não usado como resultado canônico")
        except Exception as exc:
            add_inventory(inventory,root,p,"","erro_leitura",0,repr(exc))
            audit.append({"tipo_ocorrencia":"erro_leitura_atrito_legado","caso_id":"","arquivo_origem":rel.as_posix(),"detalhe":repr(exc),"severidade":"revisar"})
    return rows


def run(root: Path, out: Path, friction_script: Path):
    root=root.resolve(); out=out.resolve(); friction_script=friction_script.resolve()
    if not root.is_dir(): raise NotADirectoryError(root)
    if out == root or root in out.parents and out == root:
        raise ValueError("A saída não pode ser a própria raiz dos casos.")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"A pasta de saída já existe e não está vazia: {out}. Escolha outra pasta; nada foi sobrescrito.")

    cases,audit=discover_cases(root,out)
    tables=base_tables(); inventory=[]; file_hashes=defaultdict(list)
    # Extração dos CSVs dos 15 casos; mantém o comportamento do parser v1.2.
    for case in cases:
        cid=case["caso_id"]; cdir=root/case["caminho_caso"]
        meta={k:case.get(k,"") for k in ("caso_id","grupo_estudo","malha","vazao_nominal_L_min","condicao_inicial_id")}
        for p in sorted(cdir.rglob("*.csv")):
            if out==p.resolve() or out in p.resolve().parents: continue
            if any(part.lower() in SKIP_DIRS or part.lower().startswith("resultados_") for part in p.relative_to(cdir).parts[:-1]): continue
            family=classify_case_csv(p,cdir)
            append_csv_family(tables[family],p,root,meta,family,inventory,audit,file_hashes)
        pp=cdir/"postProcessing"
        if pp.is_dir():
            for p in sorted(list(pp.rglob("*.dat"))+list(pp.rglob("*.QOleoMeio"))):
                try:
                    raw=p.read_text(encoding="utf-8",errors="replace"); parsed=parse_dat(raw)
                    rel=p.relative_to(root).as_posix(); fn=p.relative_to(pp).parts[0] if p.relative_to(pp).parts else ""
                    for rec in parsed:
                        tables["functionObjects_temporais"].append({**meta,"funcao":fn,"objeto_arquivo":p.name,**rec,"arquivo_origem":rel})
                    status="valido" if parsed else ("vazio" if not raw.strip() else "sem_dados_parseaveis")
                    add_inventory(inventory,root,p,cid,status,len(parsed),"parser de linhas escalares/vetoriais simples; arquivos não reconhecidos permanecem inventariados")
                    file_hashes[sha256(p)].append(rel)
                    if not parsed and raw.strip():
                        audit.append({"tipo_ocorrencia":"dat_sem_dados_parseaveis","caso_id":cid,"arquivo_origem":rel,"detalhe":"Conteúdo não foi convertido; arquivo original preservado e inventariado.","severidade":"revisar"})
                except Exception as exc:
                    add_inventory(inventory,root,p,cid,"erro_leitura",0,repr(exc))
                    audit.append({"tipo_ocorrencia":"erro_leitura_dat","caso_id":cid,"arquivo_origem":p.relative_to(root).as_posix(),"detalhe":repr(exc),"severidade":"erro"})
        for p in sorted(cdir.rglob("log.QOleoMeio")):
            try:
                txt=p.read_text(encoding="utf-8",errors="replace"); t=None; n=0
                pat=re.compile(r"weightedAreaIntegrate\(plano_meio\) of U\s*=\s*\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)")
                for ln,line in enumerate(txt.splitlines(),1):
                    mt=re.search(r"Time\s*=\s*([-+0-9.eE]+)",line)
                    if mt and is_num(mt.group(1)): t=float(mt.group(1))
                    m=pat.search(line)
                    if m and t is not None:
                        x,y,z=map(float,m.groups())
                        tables["qoleomeio_temporal"].append({**meta,"tempo_s":t,"componente_x_m3_s":x,"componente_y_m3_s":y,"componente_z_m3_s":z,"valor_bruto":m.group(0),"arquivo_origem":p.relative_to(root).as_posix(),"linha_arquivo":ln}); n+=1
                add_inventory(inventory,root,p,cid,"valido" if n else "sem_dados_parseaveis",n,"extração específica de weightedAreaIntegrate(plano_meio) of U")
            except Exception as exc:
                add_inventory(inventory,root,p,cid,"erro_leitura",0,repr(exc))
                audit.append({"tipo_ocorrencia":"erro_leitura_log_qoleomeio","caso_id":cid,"arquivo_origem":p.relative_to(root).as_posix(),"detalhe":repr(exc),"severidade":"erro"})

    # Calcula atrito para todos os tempos numéricos com os dois campos presentes.
    friction_rows=calculate_friction_for_cases(root,cases,friction_script,inventory,audit)
    legacy_rows=ingest_legacy_friction(root,inventory,audit)

    # Hashes idênticos são sinalizados, sem exclusão de ocorrências.
    for digest,paths in sorted(file_hashes.items()):
        if len(paths)>1:
            audit.append({"tipo_ocorrencia":"arquivos_identicos_hash","caso_id":"","arquivo_origem":" | ".join(paths),"detalhe":f"SHA256={digest}; todas as ocorrências foram mantidas.","severidade":"informativo"})
    for tn,rows in tables.items():
        seen=defaultdict(list)
        for r in rows:
            key=(r.get("caso_id"),r.get("tempo_s"),r.get("arquivo_origem"),r.get("linha_registro",r.get("linha_arquivo")),r.get("funcao"))
            seen[key].append(r)
        for key,group in seen.items():
            if len(group)>1:
                audit.append({"tipo_ocorrencia":"registros_com_mesma_chave_de_origem","caso_id":key[0] or "","arquivo_origem":key[2] or "","detalhe":f"tabela={tn}; chave={key}; n={len(group)}; registros mantidos.","severidade":"revisar"})

    raw_dir=out/"dados_brutos"; proc_dir=out/"dados_processados"; audit_dir=out/"auditoria"; legacy_dir=out/"dados_referencia_legada"
    for d in (raw_dir,proc_dir,audit_dir,legacy_dir): d.mkdir(parents=True,exist_ok=True)
    raw_names=("sampling_temporal","functionObjects_temporais","qoleomeio_temporal","comparacao_planos_axiais","resultados_hL","demais_csv_temporais","resultados_derivados")
    for name in raw_names: write_csv(raw_dir/f"{name}.csv",tables[name])
    write_csv(proc_dir/"atrito_temporal.csv",friction_rows)
    write_csv(legacy_dir/"atrito_legado.csv",legacy_rows)
    write_csv(audit_dir/"casos_disponiveis.csv",cases)
    write_csv(audit_dir/"inventario_arquivos.csv",inventory)
    write_csv(audit_dir/"auditoria_registros.csv",audit,["tipo_ocorrencia","caso_id","arquivo_origem","detalhe","severidade"])

    manifest={"versao_consolidador":VERSION,"raiz":str(root),"saida":str(out),
      "politica":"extração bruta + cálculo explícito de atrito; sem janelas, médias temporais, interpolação, filtros, GCI ou exclusão de duplicatas",
      "casos_localizados":len(cases),"arquivos_inventariados":len(inventory),
      "registros_por_tabela_bruta":{k:len(tables[k]) for k in raw_names},
      "registros_atrito_calculado":len(friction_rows),"registros_atrito_legado":len(legacy_rows),"ocorrencias_auditoria":len(audit),
      "calculo_atrito":{"script_referencia":str(friction_script),"rho_kg_m3":900,
        "campos": ["alpha.oil","wallShearStress"],"patches":["parede_interna","parede_externa"],
        "ponderacao":"alpha.oil da célula owner multiplicada pela área geométrica da face",
        "forca":"integral da magnitude do cisalhamento ponderada; não é resultante vetorial axial",
        "tempos":"todos os diretórios temporais numéricos com ambos os campos disponíveis"},
      "observacoes":["R1/R2/R3 permanecem casos independentes; não são réplicas estatísticas.",
        "Força integrada (N) e tensão de cisalhamento (Pa) permanecem em colunas distintas.",
        "CSV históricos de atrito foram isolados em dados_referencia_legada e não compõem atrito_temporal.csv.",
        "Arquivos .dat não reconhecidos permanecem inventariados; não são descartados nem interpretados à força.",
        "Nenhum campo ou arquivo foi escrito/modificado na árvore dos casos de origem."]}
    (audit_dir/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    return {"casos":len(cases),"arquivos":len(inventory),"auditoria":len(audit),"atrito_calculado":len(friction_rows),"atrito_legado":len(legacy_rows),**{k:len(tables[k]) for k in raw_names}}


def main():
    ap=argparse.ArgumentParser(description="Consolidador central CFD — v1.3.0")
    ap.add_argument("--root",type=Path,default=Path("."),help="Raiz contendo os 15 casos")
    ap.add_argument("--out",type=Path,default=Path("resultados_consolidados_v1.3.0"),help="Nova pasta de saída; não sobrescreve diretório existente")
    ap.add_argument("--friction-script",type=Path,default=Path("calcular_atrito_paredes.py"),help="Script original usado para o cálculo de atrito")
    a=ap.parse_args()
    try: counts=run(a.root,a.out,a.friction_script)
    except Exception as e: print(f"[ERRO] {e}",file=sys.stderr); return 2
    print("CONSOLIDAÇÃO CONCLUÍDA — v"+VERSION)
    for k,v in counts.items(): print(f"{k}: {v}")
    print(f"Saída: {a.out.resolve()}")
    return 0

if __name__=="__main__": raise SystemExit(main())
