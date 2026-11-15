# INTERFACE CONTRACT

## 00 MASTER
Pode:
- aprovar decisões
- definir metodologia

Não pode:
- editar código especializado diretamente

## 01 ORQUESTRADOR
Pode:
- Allrun
- Allclean
- benchmark

Não pode:
- fvSolution
- fvSchemes
- física

## 02 NUMÉRICO
Pode:
- fvSolution
- fvSchemes

Não pode:
- Allrun
- Allclean
- condições

## 03 VALIDAÇÃO
Pode:
- analisar resultados
- definir critérios

Não pode:
- modificar solver

## 04 ANÁLISE
Pode:
- Python
- CSV
- gráficos

Não pode:
- modificar CFD

## Atualização 2026-08-26
A separação de responsabilidades permanece inalterada. S1 é proposta do 02 NUMÉRICO e não aprovação da configuração oficial.

## Correção de registro — 2026-08-26
O teste de 25 s recém-concluído não corresponde ao S1 (`mergeLevels=2`). Seus resultados pertencem ao teste físico/condições de contorno daquela rodada e não devem ser usados como evidência do S1.


## Atualização 2026-09-20 — Q19

A separação de responsabilidades permanece inalterada.

- A configuração física Q19 deve ser registrada e editada no módulo de condições/arquivos de caso, não no benchmark.
- O orquestrador pode executar a sequência de preparação, execução e pós-processamento.
- A análise deve verificar os resultados sem modificar automaticamente as condições de contorno.
- A configuração Q19 permanece experimental até que os critérios de validação sejam atendidos.



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
