import re
import numpy as np
import csv
from pathlib import Path

# ============================================================
# CONFIGURACAO
# ============================================================

CASE = Path("M1/M1_Q35")
TIME = "6.000051592733528"

RHO_OIL = 900.0
RHO_AIR = 1.2
ALPHA_MIN = 0.99

MESH = CASE / "constant/polyMesh"
TIME_DIR = CASE / TIME

PATCHES = {
    "parede_interna": (4806000, 54000),
    "parede_externa": (4860000, 54000),
}


# ============================================================
# LEITURA DE LISTAS OPENFOAM
# ============================================================



def read_list(path, expected_type=None, components=1):

    text = path.read_text()

    # Remove o cabecalho FoamFile
    text = re.sub(
        r"FoamFile\s*\{.*?\}",
        "",
        text,
        count=1,
        flags=re.S
    )

    # Localiza a lista, aceitando fechamento com ou sem ;
    match = re.search(
        r"(?m)^\s*(\d+)\s*\(\s*(.*?)\s*\)\s*;?",
        text,
        re.S
    )

    if not match:
        raise ValueError(f"Lista nao encontrada: {path}")

    n = int(match.group(1))

    values = np.fromstring(
        match.group(2),
        sep=" "
    )

    if len(values) != n * components:
        raise ValueError(
            f"{path}: esperados {n*components} valores, "
            f"encontrados {len(values)}"
        )

    if components > 1:
        values = values.reshape(n, components)

    return values


def read_internal_scalar(path):

    text = path.read_text()

    match = re.search(
        r"internalField\s+nonuniform\s+"
        r"List<scalar>\s+(\d+)\s*\((.*?)\)\s*;",
        text,
        re.S
    )

    if not match:
        raise ValueError(f"InternalField nao encontrado: {path}")

    n = int(match.group(1))
    values = np.fromstring(match.group(2), sep=" ")

    if len(values) != n:
        raise ValueError(f"Quantidade incorreta em {path}")

    return values


def extract_patch(text, patch_name):

    match = re.search(
        rf"\b{re.escape(patch_name)}\s*\{{",
        text
    )

    if not match:
        raise ValueError(f"Patch nao encontrado: {patch_name}")

    start = match.end()
    depth = 1
    pos = start

    while depth and pos < len(text):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
        pos += 1

    if depth:
        raise ValueError(f"Bloco incompleto: {patch_name}")

    return text[start:pos-1]


def read_patch_vectors(path, patch_name):

    text = path.read_text()
    block = extract_patch(text, patch_name)

    match = re.search(
        r"value\s+nonuniform\s+List<vector>\s+"
        r"(\d+)\s*\((.*?)\)\s*;",
        block,
        re.S
    )

    if not match:
        raise ValueError(
            f"Valores vetoriais nao encontrados em {patch_name}"
        )

    n = int(match.group(1))

    values = np.fromstring(
        re.sub(r"[()]", " ", match.group(2)),
        sep=" "
    )

    if len(values) != 3*n:
        raise ValueError(
            f"{patch_name}: esperados {3*n}, encontrados {len(values)}"
        )

    return values.reshape(n, 3)


# ============================================================
# LEITURA DOS CAMPOS
# ============================================================

print("Lendo owner...")
owner = read_list(MESH / "owner", r"labelList", 1).astype(np.int64)

print("Lendo alpha.oil...")
alpha = read_internal_scalar(TIME_DIR / "alpha.oil")

print("Lendo wallShearStress...")
stress_file = TIME_DIR / "wallShearStress"

# ============================================================
# VALIDACOES
# ============================================================

if len(alpha) != 1620000:
    raise ValueError("Numero inesperado de celulas em alpha.oil")

if len(owner) != 4923000:
    raise ValueError("Numero inesperado de faces em owner")

print(f"Celulas: {len(alpha):,}")
print(f"Faces: {len(owner):,}")



# ============================================================
# ANALISE DO ATRITO NAS REGIOES OCUPADAS POR OLEO
# ============================================================

output_dir = Path("resultados_atrito_oleo_M1_Q35")
output_dir.mkdir(exist_ok=True)

for patch, (start, count) in PATCHES.items():

    print("\n" + "=" * 60)
    print(patch)
    print("=" * 60)

    end = start + count
    face_owner = owner[start:end]

    if len(face_owner) != count:
        raise ValueError(f"Quantidade incorreta de faces: {patch}")

    if face_owner.min() < 0 or face_owner.max() >= len(alpha):
        raise ValueError(f"Indice owner invalido: {patch}")

    alpha_adj = alpha[face_owner]

    tau_vector = read_patch_vectors(stress_file, patch)

    if len(tau_vector) != count:
        raise ValueError(
            f"Quantidade de tensoes diferente das faces: {patch}"
        )

    # Magnitude da tensao cinematica
    tau_kin = np.linalg.norm(tau_vector, axis=1)

    # Selecao das faces adjacentes a celulas preenchidas por oleo
    mask_oil = alpha_adj >= ALPHA_MIN

    n_oil = np.count_nonzero(mask_oil)
    percentual = 100.0 * n_oil / count

    if n_oil == 0:
        raise ValueError(
            f"Nenhuma face com alpha.oil >= {ALPHA_MIN}: {patch}"
        )

    # Tensao dinamica do oleo nas faces selecionadas
    tau_oil = RHO_OIL * tau_kin[mask_oil]

    print(f"Faces totais: {count:,}")
    print(f"Faces selecionadas: {n_oil:,}")
    print(f"Percentual selecionado: {percentual:.2f}%")
    print(f"Limite alpha.oil: {ALPHA_MIN}")

    print("\nAlpha.oil selecionado:")
    print(f"Media: {alpha_adj[mask_oil].mean():.8f}")
    print(f"Minimo: {alpha_adj[mask_oil].min():.8f}")
    print(f"Maximo: {alpha_adj[mask_oil].max():.8f}")

    print("\nAtrito do oleo:")
    print(f"Media: {tau_oil.mean():.8e} Pa")
    print(f"Mediana: {np.median(tau_oil):.8e} Pa")
    print(f"Desvio padrao: {tau_oil.std():.8e} Pa")
    print(f"Minimo: {tau_oil.min():.8e} Pa")
    print(f"Maximo: {tau_oil.max():.8e} Pa")

    # Exportacao de todas as faces, preservando a identificacao
    output_file = output_dir / f"{patch}.csv"

    with output_file.open("w", newline="") as f:
        writer = csv.writer(f)

        writer.writerow([
            "face_local",
            "cell_owner",
            "alpha_oil",
            "selecionada",
            "tau_kin_m2_s2",
            "tau_oil_Pa"
        ])

        for i in range(count):
            selecionada = bool(mask_oil[i])

            writer.writerow([
                i,
                int(face_owner[i]),
                alpha_adj[i],
                selecionada,
                tau_kin[i],
                RHO_OIL * tau_kin[i] if selecionada else ""
            ])

    print(f"\nCSV salvo: {output_file}")

print("\nAnalise concluida.")
