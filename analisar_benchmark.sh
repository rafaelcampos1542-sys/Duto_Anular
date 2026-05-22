#!/bin/bash

echo "===================================="
echo "📊 RESULTADOS DO BENCHMARK"
echo "===================================="

printf "%-10s | %-12s | %-12s\n" "Caso" "Time final" "ExecTime (s)"
echo "----------------------------------------------"

RESULTS=()

for f in log.interFoam.*; do
    [ -f "$f" ] || continue

    LABEL=$(echo "$f" | sed 's/log.interFoam.//')

    # Último Time físico
    LAST_TIME=$(grep "Time =" "$f" | tail -1 | awk '{print $3}')

    # Último ExecutionTime
    EXEC_TIME=$(grep "ExecutionTime" "$f" | tail -1 | awk '{print $3}')

    printf "%-10s | %-12s | %-12s\n" "$LABEL" "$LAST_TIME" "$EXEC_TIME"

    # Guarda para ordenar depois
    RESULTS+=("$EXEC_TIME $LABEL $LAST_TIME")
done

echo ""
echo "🏆 RANKING (mais rápido primeiro)"
echo "----------------------------------------------"

printf "%-10s | %-12s | %-12s\n" "Caso" "Time final" "ExecTime (s)"
echo "----------------------------------------------"

printf "%s\n" "${RESULTS[@]}" | sort -n | while read EXEC LABEL LAST; do
    printf "%-10s | %-12s | %-12s\n" "$LABEL" "$LAST" "$EXEC"
done

echo ""
echo "✅ Vencedor:"
BEST=$(printf "%s\n" "${RESULTS[@]}" | sort -n | head -1)
BEST_LABEL=$(echo $BEST | awk '{print $2}')
echo "👉 $BEST_LABEL"