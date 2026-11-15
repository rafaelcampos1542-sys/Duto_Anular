2026-08-26

[DIAGNÓSTICO FÍSICO]
- `wallShearStress` não foi encontrado nos resultados disponíveis; isso não prova regime laminar.
- `alpha.oil` apresentou min=0 e max=1 nos tempos avaliados.
- No outlet em 40 s: areaIntegrate(alpha.oil)=0,000563792 m²; areaAverage(alpha.oil)=0,0945501.
- No outlet em 60 s: sumDirection(phi)=0,00131601; sumDirectionBalance(phi)=0,00061262; weightedSum(phi, alpha.oil)=0,000707103; sum(phi)=0,00061262.
- A independência temporal 40→60 s ainda não foi aprovada.

[ENTRADA]
- U inlet verificado: uniform (0 0.2054 0) m/s.
- A configuração anterior de alpha.oil no inlet usava codedFixedValue; isso não é equivalente a zeroGradient.
- Orientação do orientador: alpha.oil no inlet como zeroGradient, U=0,2054 m/s e óleo inicialmente a 53,904 mm.
- A nova condição ainda não foi validada.

[NUMÉRICO]
- Criado candidato S1 isolado: mergeLevels 1 -> 2 no GAMG de p_rgh.
- S1 deve ser testado isoladamente e não é configuração aprovada.
# CHANGELOG

2026-08-14

[ORQUESTRADOR]
- corrigido has_time_dirs()
- 0/ não é mais tratado como tempo de simulação
- archive não chama post quando não há resultado

[FVSOLUTION]
- GAMG_OPT mantido como candidato CPU principal

[VALIDAÇÃO]
- independência temporal ainda não concluída

2026-08-14

[ORQUESTRADOR]
- integrado o comando `./Allrun extract-profiles <backup> --times ...` ao fluxo do Allrun;
- o orquestrador localiza e valida o backup antes de chamar `analise.py extrair-perfis`;
- a saída é criada fora do backup e recebe diretório único por execução;
- adicionada geração de log específico para cada extração;
- o backup original nunca é removido, movido ou sobrescrito pelo orquestrador;
- a lógica de seleção e cópia dos perfis permanece exclusivamente no `analise.py`.


2026-08-18

[ESPECIALISTA NUMÉRICO]

- Benchmark V6 analisado.
- GAMG + 6 MPI normal confirmado como configuração MPI de referência/candidato.
- MPI oversubscribe não apresentou vantagem consistente e não deve ser usado como padrão.
- V6 mostrou que, no trecho inicial, maxCo=0,5 não é o limitante do timestep:
  Co permaneceu muito abaixo de 0,5.
- maxDeltaT=0,0015 também não foi identificado como limitante no trecho inicial.
- Não alterar maxCo/maxAlphaCo neste estágio.
- Não relaxar tolerâncias de p_rgh/U neste estágio.
- Não alterar parâmetros de alpha.oil neste estágio.
- Não alterar fvSchemes sem teste isolado e validação física.
- Identificado p_rgh/GAMG como principal alvo de otimização numérica.
- PIMPLE permanece inalterado como referência:
  nOuterCorrectors=2
  nCorrectors=3
  nNonOrthogonalCorrectors=0.

[FVSOLUTION]

- Criado candidato S1 isolado:
  p_rgh.GAMG mergeLevels 1 -> 2.
- Demais parâmetros do GAMG permanecem inalterados:
  smoother=DICGaussSeidel
  tolerance=1e-7
  relTol=0.05
  nCellsInCoarsestLevel=20
  cacheAgglomeration=yes.
- S1 deve ser comparado contra GAMG_OPT original + 6 MPI normal.
- S1 é somente candidato experimental; NÃO é configuração aprovada.

[PRÓXIMOS TESTES NUMÉRICOS]

Ordem planejada:
1. S1 — mergeLevels 1 -> 2.
2. S2 — nCellsInCoarsestLevel 20 -> 40.
3. S3 — investigação do smoother GAMG.
4. P1 — nOuterCorrectors 2 -> 1.
5. P2 — nCorrectors 3 -> 2.
6. Somente após análise da malha: testes de fvSchemes.
7. Posteriormente: estudo controlado de maxCo/maxAlphaCo.
8. Parâmetros de alpha.oil somente por último.

[REGRA DE TESTE]

- Cada teste deve alterar somente uma família de parâmetros.
- Nenhuma alteração deve ser incorporada à configuração oficial sem benchmark e validação.
- Alterações em PIMPLE, timestep, alpha ou fvSchemes que possam alterar a solução são classificadas como:
  OTIMIZAÇÃO NUMÉRICA COM NECESSIDADE DE VALIDAÇÃO FÍSICA.

[STATUS]

- Configuração de referência:
  GAMG_OPT + 6 MPI normal.
- S1:
  mergeLevels=2 — CANDIDATO, ainda não validado.
- Configuração oficial:
  NÃO definida.

2026-08-14

[ORQUESTRADOR]
- adicionado o comando `./Allrun resume <solver> <endTime>`;
- resume identifica numericamente o maior diretório de tempo real, excluindo `0/` e `0.orig/`;
- resume não executa `clean`, `init`, `setFields`, `blockMesh` ou `archive`;
- resume exige a presença de `constant/polyMesh` e de pelo menos um tempo de simulação > 0;
- resume usa `startFrom latestTime` e define o novo `endTime` para a continuação;
- resume preserva os diretórios de tempo existentes e usa logs exclusivos por execução;
- configuração MPI padrão permanece em 6 ranks e oversubscribe continua desativado por padrão;
- `run` e os demais comandos existentes não foram alterados.

Adicionar uma entrada de 26/08 documentando:

teste de 25 s concluído;
areaAverage(alpha.oil) no inlet em t=0 = 0,476505;
areaIntegrate(alpha.oil) em 25 s = 0,00586024 m²;
área total do inlet = 0,00596804 m²;
vazão CFD ≈ 72 L/min;
diagnóstico de que U=0,2054 m/s uniforme não garante Q=35 L/min;
investigação da condição de entrada em andamento.

INTERFACE_CONTRACT
Não mudaria as permissões. A separação atual continua correta: física/condições permanecem fora do orquestrador e do módulo numérico.

2026-08-26

[FVSOLUTION / BENCHMARK]

- Resultado do S1 — p_rgh.GAMG mergeLevels 1 -> 2 registrado.
- S1 foi executado com 6 MPI normal.
- Demais parâmetros do p_rgh.GAMG permaneceram inalterados.
- Referência GAMG_OPT:
  ~1253 s para 0,05 s de simulação.
- S1 mergeLevels=2:
  ~1115 s para 0,05 s de simulação.
- Ganho observado de aproximadamente 11% no trecho benchmarkado.
- S1 apresenta vantagem de desempenho em relação à referência.
- S1 permanece como CANDIDATO até validação física.
- Não promover S1 automaticamente para configuração oficial.

[FÍSICA / CONDIÇÃO DE ENTRADA]

- Foi executado caso de 25 s com:
  U inlet = uniform (0 0.2054 0).
- O cálculo analítico permanece consistente:
  A_L = 0,002840529 m²
  V = 0,2054 m/s
  Q = 35,0067 L/min.
- Em t=0, a área média de alpha.oil no inlet foi:
  areaAverage(alpha.oil) = 0,476505.
- Área total do inlet:
  0,00596804 m².
- Portanto, a área inicial de óleo é aproximadamente:
  0,476505 × 0,00596804 ≈ 0,002843 m²,
  consistente com a área líquida analítica.
- Ao final de 25 s:
  areaIntegrate(inlet, alpha.oil) = 0,00586024 m².
- A fração média de óleo no inlet passou para aproximadamente 0,982.
- A vazão de óleo medida por weightedSum(phi) ficou em aproximadamente
  0,00120 m³/s, equivalente a ~72 L/min.
- Diagnóstico: U uniforme = 0,2054 m/s não garante vazão constante de
  35 L/min quando a área ocupada pelo óleo varia.
- O problema não foi atribuído ao cálculo analítico de V/Q nem ao
  setFieldsDict, pois ambos foram verificados.
- A condição de entrada de alpha.oil/U permanece sob investigação.
- Não iniciar nova simulação longa antes de definir e testar a nova
  condição de entrada.

[VALIDAÇÃO]

- O caso de 25 s não deve ser considerado fisicamente validado.
- O resultado de vazão elevada deve ser tratado como diagnóstico da
  condição de entrada, não como resultado final do TCC.

  

## 2026-09-20 — Novo teste físico Q19

- Foi executada uma nova rodada com reconstrução completa da malha e reinicialização dos campos.
- Comandos principais: `blockMesh`, `topoSet`, `createPatch`, `checkMesh`, `setFields`, `decomposePar`, `interIsoFoam` com 6 MPI, `reconstructPar`, `./Allrun post` e `./Allrun compare`.
- O caso foi nomeado `Q19`, mas os comentários dos campos ainda apresentam referências a `Q=10` e `Q=15`; essa documentação deve ser uniformizada.
- A nova configuração usa `inlet_oil` com `alpha.oil = fixedValue uniform 1`.
- `inlet_air` usa `inletOutlet` para `alpha.oil`.
- `U` no `inlet_oil` foi informado como `uniform (0 0.2461 0)`.
- A saída usa `pressureInletOutletVelocity` para `U` e `prghPressure` para `p_rgh`.
- O resultado inicial foi considerado promissor pelo usuário, mas ainda não há evidência suficiente para declarar consistência física.
- Deve ser feita uma verificação sintática do arquivo `alpha.oil`, pois o trecho informado contém `ou value`, aparentemente um erro de edição.
- O teste deve ser classificado como **condição física experimental em avaliação**, sem promoção automática para configuração oficial.



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
