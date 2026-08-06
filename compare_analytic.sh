#!/bin/bash
#===============================================================================
# COMPARE_ANALYTIC — Compara resultados CFD com curva analítica Q × h_L
# Requer: calculadora_anular.py e resultados_hL.csv do pós-processamento
#===============================================================================
set -e

cd "${0%/*}" || exit 1

# Cores
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLU}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YLW}[WARN]${NC} $1"; }
log_ok()    { echo -e "${GRN}[OK]${NC} $1"; }

# ── VERIFICAR DEPENDÊNCIAS ───────────────────────────────────────────────
if [ ! -f "calculadora_anular.py" ]; then
    log_warn "calculadora_anular.py não encontrado. Baixe do repositório."
fi

if [ ! -f "resultados_hL.csv" ]; then
    log_warn "resultados_hL.csv não encontrado."
    log_info "Execute primeiro: python3 analisar_resultados.py"
    exit 1
fi

# ── GERAR CURVA ANALÍTICA ──────────────────────────────────────────────────
log_info "Gerando curva analítica..."
python3 - << 'PYEOF'
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import sys
sys.path.insert(0, '.')

# Importar funções do calculadora_anular
try:
    from calculadora_anular import gerar_curva, encontrar_raizes_Q
    HAS_ANALYTIC = True
except ImportError:
    HAS_ANALYTIC = False
    print("[WARN] calculadora_anular.py não importável. Usando apenas dados numéricos.")

# Ler resultados numéricos
try:
    df = pd.read_csv('resultados_hL.csv')
    print(f"[OK] Dados numéricos: {len(df)} pontos temporais")
except Exception as e:
    print(f"[ERRO] Falha ao ler resultados_hL.csv: {e}")
    sys.exit(1)

# Plot comparativo
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Plot 1: h_L(t) numérico
ax1 = axes[0]
ax1.plot(df['tempo_s'], df['h_L_meio_mm'], 'b-o', markersize=4, label='CFD (meio)')
if 'h_L_saida_mm' in df.columns and not df['h_L_saida_mm'].isna().all():
    ax1.plot(df['tempo_s'], df['h_L_saida_mm'], 'r-s', markersize=4, label='CFD (saída)')
ax1.set_xlabel('Tempo [s]', fontsize=12)
ax1.set_ylabel('h_L [mm]', fontsize=12)
ax1.set_title('Evolução Temporal da Interface', fontsize=12)
ax1.legend()
ax1.grid(True, alpha=0.3)

# Plot 2: Q × h_L comparativo
ax2 = axes[1]

# Curva analítica
if HAS_ANALYTIC:
    h_a, Q_a, V_a, Re_a = gerar_curva(n_pontos=1000)
    ax2.plot(Q_a*60000, h_a*1000, 'k-', linewidth=2, label='Analítico (O&F 2023)')

# Dados numéricos
if 'Q_meio_Lmin' in df.columns and not df['Q_meio_Lmin'].isna().all():
    ax2.scatter(df['Q_meio_Lmin'], df['h_L_meio_mm'], c=df['tempo_s'], 
                cmap='viridis', s=50, marker='o', edgecolors='black', 
                label='CFD (meio)', zorder=5)

if 'Q_saida_Lmin' in df.columns and not df['Q_saida_Lmin'].isna().all():
    ax2.scatter(df['Q_saida_Lmin'], df['h_L_saida_mm'], c=df['tempo_s'], 
                cmap='plasma', s=50, marker='s', edgecolors='black', 
                label='CFD (saída)', zorder=5)

ax2.set_xlabel('Q [L/min]', fontsize=12)
ax2.set_ylabel('h_L [mm]', fontsize=12)
ax2.set_title('Comparação: Analítico vs CFD', fontsize=12)
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('comparacao_analitico_cfd.png', dpi=300, bbox_inches='tight')
print("[OK] Gráfico salvo: comparacao_analitico_cfd.png")
plt.show()

# Estatísticas
print("\n" + "="*60)
print("RESUMO COMPARATIVO")
print("="*60)
print(f"h_L inicial (CFD):  {df['h_L_meio_mm'].iloc[0]:.2f} mm")
print(f"h_L final (CFD):    {df['h_L_meio_mm'].iloc[-1]:.2f} mm")
print(f"Variação:           {df['h_L_meio_mm'].iloc[-1] - df['h_L_meio_mm'].iloc[0]:.2f} mm")

if HAS_ANALYTIC and 'Q_meio_Lmin' in df.columns:
    Q_medio = df['Q_meio_Lmin'].mean()
    print(f"\nQ médio numérico:   {Q_medio:.2f} L/min")
    raizes = encontrar_raizes_Q(Q_medio/60000, verbose=False)
    if raizes:
        print(f"Raízes analíticas para Q={Q_medio:.2f} L/min:")
        for i, (h, V, Re, f, reg) in enumerate(raizes, 1):
            print(f"  Raiz {i}: h_L = {h*1000:.2f} mm")
PYEOF

log_ok "Comparação finalizada!"
