#!/bin/bash
# Benchmark consolidado — preserva a lógica do benchmark original.
set -euo pipefail

CASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$CASE_DIR"

if [[ -z "${WM_PROJECT_DIR:-}" ]]; then
    echo "[ERRO] OpenFOAM não carregado. Execute source <OpenFOAM>/etc/bashrc"
    exit 1
fi
source "$WM_PROJECT_DIR/bin/tools/RunFunctions"

BENCH_TIME="${BENCH_TIME:-0.1}"
WRITE_INTERVAL="${WRITE_INTERVAL:-0.05}"
CHECK_INTERVAL="${CHECK_INTERVAL:-10}"
TIMEOUT_LIMIT="${TIMEOUT_LIMIT:-20m}"

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'
BLU='\033[0;34m'; CYN='\033[0;36m'; NC='\033[0m'
info(){ echo -e "${BLU}[BENCH]${NC} $*"; }
ok(){ echo -e "${GRN}[BENCH]${NC} $*"; }
warn(){ echo -e "${YLW}[BENCH]${NC} $*"; }
err(){ echo -e "${RED}[BENCH]${NC} $*"; }

[[ -d 0.orig ]] || { err "0.orig não encontrado."; exit 1; }

prepare_mesh() {
    rm -rf 0 processor* constant/polyMesh dynamicCode postProcessing log.* 2>/dev/null || true
    cp -r 0.orig 0
    blockMesh > log.blockMesh 2>&1
    checkMesh > log.checkMesh 2>&1
}

run_bench() {
    local np="$1" label="$2" fv_file="$3" petsc="$4"

    info "Caso=$label | cores=$np | config=$fv_file | PETSc=$petsc"

    rm -rf 0 processor* dynamicCode 2>/dev/null || true
    cp -r 0.orig 0

    if [[ -f "system/$fv_file" ]]; then
        cp "system/$fv_file" system/fvSolution
    else
        warn "system/$fv_file não encontrado; usando fvSolution atual."
    fi

    foamDictionary system/controlDict -entry endTime -set "$BENCH_TIME" >/dev/null
    foamDictionary system/controlDict -entry writeInterval -set "$WRITE_INTERVAL" >/dev/null
    foamDictionary system/controlDict -entry startFrom -set startTime >/dev/null
    foamDictionary system/controlDict -entry startTime -set 0 >/dev/null

    if [[ "$petsc" == yes ]]; then
        if ! grep -q "petscFoam" system/controlDict 2>/dev/null; then
            cat >> system/controlDict <<'EOF'

libs
(
    petscFoam
);
EOF
        fi
    else
        sed -i '/petscFoam/d' system/controlDict 2>/dev/null || true
    fi

    setFields > "log.setFields.${label}" 2>&1
    foamDictionary system/decomposeParDict -entry numberOfSubdomains -set "$np" >/dev/null
    decomposePar -force > "log.decomposePar.${label}" 2>&1

    local ts logfile pid
    ts=$(date +%H%M%S)
    logfile="log.interIsoFoam.${label}_${ts}"

    info "Executando interIsoFoam ($logfile)..."
    timeout "$TIMEOUT_LIMIT" mpirun --oversubscribe -np "$np" \
        interIsoFoam -parallel > "$logfile" 2>&1 &
    pid=$!

    while kill -0 "$pid" 2>/dev/null; do
        sleep "$CHECK_INTERVAL"
        local t exec
        t=$(grep '^Time = ' "$logfile" | tail -1 | awk '{print $3}' || true)
        exec=$(grep 'ExecutionTime = ' "$logfile" | tail -1 | awk '{print $3}' || true)
        [[ -n "$t" ]] && echo "  -> t=$t s | CPU=$exec s"
    done

    wait "$pid" || true
    reconstructPar > "log.reconstructPar.${label}" 2>&1 || true
    ok "Benchmark finalizado: $label"
}

prepare_mesh

[[ -f system/fvSolution.gamg.bak ]] && {
    run_bench 4 cpu4_gamg fvSolution.gamg.bak no
    run_bench 8 cpu8_gamg fvSolution.gamg.bak no
    run_bench 14 cpu14_gamg fvSolution.gamg.bak no
}

[[ -f system/fvSolution.petsc_cpu.bak ]] && {
    run_bench 4 cpu4_petsc fvSolution.petsc_cpu.bak yes
    run_bench 8 cpu8_petsc fvSolution.petsc_cpu.bak yes
    run_bench 14 cpu14_petsc fvSolution.petsc_cpu.bak yes
}

if [[ -f system/fvSolution.amgx.bak ]]; then
    export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
    run_bench 1 gpu1 fvSolution.amgx.bak yes
    run_bench 2 gpu2 fvSolution.amgx.bak yes
    run_bench 4 gpu4 fvSolution.amgx.bak yes
fi

ok "BENCHMARK FINALIZADO."
