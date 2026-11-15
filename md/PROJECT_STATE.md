# PROJECT STATE — DUTO ANULAR

## Solver
Application: interIsoFoam
OpenFOAM: v2312

## Caso atual
Q = 35 L/min
Malha = grossa
EndTime = 20 s

## Configuração atualmente em execução
fvSolution = fvSolution.GAMG_OPT
MPI = 6
oversubscribe = no

maxCo = 0.5
maxAlphaCo = 0.5
maxDeltaT = 0.0015

## Status
Caso-base de 20 s em execução.

## Configuração oficial
Ainda não definida.

## Última decisão
GAMG + 6 MPI foi a melhor configuração CPU normal
testada na malha grossa.

## Próximo objetivo
Completar caso-base e então validar física.

interIsoFoam, OpenFOAM v2312
Q-alvo = 35 L/min
malha atual = 1.600.000 células
6 MPI, sem oversubscribe
fvSolution.GAMG_OPT
maxCo = 0.5
maxAlphaCo = 0.5
maxDeltaT = 0.0015
teste de 25 s concluído
condição atual U inlet = uniform (0 0.2054 0)
problema identificado: no início, alpha.oil no inlet ≈ 0,4765, coerente com 35 L/min; em 25 s, areaIntegrate(alpha.oil) ≈ 0,005860 m², levando a ~72 L/min
portanto, a condição de entrada de velocidade uniforme não está mantendo a vazão de óleo
nova configuração física ainda não validada

## Atualização 2026-08-26
- interIsoFoam, OpenFOAM v2312.
- Malha atual: 1.600.000 células.
- GAMG_OPT + 6 MPI, sem oversubscribe: permanece CANDIDATO.
- maxCo=0.5, maxAlphaCo=0.5, maxDeltaT=0.0015; maxDeltaT permanece PROVISÓRIO.
- Teste de 25 s concluído; U inlet=(0 0.2054 0) m/s.
- Nova orientação física: alpha.oil inlet=zeroGradient e óleo inicial a 53,904 mm.
- Vazão CFD aproximada registrada: 72 L/min em evolução.
- wallShearStress não encontrado nos resultados disponíveis; regime ainda não classificado.
- Não há configuração física final aprovada.
- O teste de 25 s recém-concluído não foi S1 (`mergeLevels=2`); portanto, seus resultados não validam S1.
- S1 (`mergeLevels=2`) permanece como proposta numérica separada, ainda sem teste/evidência nesta rodada.



## Atualização 2026-09-20 — Caso físico Q19

### Nova configuração experimental

- Identificação da rodada: `Q19`.
- Execução: `interIsoFoam` com 6 MPI, sem indicação de oversubscribe.
- Entrada de óleo:
  - `alpha.oil = fixedValue uniform 1`;
  - `U = uniform (0 0.2461 0) m/s`.
- Entrada de ar:
  - `alpha.oil = inletOutlet`, `inletValue uniform 0`;
  - `U = pressureInletOutletVelocity`.
- Saída:
  - `U = pressureInletOutletVelocity`;
  - `p_rgh = prghPressure`, `p uniform 0`;
  - `alpha.oil = inletOutlet`, `inletValue uniform 0` (a sintaxe deve ser confirmada no arquivo real).

### Status

- Resultado inicial: PROMISSOR, conforme avaliação preliminar do usuário.
- Validação física: NÃO CONCLUÍDA.
- Configuração oficial: NÃO DEFINIDA.
- Q19 deve ser comparado com a configuração anterior usando as mesmas métricas e, idealmente, a mesma duração física.

### Alertas de consistência documental

- O nome da rodada é `Q19`, mas os comentários fornecidos nos campos mencionam `Q=10` e `Q=15`.
- O valor `U=0.2461 m/s` deve ser relacionado explicitamente à vazão-alvo e à área efetiva do subpatch `inlet_oil`; não assumir automaticamente que representa a vazão total.
- O trecho `value uniform 0; ou value ...` em `alpha.oil/outlet` deve ser corrigido antes de executar uma nova rodada.



## Atualização — Q19 / configuração física experimental (2026-09-20)

### Sequência executada

A rodada foi preparada e executada com a seguinte sequência:

```bash
rm -rf constant/polyMesh
blockMesh > log.blockMesh 2>&1

topoSet > log.topoSet 2>&1
createPatch -overwrite > log.createPatch 2>&1
checkMesh > log.checkMesh 2>&1

rm -rf processor* postProcessing dynamicCode 0
cp -r 0.orig 0

setFields > log.setFields_Q19 2>&1
decomposePar > log.decomposePar_Q19 2>&1
mpirun -np 6 interIsoFoam -parallel > log.Q19 2>&1

reconstructPar > log.reconstructPar_Q19 2>&1
./Allrun post
./Allrun compare
```

Também foram previstos os comandos de inspeção do log:

```bash
grep -E "Time =|deltaT =|Courant Number mean|Interface Courant" log.Q19 | tail -40
grep -E "Time =|deltaT =" log.Q19 | tail -5
```

### Condições registradas

- `alpha.oil/inlet_oil`: `fixedValue`, `uniform 1`.
- `alpha.oil/inlet_air`: `inletOutlet`, `inletValue uniform 0`.
- `alpha.oil/outlet`: `inletOutlet`, `inletValue uniform 0`.
- `U/inlet_oil`: `fixedValue`, `uniform (0 0.2461 0)`.
- `U/inlet_air`: `pressureInletOutletVelocity`.
- `U/outlet`: `pressureInletOutletVelocity`.
- `p_rgh/outlet`: `prghPressure`, `p uniform 0`.
- Execução: `interIsoFoam`, 6 processos MPI.

### Pendências e cautelas

1. Os comentários nos campos ainda estão inconsistentes: aparecem referências a `Q=10`, `Q=15` e a rodada é identificada como `Q19`. Os comentários devem ser corrigidos antes de usar os arquivos como documentação final.
2. O trecho de `alpha.oil/outlet` que foi colado contém `value uniform 0; ou value ...`. Se esse texto existir literalmente no arquivo, ele precisa ser removido, pois não é sintaxe OpenFOAM válida.
3. O valor `U=(0 0.2461 0) m/s` não deve ser convertido automaticamente em uma vazão-alvo sem verificar a área efetiva de `inlet_oil` e a direção normal do patch.
4. A prescrição `alpha.oil=1` define a composição da entrada de óleo, mas não garante, sozinha, a vazão de óleo desejada.
5. A rodada permanece **experimental/em avaliação**. Não há promoção automática para configuração oficial.
6. A avaliação deve usar o log completo e os resultados pós-processados, incluindo:
   - tempo físico final e status de término;
   - `Co`, `alphaCo`, `deltaT`;
   - resíduos e erros de continuidade;
   - vazão total e vazão de óleo na entrada e na saída;
   - `h_L` e `areaOleo` no meio e na saída;
   - evolução temporal e possível refluxo.

### Estado desta atualização

Esta atualização registra a sequência e as condições informadas, mas **não registra valores numéricos do log `log.Q19`**, pois os resultados dos comandos `grep` não foram fornecidos no material recebido. Portanto, não é possível declarar estabilidade numérica, conservação de massa, vazão correta ou consistência física a partir desta atualização isolada.

## Estado atual — 2026-09-20

- Caso experimental: Q19.
- Solver: interIsoFoam, OpenFOAM v2312.
- Execução: 6 MPI, sem oversubscribe.
- Condição de entrada dividida em inlet_oil e inlet_air.
- Configuração física: EXPERIMENTAL / EM AVALIAÇÃO.
- Validação física: NÃO CONCLUÍDA.
- Valores numéricos do log Q19: ainda não registrados.
- Configuração oficial: NÃO DEFINIDA.