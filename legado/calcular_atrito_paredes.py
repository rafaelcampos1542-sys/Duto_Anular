#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calcula atrito médio nas paredes interna/externa e exporta CSV.

Uso:
  python calcular_atrito_paredes.py CASO
  python calcular_atrito_paredes.py CASO 5.0
  python calcular_atrito_paredes.py CASO --output caminho/atrito.csv

Sem TEMPO, processa todos os diretórios temporais disponíveis.
A área ponderada usa alpha.oil da célula proprietária da face como estimativa
da fração molhada; não é uma reconstrução geométrica exata da linha de contato.
"""

import argparse
import csv
import math
import re
from pathlib import Path


def read_list(path, marker=None):
    text = path.read_text(errors="replace")
    if marker:
        pos = text.find(marker)
        if pos < 0:
            raise RuntimeError(f"Marcador não encontrado: {marker}")
        text = text[pos:]
    match = re.search(r"\b(\d+)\s*\(", text)
    if not match:
        raise RuntimeError(f"Lista não encontrada: {path}")
    count, start = int(match.group(1)), match.end()
    depth, i = 1, start
    while i < len(text) and depth:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    if depth:
        raise RuntimeError(f"Lista incompleta: {path}")
    return count, text[start:i - 1]


def read_scalar_field(path):
    count, content = read_list(path, "internalField")
    values = [float(x) for x in content.split()]
    if len(values) != count:
        raise RuntimeError(f"{path.name}: esperados {count}, lidos {len(values)}")
    return values


def read_vector_list(path, patch):
    text = path.read_text(errors="replace")
    match = re.search(
        rf"\b{re.escape(patch)}\s*\{{.*?"
        rf"\bvalue\s+nonuniform\s+List<vector>\s+(\d+)\s*\(",
        text, re.S
    )
    if not match:
        raise RuntimeError(f"Valores não encontrados para {patch} em {path}")
    count, start = int(match.group(1)), match.end()
    depth, i = 1, start
    while i < len(text) and depth:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    if depth:
        raise RuntimeError(f"Lista vetorial incompleta: {patch}")
    vectors = re.findall(
        r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)",
        text[start:i - 1]
    )
    if len(vectors) != count:
        raise RuntimeError(f"{patch}: esperados {count}, lidos {len(vectors)}")
    return [tuple(map(float, v)) for v in vectors]


def read_points(path):
    count, content = read_list(path)
    vectors = re.findall(
        r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)",
        content
    )
    if len(vectors) != count:
        raise RuntimeError(f"Points: esperados {count}, lidos {len(vectors)}")
    return [tuple(map(float, v)) for v in vectors]


def read_patches(path):
    text = path.read_text(errors="replace")
    patches = {}
    for name in ("interna", "externa"):
        patch_name = f"parede_{name}"
        match = re.search(rf"\b{patch_name}\s*\{{(.*?)\}}", text, re.S)
        if not match:
            raise RuntimeError(f"Patch não encontrado: {patch_name}")
        block = match.group(1)
        nf = re.search(r"\bnFaces\s+(\d+)\s*;", block)
        sf = re.search(r"\bstartFace\s+(\d+)\s*;", block)
        if not nf or not sf:
            raise RuntimeError(f"Dados incompletos: {patch_name}")
        patches[name] = {"nFaces": int(nf.group(1)), "startFace": int(sf.group(1))}
    return patches


def read_owner_range(path, first, last):
    values, opened, index = [], False, 0
    with path.open() as f:
        for line in f:
            if not opened:
                if line.strip() == "(":
                    opened = True
                continue
            if index > last:
                break
            if first <= index <= last:
                values.append(int(line.strip()))
            index += 1
    if len(values) != last - first + 1:
        raise RuntimeError("Falha na leitura de owner")
    return values


def read_selected_faces(path, first, last):
    selected, opened, index = {}, False, 0
    with path.open() as f:
        for line in f:
            if not opened:
                if line.strip() == "(":
                    opened = True
                continue
            if index > last:
                break
            if first <= index <= last:
                match = re.search(r"\d+\(([^()]*)\)", line)
                if not match:
                    raise RuntimeError(f"Face inválida: {index}")
                selected[index] = [int(x) for x in match.group(1).split()]
            index += 1
    if len(selected) != last - first + 1:
        raise RuntimeError("Falha na leitura de faces")
    return selected


def cross(a, b):
    return (
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    )


def face_area(vertices):
    av = [0.0, 0.0, 0.0]
    for i in range(len(vertices)):
        c = cross(vertices[i], vertices[(i + 1) % len(vertices)])
        for k in range(3):
            av[k] += c[k]
    return 0.5 * math.sqrt(sum(x*x for x in av))


def magnitude(v):
    return math.sqrt(sum(x*x for x in v))


def calculate_time(t, time_dir, patches, points, owners, faces, first):
    alpha = read_scalar_field(time_dir / "alpha.oil")
    row = {"tempo_s": t}
    total_area, total_integral = 0.0, 0.0

    for name, patch in patches.items():
        tau = read_vector_list(time_dir / "wallShearStress", f"parede_{name}")
        if len(tau) != patch["nFaces"]:
            raise RuntimeError(f"{name}: número de faces de wallShearStress incompatível")

        geom_area = wet_area = weighted_tau = 0.0
        for j in range(patch["nFaces"]):
            face_id = patch["startFace"] + j
            owner = owners[face_id - first]
            if not 0 <= owner < len(alpha):
                raise RuntimeError(f"Owner inválido na face {face_id}: {owner}")
            area = face_area([points[k] for k in faces[face_id]])
            alpha_face = min(1.0, max(0.0, alpha[owner]))
            weight = alpha_face * area
            geom_area += area
            wet_area += weight
            weighted_tau += weight * magnitude(tau[j])

        mean_tau = weighted_tau / wet_area if wet_area > 0 else float("nan")
        row[f"area_geometrica_{name}_m2"] = geom_area
        row[f"area_ponderada_oleo_{name}_m2"] = wet_area
        row[f"tau_media_{name}_Pa"] = mean_tau * 900
        row[f"integral_tau_ponderada_{name}_N"] = weighted_tau * 900
        total_area += wet_area
        total_integral += weighted_tau * 900

    row["area_ponderada_oleo_total_m2"] = total_area
    row["integral_tau_ponderada_total_N"] = total_integral
    row["tau_media_global_Pa"] = (
        total_integral / total_area if total_area > 0 else float("nan")
    )
    return row


def main():
    parser = argparse.ArgumentParser(description="Pós-processamento do atrito nas paredes.")
    parser.add_argument("caso", help="Diretório do caso OpenFOAM")
    parser.add_argument("tempo", nargs="?", type=float, help="Tempo específico (opcional)")
    parser.add_argument("--output", help="CSV de saída (padrão: CASO/atrito_paredes.csv)")
    args = parser.parse_args()

    case = Path(args.caso).expanduser().resolve()
    if not case.is_dir():
        raise SystemExit(f"Diretório não encontrado: {case}")

    mesh = case / "constant/polyMesh"
    patches = read_patches(mesh / "boundary")
    points = read_points(mesh / "points")
    first = min(p["startFace"] for p in patches.values())
    last = max(p["startFace"] + p["nFaces"] for p in patches.values()) - 1
    owners = read_owner_range(mesh / "owner", first, last)
    faces = read_selected_faces(mesh / "faces", first, last)

    times = sorted(
        ((float(p.name), p) for p in case.iterdir()
         if p.is_dir() and re.fullmatch(r"\d+(?:\.\d+)?", p.name)),
        key=lambda x: x[0]
    )
    if not times:
        raise SystemExit("Nenhum diretório temporal encontrado.")
    if args.tempo is not None:
        chosen = min(times, key=lambda x: abs(x[0] - args.tempo))
        if abs(chosen[0] - args.tempo) > 0.01:
            raise SystemExit(f"Não há tempo gravado próximo de {args.tempo} s (tol. 0,01 s).")
        times = [chosen]

    output = Path(args.output).expanduser().resolve() if args.output else case / "atrito_paredes.csv"
    output.parent.mkdir(parents=True, exist_ok=True)

    rows, skipped = [], []
    print(f"Caso: {case}")
    print(f"Tempos selecionados: {len(times)}")

    for t, time_dir in times:
        alpha_file = time_dir / "alpha.oil"
        tau_file = time_dir / "wallShearStress"
        if not alpha_file.is_file() or not tau_file.is_file():
            skipped.append((t, "alpha.oil ou wallShearStress ausente"))
            continue
        try:
            row = calculate_time(t, time_dir, patches, points, owners, faces, first)
            rows.append(row)
            print(
                f"[OK] t={t:.8g} s | interna={row['tau_media_interna_Pa']:.8g} Pa | "
                f"externa={row['tau_media_externa_Pa']:.8g} Pa | "
                f"global={row['tau_media_global_Pa']:.8g} Pa"
            )
        except Exception as exc:
            skipped.append((t, str(exc)))
            print(f"[AVISO] t={t:.8g} s ignorado: {exc}")

    if not rows:
        raise SystemExit("Nenhum tempo processado. Confira os campos e os patches.")

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nCSV salvo: {output}")
    print(f"Processados: {len(rows)} | Ignorados: {len(skipped)}")
    for t, reason in skipped:
        print(f"  t={t:.8g} s: {reason}")


if __name__ == "__main__":
    main()
