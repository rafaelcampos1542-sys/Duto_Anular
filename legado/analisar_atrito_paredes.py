import re
import numpy as np
from pathlib import Path

# ============================================================
# CONFIGURAÇÃO
# ============================================================

CASE = Path("M1/M1_Q35")
TIME = "6.000051592733528"

R_INT = 0.0375
R_EXT = 0.0575

# Tolerância usada na identificação da primeira camada
TOL = 0.00005

DIR_COORD = CASE / "0"
DIR_TIME = CASE / TIME


# ============================================================
# LEITURA DOS CAMPOS OPENFOAM
# ============================================================

def read_internal_field(path, field_type="scalar"):

    text = path.read_text()

    if field_type == "scalar":
        pattern = (
            r"internalField\s+nonuniform\s+"
            r"List<scalar>\s+(\d+)\s*\((.*?)\)\s*;"
        )
        ncomp = 1

    elif field_type == "vector":
        pattern = (
            r"internalField\s+nonuniform\s+"
            r"List<vector>\s+(\d+)\s*\((.*?)\)\s*;"
        )
        ncomp = 3

    match = re.search(pattern, text, re.S)

    if not match:
        raise ValueError(f"Não foi possível ler {path}")

    n = int(match.group(1))

    if field_type == "scalar":
        values = np.fromstring(match.group(2), sep=" ")

    else:
        values = np.fromstring(
            re.sub(r"[()]", " ", match.group(2)),
            sep=" "
        )

    if len(values) != n * ncomp:
        raise ValueError(
            f"Quantidade incorreta em {path}: "
            f"esperado {n*ncomp}, encontrado {len(values)}"
        )

    if field_type == "vector":
        values = values.reshape(n, 3)

    return values


# ============================================================
# LEITURA
# ============================================================

print("Lendo campos...")

cx = read_internal_field(DIR_COORD / "Cx")
cz = read_internal_field(DIR_COORD / "Cz")

alpha = read_internal_field(
    DIR_TIME / "alpha.oil"
)

tau = read_internal_field(
    DIR_TIME / "wallShearStress",
    "vector"
)

# ============================================================
# VERIFICAÇÃO
# ============================================================

n = len(cx)

assert len(cz) == n
assert len(alpha) == n
assert len(tau) == n

print(f"Campos carregados: {n:,} células")

# ============================================================
# DISTÂNCIA RADIAL
# ============================================================

r = np.hypot(cx, cz)

dist_int = r - R_INT
dist_ext = R_EXT - r

# ============================================================
# ANÁLISE
# ============================================================

def analisar_parede(nome, distancia):

    dmin = distancia.min()

    mask = np.abs(distancia - dmin) <= TOL

    a = alpha[mask]
    t = np.linalg.norm(tau[mask], axis=1)

    rho = 900.0*a + 1.2*(1.0-a)

    tau_dyn = rho*t

    print("\n" + "="*55)
    print(nome)
    print("="*55)

    print(f"Células: {mask.sum():,}")
    print(f"Distância média: {distancia[mask].mean()*1000:.6f} mm")

    print("\nFração de óleo:")
    print(f"Média: {a.mean():.8f}")
    print(f"Mínimo: {a.min():.8f}")
    print(f"Máximo: {a.max():.8f}")

    print("\nTensão cinemática:")
    print(f"Média: {t.mean():.8e} m²/s²")
    print(f"Mínimo: {t.min():.8e} m²/s²")
    print(f"Máximo: {t.max():.8e} m²/s²")

    print("\nDensidade reconstruída:")
    print(f"Média: {rho.mean():.6f} kg/m³")

    print("\nTensão dinâmica equivalente:")
    print(f"Média: {tau_dyn.mean():.8e} Pa")
    print(f"Mínimo: {tau_dyn.min():.8e} Pa")
    print(f"Máximo: {tau_dyn.max():.8e} Pa")

    return mask


mask_int = analisar_parede(
    "PAREDE INTERNA",
    dist_int
)

mask_ext = analisar_parede(
    "PAREDE EXTERNA",
    dist_ext
)

print("\nAnálise concluída.")
