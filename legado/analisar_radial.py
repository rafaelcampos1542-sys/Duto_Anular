import re
import numpy as np
from pathlib import Path

case = Path("M1/M1_Q35/0")

def read_scalar_field(path):
    text = path.read_text()
    match = re.search(
        r"internalField\s+nonuniform\s+List<scalar>\s+(\d+)\s*\((.*?)\)\s*;",
        text,
        re.S
    )

    if not match:
        raise ValueError(f"Erro ao ler {path}")

    n = int(match.group(1))
    values = np.fromstring(match.group(2), sep=" ")

    if len(values) != n:
        raise ValueError(f"Quantidade incorreta em {path}")

    return values

cx = read_scalar_field(case / "Cx")
cz = read_scalar_field(case / "Cz")

r = np.sqrt(cx**2 + cz**2)

raio_interno = 0.0375
raio_externo = 0.0575

dist_interna = r - raio_interno
dist_externa = raio_externo - r

for nome, dist in [
    ("PAREDE INTERNA", dist_interna),
    ("PAREDE EXTERNA", dist_externa),
]:
    print(f"\n=== {nome} ===")

    primeira_camada = np.isclose(
        dist,
        dist.min(),
        atol=1e-7
    )

    valores = dist[primeira_camada]

    print("Células:", len(valores))
    print("Distância mínima:", f"{dist.min()*1000:.6f} mm")
    print("Distância máxima:", f"{dist.max()*1000:.6f} mm")