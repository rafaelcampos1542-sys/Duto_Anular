#!/bin/bash
#===============================================================================
# ANALISAR_BENCHMARK.SH — Análise justa dos resultados do benchmark
# Compara todos os casos que atingiram o MESMO tempo físico
#===============================================================================

cd "$(dirname "$0")" || exit 1

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
CYN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${BLU}[ANALISE]${NC} $1"; }
log_warn()  { echo -e "${YLW}[ANALISE]${NC} $1"; }
log_ok()    { echo -e "${GRN}[ANALISE]${NC} $1"; }
log_error() { echo -e "${RED}[ANALISE]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║         ANÁLISE DOS RESULTADOS DO BENCHMARK                          ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"

# ── COLETAR DADOS ──────────────────────────────────────────────────────────
declare -a RESULTS
declare -a VALID_RESULTS

for f in log.interIsoFoam.*; do
    [ -f "$f" ] || continue

    LABEL=$(echo "$f" | sed 's/log.interIsoFoam.//')

    # Último Time físico alcançado
    LAST_TIME=$(grep -E '^Time = ' "$f" | tail -1 | awk '{print $3}')
    # Último ExecutionTime (wall-clock)
    EXEC_TIME=$(grep -E '^ExecutionTime = ' "$f" | tail -1 | awk '{print $3}')
    # Último ClockTime
    CLOCK_TIME=$(grep -E '^ClockTime = ' "$f" | tail -1 | awk '{print $3}')
    # DeltaT médio
    DELTA_T=$(grep -E '^deltaT = ' "$f" | tail -1 | awk '{print $3}')
    # Courant máximo
    CO_MAX=$(grep -E '^Courant Number mean: ' "$f" | tail -1 | awk '{print $6}')

    if [ -z "$LAST_TIME" ] || [ -z "$EXEC_TIME" ]; then
        printf "%-20s | %-12s | %-12s | %-16s\n" "$LABEL" "INCOMPLETO" "-" "-"
        continue
    fi

    # Calcular custo por segundo físico (métrica principal)
    COST=$(awk -v exec="$EXEC_TIME" -v phys="$LAST_TIME" 'BEGIN { if (phys > 0) printf "%.2f", exec/phys; else print "INF" }')

    # Throughput: segundos físicos por hora de CPU
    THROUGHPUT=$(awk -v exec="$EXEC_TIME" -v phys="$LAST_TIME" 'BEGIN { if (exec > 0) printf "%.4f", phys/exec*3600; else print "0" }')

    # Verificar se completou o tempo alvo
    TARGET=$(grep -E "Simulação até t = " log.interIsoFoam.* 2>/dev/null | head -1 | grep -oP '\d+\.?\d*' | tail -1 || echo "0")
    if [ -z "$TARGET" ]; then TARGET="0.1"; fi

    COMPLETADO=$(awk -v t="$LAST_TIME" -v tgt="$TARGET" 'BEGIN { if (t+0.001 >= tgt) print "SIM"; else print "NAO" }')

    RESULTS+=("$COST $THROUGHPUT $LABEL $LAST_TIME $EXEC_TIME $CLOCK_TIME $DELTA_T $CO_MAX $COMPLETADO")
done

# ── TABELA COMPLETA ──────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════════"
printf "%-18s | %-10s | %-12s | %-10s | %-10s | %-8s | %-10s | %-8s\n" \
    "Caso" "Time [s]" "ExecTime [s]" "Custo [s/s]" "Thrpt [s/h]" "dT [s]" "Co_max" "Completo"
echo "─────────────────────────────────────────────────────────────────────────"

for r in "${RESULTS[@]}"; do
    read COST THROUGHPUT LABEL LAST_TIME EXEC_TIME CLOCK_TIME DELTA_T CO_MAX COMPLETADO <<< "$r"

    if [ "$COMPLETADO" = "SIM" ]; then
        COLOR="$GRN"
    else
        COLOR="$YLW"
    fi

    printf "${COLOR}%-18s${NC} | %-10s | %-12s | %-10s | %-10s | %-8s | %-10s | %-8s\n" \
        "$LABEL" "$LAST_TIME" "$EXEC_TIME" "$COST" "$THROUGHPUT" "$DELTA_T" "$CO_MAX" "$COMPLETADO"
done

# ── RANKING (apenas casos completos) ───────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "  🏆 RANKING — Casos que completaram o tempo físico alvo"
echo "═══════════════════════════════════════════════════════════════════════"
printf "%-18s | %-12s | %-12s | %-16s\n" "Caso" "Time [s]" "ExecTime [s]" "Custo [s_CPU/s_fisico]"
echo "─────────────────────────────────────────────────────────────────────────"

for r in "${RESULTS[@]}"; do
    read COST THROUGHPUT LABEL LAST_TIME EXEC_TIME CLOCK_TIME DELTA_T CO_MAX COMPLETADO <<< "$r"
    if [ "$COMPLETADO" = "SIM" ]; then
        VALID_RESULTS+=("$COST $LABEL $LAST_TIME $EXEC_TIME")
    fi
done

if [ ${#VALID_RESULTS[@]} -eq 0 ]; then
    log_warn "Nenhum caso completou o tempo físico alvo!"
    log_info "Verifique se o benchmark rodou até o endTime definido."
else
    # Ordenar por custo (menor = melhor)
    IFS=$'\n' SORTED=($(sort -n <<<"${VALID_RESULTS[*]}")); unset IFS

    for r in "${SORTED[@]}"; do
        read COST LABEL LAST_TIME EXEC_TIME <<< "$r"
        printf "%-18s | %-12s | %-12s | %-16s\n" "$LABEL" "$LAST_TIME" "$EXEC_TIME" "$COST"
    done

    echo ""
    BEST=$(echo "${SORTED[0]}" | awk '{print $2}')
    BEST_COST=$(echo "${SORTED[0]}" | awk '{print $1}')
    log_ok "Vencedor: $BEST (custo = ${BEST_COST} s_CPU/s_fisico)"
    log_info "Quanto MENOR o custo, mais eficiente (menos CPU por segundo simulado)"
fi

# ── ESTATÍSTICAS POR SOLVER ──────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "  📊 COMPARAÇÃO POR FAMÍLIA DE SOLVER"
echo "═══════════════════════════════════════════════════════════════════════"

for FAMILIA in "gamg" "petsc" "gpu"; do
    SUM_COST=0
    COUNT=0
    for r in "${RESULTS[@]}"; do
        read COST THROUGHPUT LABEL LAST_TIME EXEC_TIME CLOCK_TIME DELTA_T CO_MAX COMPLETADO <<< "$r"
        if echo "$LABEL" | grep -q "$FAMILIA" && [ "$COMPLETADO" = "SIM" ]; then
            SUM_COST=$(awk -v s="$SUM_COST" -v c="$COST" 'BEGIN {print s+c}')
            COUNT=$((COUNT+1))
        fi
    done
    if [ $COUNT -gt 0 ]; then
        AVG=$(awk -v s="$SUM_COST" -v c="$COUNT" 'BEGIN {printf "%.2f", s/c}')
        printf "  %-10s: média de custo = %s s_CPU/s_fisico (%d casos)\n" "$FAMILIA" "$AVG" "$COUNT"
    fi
done

echo ""
