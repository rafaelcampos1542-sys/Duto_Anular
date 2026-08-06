#!/bin/bash
#===============================================================================
# RUN_UNTIL — Executa simulação até um tempo físico alvo e para automaticamente
# Útil para: "rode 5 segundos e veja o que acontece"
#===============================================================================
set -e

cd "${0%/*}" || exit 1

# ── PARÂMETROS ─────────────────────────────────────────────────────────────
TARGET_TIME="${1:-5.0}"       # Tempo físico alvo (padrão: 5.0 s)
CHECK_INTERVAL="${2:-30}"     # Verificar a cada N segundos reais
SOLVER="${3:-petsc_cpu}"      # Solver a usar
NPROCS="${4:-8}"              # Número de cores

# Cores
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLU}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YLW}[WARN]${NC} $1"; }
log_ok()    { echo -e "${GRN}[OK]${NC} $1"; }
log_error() { echo -e "${RED}[ERRO]${NC} $1"; }

# ── VALIDAÇÃO ───────────────────────────────────────────────────────────────
if [ ! -f "system/controlDict" ]; then
    log_error "system/controlDict não encontrado!"
    exit 1
fi

# Ler endTime atual do controlDict
ORIG_END_TIME=$(foamDictionary system/controlDict -entry endTime -value 2>/dev/null || echo "30")
log_info "endTime original do controlDict: $ORIG_END_TIME s"
log_info "Objetivo: rodar até t = $TARGET_TIME s físicos"

# Ajustar endTime para o alvo
foamDictionary system/controlDict -entry endTime -set "$TARGET_TIME"
foamDictionary system/controlDict -entry writeInterval -set "0.5"

# ── PREPARAR CASO ──────────────────────────────────────────────────────────
log_info "Preparando caso..."

# Se não tiver malha, gerar
if [ ! -d "constant/polyMesh" ]; then
    log_info "Malha não encontrada. Gerando..."
    blockMesh > log.blockMesh 2>&1
    checkMesh > log.checkMesh 2>&1
fi

# Se não tiver 0, restaurar de 0.orig
if [ ! -d "0" ] && [ -d "0.orig" ]; then
    cp -r 0.orig 0
fi

# Se ainda não tiver 0, erro
if [ ! -d "0" ]; then
    log_error "Diretório 0/ não encontrado e 0.orig não existe!"
    exit 1
fi

# Aplicar setFields se necessário
if [ -f "system/setFieldsDict" ]; then
    log_info "Aplicando setFields..."
    setFields > log.setFields 2>&1
fi

# ── CONFIGURAR SOLVER ──────────────────────────────────────────────────────
log_info "Configurando solver: $SOLVER"

# Configurar decomposeParDict
foamDictionary system/decomposeParDict -entry numberOfSubdomains -set "$NPROCS" 2>/dev/null || true

# Ajustar libs conforme solver
if [ "$SOLVER" = "petsc_cpu" ] || [ "$SOLVER" = "petsc_gpu" ]; then
    if ! grep -q "petscFoam" system/controlDict 2>/dev/null; then
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
fi

# ── DECOMPOR E RODAR ─────────────────────────────────────────────────────
if [ ! -d "processor0" ]; then
    log_info "Decompondo domínio..."
    decomposePar -force > log.decomposePar 2>&1
fi

log_info "Iniciando simulação até t = $TARGET_TIME s..."
log_info "Para acompanhar: tail -f log.interIsoFoam"
log_info "Para interromper: touch STOP_IT"

# Criar flag de parada (remover se existir)
rm -f STOP_IT

# Rodar em background
mpirun --oversubscribe -np "$NPROCS" interIsoFoam -parallel > log.interIsoFoam 2>&1 &
PID=$!

log_info "PID da simulação: $PID"

# Monitorar progresso
while kill -0 $PID 2>/dev/null; do
    sleep "$CHECK_INTERVAL"

    # Verificar se usuário pediu parada
    if [ -f "STOP_IT" ]; then
        log_warn "Flag STOP_IT detectada. Interrompendo simulação..."
        kill -TERM $PID 2>/dev/null || true
        sleep 2
        kill -KILL $PID 2>/dev/null || true
        rm -f STOP_IT
        break
    fi

    # Verificar tempo atual
    if [ -f "log.interIsoFoam" ]; then
        CURRENT_TIME=$(grep "^Time = " log.interIsoFoam | tail -n 1 | awk '{print $3}' || echo "0")
        if [ -n "$CURRENT_TIME" ]; then
            log_info "Progresso: t = ${CURRENT_TIME}s / ${TARGET_TIME}s"
        fi
    fi
done

wait $PID 2>/dev/null || true

# ── RECONSTRUIR ────────────────────────────────────────────────────────────
log_info "Reconstruindo resultados..."
reconstructPar > log.reconstructPar 2>&1 || log_warn "reconstructPar falhou (pode ser normal se não houver tempos para reconstruir)"

touch case.foam

# ── PÓS-PROCESSAMENTO ─────────────────────────────────────────────────────
log_info "Executando pós-processamento..."

# Rodar sample se houver sampleDict
if [ -f "system/sample" ] || [ -f "system/sampleDict" ]; then
    log_info "Executando sample..."
    sample > log.sample 2>&1 || log_warn "sample falhou"
fi

# Rodar script Python se existir
if [ -f "analisar_resultados.py" ]; then
    log_info "Rodando analisar_resultados.py..."
    python3 analisar_resultados.py || log_warn "analisar_resultados.py falhou"
fi

# ── RESTAURAR endTime ORIGINAL ────────────────────────────────────────────
foamDictionary system/controlDict -entry endTime -set "$ORIG_END_TIME"
log_info "endTime restaurado para $ORIG_END_TIME s"

echo ""
echo "======================================================================"
echo "  SIMULAÇÃO FINALIZADA"
echo "  Tempo alvo: $TARGET_TIME s"
echo "  Último tempo escrito: $(ls -1d [0-9]* 2>/dev/null | grep -v '^0$' | sort -V | tail -n 1 || echo 'N/A')"
echo "  Para visualizar: paraview case.foam"
echo "======================================================================"
