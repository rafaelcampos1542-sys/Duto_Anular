#!/bin/bash
#===============================================================================
# MASTER.SH — Orquestrador do workflow completo Canal Anular
# Uso: ./master.sh [comando] [opções]
#===============================================================================
set -e

cd "${0%/*}" || exit 1

# Cores
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
CYN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${BLU}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YLW}[WARN]${NC} $1"; }
log_ok()    { echo -e "${GRN}[OK]${NC} $1"; }
log_error() { echo -e "${RED}[ERRO]${NC} $1"; }
log_cmd()   { echo -e "${CYN}[CMD]${NC} $1"; }

# ── AJUDA ──────────────────────────────────────────────────────────────────
show_help() {
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════════╗
║           WORKFLOW CANAL ANULAR — OpenFOAM v2312                     ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  USO: ./master.sh <comando> [opções]                                 ║
║                                                                      ║
║  COMANDOS:                                                           ║
║    clean              Limpa caso (com backup automático)               ║
║    mesh               Gera malha e verifica qualidade                  ║
║    init               Aplica setFields e inicializa                  ║
║    run [solver] [t]   Roda simulação completa                        ║
║                         solver: gamg | petsc_cpu (padrão) | petsc_gpu  ║
║                         t: tempo físico alvo (padrão: usa controlDict) ║
║    run5 [solver]      Roda até 5 segundos físicos (atalho)            ║
║    post               Executa pós-processamento Python                ║
║    compare            Compara com curva analítica                    ║
║    full [solver]      Workflow completo: clean → mesh → init → run    ║
║    status             Mostra status do caso atual                      ║
║    help               Mostra esta ajuda                              ║
║                                                                      ║
║  EXEMPLOS:                                                           ║
║    ./master.sh clean                                                 ║
║    ./master.sh run petsc_cpu 10       # 10 segundos com PETSc CPU    ║
║    ./master.sh run5                    # Rápido teste de 5 segundos      ║
║    ./master.sh full petsc_cpu         # Workflow completo              ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
EOF
}

# ── STATUS ─────────────────────────────────────────────────────────────────
show_status() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║  STATUS DO CASO                                                      ║"
    echo "╠══════════════════════════════════════════════════════════════════════╣"

    # Diretórios
    echo -n "║  Malha:           "
    if [ -d "constant/polyMesh" ]; then echo -e "${GRN}OK${NC}"; else echo -e "${RED}AUSENTE${NC}"; fi

    echo -n "║  Condições iniciais: "
    if [ -d "0" ]; then echo -e "${GRN}OK${NC}"; else echo -e "${RED}AUSENTE${NC}"; fi

    echo -n "║  0.orig backup:      "
    if [ -d "0.orig" ]; then echo -e "${GRN}OK${NC}"; else echo -e "${YLW}AUSENTE${NC}"; fi

    # Tempos
    local tempos=$(ls -1d [0-9]* 2>/dev/null | grep -v '^0$' | wc -l)
    echo -e "║  Tempos escritos:   ${BLU}$tempos${NC}"

    # Último tempo
    local ultimo=$(ls -1d [0-9]* 2>/dev/null | grep -v '^0$' | sort -V | tail -n 1 || echo "N/A")
    echo -e "║  Último tempo:      ${BLU}$ultimo${NC}"

    # Paralelo
    echo -n "║  Decomposto:        "
    if [ -d "processor0" ]; then echo -e "${GRN}SIM${NC}"; else echo -e "${YLW}NÃO${NC}"; fi

    # Logs
    echo -n "║  Log interIsoFoam:  "
    if [ -f "log.interIsoFoam" ]; then 
        local last_line=$(tail -n 1 log.interIsoFoam 2>/dev/null | cut -c1-50)
        echo -e "${GRN}EXISTE${NC} (última: $last_line...)"
    else 
        echo -e "${RED}AUSENTE${NC}"
    fi

    # Resultados pós-processamento
    echo -n "║  CSV resultados:    "
    if [ -f "resultados_hL.csv" ]; then echo -e "${GRN}OK${NC}"; else echo -e "${YLW}AUSENTE${NC}"; fi

    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
}

# ── COMANDOS ─────────────────────────────────────────────────────────────────
cmd_clean() {
    log_cmd "Executando allclean..."
    ./allclean
}

cmd_mesh() {
    log_cmd "Gerando malha..."
    . ${WM_PROJECT_DIR:?}/bin/tools/RunFunctions
    runApplication blockMesh
    runApplication checkMesh
    log_ok "Malha gerada e verificada"
}

cmd_init() {
    log_cmd "Inicializando campos..."
    if [ ! -d "0" ] && [ -d "0.orig" ]; then
        cp -r 0.orig 0
    fi
    setFields > log.setFields 2>&1
    log_ok "setFields aplicado"
}

cmd_run() {
    local solver="${1:-petsc_cpu}"
    local target_time="${2:-}"

    if [ -n "$target_time" ]; then
        log_cmd "Rodando com $solver até t = ${target_time}s..."
        ./run_until.sh "$target_time" 30 "$solver"
    else
        log_cmd "Rodando simulação completa com $solver..."
        SOLVER="$solver" ./allrun
    fi
}

cmd_run5() {
    local solver="${1:-petsc_cpu}"
    log_cmd "Roda rápida: 5 segundos físicos com $solver"
    ./run_until.sh 5.0 30 "$solver"
}

cmd_post() {
    log_cmd "Pós-processamento..."
    if [ -f "analisar_resultados.py" ]; then
        python3 analisar_resultados.py
    else
        log_warn "analisar_resultados.py não encontrado"
    fi

    if [ -f "system/sample" ] || [ -f "system/sampleDict" ]; then
        sample > log.sample 2>&1 || true
    fi
}

cmd_compare() {
    log_cmd "Comparando com analítico..."
    ./compare_analytic.sh
}

cmd_full() {
    local solver="${1:-petsc_cpu}"
    log_cmd "Workflow completo com solver=$solver"
    cmd_clean
    cmd_mesh
    cmd_init
    cmd_run "$solver"
    cmd_post
    cmd_compare
    log_ok "Workflow completo finalizado!"
}

# ── MAIN ───────────────────────────────────────────────────────────────────
COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    clean)       cmd_clean ;;
    mesh)        cmd_mesh ;;
    init)        cmd_init ;;
    run)         cmd_run "$@" ;;
    run5)        cmd_run5 "$@" ;;
    post)        cmd_post ;;
    compare)     cmd_compare ;;
    full)        cmd_full "$@" ;;
    status)      show_status ;;
    help|--help|-h) show_help ;;
    *)
        log_error "Comando desconhecido: $COMMAND"
        show_help
        exit 1
        ;;
esac
