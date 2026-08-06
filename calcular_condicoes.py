#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
CALCULAR_CONDICOES.py — Calcula condições de contorno para OpenFOAM
a partir do modelo analítico de Ortiz-Vidal & Fiorot (2023)
================================================================================

Uso:
    python3 calcular_condicoes.py [Q_em_L_min]

Exemplo:
    python3 calcular_condicoes.py 12
    → Calcula para Q = 12 L/min e gera arquivos de configuração

Se não informar Q, usa o valor padrão de 12 L/min (região estável, Re ~ 14)
================================================================================
"""

import numpy as np
from scipy.optimize import brentq
import sys
import os

# ================================================================
# PARÂMETROS DO MODELO (ajuste conforme seu caso)
# ================================================================
d_o = 0.115          # [m] diâmetro externo
d_i = 0.075          # [m] diâmetro interno
beta = np.deg2rad(15)  # [rad] inclinação do canal
g = 9.81             # [m/s²] gravidade
rho = 900            # [kg/m³] densidade do óleo
mu = 0.576           # [Pa·s] viscosidade dinâmica do óleo
epsilon = 0.0        # [m] rugosidade absoluta (0 = liso)

# Derivados
r_o = d_o / 2
r_i = d_i / 2
delta = (d_o - d_i) / 2
nu = mu / rho

# ================================================================
# FUNÇÕES (mesmas do calculadora_anular.py)
# ================================================================
def area_circular_segment(d, h):
    if h <= 0: return 0.0
    if h >= d: return np.pi * d**2 / 4
    theta = np.arccos(1 - 2*h/d)
    return (d**2 / 4) * (theta - (1 - 2*h/d) * np.sqrt(1 - (1 - 2*h/d)**2))

def perimetro_molhado_circular(d, h):
    if h <= 0: return 0.0
    if h >= d: return np.pi * d
    theta = np.arccos(1 - 2*h/d)
    return d * theta

def geometria(h_L):
    if h_L <= 0: return 0.0, 1.0, 0.0
    if h_L <= delta:
        A_L = area_circular_segment(d_o, h_L)
        S_L = perimetro_molhado_circular(d_o, h_L)
    elif h_L <= (d_o - delta):
        A_L_total = area_circular_segment(d_o, h_L)
        h_i = h_L - delta
        A_L_interno = area_circular_segment(d_i, h_i)
        A_L = A_L_total - A_L_interno
        S_L_externo = perimetro_molhado_circular(d_o, h_L)
        S_L_interno = perimetro_molhado_circular(d_i, h_i)
        S_L = S_L_externo + S_L_interno
    else:
        A_L_total_anular = np.pi * (d_o**2 - d_i**2) / 4
        A_L_seg_sup = area_circular_segment(d_o, h_L)
        A_L = A_L_total_anular - A_L_seg_sup
        S_L_externo = perimetro_molhado_circular(d_o, h_L)
        S_L = S_L_externo + np.pi * d_i
    D_h = 4 * A_L / S_L if S_L > 0 else 0
    return A_L, S_L, D_h

def churchill(Re, epsilon_Dh):
    if Re <= 0: return 1.0
    A = (-2.457 * np.log((7.0/Re)**0.9 + 0.27*epsilon_Dh))**16
    B = (37530.0 / Re)**16
    f = 8 * ((8.0/Re)**12 + 1.0/(A + B)**1.5)**(1.0/12.0)
    return f

def calcular_V_Q(h_L, tol=1e-12, max_iter=100):
    A_L, S_L, D_h = geometria(h_L)
    if D_h <= 0 or A_L <= 0: return 0.0, 0.0, 0.0, 0.0
    epsilon_Dh = epsilon / D_h
    f = 0.02
    for _ in range(max_iter):
        V = np.sqrt(2 * g * D_h * np.tan(beta) / f)
        Re = rho * V * D_h / mu
        f_new = churchill(Re, epsilon_Dh)
        if abs(f_new - f) < tol:
            f = f_new
            break
        f = f_new
    Re = rho * V * D_h / mu
    Q = A_L * V
    return V, Q, Re, f

def Q_residual(h_L, Q_target):
    _, Q, _, _ = calcular_V_Q(h_L)
    return Q - Q_target

def encontrar_raizes_Q(Q_target_m3s, n_pontos=5000):
    h_vals = np.linspace(0.0005, d_o - 0.0005, n_pontos)
    Q_vals = np.array([calcular_V_Q(h)[1] for h in h_vals])
    residuos = Q_vals - Q_target_m3s
    sinais = np.sign(residuos)
    raizes = []
    for i in range(len(sinais)-1):
        if sinais[i] == 0:
            h_root = h_vals[i]
            V, Q, Re, f = calcular_V_Q(h_root)
            reg = 1 if h_root <= delta else (2 if h_root <= (d_o-delta) else 3)
            raizes.append((h_root, V, Q, Re, f, reg))
        elif sinais[i] * sinais[i+1] < 0:
            try:
                h_root = brentq(Q_residual, h_vals[i], h_vals[i+1], args=(Q_target_m3s,), xtol=1e-12)
                V, Q, Re, f = calcular_V_Q(h_root)
                reg = 1 if h_root <= delta else (2 if h_root <= (d_o-delta) else 3)
                raizes.append((h_root, V, Q, Re, f, reg))
            except ValueError:
                pass
    raizes.sort(key=lambda x: x[0])
    return raizes

# ================================================================
# GERAR ARQUIVOS OpenFOAM
# ================================================================
def gerar_setFieldsDict(h_L_m, arquivo="setFieldsDict"):
    z_max = -r_o + h_L_m
    conteudo = (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| =========                 |                                                 |\n"
        "| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |\n"
        "|  \\\\    /   O peration     | Version:  v2312                                 |\n"
        "|   \\\\  /    A nd           | Website:  www.openfoam.com                      |\n"
        "|    \\\\/     M anipulation  |                                                 |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        "    class       dictionary;\n"
        "    object      setFieldsDict;\n"
        "}\n"
        "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n"
        "\n"
        "// Gerado automaticamente por calcular_condicoes.py\n"
        f"// Q = {Q_alvo*60000:.2f} L/min | h_L = {h_L_m*1000:.3f} mm | V = {V:.4f} m/s\n"
        "\n"
        "defaultFieldValues\n"
        "(\n"
        "    volScalarFieldValue alpha.oil 0\n"
        ");\n"
        "\n"
        "regions\n"
        "(\n"
        "    boxToCell\n"
        "    {\n"
        f"        box (-0.06 -2.501 -0.06) (0.06 2.501 {z_max:.6f});\n"
        "        fieldValues\n"
        "        (\n"
        "            volScalarFieldValue alpha.oil 1\n"
        "        );\n"
        "    }\n"
        ");\n"
        "\n"
        "// ************************************************************************* //\n"
    )
    with open(arquivo, 'w') as f:
        f.write(conteudo)
    print(f"[OK] {arquivo} gerado (zMax = {z_max:.6f} m)")

def gerar_alpha_oil(h_L_m, arquivo="alpha.oil"):
    z_iface = -r_o + h_L_m
    conteudo = (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| =========                 |                                                 |\n"
        "| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |\n"
        "|  \\\\    /   O peration     | Version:  v2312                                 |\n"
        "|   \\\\  /    A nd           | Website:  www.openfoam.com                      |\n"
        "|    \\\\/     M anipulation  |                                                 |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        "    class       volScalarField;\n"
        "    object      alpha.oil;\n"
        "}\n"
        "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n"
        "\n"
        f"// Q = {Q_alvo*60000:.2f} L/min | h_L = {h_L_m*1000:.3f} mm\n"
        "\n"
        "dimensions      [0 0 0 0 0 0 0];\n"
        "\n"
        "internalField   uniform 0;\n"
        "\n"
        "boundaryField\n"
        "{\n"
        "    inlet\n"
        "    {\n"
        "        type            codedFixedValue;\n"
        "        value           uniform 0;\n"
        "        name            alphaOilInletProfile;\n"
        "\n"
        "        code\n"
        "        #{\n"
        f"            const scalar hL_target = {h_L_m:.6f};\n"
        f"            const scalar rOut      = {r_o:.6f};\n"
        f"            const scalar zIface    = {z_iface:.6f};\n"
        "\n"
        "            const fvPatch& p = this->patch();\n"
        "            scalarField alpha(p.size(), 0.0);\n"
        "\n"
        "            forAll(p, faceI)\n"
        "            {\n"
        "                scalar zf = p.Cf()[faceI].z();\n"
        "                alpha[faceI] = (zf < zIface) ? 1.0 : 0.0;\n"
        "            }\n"
        "\n"
        "            operator==(alpha);\n"
        "        #};\n"
        "    }\n"
        "\n"
        "    outlet\n"
        "    {\n"
        "        type            zeroGradient;\n"
        "    }\n"
        "\n"
        "    parede_interna\n"
        "    {\n"
        "        type            zeroGradient;\n"
        "    }\n"
        "\n"
        "    parede_externa\n"
        "    {\n"
        "        type            zeroGradient;\n"
        "    }\n"
        "}\n"
        "\n"
        "// ************************************************************************* //\n"
    )
    with open(arquivo, 'w') as f:
        f.write(conteudo)
    print(f"[OK] {arquivo} gerado (zIface = {z_iface:.6f} m)")

def gerar_turbulenceProperties(Re, arquivo="turbulenceProperties", Re_crit=2300):
    """Escreve turbulenceProperties com base no Re da raiz encontrada.
    Re < Re_crit  -> laminar
    Re >= Re_crit -> RAS (kOmegaSST)
    """
    if Re < Re_crit:
        bloco = "simulationType  laminar;\n"
        modelo = "laminar"
    else:
        bloco = (
            "simulationType  RAS;\n\n"
            "RAS\n"
            "{\n"
            "    RASModel        kOmegaSST;\n"
            "    turbulence      on;\n"
            "    printCoeffs     on;\n"
            "}\n"
        )
        modelo = "RAS (kOmegaSST)"

    conteudo = (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| =========                 |                                                 |\n"
        "| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |\n"
        "|  \\\\    /   O peration     | Version:  v2312                                 |\n"
        "|   \\\\  /    A nd           | Website:  www.openfoam.com                      |\n"
        "|    \\\\/     M anipulation  |                                                 |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        "    class       dictionary;\n"
        "    object      turbulenceProperties;\n"
        "}\n"
        "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\n"
        f"// Re = {Re:.2f}  ->  modelo escolhido automaticamente: {modelo}\n"
        + bloco +
        "\n// ************************************************************************* //\n"
    )

    with open(arquivo, "w") as f:
        f.write(conteudo)
    print(f"[OK] turbulenceProperties gerado ({modelo}, Re={Re:.2f}) -> {arquivo}")
    
def gerar_U(h_L_m, V_m, arquivo="U"):
    conteudo = (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| =========                 |                                                 |\n"
        "| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |\n"
        "|  \\\\    /   O peration     | Version:  v2312                                 |\n"
        "|   \\\\  /    A nd           | Website:  www.openfoam.com                      |\n"
        "|    \\\\/     M anipulation  |                                                 |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        "    class       volVectorField;\n"
        "    object      U;\n"
        "}\n"
        "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n"
        "\n"
        f"// Q = {Q_alvo*60000:.2f} L/min | h_L = {h_L_m*1000:.3f} mm | V = {V_m:.4f} m/s\n"
        "\n"
        "dimensions      [0 1 -1 0 0 0 0];\n"
        "\n"
        "internalField   uniform (0 0 0);\n"
        "\n"
        "boundaryField\n"
        "{\n"
        "    inlet\n"
        "    {\n"
        "        type            codedFixedValue;\n"
        "        value           uniform (0 0 0);\n"
        "        name            velocityProfile;\n"
        "\n"
        "        code\n"
        "        #{\n"
        "            const fvPatch& p = this->patch();\n"
        "            const fvMesh& mesh = p.boundaryMesh().mesh();\n"
        "            vectorField v(p.size(), vector(0,0,0));\n"
        "\n"
        f"            const scalar uOleo = {V_m:.4f};\n"
        "            const scalar uAr   = 0.01;\n"
        "\n"
        "            const volScalarField* alphaPtr =\n"
        "                mesh.findObject<volScalarField>(\"alpha.oil\");\n"
        "\n"
        "            if (!alphaPtr)\n"
        "            {\n"
        "                forAll(v, faceI)\n"
        "                {\n"
        "                    v[faceI] = vector(0, uOleo, 0);\n"
        "                }\n"
        "            }\n"
        "            else\n"
        "            {\n"
        "                const scalarField alphaPatch =\n"
        "                    alphaPtr->boundaryField()[p.index()];\n"
        "\n"
        "                forAll(v, faceI)\n"
        "                {\n"
        "                    if (faceI < alphaPatch.size())\n"
        "                    {\n"
        "                        scalar w = alphaPatch[faceI];\n"
        "                        v[faceI] = vector(0, w*uOleo + (1.0 - w)*uAr, 0);\n"
        "                    }\n"
        "                    else\n"
        "                    {\n"
        "                        v[faceI] = vector(0, uOleo, 0);\n"
        "                    }\n"
        "                }\n"
        "            }\n"
        "\n"
        "            operator==(v);\n"
        "        #};\n"
        "    }\n"
        "\n"
        "    outlet\n"
        "    {\n"
        "        type            zeroGradient;\n"
        "    }\n"
        "\n"
        "    parede_interna\n"
        "    {\n"
        "        type            noSlip;\n"
        "    }\n"
        "\n"
        "    parede_externa\n"
        "    {\n"
        "        type            noSlip;\n"
        "    }\n"
        "}\n"
        "\n"
        "// ************************************************************************* //\n"
    )
    with open(arquivo, 'w') as f:
        f.write(conteudo)
    print(f"[OK] {arquivo} gerado (uOleo = {V_m:.4f} m/s)")

# ================================================================
# MAIN
# ================================================================
if __name__ == "__main__":
    # Ler Q da linha de comando ou usar padrão
    if len(sys.argv) > 1:
        Q_Lmin = float(sys.argv[1])
    else:
        Q_Lmin = 12.0  # Padrão: região estável, Re ~ 14

    Q_alvo = Q_Lmin / 60000.0  # converter para m³/s

    print("="*70)
    print(" CALCULADORA DE CONDIÇÕES — Canal Anular (O&F 2023)")
    print("="*70)
    print(f"\nQ alvo: {Q_Lmin:.2f} L/min = {Q_alvo:.6f} m³/s")

    # Encontrar raízes
    raizes = encontrar_raizes_Q(Q_alvo)

    if not raizes:
        print("\n[ERRO] Nenhuma raiz encontrada para esta vazão!")
        sys.exit(1)

    print(f"\n{'='*70}")
    print("RAÍZES ENCONTRADAS:")
    print(f"{'='*70}")
    print(f"{'#':>3} | {'h_L [mm]':>10} | {'V [m/s]':>10} | {'Re':>10} | {'Região':>8} | {'Estado':>10}")
    print("-"*70)

    # Calcular estabilidade
    h_curve = np.linspace(0.001, d_o - 0.001, 3000)
    Q_curve = np.array([calcular_V_Q(h)[1] for h in h_curve])
    dQ = np.gradient(Q_curve, h_curve)

    for i, (h, V, Q, Re, f, reg) in enumerate(raizes, 1):
        idx = np.argmin(np.abs(h_curve - h))
        slope = dQ[idx] if idx < len(dQ) else 0
        estado = "ESTÁVEL" if slope > 0 else "INSTÁVEL"
        print(f"{i:>3} | {h*1000:>10.3f} | {V:>10.4f} | {Re:>10.1f} | {reg:>8} | {estado:>10}")

    # Escolher raiz estável (primeira com slope > 0)
    raiz_estavel = None
    for h, V, Q, Re, f, reg in raizes:
        idx = np.argmin(np.abs(h_curve - h))
        if dQ[idx] > 0:
            raiz_estavel = (h, V, Q, Re, f, reg)
            break

    if raiz_estavel is None:
        print("\n[AVISO] Nenhuma raiz estável encontrada! Usando primeira raiz.")
        raiz_estavel = raizes[0]

    h_L, V, Q, Re, f, reg = raiz_estavel

    print(f"\n{'='*70}")
    print("RAIZ SELECIONADA (ESTÁVEL):")
    print(f"{'='*70}")
    print(f"  h_L = {h_L*1000:.3f} mm")
    print(f"  V   = {V:.4f} m/s")
    print(f"  Re  = {Re:.1f}")
    print(f"  Região = {reg}")
    print(f"  zMax (setFields) = {-r_o + h_L:.6f} m")

    # Gerar arquivos
    print(f"\n{'='*70}")
    print("GERANDO ARQUIVOS OpenFOAM:")
    print(f"{'='*70}")

    gerar_setFieldsDict(h_L, "setFieldsDict")
    gerar_alpha_oil(h_L, "alpha.oil")
    gerar_U(h_L, V, "U")

    print(f"\n{'='*70}")
    print("INSTRUÇÕES:")
    print(f"{'='*70}")
    print("""
1. Copie os arquivos gerados para o diretório do caso:
   cp setFieldsDict system/
   cp alpha.oil U 0/

2. Certifique-se de que o transportProperties tem 'alpha.oil' (não water)

3. Execute:
   ./master.sh full petsc_cpu

   Ou manualmente:
   blockMesh → setFields → decomposePar → interIsoFoam
""")
