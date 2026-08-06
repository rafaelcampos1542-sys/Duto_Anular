#!/bin/bash
#===============================================================================
# BENCHMARK DE SOLVERS — Canal Anular (OpenFOAM v2312)
# Compara GAMG, PETSc CPU e PETSc GPU de forma justa
#===============================================================================
set -e

cd "$(dirname "$0")" || exit 1
. $WM_PROJECT_DIR/bin/tools/RunFunctions

# ── CONFIGURAÇÕES ──────────────────────────────────────────────────────────
BENCH_TIME="0.1"          # Tempo físico FIXO para todos os casos [s]
WRITE_INTERVAL="0.05"     # Escrever a cada 0.05s (2 escritas no total)
CHECK_INTERVAL="10"       # Verificar progresso a cada N segundos

# Cores
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
CYN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${BLU}[BENCH]${NC} $1"; }
log_warn()  { echo -e "${YLW}[BENCH]${NC} $1"; }
log_ok()    { echo -e "${GRN}[BENCH]${NC} $1"; }
log_error() { echo -e "${RED}[BENCH]${NC} $1"; }

# ── FUNÇÃO: RODAR UM CASO DE BENCHMARK ────────────────────────────────────
runBench () {
    NP=$1
    LABEL=$2
    FV_FILE=$3
    USE_PETSC=$4

    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║  BENCHMARK: $LABEL"
    echo "║  Cores: $NP | FV: $FV_FILE | PETSc: $USE_PETSC"
    echo "╚══════════════════════════════════════════════════════════════════════╝"

    # 1. LIMPEZA COMPLETA (exceto malha)
    rm -rf 0 processor* dynamicCode log.interIsoFoam* log.setFields* log.decomposePar*

    # 2. RESTAURAR CONDIÇÕES INICIAIS
    if [ ! -d "0.orig" ]; then
        log_error "0.orig não encontrado! Execute: cp -r 0 0.orig"
        return 1
    fi
    cp -r 0.orig 0

    # 3. CONFIGURAR SOLVER
    if [ -f "system/$FV_FILE" ]; then
        cp system/$FV_FILE system/fvSolution
        log_info "fvSolution: $FV_FILE"
    else
        log_warn "system/$FV_FILE não encontrado. Usando fvSolution atual."
    fi

    # 4. CONFIGURAR controlDict (TEMPO FIXO!)
    foamDictionary system/controlDict -entry endTime -set "$BENCH_TIME" > /dev/null 2>&1
    foamDictionary system/controlDict -entry writeInterval -set "$WRITE_INTERVAL" > /dev/null 2>&1
    foamDictionary system/controlDict -entry startFrom -set "startTime" > /dev/null 2>&1
    foamDictionary system/controlDict -entry startTime -set "0" > /dev/null 2>&1
    log_info "Simulação até t = ${BENCH_TIME}s físicos (fixo para todos)"

    # 5. CONFIGURAR libs (PETSc)
    if [ "$USE_PETSC" = "yes" ]; then
        if ! grep -q "petscFoam" system/controlDict 2>/dev/null; then
            # Adicionar libs se não existir
            if grep -q "^libs" system/controlDict; then
                sed -i '/libs/,/);/{/);/i\\    petscFoam
}' system/controlDict
            else
                sed -i '/^\/\//a\
libs\
(\
    petscFoam\
);' system/controlDict
            fi
        fi
        log_info "Lib petscFoam ativada"
    else
        # Remover petscFoam se existir
        sed -i '/petscFoam/d' system/controlDict 2>/dev/null || true
        log_info "Lib petscFoam removida (modo nativo)"
    fi

    # 6. APLICAR setFields
    log_info "Aplicando setFields..."
    setFields > log.setFields.${LABEL} 2>&1

    # 7. PRÉ-COMPILAR coded BC (warm-up igual para todos)
    log_info "Warm-up: pré-compilando coded BC..."
    interIsoFoam -postProcess > /dev/null 2>&1 || true

    # 8. DECOMPOR
    foamDictionary system/decomposeParDict -entry numberOfSubdomains -set $NP > /dev/null 2>&1
    log_info "Decompondo em $NP partições..."
    decomposePar -force > log.decomposePar.${LABEL} 2>&1

    if [ ! -d "processor0" ]; then
        log_error "decomposePar falhou!"
        return 1
    fi

    # 9. EXECUTAR COM MONITORAMENTO
    TS=$(date +%H%M%S)
    LOGFILE="log.interIsoFoam.${LABEL}_${TS}"

    log_info "Executando interIsoFoam (log: $LOGFILE)..."

    # Rodar em background para poder monitorar
    mpirun --oversubscribe -np $NP --use-hwthread-cpus interIsoFoam -parallel > $LOGFILE 2>&1 &
    PID=$!

    # Monitorar até terminar
    while kill -0 $PID 2>/dev/null; do
        sleep $CHECK_INTERVAL
        if [ -f "$LOGFILE" ]; then
            LAST_TIME=$(grep "^Time = " $LOGFILE | tail -1 | awk '{print $3}' 2>/dev/null || echo "0")
            EXEC_TIME=$(grep "^ExecutionTime = " $LOGFILE | tail -1 | awk '{print $3}' 2>/dev/null || echo "0")
            if [ -n "$LAST_TIME" ] && [ -n "$EXEC_TIME" ]; then
                echo -e "  ${CYN}→${NC} t = ${LAST_TIME}s | ExecTime = ${EXEC_TIME}s"
            fi
        fi
    done

    wait $PID 2>/dev/null || true

    # Verificar se completou
    if grep -q "Finalising parallel run" $LOGFILE 2>/dev/null || grep -q "End" $LOGFILE 2>/dev/null; then
        log_ok "Simulação $LABEL completada!"
    else
        log_warn "Simulação $LABEL pode ter sido interrompida"
    fi

    # 10. RECONSTRUIR (opcional para benchmark, mas bom para verificação)
    reconstructPar > log.reconstructPar.${LABEL} 2>&1 || true

    return 0
}

# ==============================================================================
# PREPARAÇÃO INICIAL
# ==============================================================================
echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║         BENCHMARK DE SOLVERS — Canal Anular                          ║"
echo "║         Tempo físico alvo: ${BENCH_TIME}s (fixo para todos)           ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"

# Verificar pré-requisitos
if [ ! -d "constant/polyMesh" ]; then
    log_info "Malha não encontrada. Gerando..."
    rm -rf 0 processor* log.* dynamicCode 2>/dev/null
    cp -r 0.orig 0 2>/dev/null || true
    blockMesh > log.blockMesh 2>&1
    checkMesh > log.checkMesh 2>&1

    # Criar 0.orig se não existir
    if [ ! -d "0.orig" ] && [ -d "0" ]; then
        cp -r 0 0.orig
        log_ok "0.orig criado a partir de 0/"
    fi
fi

# Salvar controlDict original para restaurar depois
if [ -f "system/controlDict" ]; then
    cp system/controlDict system/controlDict.benchmark_backup
fi

# ==============================================================================
# BENCHMARK 1: GAMG (CPU Nativo)
# ==============================================================================
if [ -f "system/fvSolution.gamg.bak" ]; then
    runBench 4  "cpu4_gamg"   "fvSolution.gamg.bak"   "no"
    runBench 8  "cpu8_gamg"   "fvSolution.gamg.bak"   "no"
    runBench 14 "cpu14_gamg"  "fvSolution.gamg.bak"   "no"
fi

# ==============================================================================
# BENCHMARK 2: PETSc CPU
# ==============================================================================
if [ -f "system/fvSolution.petsc_cpu.bak" ]; then
    runBench 4  "cpu4_petsc"  "fvSolution.petsc_cpu.bak"  "yes"
    runBench 8  "cpu8_petsc"  "fvSolution.petsc_cpu.bak"  "yes"
    runBench 14 "cpu14_petsc" "fvSolution.petsc_cpu.bak"  "yes"
fi

# ==============================================================================
# BENCHMARK 3: PETSc GPU (AmgX)
# ==============================================================================
if [ -f "system/fvSolution.amgx.bak" ]; then
    export CUDA_VISIBLE_DEVICES=0
    runBench 1  "gpu1"        "fvSolution.amgx.bak"   "yes"
    runBench 2  "gpu2"        "fvSolution.amgx.bak"   "yes"
    runBench 4  "gpu4"        "fvSolution.amgx.bak"   "yes"
fi

# ==============================================================================
# RESTAURAR controlDict
# ==============================================================================
if [ -f "system/controlDict.benchmark_backup" ]; then
    mv system/controlDict.benchmark_backup system/controlDict
    log_info "controlDict original restaurado"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║         BENCHMARK FINALIZADO                                         ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
