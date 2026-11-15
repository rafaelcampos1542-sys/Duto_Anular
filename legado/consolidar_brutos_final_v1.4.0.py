#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Consolidador final de dados úteis — OpenFOAM / Duto Anular — v1.4.0

Somente leitura na árvore de origem. Calcula atrito com o algoritmo de referência; não filtra
janelas temporais, não interpola, não calcula médias/balanços/GCI e não remove
registros duplicados. A saída é gravada em diretório separado.

Uso:
  ./venv/bin/python consolidar_brutos_final_v1.4.0.py --root . --out resultados_consolidados_final_v1.4.0
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, math, re, sys
from collections import defaultdict
from pathlib import Path
from typing import Any

VERSION = "1.4.0"
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
    """
    Extrai somente registros reconhecidos e preserva metadados do cabeçalho.
    Formatos suportados:
      - tempo + escalar;
      - tempo + vetor (x y z);
      - tempo + patch + vetor mínimo + vetor máximo (wallShear).
    Arquivos não reconhecidos permanecem no inventário, sem entrar nas tabelas úteis.
    """
    metadata = {
        "region_type": "",
        "patch_cabecalho": "",
        "faces_cabecalho": "",
        "area_cabecalho_m2": "",
        "scale_factor_cabecalho": "",
        "weight_field_cabecalho": "",
        "operacao_cabecalho": "",
    }
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("#"):
            continue
        h = s[1:].strip()
        if h.lower().startswith("region type"):
            metadata["region_type"] = h.split(":", 1)[-1].strip()
            if "patch " in metadata["region_type"]:
                metadata["patch_cabecalho"] = metadata["region_type"].split("patch ", 1)[1].strip()
        elif h.lower().startswith("faces"):
            metadata["faces_cabecalho"] = h.split(":", 1)[-1].strip()
        elif h.lower().startswith("area"):
            metadata["area_cabecalho_m2"] = h.split(":", 1)[-1].strip()
        elif h.lower().startswith("scale factor"):
            metadata["scale_factor_cabecalho"] = h.split(":", 1)[-1].strip()
        elif h.lower().startswith("weight field"):
            metadata["weight_field_cabecalho"] = h.split(":", 1)[-1].strip()
        elif h.lower().startswith("time"):
            metadata["operacao_cabecalho"] = h.split(")", 1)[0].split(" ", 1)[-1].strip()

    out = []
    for line_no, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue

        # wallShear: tempo, patch, vetor mínimo e vetor máximo.
        wall_match = re.fullmatch(
            r"\s*([-+0-9.eE]+)\s+(\S+)\s+"
            r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)\s+"
            r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)\s*",
            s
        )
        if wall_match:
            vals = wall_match.groups()
            try:
                nums = [float(x) for x in (vals[0], *vals[2:])]
            except ValueError:
                continue
            if not all(math.isfinite(x) for x in nums):
                continue
            out.append({
                **metadata, "linha_arquivo": line_no, "tempo_s": nums[0],
                "tipo_valor": "vetores_min_max", "patch_registro": vals[1],
                "valor_escalar": "", "componente_x": "", "componente_y": "", "componente_z": "",
                "min_x": nums[1], "min_y": nums[2], "min_z": nums[3],
                "max_x": nums[4], "max_y": nums[5], "max_z": nums[6],
                "valor_bruto": s
            })
            continue

        nums = NUM_RE.findall(s)
        if len(nums) not in (2, 4):
            continue
        try:
            v = [float(x) for x in nums]
        except ValueError:
            continue
        if not all(math.isfinite(x) for x in v):
            continue
        if len(v) == 2:
            rec = {
                **metadata, "linha_arquivo": line_no, "tempo_s": v[0],
                "tipo_valor": "escalar", "patch_registro": "",
                "valor_escalar": v[1], "componente_x": "", "componente_y": "", "componente_z": "",
                "min_x": "", "min_y": "", "min_z": "", "max_x": "", "max_y": "", "max_z": "",
                "valor_bruto": s
            }
        else:
            rec = {
                **metadata, "linha_arquivo": line_no, "tempo_s": v[0],
                "tipo_valor": "vetor", "patch_registro": "",
                "valor_escalar": "", "componente_x": v[1], "componente_y": v[2], "componente_z": v[3],
                "min_x": "", "min_y": "", "min_z": "", "max_x": "", "max_y": "", "max_z": "",
                "valor_bruto": s
            }
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


# Implementação incorporada do cálculo de calcular_atrito_paredes.py.
# A fórmula e os parâmetros são preservados; a leitura e a geometria são otimizadas.
RHO_OIL = 900.0
VECTOR_RE = re.compile(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)")


def read_foam_list(path: Path, marker: str | None = None):
    """Lê uma lista OpenFOAM usando o terminador `);`, sem varredura caractere a caractere."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if marker:
        pos = text.find(marker)
        if pos < 0:
            raise RuntimeError(f"Marcador não encontrado: {marker}")
        text = text[pos:]
    match = re.search(r"\b(\d+)\s*\((.*?)\)\s*;", text, re.S)
    if not match:
        raise RuntimeError(f"Lista não encontrada ou sem terminador `);`: {path}")
    return int(match.group(1)), match.group(2)


def read_scalar_field(path: Path):
    count, content = read_foam_list(path, "internalField")
    values = [float(x) for x in NUM_RE.findall(content)]
    if len(values) != count:
        raise RuntimeError(f"{path.name}: esperados {count}, lidos {len(values)}")
    return values


def read_vector_list(path: Path, patch: str):
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        rf"\b{re.escape(patch)}\s*\{{.*?\bvalue\s+nonuniform\s+List<vector>\s+(\d+)\s*\((.*?)\)\s*;",
        text, re.S
    )
    if not match:
        raise RuntimeError(f"Valores vetoriais não encontrados para {patch} em {path}")
    count = int(match.group(1))
    vectors = VECTOR_RE.findall(match.group(2))
    if len(vectors) != count:
        raise RuntimeError(f"{patch}: esperados {count} vetores, lidos {len(vectors)}")
    return [tuple(map(float, v)) for v in vectors]


def read_points_fast(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")

    match = re.search(r"\b(\d+)\s*\(", text)
    if not match:
        raise RuntimeError(f"Lista de pontos não encontrada: {path}")

    count = int(match.group(1))
    start = match.end()

    depth = 1
    i = start

    while i < len(text) and depth:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1

    if depth != 0:
        raise RuntimeError(f"Lista de pontos incompleta: {path}")

    content = text[start:i - 1]
    vectors = VECTOR_RE.findall(content)

    if len(vectors) != count:
        raise RuntimeError(
            f"Points: esperados {count}, lidos {len(vectors)}"
        )

    return [tuple(map(float, v)) for v in vectors]


def read_patches_fast(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    patches = {}
    for name in ("interna", "externa"):
        patch_name = f"parede_{name}"
        match = re.search(rf"\b{patch_name}\s*\{{(.*?)\}}", text, re.S)
        if not match:
            raise RuntimeError(f"Patch não encontrado: {patch_name}")
        nf = re.search(r"\bnFaces\s+(\d+)\s*;", match.group(1))
        sf = re.search(r"\bstartFace\s+(\d+)\s*;", match.group(1))
        if not nf or not sf:
            raise RuntimeError(f"Dados incompletos: {patch_name}")
        patches[name] = {"nFaces": int(nf.group(1)), "startFace": int(sf.group(1))}
    return patches


def read_owner_range_fast(path: Path, first: int, last: int):
    values=[]; opened=False; index=0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            st=line.strip()
            if not opened:
                if st == "(": opened=True
                continue
            if index > last: break
            if first <= index <= last: values.append(int(st))
            index += 1
    if len(values) != last-first+1:
        raise RuntimeError("Falha na leitura de owner")
    return values


def read_selected_faces_fast(path: Path, first: int, last: int):
    selected={}; opened=False; index=0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            st=line.strip()
            if not opened:
                if st == "(": opened=True
                continue
            if index > last: break
            if first <= index <= last:
                match=re.search(r"\d+\(([^()]*)\)", st)
                if not match: raise RuntimeError(f"Face inválida: {index}")
                selected[index]=[int(x) for x in match.group(1).split()]
            index += 1
    if len(selected) != last-first+1:
        raise RuntimeError("Falha na leitura de faces")
    return selected


def cross(a,b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def face_area(vertices):
    av=[0.0,0.0,0.0]
    for i in range(len(vertices)):
        c=cross(vertices[i],vertices[(i+1)%len(vertices)])
        for k in range(3): av[k]+=c[k]
    return 0.5*math.sqrt(sum(x*x for x in av))


def magnitude(v):
    return math.sqrt(sum(x*x for x in v))


def prepare_case_friction_mesh(mesh: Path):
    """Lê a malha e pré-calcula área/owner uma única vez por caso."""
    patches=read_patches_fast(mesh/"boundary")
    points=read_points_fast(mesh/"points")
    first=min(p["startFace"] for p in patches.values())
    last=max(p["startFace"]+p["nFaces"] for p in patches.values())-1
    owners=read_owner_range_fast(mesh/"owner",first,last)
    faces=read_selected_faces_fast(mesh/"faces",first,last)
    prepared={}
    for name,patch in patches.items():
        entries=[]
        for j in range(patch["nFaces"]):
            face_id=patch["startFace"]+j
            owner=owners[face_id-first]
            area=face_area([points[k] for k in faces[face_id]])
            entries.append((owner,area))
        prepared[name]=entries
    return patches, points, owners, faces, first, prepared



def calculate_friction_time(t, time_dir, patches, prepared):
    """
    Calcula dois metodos:
    1. Original: ponderacao por alpha.oil e area da face.
    2. Oleo: somente faces com alpha.oil >= 0.99.
    """

    alpha = read_scalar_field(time_dir / "alpha.oil")
    row = {"tempo_s": t}

    total_area = 0.0
    total_integral = 0.0

    ALPHA_MIN = 0.99

    for name, patch in patches.items():

        tau = read_vector_list(
            time_dir / "wallShearStress",
            f"parede_{name}"
        )

        if len(tau) != patch["nFaces"]:
            raise RuntimeError(
                f"{name}: numero de faces incompatível"
            )

        # Acumuladores do metodo original
        geom_area = 0.0
        wet_area = 0.0
        weighted_tau = 0.0

        # Acumuladores do metodo filtrado
        oil_area = 0.0
        oil_integral = 0.0
        oil_faces = 0

        for j, (owner, area) in enumerate(prepared[name]):

            if not 0 <= owner < len(alpha):
                raise RuntimeError(
                    f"Owner invalido na face {name}: {owner}"
                )

            alpha_face = min(1.0, max(0.0, alpha[owner]))
            tau_kin = magnitude(tau[j])

            # METODO ORIGINAL
            weight = alpha_face * area

            geom_area += area
            wet_area += weight
            weighted_tau += weight * tau_kin

            # NOVO METODO: SOMENTE OLEO
            if alpha_face >= ALPHA_MIN:
                oil_faces += 1
                oil_area += area
                oil_integral += area * tau_kin

        # Resultados originais - mantidos
        mean_tau = (
            weighted_tau / wet_area
            if wet_area > 0 else float("nan")
        )

        row[f"area_geometrica_{name}_m2"] = geom_area
        row[f"area_ponderada_oleo_{name}_m2"] = wet_area
        row[f"tau_media_{name}_Pa"] = mean_tau * RHO_OIL
        row[f"integral_tau_ponderada_{name}_N"] = (
            weighted_tau * RHO_OIL
        )

        # Resultados novos - filtro alpha >= 0.99
        oil_mean_tau = (
            oil_integral / oil_area
            if oil_area > 0 else float("nan")
        )

        row[f"faces_oleo_{name}"] = oil_faces
        row[f"area_filtrada_oleo_{name}_m2"] = oil_area

        row[f"tau_media_filtrada_{name}_Pa"] = (
            oil_mean_tau * RHO_OIL
        )

        row[f"integral_tau_filtrada_{name}_N"] = (
            oil_integral * RHO_OIL
        )

        total_area += wet_area
        total_integral += weighted_tau * RHO_OIL

    # Resultado global original
    row["area_ponderada_oleo_total_m2"] = total_area
    row["integral_tau_ponderada_total_N"] = total_integral
    row["tau_media_global_Pa"] = (
        total_integral / total_area
        if total_area > 0 else float("nan")
    )

    return row


def calculate_friction_for_cases(root, cases, inventory, audit):
    """Calcula atrito internamente; não depende de calcular_atrito_paredes.py externo."""
    rows=[]
    total_cases=len(cases)
    for case_index,case in enumerate(cases,1):
        cid=case["caso_id"]; cdir=root/case["caminho_caso"]; mesh=cdir/"constant"/"polyMesh"
        print(f"[ATRITO {case_index}/{total_cases}] Preparando malha: {cid}",flush=True)
        try:
            patches,points,owners,faces,first,prepared=prepare_case_friction_mesh(mesh)
        except Exception as exc:
            audit.append({"tipo_ocorrencia":"falha_leitura_malha_atrito","caso_id":cid,
                          "arquivo_origem":mesh.as_posix(),"detalhe":repr(exc),"severidade":"erro"})
            print(f"[ERRO] {cid}: falha ao preparar malha: {exc}",flush=True)
            continue
        time_dirs=sorted(((float(p.name),p) for p in cdir.iterdir()
                          if p.is_dir() and re.fullmatch(r"\d+(?:\.\d+)?",p.name)),key=lambda x:x[0])
        available=sum(1 for _,td in time_dirs if (td/"alpha.oil").is_file() and (td/"wallShearStress").is_file())
        print(f"[ATRITO {case_index}/{total_cases}] {cid}: {available}/{len(time_dirs)} tempos com ambos os campos",flush=True)
        for ti,(t,time_dir) in enumerate(time_dirs,1):
            alpha_file=time_dir/"alpha.oil"; tau_file=time_dir/"wallShearStress"
            if not alpha_file.is_file() or not tau_file.is_file():
                missing=[n for n,pth in (("alpha.oil",alpha_file),("wallShearStress",tau_file)) if not pth.is_file()]
                audit.append({"tipo_ocorrencia":"tempo_sem_campos_para_atrito","caso_id":cid,
                    "arquivo_origem":time_dir.relative_to(root).as_posix(),
                    "detalhe":f"tempo_s={t}; campos ausentes={','.join(missing)}","severidade":"revisar"})
                continue
            try:
                result=calculate_friction_time(t,time_dir,patches,prepared)
                meta=case_meta(cid)
                row={**meta,**result,"fonte_calculo":"campos_OpenFOAM",
                     "versao_algoritmo":"consolidador_v1.3.1_metodo_calcular_atrito_paredes",
                     "rho_kg_m3":RHO_OIL,"arquivo_alpha_origem":alpha_file.relative_to(root).as_posix(),
                     "arquivo_wallShearStress_origem":tau_file.relative_to(root).as_posix(),
                     "malha_origem":mesh.relative_to(root).as_posix(),
                     "metodo_ponderacao":"alpha.oil da celula owner x area geometrica da face",
                     "observacao_forca":"integral da magnitude do cisalhamento; nao representa resultante vetorial axial"}
                rows.append(row)
                add_inventory(inventory,root,alpha_file,cid,"usado_calculo_atrito",1,f"tempo_s={t}; campo alpha.oil")
                add_inventory(inventory,root,tau_file,cid,"usado_calculo_atrito",1,f"tempo_s={t}; campo wallShearStress")
                if ti==1 or ti%5==0 or ti==len(time_dirs):
                    print(f"  [{cid}] {ti}/{len(time_dirs)} tempos verificados; {len(rows)} registros calculados até agora",flush=True)
            except Exception as exc:
                audit.append({"tipo_ocorrencia":"falha_calculo_atrito","caso_id":cid,
                    "arquivo_origem":time_dir.relative_to(root).as_posix(),
                    "detalhe":f"tempo_s={t}; {repr(exc)}","severidade":"erro"})
                print(f"[AVISO] {cid} t={t:g}: {exc}",flush=True)
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


def run(root: Path, out: Path):
    root=root.resolve(); out=out.resolve()
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
                        header_patch=rec.get("patch_cabecalho","")
                        expected_patch={"atritointerno":"parede_interna","atritoexterno":"parede_externa"}.get(fn.lower(),"")
                        patch_real=header_patch or rec.get("patch_registro","")
                        if expected_patch and patch_real:
                            patch_status="consistente" if patch_real==expected_patch else "patch_incompativel_com_nome_funcao"
                        elif expected_patch and not patch_real:
                            patch_status="patch_nao_identificavel"
                        else:
                            patch_status="nao_aplicavel"
                        tables["functionObjects_temporais"].append({
                            **meta,"funcao":fn,"objeto_arquivo":p.name,**rec,
                            "patch_identificado":patch_real,"patch_esperado_pelo_nome":expected_patch,
                            "status_associacao_patch":patch_status,"arquivo_origem":rel
                        })
                        if patch_status=="patch_incompativel_com_nome_funcao":
                            audit.append({
                                "tipo_ocorrencia":"configuracao_patch_inconsistente",
                                "caso_id":cid,"arquivo_origem":rel,
                                "detalhe":f"funcao={fn}; patch_cabecalho={patch_real}; esperado={expected_patch}; valores preservados e identificados pelo cabeçalho.",
                                "severidade":"revisar"
                            })
                        elif patch_status=="patch_nao_identificavel":
                            audit.append({
                                "tipo_ocorrencia":"patch_nao_identificavel",
                                "caso_id":cid,"arquivo_origem":rel,
                                "detalhe":f"funcao={fn}; não foi possível identificar o patch pelo cabeçalho.",
                                "severidade":"revisar"
                            })
                    status="valido" if parsed else ("vazio" if not raw.strip() else "sem_dados_parseaveis")
                    detail="parser de registros úteis; metadados de cabeçalho preservados; arquivos não reconhecidos ficam apenas no inventário"
                    add_inventory(inventory,root,p,cid,status,len(parsed),detail)
                    file_hashes[sha256(p)].append(rel)
                    if not parsed and raw.strip():
                        audit.append({"tipo_ocorrencia":"dat_sem_dados_parseaveis","caso_id":cid,"arquivo_origem":rel,"detalhe":"Conteúdo não reconhecido; não entrou nas tabelas úteis, mas permaneceu inventariado.","severidade":"revisar"})
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
    friction_rows=calculate_friction_for_cases(root,cases,inventory,audit)
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
      "calculo_atrito": {
          "implementacao": "integrada ao consolidador",
          "rho_oleo_kg_m3": 900.0,
          "campos": ["alpha.oil", "wallShearStress"],
          "patches": ["parede_interna", "parede_externa"],
          "metodo_original": "ponderacao de alpha.oil da celula owner pela area geometrica",
          "metodo_comparativo": "selecao de faces com alpha.oil >= 0.99; media ponderada pela area",
          "limite_alpha_oil": 0.99,
          "forca": "integral da magnitude da tensao nas faces selecionadas",
          "tempos": "todos os tempos com ambos os campos disponiveis"
      },
      "observacoes":["R1/R2/R3 permanecem casos independentes; não são réplicas estatísticas.",
        "Força integrada (N) e tensão de cisalhamento (Pa) permanecem em colunas distintas.",
        "CSV históricos de atrito foram isolados em dados_referencia_legada e não compõem atrito_temporal.csv.",
        "Somente registros .dat reconhecidos entram nas tabelas úteis; arquivos vazios ou não reconhecidos permanecem no inventário com status próprio.",
        "Cabeçalhos .dat são preservados; em funções de atrito, o patch real é identificado pelo cabeçalho e comparado ao nome da função.",
        "A auditoria de patch sinaliza inconsistências, mas não altera, corrige, descarta ou substitui valores históricos.",
        "Nenhum campo ou arquivo foi escrito/modificado na árvore dos casos de origem."]}
    (audit_dir/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    return {"casos":len(cases),"arquivos":len(inventory),"auditoria":len(audit),"atrito_calculado":len(friction_rows),"atrito_legado":len(legacy_rows),**{k:len(tables[k]) for k in raw_names}}


def main():
    ap=argparse.ArgumentParser(description="Consolidador final CFD — v1.4.0 (autônomo; extração e auditoria de patch)")
    ap.add_argument("--root",type=Path,default=Path("."),help="Raiz contendo os 15 casos")
    ap.add_argument("--out",type=Path,default=Path("resultados_consolidados_final_v1.4.0"),help="Nova pasta de saída; não sobrescreve diretório existente")
    a=ap.parse_args()
    try: counts=run(a.root,a.out)
    except Exception as e: print(f"[ERRO] {e}",file=sys.stderr); return 2
    print("CONSOLIDAÇÃO CONCLUÍDA — v"+VERSION)
    for k,v in counts.items(): print(f"{k}: {v}")
    print(f"Saída: {a.out.resolve()}")
    return 0

if __name__=="__main__": raise SystemExit(main())
