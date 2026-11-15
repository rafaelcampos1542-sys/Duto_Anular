#!/bin/bash

set -u
set -o pipefail

BASE_DIR="$(pwd)"
NP=6
SOLVER="interIsoFoam"

PYTHON_BIN="$HOME/OpenFOAM/rafael_camps-v2312/run/Duto_Anular/venv/bin/python"

VAZOES=(35 60)

echo "================================================"
echo " BATERIA M0 - CLONAGEM E PREPARAÇÃO DE CASOS"
echo " Diretório base: $BASE_DIR"
echo " Núcleos MPI: $NP"
echo " Vazões: ${VAZOES[*]}"
echo "================================================"

for Q in "${VAZOES[@]}"; do

    NOME_CASO="M0_Q${Q}"
    CASO="$BASE_DIR/$NOME_CASO"

    echo ""
    echo "================================================"
    echo " INICIANDO: $NOME_CASO"
    echo "================================================"

    if [[ -d "$CASO" ]]; then
        echo "ERRO: caso já existe: $CASO"
        exit 1
    fi

    # =========================================================
    # 1. COPIAR O CASO-BASE SEM A MALHA E OS RESULTADOS
    # =========================================================

    rsync -a \
        --exclude='M0*' \
        --exclude='Q*' \
        --exclude='TQ*' \
        --exclude='processor*' \
        --exclude='postProcessing' \
        --exclude='dynamicCode' \
        --exclude='log.*' \
        --exclude='backup*' \
        --exclude='benchmark*' \
        --exclude='*.zip' \
        --exclude='*.tar*' \
        --exclude='.git' \
        --exclude='.vscode' \
        --exclude='__pycache__' \
        --exclude='run_m0_cloning.sh' \
        --exclude='venv' \
        --exclude='meu_env' \
        --exclude='md' \
        --exclude='0' \
        --exclude='.gitignore' \
        "$BASE_DIR/" "$CASO/" || {
            echo "ERRO: falha ao copiar o caso-base."
            exit 1
        }

    cd "$CASO" || exit 1

    # =========================================================
    # 2. CONFIGURAR A VAZÃO
    # =========================================================

    "$PYTHON_BIN" modelo_anular.py condicoes "$Q" \
        > "log.modelo_Q${Q}" 2>&1

    if [[ $? -ne 0 ]]; then
        echo "ERRO: modelo_anular.py falhou para Q${Q}"
        exit 1
    fi

    # Restaurar as condições iniciais
    rm -rf 0
    cp -a 0.orig 0


    # =========================================================
    # 3. CRIAR OS FACESETS
    # =========================================================

    echo "Executando topoSet para Q${Q}..."

    topoSet > "log.topoSet_Q${Q}" 2>&1

    if [[ $? -ne 0 ]]; then
        echo "ERRO: topoSet falhou para Q${Q}"
        exit 1
    fi

    # Verificar os tamanhos dos conjuntos
    grep -E \
        "faceSet (inletFaces|inletOil|inletAir).*size" \
        "log.topoSet_Q${Q}" || {
            echo "ERRO: não foi possível confirmar os faceSets."
            exit 1
        }

    # =========================================================
    # 4. DIVIDIR O INLET EM INLET_OIL E INLET_AIR
    # =========================================================

    echo "Executando createPatch para Q${Q}..."

    createPatch -overwrite \
        > "log.createPatch_Q${Q}" 2>&1

    if [[ $? -ne 0 ]]; then
        echo "ERRO: createPatch falhou para Q${Q}"
        exit 1
    fi

    # Verificar se os novos patches foram criados
    if ! grep -q "inlet_oil" constant/polyMesh/boundary; then
        echo "ERRO: patch inlet_oil não foi encontrado."
        exit 1
    fi

    if ! grep -q "inlet_air" constant/polyMesh/boundary; then
        echo "ERRO: patch inlet_air não foi encontrado."
        exit 1
    fi

    # Confirmar que os patches não estão vazios
    echo "Verificando patches criados..."

    sed -n '/inlet_oil/,/}/p' \
        constant/polyMesh/boundary

    sed -n '/inlet_air/,/}/p' \
        constant/polyMesh/boundary

    if grep -A5 "inlet_oil" constant/polyMesh/boundary \
        | grep -q "nFaces[[:space:]]\+0"; then
        echo "ERRO: inlet_oil possui zero faces."
        exit 1
    fi

    if grep -A5 "inlet_air" constant/polyMesh/boundary \
        | grep -q "nFaces[[:space:]]\+0"; then
        echo "ERRO: inlet_air possui zero faces."
        exit 1
    fi

    # =========================================================
    # 5. VERIFICAR A MALHA
    # =========================================================

    echo "Executando checkMesh para Q${Q}..."

    checkMesh -allGeometry -allTopology \
        > "log.checkMesh_Q${Q}" 2>&1

    if [[ $? -ne 0 ]]; then
        echo "ERRO: checkMesh falhou para Q${Q}"
        exit 1
    fi

    if ! grep -q "Mesh OK" "log.checkMesh_Q${Q}"; then
        echo "ERRO: checkMesh não confirmou Mesh OK."
        exit 1
    fi

    # =========================================================
    # 6. APLICAR CONDIÇÕES INICIAIS
    # =========================================================

    echo "Executando setFields para Q${Q}..."

    setFields > "log.setFields_Q${Q}" 2>&1

    if [[ $? -ne 0 ]]; then
        echo "ERRO: setFields falhou para Q${Q}"
        exit 1
    fi

    # =========================================================
    # 7. DECOMPOR A MALHA
    # =========================================================

    echo "Executando decomposePar para Q${Q}..."

    decomposePar > "log.decomposePar_Q${Q}" 2>&1

    if [[ $? -ne 0 ]]; then
        echo "ERRO: decomposePar falhou para Q${Q}"
        exit 1
    fi

    # =========================================================
    # 8. EXECUTAR O SOLVER
    # =========================================================

    echo "Executando interIsoFoam para Q${Q}..."

    mpirun -np "$NP" "$SOLVER" -parallel \
        > "log.interIsoFoam_Q${Q}" 2>&1

    STATUS_SOLVER=$?

    if [[ $STATUS_SOLVER -ne 0 ]]; then
        echo "ERRO: solver falhou para Q${Q}"
        exit "$STATUS_SOLVER"
    fi

    # =========================================================
    # 9. RECONSTRUIR
    # =========================================================

    echo "Reconstruindo resultados para Q${Q}..."

    reconstructPar > "log.reconstructPar_Q${Q}" 2>&1

    if [[ $? -ne 0 ]]; then
        echo "ERRO: reconstructPar falhou para Q${Q}"
        exit 1
    fi

    # =========================================================
    # 10. PÓS-PROCESSAMENTO
    # =========================================================

    ../Allrun post \
        > "log.Allrun_post_Q${Q}" 2>&1

    if [[ $? -ne 0 ]]; then
        echo "AVISO: Allrun post apresentou erro."
    fi

    ../Allrun compare \
        > "log.Allrun_compare_Q${Q}" 2>&1

    if [[ $? -ne 0 ]]; then
        echo "AVISO: Allrun compare apresentou erro."
    fi


    echo "[OK] $NOME_CASO concluído."

    cd "$BASE_DIR" || exit 1

done

echo ""
echo "================================================"
echo " TODAS AS SIMULAÇÕES M0 FINALIZADAS"
echo "================================================"