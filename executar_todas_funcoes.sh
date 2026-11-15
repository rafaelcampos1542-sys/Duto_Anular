
#!/usr/bin/env bash
set -u
set -o pipefail

CASOS=(
    M0/M0_Q10 M0/M0_Q35 M0/M0_Q60
    M1/M1_Q10 M1/M1_Q35 M1/M1_Q60
    M2/M2_Q10 M2/M2_Q35 M2/M2_Q60
    M1_Q20_R1 M1_Q20_R2 M1_Q20_R3
    M1_Q55_R1 M1_Q55_R2 M1_Q55_R3
)

FUNCOES=(
    readAlpha
    readWallShearStress
    areaOleoExterna
    areaOleoInterna
    areaOleoMeio
    areaOleoProximo
    atritoExterno
    atritoInterno
    velocidadePonderada
    QOleoMeio
    QOleoProximo
)

# Dicionários necessários em cada caso
ARQUIVOS=(
    readAlpha
    readWallShearStress
    posProcessAtrito
    areaOleoExterna
    areaOleoInterna
    areaOleoMeio
    areaOleoProximo
    atritoExterno
    atritoInterno
    velocidadePonderada
    QOleoMeio
    QOleoProximo
    fluxoOleoInletAir
    postProcessPerfilLateral
)

ERROS=0

for c in "${CASOS[@]}"; do

    echo
    echo "=========================================="
    echo "PROCESSANDO: $c"
    echo "=========================================="

    # 1. Verificar existência do caso
    if [ ! -d "$c" ]; then
        echo "ERRO: caso não encontrado."
        ((ERROS+=1))
        continue
    fi

    # 2. Verificar arquivos de origem
    FALTA=0

    for f in "${ARQUIVOS[@]}"; do
        if [ ! -f "$f" ]; then
            echo "ERRO: arquivo ausente: $f"
            FALTA=1
        fi
    done

    if [ "$FALTA" -eq 1 ]; then
        echo "Caso ignorado: existem arquivos ausentes."
        ((ERROS+=1))
        continue
    fi

    # 3. Criar system e copiar dicionários
    mkdir -p "$c/system"

    echo "Copiando dicionários para $c/system/..."

    if ! cp -v "${ARQUIVOS[@]}" "$c/system/"; then
        echo "ERRO: falha ao copiar dicionários."
        ((ERROS+=1))
        continue
    fi

    echo "OK: dicionários copiados."

    # 4. Identificar tempos disponíveis
    TIMES=$(foamListTimes -case "$c" -noZero 2>/dev/null |
        awk '$1 ~ /^[0-9]/ {print $1}')

    FIRST=$(printf '%s\n' "$TIMES" | head -n 1)
    LAST=$(printf '%s\n' "$TIMES" | tail -n 1)

    if [ -z "$FIRST" ] || [ -z "$LAST" ]; then
        echo "ERRO: nenhum tempo disponível."
        ((ERROS+=1))
        continue
    fi

    echo "Tempo inicial: $FIRST"
    echo "Tempo final:   $LAST"

    # 5. Funções principais
    echo
    echo "Executando funções principais..."

    if postProcess -case "$c" \
        -funcs "(${FUNCOES[*]})" \
        -time "$FIRST:$LAST" \
        > "$c/log.posProcessamento" 2>&1; then

        echo "OK: funções principais executadas."
    else
        echo "ERRO: funções principais."
        echo "Consultar: $c/log.posProcessamento"
        ((ERROS+=1))
    fi

    # 6. Gerar campos de magnitude da tensão de cisalhamento
    echo
    echo "Gerando tauWallMag e tauWallMagOil..."

    if postProcess -case "$c" \
        -dict system/posProcessAtrito \
        -time "$FIRST:$LAST" \
        > "$c/log.posProcessAtrito" 2>&1; then

        echo "OK: campos de atrito gerados."
    else
        echo "ERRO: geração dos campos de atrito."
        echo "Consultar: $c/log.posProcessAtrito"
        ((ERROS+=1))
    fi

    # 7. Fluxo de óleo na entrada de ar
    echo
    echo "Calculando fluxo na entrada de ar..."

    if postProcess -case "$c" \
        -dict system/fluxoOleoInletAir \
        -fields '(alpha.oil phi)' \
        -time 3:6 \
        > "$c/log.fluxoOleoInletAir" 2>&1; then

        echo "OK: fluxo na entrada de ar."
    else
        echo "ERRO: fluxo na entrada de ar."
        echo "Consultar: $c/log.fluxoOleoInletAir"
        ((ERROS+=1))
    fi

    # 8. Perfil lateral
    echo
    echo "Extraindo perfil lateral..."

    if postProcess -case "$c" \
        -dict system/postProcessPerfilLateral \
        -fields '(alpha.oil U)' \
        -time "$FIRST:$LAST" \
        > "$c/log.perfilLateral" 2>&1; then

        echo "OK: perfil lateral."
    else
        echo "ERRO: perfil lateral."
        echo "Consultar: $c/log.perfilLateral"
        ((ERROS+=1))
    fi

done

echo
echo "=========================================="
echo "PROCESSAMENTO FINALIZADO"
echo "Total de casos: ${#CASOS[@]}"
echo "Total de erros: $ERROS"
echo "=========================================="
