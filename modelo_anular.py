#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modelo_anular.py
Modelo analítico único do Canal Anular + geração das condições OpenFOAM.

Consolida as funções que estavam duplicadas em:
  - calculadora_anular.py
  - calcular_condicoes.py

Uso:
  python3 modelo_anular.py                  # teste rápido
  python3 modelo_anular.py condicoes 35     # gera condições para Q=35 L/min
  python3 modelo_anular.py curva             # gera curva analítica CSV
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import brentq


# ---------------------------------------------------------------------------
# PARÂMETROS DO MODELO
# ---------------------------------------------------------------------------
D_O = 0.115                  # diâmetro externo [m]
D_I = 0.075                  # diâmetro interno [m]
BETA = np.deg2rad(15.0)     # inclinação [rad]
G = 9.81                     # gravidade [m/s²]
RHO = 900.0                  # densidade do óleo [kg/m³]
MU = 0.576                   # viscosidade dinâmica [Pa·s]
EPSILON_ANALITICO = 1.5e-6  # rugosidade usada na curva analítica original [m]
EPSILON_CONDICOES = 0.0     # preserva o valor usado pelo gerador de BC original [m]

R_O = D_O / 2.0
R_I = D_I / 2.0
DELTA = (D_O - D_I) / 2.0


# ---------------------------------------------------------------------------
# GEOMETRIA E HIDRÁULICA
# ---------------------------------------------------------------------------
def area_circular_segment(d: float, h: float) -> float:
    """Área de segmento circular de diâmetro d e altura h."""
    if h <= 0:
        return 0.0
    if h >= d:
        return np.pi * d**2 / 4.0
    x = 1.0 - 2.0 * h / d
    x = np.clip(x, -1.0, 1.0)
    theta = np.arccos(x)
    return (d**2 / 4.0) * (theta - x * np.sqrt(max(0.0, 1.0 - x**2)))


def perimetro_molhado_circular(d: float, h: float) -> float:
    """Perímetro molhado de um segmento circular."""
    if h <= 0:
        return 0.0
    if h >= d:
        return np.pi * d
    x = np.clip(1.0 - 2.0 * h / d, -1.0, 1.0)
    return d * np.arccos(x)


def geometria(h_L: float, d_o: float = D_O, d_i: float = D_I):
    """
    Geometria hidráulica do anular parcialmente preenchido.

    Retorna:
        A_L [m²], S_L [m], D_h [m]
    """
    delta = (d_o - d_i) / 2.0

    if h_L <= 0:
        return 0.0, 0.0, 0.0

    if h_L <= delta:
        # Região 1: líquido abaixo do tubo interno.
        A_L = area_circular_segment(d_o, h_L)
        S_L = perimetro_molhado_circular(d_o, h_L)

    elif h_L <= (d_o - delta):
        # Região 2: líquido em contato com o tubo interno.
        A_total = area_circular_segment(d_o, h_L)
        h_i = h_L - delta
        A_interno = area_circular_segment(d_i, h_i)
        A_L = A_total - A_interno

        S_externo = perimetro_molhado_circular(d_o, h_L)
        S_interno = perimetro_molhado_circular(d_i, h_i)
        S_L = S_externo + S_interno

    else:
        # Região 3: tubo interno submerso.
        A_anular = np.pi * (d_o**2 - d_i**2) / 4.0
        h_vazio = d_o - h_L
        A_vazio = area_circular_segment(d_o, h_vazio)
        A_L = A_anular - A_vazio

        S_L = perimetro_molhado_circular(d_o, h_L) + np.pi * d_i

    D_h = 4.0 * A_L / S_L if S_L > 0 else 0.0
    return A_L, S_L, D_h


def churchill(Re: float, epsilon_Dh: float) -> float:
    """Fator de atrito de Churchill."""
    if Re <= 0:
        return 1.0

    A = (-2.457 * np.log((7.0 / Re) ** 0.9 + 0.27 * epsilon_Dh)) ** 16
    B = (37530.0 / Re) ** 16
    return 8.0 * ((8.0 / Re) ** 12 + 1.0 / (A + B) ** 1.5) ** (1.0 / 12.0)


def calcular_V_Q(
    h_L: float,
    d_o: float = D_O,
    d_i: float = D_I,
    beta: float = BETA,
    g: float = G,
    rho: float = RHO,
    mu: float = MU,
    epsilon: float = EPSILON_ANALITICO,
    tol: float = 1e-12,
    max_iter: int = 100,
):
    """Calcula V, Q, Re e f para uma altura h_L."""
    A_L, S_L, D_h = geometria(h_L, d_o, d_i)
    if D_h <= 0 or A_L <= 0:
        return 0.0, 0.0, 0.0, 0.0

    epsilon_Dh = epsilon / D_h
    f = 0.02

    for _ in range(max_iter):
        V = np.sqrt(2.0 * g * D_h * np.tan(beta) / f)
        Re = rho * V * D_h / mu
        f_new = churchill(Re, epsilon_Dh)
        if abs(f_new - f) < tol:
            f = f_new
            break
        f = f_new

    V = np.sqrt(2.0 * g * D_h * np.tan(beta) / f)
    Re = rho * V * D_h / mu
    Q = A_L * V
    return V, Q, Re, f


def Q_residual(h_L: float, Q_target: float, **kwargs) -> float:
    """Resíduo Q(h_L)-Q_target."""
    return calcular_V_Q(h_L, **kwargs)[1] - Q_target


def regiao_h(h_L: float, d_o: float = D_O, d_i: float = D_I) -> int:
    """Classifica a altura nas três regiões geométricas."""
    delta = (d_o - d_i) / 2.0
    if h_L <= delta:
        return 1
    if h_L <= d_o - delta:
        return 2
    return 3


def encontrar_raizes_Q(
    Q_target_m3s: float,
    d_o: float = D_O,
    d_i: float = D_I,
    epsilon: float = EPSILON_ANALITICO,
    n_pontos: int = 5000,
):
    """Encontra todas as raízes h_L para uma vazão alvo."""

    h_vals = np.linspace(
        0.0005,
        d_o - 0.0005,
        n_pontos,
    )

    Q_vals = np.array([
        calcular_V_Q(
            h,
            d_o=d_o,
            d_i=d_i,
            epsilon=epsilon,
        )[1]
        for h in h_vals
    ])

    residuos = Q_vals - Q_target_m3s
    sinais = np.sign(residuos)

    raizes = []

    for i in range(len(sinais) - 1):

        # Raiz exatamente em um dos pontos da malha
        if sinais[i] == 0:
            h_root = h_vals[i]

        # Mudança de sinal -> existe uma raiz no intervalo
        elif sinais[i] * sinais[i + 1] < 0:

            try:
                h_root = brentq(
                    lambda h: Q_residual(
                        h,
                        Q_target_m3s,
                        d_o=d_o,
                        d_i=d_i,
                        epsilon=epsilon,
                    ),
                    h_vals[i],
                    h_vals[i + 1],
                    xtol=1e-12,
                )

            except ValueError:
                continue

        else:
            continue

        V, Q, Re, f = calcular_V_Q(
            h_root,
            d_o=d_o,
            d_i=d_i,
            epsilon=epsilon,
        )

        raizes.append(
            (
                h_root,
                V,
                Q,
                Re,
                f,
                regiao_h(
                    h_root,
                    d_o,
                    d_i,
                ),
            )
        )

    raizes.sort(key=lambda x: x[0])

    return raizes


def gerar_curva(
    n_pontos: int = 1000,
    d_o: float = D_O,
    d_i: float = D_I,
    epsilon: float = EPSILON_ANALITICO,
):
    """Gera a curva analítica Q x h_L."""
    h_vals = np.linspace(0.0001, d_o - 0.0001, n_pontos)
    vals = [
        calcular_V_Q(h, d_o=d_o, d_i=d_i, epsilon=epsilon)
        for h in h_vals
    ]
    V_vals = np.array([v[0] for v in vals])
    Q_vals = np.array([v[1] for v in vals])
    Re_vals = np.array([v[2] for v in vals])
    return h_vals, Q_vals, V_vals, Re_vals


# ---------------------------------------------------------------------------
# GERAÇÃO DE ARQUIVOS OPENFOAM
# ---------------------------------------------------------------------------
def _header(object_name: str, field_class: str) -> str:
    return f"""/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2312                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       {field_class};
    object      {object_name};
}}
// ************************************************************************* //
"""


def gerar_setFieldsDict(h_L_m: float, Q_Lmin: float, V_m: float, destino: Path):
    z_max = -R_O + h_L_m
    conteudo = _header("setFieldsDict", "dictionary") + f"""
// Gerado automaticamente por modelo_anular.py
// Q = {Q_Lmin:.2f} L/min | h_L = {h_L_m*1000:.3f} mm | V = {V_m:.4f} m/s

defaultFieldValues
(
    volScalarFieldValue alpha.oil 0
);

regions
(
    boxToCell
    {{
        box (-0.06 -1.501 -0.06) (0.06 1.501 {z_max:.6f});
        fieldValues
        (
            volScalarFieldValue alpha.oil 1
        );
    }}
);
"""
    destino.write_text(conteudo)


def gerar_alpha_oil(h_L_m: float, Q_Lmin: float, destino: Path):
    z_iface = -R_O + h_L_m
    conteudo = _header("alpha.oil", "volScalarField") + f"""
// Q = {Q_Lmin:.2f} L/min | h_L = {h_L_m*1000:.3f} mm

dimensions      [0 0 0 0 0 0 0];
internalField   uniform 0;

boundaryField
{{
    inlet
    {{
        type            codedFixedValue;
        value           uniform 0;
        name            alphaOilInletProfile;

        code
        #{{ 
            const scalar hL_target = {h_L_m:.6f};
            const scalar rOut      = {R_O:.6f};
            const scalar zIface    = {z_iface:.6f};

            const fvPatch& p = this->patch();
            scalarField alpha(p.size(), 0.0);

            forAll(p, faceI)
            {{
                scalar zf = p.Cf()[faceI].z();
                alpha[faceI] = (zf < zIface) ? 1.0 : 0.0;
            }}

            operator==(alpha);
        #}};
    }}

    outlet
    {{
        type            inletOutlet;
        inletValue      uniform 0;
        value           uniform 0;
    }}

    parede_interna
    {{
        type            zeroGradient;
    }}

    parede_externa
    {{
        type            zeroGradient;
    }}
}}
"""
    destino.write_text(conteudo)


def gerar_U(h_L_m: float, V_m: float, Q_Lmin: float, destino: Path):
    conteudo = _header("U", "volVectorField") + f"""
// Q = {Q_Lmin:.2f} L/min | h_L = {h_L_m*1000:.3f} mm | V = {V_m:.4f} m/s

dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);

boundaryField
{{
    inlet
    {{
        type            codedFixedValue;
        value           uniform (0 0 0);
        name            velocityProfile;

        code
        #{{
            const fvPatch& p = this->patch();
            const fvMesh& mesh = p.boundaryMesh().mesh();
            vectorField v(p.size(), vector(0,0,0));

            const scalar uOleo = {V_m:.4f};
            const scalar uAr   = 0.01;

            const volScalarField* alphaPtr =
                mesh.findObject<volScalarField>("alpha.oil");

            if (!alphaPtr)
            {{
                forAll(v, faceI)
                    v[faceI] = vector(0, uOleo, 0);
            }}
            else
            {{
                const scalarField alphaPatch =
                    alphaPtr->boundaryField()[p.index()];

                forAll(v, faceI)
                {{
                    if (faceI < alphaPatch.size())
                    {{
                        scalar w = alphaPatch[faceI];
                        v[faceI] = vector(0, w*uOleo + (1.0 - w)*uAr, 0);
                    }}
                    else
                    {{
                        v[faceI] = vector(0, uOleo, 0);
                    }}
                }}
            }}

            operator==(v);
        #}};
    }}

    outlet
    {{
        type            pressureInletOutletVelocity;
        value           uniform (0 0 0);
    }}

    parede_interna
    {{
        type            noSlip;
    }}

    parede_externa
    {{
        type            noSlip;
    }}
}}
"""
    destino.write_text(conteudo)


def gerar_turbulenceProperties(Re: float, destino: Path, Re_crit: float = 2300.0):
    if Re < Re_crit:
        bloco = "simulationType  laminar;\n"
        modelo = "laminar"
    else:
        bloco = """simulationType  RAS;

RAS
{
    RASModel        kOmegaSST;
    turbulence      on;
    printCoeffs     on;
}
"""
        modelo = "RAS (kOmegaSST)"

    conteudo = _header("turbulenceProperties", "dictionary") + f"""
// Re = {Re:.2f} -> modelo: {modelo}
{bloco}
"""
    destino.write_text(conteudo)


def gerar_condicoes(Q_Lmin: float, case_dir: Path | str = ".") -> dict:
    """
    Encontra a raiz estável e grava diretamente:
      system/setFieldsDict
      0.orig/alpha.oil
      0.orig/U
      constant/turbulenceProperties
    """
    case = Path(case_dir).resolve()
    Q_target = Q_Lmin / 60000.0

    raizes = encontrar_raizes_Q(
        Q_target,
        epsilon=EPSILON_CONDICOES,
    )
    if not raizes:
        raise RuntimeError(
            f"Nenhuma raiz encontrada para Q={Q_Lmin:.3f} L/min."
        )

    h_curve = np.linspace(0.001, D_O - 0.001, 3000)
    q_curve = np.array([
        calcular_V_Q(h, epsilon=EPSILON_CONDICOES)[1]
        for h in h_curve
    ])
    dQ = np.gradient(q_curve, h_curve)

    raiz_estavel = None
    for raiz in raizes:
        h = raiz[0]
        idx = np.argmin(np.abs(h_curve - h))
        if dQ[idx] > 0:
            raiz_estavel = raiz
            break

    if raiz_estavel is None:
        raiz_estavel = raizes[0]

    h_L, V, Q, Re, f, reg = raiz_estavel

    (case / "system").mkdir(parents=True, exist_ok=True)
    (case / "0.orig").mkdir(parents=True, exist_ok=True)
    (case / "constant").mkdir(parents=True, exist_ok=True)

    gerar_setFieldsDict(
        h_L, Q_Lmin, V,
        case / "system" / "setFieldsDict"
    )
    gerar_alpha_oil(
        h_L, Q_Lmin,
        case / "0.orig" / "alpha.oil"
    )
    gerar_U(
        h_L, V, Q_Lmin,
        case / "0.orig" / "U"
    )
    gerar_turbulenceProperties(
        Re,
        case / "constant" / "turbulenceProperties"
    )

    return {
        "Q_Lmin": Q_Lmin,
        "Q_m3s": Q,
        "h_L_m": h_L,
        "h_L_mm": h_L * 1000.0,
        "V_mps": V,
        "Re": Re,
        "f": f,
        "regiao": reg,
        "raizes": raizes,
    }


def imprimir_condicoes(info: dict):
    print("=" * 72)
    print(" CONDIÇÕES ANALÍTICAS — CANAL ANULAR")
    print("=" * 72)
    print(f"Q alvo      : {info['Q_Lmin']:.3f} L/min")
    print(f"h_L         : {info['h_L_mm']:.3f} mm")
    print(f"V           : {info['V_mps']:.6f} m/s")
    print(f"Re          : {info['Re']:.3f}")
    print(f"f Churchill : {info['f']:.8f}")
    print(f"Região      : {info['regiao']}")
    print(f"z interface : {-R_O + info['h_L_m']:.6f} m")
    print("-" * 72)
    print("Raízes encontradas:")
    for i, (h, V, Q, Re, f, reg) in enumerate(info["raizes"], 1):
        print(
            f"  {i}: h_L={h*1000:.3f} mm | "
            f"V={V:.5f} m/s | Re={Re:.2f} | região={reg}"
        )
    print("-" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="Modelo analítico e gerador de condições do Canal Anular."
    )
    sub = parser.add_subparsers(dest="comando")

    p_cond = sub.add_parser("condicoes", help="gera condições OpenFOAM")
    p_cond.add_argument("Q", type=float, nargs="?", default=35.0)
    p_cond.add_argument("--case", default=".")

    p_curva = sub.add_parser("curva", help="gera curva analítica CSV")
    p_curva.add_argument("--pontos", type=int, default=1000)
    p_curva.add_argument("--saida", default="curva_analitica.csv")

    args = parser.parse_args()

    if args.comando == "condicoes":
        info = gerar_condicoes(args.Q, args.case)
        imprimir_condicoes(info)
        print("\n[OK] Condições gravadas no caso.")
        return

    if args.comando == "curva":
        h, q, v, re = gerar_curva(args.pontos)
        arr = np.column_stack((h * 1000, q * 60000, v, re))
        np.savetxt(
            args.saida,
            arr,
            delimiter=",",
            header="h_L_mm,Q_Lmin,V_mps,Re",
            comments="",
        )
        print(f"[OK] Curva salva em {args.saida}")
        return

    h, q, v, re = gerar_curva(100)
    print("=" * 60)
    print(" TESTE DO MODELO ANULAR")
    print("=" * 60)
    print(f"Curva: {len(h)} pontos")
    print(f"Q máximo: {q.max()*60000:.3f} L/min")
    print(f"h máximo: {h.max()*1000:.3f} mm")
    print("\nUse:")
    print("  python3 modelo_anular.py condicoes 35")
    print("  python3 modelo_anular.py curva")


if __name__ == "__main__":
    main()
