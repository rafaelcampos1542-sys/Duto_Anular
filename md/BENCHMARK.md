# BENCHMARK — histórico dos testes recentes

> **Documento consolidado a partir dos arquivos/logs fornecidos nesta conversa.**
> Resultados de benchmark de desempenho são separados de resultados físicos/validação.
> Nenhuma configuração é declarada como aprovada apenas por desempenho ou convergência.

## 1. Escopo e regras

- Solver: `interIsoFoam` / OpenFOAM v2312.
- Malha de desenvolvimento: 240.000 células.
- O benchmark mede principalmente avanço físico por tempo computacional (`sim_time / wall_s`).
- `TIMEOUT` não é falha física; significa que o limite de execução foi atingido.
- `FAIL` não deve ser interpretado como resultado físico.
- Os testes curtos não são resultados de validação física.

## 2. Benchmark V6 — diagnóstico de MPI/GAMG

Arquivo de resultados: `results.tsv`.

### Fase 1 — triagem

| Caso | ranks | MPI | status | wall (s) | sim time (s) | timesteps | ExecutionTime (s) | throughput (sim s / wall s) | p_rgh solves | p_rgh it. |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|

### Fase 2 — confirmação

| Caso | ranks | MPI | status | wall (s) | sim time (s) | timesteps | ExecutionTime (s) | throughput | p_rgh solves | p_rgh it. |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|

### TOP 2 registrado pelo próprio benchmark

1. `cpu6_gamg_normal` — 6 ranks, MPI normal, throughput `7.97314285714e-06`.
2. `cpu8_gamg_oversub` — 8 ranks, oversubscribe, throughput `7.4416e-06`.

**Observação:** o arquivo `results.tsv` contém confirmação executada apenas para `cpu6_gamg_normal`. O `cpu8_gamg_oversub` aparece no TOP 2 da triagem, mas não há uma linha de confirmação correspondente nesse arquivo.

## 3. Benchmark V4 — comparação de famílias/quantidades de processos

Arquivo: `benchmark_results_v4(4).tsv`.

| Caso | família | ranks | MPI | status | wall (s) | sim time (s) | throughput |
|---|---|---:|---|---|---:|---:|---:|
| `cpu4_gamg_opt` | `GAMG_OPT` | 4 | MPI_NORMAL | TIMEOUT | 1202 | 0.0228688 | 1.902562396e-05 |
| `cpu6_gamg_opt` | `GAMG_OPT` | 6 | MPI_NORMAL | TIMEOUT | 1202 | 0.0236285 | 1.965765391e-05 |
| `cpu8_gamg_opt` | `GAMG_OPT` | 8 | MPI_NORMAL | FAIL:1 | 5 | nan | NA |
| `cpu10_gamg_opt` | `GAMG_OPT` | 10 | MPI_NORMAL | FAIL:1 | 5 | nan | NA |
| `cpu12_gamg_opt` | `GAMG_OPT` | 12 | MPI_NORMAL | FAIL:1 | 5 | nan | NA |
| `cpu14_gamg_opt` | `GAMG_OPT` | 14 | MPI_NORMAL | FAIL:1 | 5 | nan | NA |
| `cpu4_petsc_opt` | `PETSC_CPU_OPT` | 4 | MPI_NORMAL | TIMEOUT | 1202 | 0.0187359 | 1.558727121e-05 |
| `cpu8_petsc_opt` | `PETSC_CPU_OPT` | 8 | MPI_NORMAL | FAIL:1 | 5 | nan | NA |
| `cpu12_petsc_opt` | `PETSC_CPU_OPT` | 12 | MPI_NORMAL | FAIL:1 | 5 | nan | NA |
| `gpu1_amgx_pressure_serial` | `AMGX_PRESSURE_OPT` | 1 | SERIAL | TIMEOUT | 1201 | 0.0123294 | 1.026594505e-05 |
| `gpu2_amgx_pressure` | `AMGX_PRESSURE_OPT` | 2 | MPI_NORMAL | TIMEOUT | 1202 | 0.0164977 | 1.372520799e-05 |
| `gpu4_amgx_pressure` | `AMGX_PRESSURE_OPT` | 4 | MPI_NORMAL | TIMEOUT | 1202 | 0.0161211 | 1.341189684e-05 |
| `cpu4_gamg_opt` | `GAMG_OPT` | 4 | MPI_OVERSUBSCRIBE | TIMEOUT | 1202 | 0.0226809 | 1.886930116e-05 |
| `cpu6_gamg_opt` | `GAMG_OPT` | 6 | MPI_OVERSUBSCRIBE | TIMEOUT | 1202 | 0.023629 | 1.965806988e-05 |
| `cpu8_gamg_opt` | `GAMG_OPT` | 8 | MPI_OVERSUBSCRIBE | TIMEOUT | 1204 | 0.0219229 | 1.82083887e-05 |
| `cpu10_gamg_opt` | `GAMG_OPT` | 10 | MPI_OVERSUBSCRIBE | TIMEOUT | 1204 | 0.0226808 | 1.883787375e-05 |
| `cpu12_gamg_opt` | `GAMG_OPT` | 12 | MPI_OVERSUBSCRIBE | TIMEOUT | 1205 | 0.0226807 | 1.882215768e-05 |
| `cpu14_gamg_opt` | `GAMG_OPT` | 14 | MPI_OVERSUBSCRIBE | TIMEOUT | 1202 | 0.0230565 | 1.918178037e-05 |
| `cpu4_petsc_opt` | `PETSC_CPU_OPT` | 4 | MPI_OVERSUBSCRIBE | TIMEOUT | 1202 | 0.0191058 | 1.589500832e-05 |
| `cpu8_petsc_opt` | `PETSC_CPU_OPT` | 8 | MPI_OVERSUBSCRIBE | TIMEOUT | 1203 | 0.0200393 | 1.665777224e-05 |
| `cpu12_petsc_opt` | `PETSC_CPU_OPT` | 12 | MPI_OVERSUBSCRIBE | TIMEOUT | 1205 | 0.0209802 | 1.741095436e-05 |
| `gpu1_amgx_pressure_serial` | `AMGX_PRESSURE_OPT` | 1 | SERIAL | TIMEOUT | 1202 | 0.0127139 | 1.057728785e-05 |
| `gpu2_amgx_pressure` | `AMGX_PRESSURE_OPT` | 2 | MPI_OVERSUBSCRIBE | TIMEOUT | 1201 | 0.0176174 | 1.466894255e-05 |
| `gpu4_amgx_pressure` | `AMGX_PRESSURE_OPT` | 4 | MPI_OVERSUBSCRIBE | TIMEOUT | 1202 | 0.0164983 | 1.372570715e-05 |

### Leitura do V4

- Entre os casos que efetivamente avançaram, `cpu6_gamg_opt` apresentou os maiores throughputs registrados nas duas modalidades de MPI mostradas.
- Os casos com 8/10/12/14 ranks em MPI normal falharam logo no início (`FAIL:1`) nesse benchmark.
- Os casos em `MPI_OVERSUBSCRIBE` chegaram a executar, mas todos foram limitados por `TIMEOUT`.
- Os casos PETSc e AMGX também tiveram `TIMEOUT` nos ensaios mostrados.
- Isso é evidência de **desempenho computacional**, não de superioridade física do solver.

## 4. Teste S1 — GAMG `mergeLevels=2`

O `README_S1_mergeLevels2(2).txt` define:

- Base: `fvSolution(4).GAMG_OPT`.
- Única alteração: no solver `p_rgh`, `mergeLevels 1;` → `mergeLevels 2;`.
- Objetivo: verificar ganho em `sim_time / execution_time_s`.
- O teste não deve ser combinado com alterações de PIMPLE, `alpha.oil`, `fvSchemes` ou timestep.
- O candidato não substitui automaticamente `system/fvSolution` e a base deve ser restaurada após o teste.

Fonte: README do teste S1. fileciteturn9file1

### Log fornecido — `log.GAMG_merge2`

| métrica | valor observado |
|---|---:|
| tempo físico final | 0.0499791 s |
| passos | 225 |
| ExecutionTime final | 1114.25 s |
| `deltaT` final | 0.0002883 s |
| maior Co observado no log | 0.573779 |
| maior alphaCo observado no log | 0.512623 |

**Não há no arquivo fornecido uma tabela explícita com o benchmark base correspondente ao mesmo ensaio. Portanto, não declarar ganho percentual de `mergeLevels=2` a partir deste log isolado.**

## 5. Testes temporais / PIMPLE fornecidos

Os arquivos `log.PIMPE2` e `log.PIMPLE1` foram fornecidos como logs de testes separados. Os nomes dos arquivos, por si só, não documentam todos os parâmetros alterados. Por isso, abaixo são registrados somente os fatos extraídos dos logs.

| log | tempo físico final | passos | ExecutionTime (s) | deltaT final (s) | max Co | max alphaCo |
|---|---:|---:|---:|---:|---:|---:|
| `log.PIMPE2` | 0.0499791 | 225 | 1146.17 | 0.0002883 | 0.573772 | 0.512622 |
| `log.PIMPLE1` | 0.0501157 | 225 | 1252.32 | 0.000288775 | 0.554338 | 0.502795 |

### Comparação direta dos logs

- `log.GAMG_merge2`: ~0,0499791 s físicos em 1114,25 s de ExecutionTime.
- `log.PIMPE2`: ~0,0499791 s físicos em 1146,17 s.
- `log.PIMPLE1`: ~0,0501157 s físicos em 1252,32 s.
- Portanto, **nesses três logs isolados**, `log.GAMG_merge2` teve o menor ExecutionTime.
- Isso não prova que `mergeLevels=2` seja a causa da diferença, porque os arquivos fornecidos não estabelecem, sozinhos, que os três logs tenham exatamente a mesma configuração exceto por `mergeLevels`.

## 6. Testes físicos recentes — 20 → 40 → 60 s

Estes resultados vêm do histórico da execução no projeto e não dos arquivos de benchmark numérico anexados.

### Fatos registrados na campanha

- A continuação a partir de `19.99997020014791 s` conseguiu avançar para 40 s após o problema de `perfil_vertical_debug` ser desativado.
- A continuação seguinte iniciou a partir de `39.9994274751765531 s` e foi levada até 60 s.
- O volume global de óleo informado para 40–60 s variou aproximadamente de `0,0173018` para `0,0172928 m³`, diferença relativa de aproximadamente `0,052%`.
- A interpretação adotada foi de que o volume estava praticamente estabilizado, mas isso **não é, sozinho, prova de estado estacionário completo**.
- Também foi observado comportamento de saída com aproximadamente 9–10% de óleo e forte fluxo bidirecional, enquanto o meio apresentava fração de óleo muito maior.

### Diagnóstico físico atual

- A condição inicial analítica atual é `h_L = 53,904324 mm` para `Q = 35 L/min`, obtida diretamente por `modelo_anular.py`.
- A execução analítica encontrou uma única raiz para `Q = 35 L/min` no cálculo realizado.
- Portanto, não há base para substituir a condição inicial por `h_L = 16,559 mm` como se fosse uma segunda raiz.
- O caso de 25 s já utilizava `alpha.oil/inlet = zeroGradient` e `U/inlet = fixedValue (0 0.2054 0)`; a vazão de óleo chegou a aproximadamente 72 L/min segundo o diagnóstico registrado no projeto.
- Assim, repetir exatamente `alpha.oil/inlet = zeroGradient` não constitui um novo teste causal.

## 7. Estado metodológico após os testes

| item | classificação atual |
|---|---|
| 6 MPI / GAMG | melhor candidato de desempenho registrado |
| `cpu6_gamg_normal` | melhor resultado confirmado no V6 fornecido |
| `cpu8_gamg_oversub` | TOP 2 da triagem V6; confirmação não presente no `results.tsv` |
| `mergeLevels=2` | experimental; ganho não quantificado neste documento por falta de base pareada explícita |
| `h_L=53,904324 mm` | raiz analítica para Q=35 L/min no cálculo executado |
| `alpha.oil inlet = zeroGradient` | já testado no caso físico de 25 s; não repetir como novo teste |
| estado físico final | não aprovado/validado |

## 8. Próximo teste físico discutido

Foi considerada a possibilidade de restaurar a configuração anterior de `alpha.oil/inlet` como **teste A/B**, preservando `U = 0,2054 m/s` e todos os demais parâmetros.

Isso deve ser tratado como **configuração experimental**, não como aprovação da BC antiga.

Objetivo:

1. comparar a evolução de `alpha.oil` na entrada;
2. comparar `Q_óleo,in`;
3. comparar `Q_ar,in`;
4. verificar refluxo na saída;
5. verificar `areaOleoMeio` e `areaOleoSaida`.

**Não alterar simultaneamente `U`, outlet, propriedades, malha, `fvSolution` ou `fvSchemes`.**

## 9. Fontes anexadas utilizadas

- `results.tsv` — Benchmark V6.
- `top2.txt` — TOP 2 da triagem V6.
- `benchmark_results_v4(4).tsv` — resultados V4.
- `README_S1_mergeLevels2(2).txt` — especificação do teste S1. fileciteturn9file1
- `log.GAMG_merge2` — log do teste correspondente ao arquivo de log fornecido.
- `log.PIMPE2` — log do teste fornecido.
- `log.PIMPLE1` — log do teste fornecido.

## 10. Regra de interpretação

> **Nenhum benchmark de desempenho, convergência iterativa ou avanço temporal curto deve ser usado isoladamente como validação física do modelo bifásico.**

> **Resultados `TIMEOUT` e `FAIL` são resultados computacionais do teste e não devem ser interpretados como falha física do modelo.**



## Atualização — teste físico Q19 (2026-09-20)

### Configuração informada

- Reconstrução da malha: `blockMesh`, `topoSet`, `createPatch`, `checkMesh`.
- Condições reinicializadas a partir de `0.orig/`.
- `setFields` executado.
- Decomposição e execução com `mpirun -np 6 interIsoFoam -parallel`.
- Pós-processamento realizado com `./Allrun post` e `./Allrun compare`.
- Log principal: `log.Q19`.

### Condições de contorno informadas

**`alpha.oil`:**
- `inlet_oil`: `fixedValue`, `value uniform 1`.
- `inlet_air`: `inletOutlet`, `inletValue uniform 0`.
- `outlet`: `inletOutlet`, `inletValue uniform 0`.

**`p_rgh`:**
- `outlet`: `prghPressure`, `p uniform 0`.
- `inlet_oil`: `fixedFluxPressure`.
- `inlet_air`: `totalPressure`, `p0 uniform 0`.

**`U`:**
- `inlet_oil`: `fixedValue uniform (0 0.2461 0)`.
- `inlet_air`: `pressureInletOutletVelocity`.
- `outlet`: `pressureInletOutletVelocity`.

### Classificação

Este caso é registrado como **novo teste físico/condição de contorno Q19**, não como benchmark de desempenho isolado.

A configuração ainda não deve ser considerada validada, porque:
1. o trecho fornecido de `alpha.oil/outlet` contém texto aparentemente inválido (`ou value ...`), que precisa ser corrigido no arquivo real;
2. os comentários dos arquivos apresentam vazões diferentes (`Q=10`, `Q=15` e o nome `Q19`);
3. não foram fornecidos nesta atualização os valores completos de `Co`, `alphaCo`, `deltaT`, conservação de massa e séries temporais;
4. um resultado pontual ou uma primeira execução aparentemente boa não demonstra consistência temporal ou independência de malha.

### Dados a registrar quando o log Q19 for analisado

- tempo físico final;
- wall time e `ExecutionTime`;
- número de passos;
- `Co` médio/máximo;
- `Interface Courant` médio/máximo;
- `deltaT` mínimo/máximo;
- erros de continuidade;
- `Q` total e de óleo na entrada e saída;
- `areaOleoMeio`, `areaOleoSaida`;
- `h_L` no meio e na saída;
- status de término.




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
## S1 — mergeLevels=2

O log GAMG_merge2 apresentou ExecutionTime de 1114,25 s
para aproximadamente 0,05 s de tempo físico.

O log apresentou menor ExecutionTime entre os logs comparados,
mas não há confirmação de que todos os ensaios tenham utilizado
exatamente a mesma configuração, exceto mergeLevels.

Portanto:

- S1 permanece CANDIDATO EXPERIMENTAL;
- não há ganho percentual oficialmente validado;
- não promover automaticamente para a configuração oficial.