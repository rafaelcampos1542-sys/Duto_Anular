# DECISÕES

## D001 — Solver CPU
GAMG_OPT + 6 MPI.
Motivo: melhor desempenho observado entre as configurações
CPU testadas na malha grossa.

Status: CANDIDATO

## D002 — Oversubscribe
Não usar por padrão.

Status: APROVADO para benchmark normal.

## D003 — maxDeltaT
0.0015 é usado atualmente para pre-run/caso-base.
Ainda NÃO é considerado validado fisicamente.

Status: PROVISÓRIO.

manter GAMG_OPT + 6 MPI como candidato de desempenho
não usar oversubscribe
manter maxDeltaT como provisório
registrar que não devemos alterar calcular_V_Q(), pois ele produz:
A_L = 0,002840529 m²
V = 0,2054 m/s
Q = 35,0067 L/min
registrar que o problema está na evolução de alpha.oil/condição de entrada, não na conversão analítica Q–V.

## D004 — Condição de entrada de alpha.oil
Orientação do orientador: usar `zeroGradient` no inlet de `alpha.oil`, manter U inlet = 0,2054 m/s e iniciar o óleo a 53,904 mm.
Status: EM VALIDAÇÃO. Não aprovada sem evidência registrada.

## D005 — Vazão CFD observada
Teste de 25 s indicou vazão CFD aproximada de 72 L/min em evolução, apesar de U inlet=0,2054 m/s.
Interpretação: a fração de óleo na seção de entrada evolui e U uniforme não garante Q de óleo=35 L/min.
Status: DIAGNÓSTICO.

## D006 — wallShearStress
A ausência de `wallShearStress` não determina o regime.
Status: NÃO RESOLVIDO; verificar modelo de turbulência e extração do campo.

## D007 — S1 GAMG
Candidato: `mergeLevels 2`, mantendo os demais parâmetros do `fvSolution.GAMG_OPT`.
Status: PROPOSTA NÃO TESTADA.
Observação: o teste de 25 s recém-concluído não foi um teste de `mergeLevels`; seus resultados não constituem evidência para aprovar ou rejeitar S1.



## D008 — Novo teste físico Q19

**Descrição:** nova configuração com entrada de óleo explicitamente prescrita em `inlet_oil`.

- `alpha.oil/inlet_oil`: `fixedValue uniform 1`.
- `alpha.oil/inlet_air`: `inletOutlet`, com `inletValue uniform 0`.
- `U/inlet_oil`: `fixedValue uniform (0 0.2461 0)`.
- `U/inlet_air`: `pressureInletOutletVelocity`.
- `U/outlet`: `pressureInletOutletVelocity`.
- `p_rgh/outlet`: `prghPressure`, `p uniform 0`.

**Status:** EXPERIMENTAL / EM AVALIAÇÃO.

**Justificativa:** a prescrição de `alpha.oil=1` em `inlet_oil` diferencia esta condição da configuração anterior com `zeroGradient` e pode evitar a evolução não controlada da composição da entrada. Entretanto, a configuração só poderá ser considerada fisicamente consistente após balanço de massa, análise temporal e confirmação de que as vazões e alturas correspondem ao experimento.

**Pendências obrigatórias:**
1. corrigir/verificar a sintaxe do bloco `outlet` de `alpha.oil`;
2. uniformizar os comentários de vazão e altura nos arquivos;
3. registrar `Co`, `alphaCo`, `deltaT`, resíduos e continuidade;
4. confirmar a área efetiva de cada subpatch de entrada;
5. verificar se `0.2461 m/s` corresponde à vazão-alvo na área realmente ocupada por óleo;
6. não alterar simultaneamente solver, malha e parâmetros temporais durante a comparação A/B.



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
### D009 — Estado da execução Q19

A sequência de reconstrução da malha, criação dos patches,
inicialização, decomposição e execução foi registrada.

Entretanto, a aprovação da configuração depende da análise de:

- status real de término;
- tempo físico final;
- Co e alphaCo;
- resíduos e continuidade;
- vazão de óleo na entrada e saída;
- área e altura de óleo;
- evolução temporal e refluxo.

Status: PENDENTE DE EVIDÊNCIA NUMÉRICA.