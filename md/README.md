# Canal Anular — Estrutura Consolidada

Esta versão reduz os scripts de controle e elimina funções Python duplicadas.

## Arquivos

```text
Duto_Anular/
├── Allrun
├── Allclean
├── benchmark.sh
├── modelo_anular.py
├── analise.py
├── README.md
├── 0.orig/
├── 0/
├── constant/
└── system/
```

### `modelo_anular.py`

É o único módulo responsável pelo modelo analítico e pela geração das condições de contorno.

Consolida as funções que existiam em `calculadora_anular.py` e `calcular_condicoes.py`:

- geometria do canal;
- área de segmento circular;
- perímetro molhado;
- diâmetro hidráulico;
- fator de atrito de Churchill;
- velocidade e vazão;
- busca das raízes `Q(h_L)`;
- identificação da região;
- geração de `setFieldsDict`;
- geração de `alpha.oil`;
- geração de `U`;
- geração de `turbulenceProperties`.

### `analise.py`

É o único módulo de pós-processamento.

Consolida:

- `analisar_resultados.py`;
- comparação analítico x CFD;
- diagnóstico `perfil_meio`;
- diagnóstico `perfil_saida`;
- detecção de gap;
- cruzamento `alpha.oil = 0.5`;
- análise da derivada da interface;
- gráficos.

### `Allrun`

É o ponto de entrada principal para a simulação.

### `Allclean`

Limpa o caso sem apagar `0.orig/`.

### `benchmark.sh`

Executa os testes de desempenho dos solvers. Continua separado porque benchmark é uma tarefa diferente da execução normal.

---

# 1. Primeira configuração

Carregue o OpenFOAM:

```bash
source /caminho/do/OpenFOAM/etc/bashrc
```

Se o ambiente já estiver configurado no `.bashrc`, basta abrir o terminal normalmente.

Verifique:

```bash
which blockMesh
which interIsoFoam
```

---

# 2. Ambiente Python

Se o `venv` já existe:

```bash
./venv/bin/pip install numpy scipy matplotlib pandas
```

Caso ainda não exista:

```bash
python3 -m venv venv
./venv/bin/pip install numpy scipy matplotlib pandas
```

---

# 3. Dar permissão aos scripts

Execute uma vez:

```bash
chmod +x Allrun Allclean benchmark.sh modelo_anular.py analise.py
```

---

# 4. Calcular as condições

Exemplo para 35 L/min:

```bash
./Allrun condicoes 35
```

Isso calcula a raiz estável e gera diretamente:

```text
system/setFieldsDict
0.orig/alpha.oil
0.orig/U
constant/turbulenceProperties
```

A condição é colocada em `0.orig/` porque esse diretório é a fonte usada para reconstruir `0/` depois da limpeza.

---

# 5. Executar uma simulação completa

A forma mais simples:

```bash
./Allrun full 35 gamg
```

Sequência:

```text
calcular condições
        ↓
clean
        ↓
blockMesh
        ↓
checkMesh
        ↓
setFields
        ↓
decomposePar
        ↓
interIsoFoam
        ↓
reconstructPar
        ↓
sampling
        ↓
resultados
        ↓
diagnóstico VOF
        ↓
comparação analítica
```

---

# 6. Escolher o solver

### GAMG

```bash
./Allrun full 35 gamg
```

### PETSc CPU

```bash
./Allrun full 35 petsc_cpu
```

### PETSc GPU

```bash
./Allrun full 35 petsc_gpu
```

---

# 7. Rodar somente 5 segundos

```bash
./Allrun run5 petsc_cpu
```

Ou:

```bash
./Allrun run gamg 5
```

O número de processos pode ser alterado:

```bash
NPROCS=14 ./Allrun run petsc_cpu 5
```

---

# 8. Rodar sem recalcular as condições

Se as condições já estiverem configuradas:

```bash
./Allrun run petsc_cpu
```

Isso usa o `endTime` existente no `system/controlDict`.

---

# 9. Pós-processamento

Depois que a simulação terminar:

```bash
./Allrun post
```

São gerados:

```text
resultados_hL.csv
diagnostico_vof_perfil_meio.png
```

O CSV contém, entre outros:

```text
tempo
h_L meio
h_L saída
h_L vertical
Q meio
Q saída
Q teórica
```

---

# 10. Comparação analítico x CFD

```bash
./Allrun compare
```

Gera:

```text
comparacao_analitico_cfd.png
```

A comparação usa o mesmo `modelo_anular.py`, evitando manter uma segunda implementação da curva analítica.

---

# 11. Diagnóstico VOF isolado

Para investigar problemas no `perfil_meio`:

```bash
./venv/bin/python analise.py diagnostico
```

O diagnóstico verifica:

- `alpha.oil`;
- posição da interface `alpha=0.5`;
- derivada da interface;
- espaçamento da amostragem;
- existência de gap;
- possível passagem da linha pelo tubo interno;
- diferença entre `perfil_meio` e `perfil_saida`.

---

# 12. Status do caso

```bash
./Allrun status
```

Mostra:

- existência da malha;
- `0/`;
- `0.orig/`;
- número de tempos;
- último tempo;
- decomposição;
- CSV;
- gráfico da comparação.

---

# 13. Limpar o caso

```bash
./Allrun clean
```

ou:

```bash
./Allclean
```

A limpeza remove:

- tempos numéricos;
- `processor*`;
- `postProcessing`;
- logs;
- `dynamicCode`;
- `case.foam`.

Mas preserva:

```text
0.orig/
system/
constant/
```

Depois recria:

```text
0/
```

a partir de:

```text
0.orig/
```

---

# 14. Benchmark

O benchmark continua separado:

```bash
./benchmark.sh
```

Ele compara as configurações disponíveis em:

```text
system/fvSolution.gamg.bak
system/fvSolution.petsc_cpu.bak
system/fvSolution.amgx.bak
```

e testa os números de processos definidos no script.

Os principais parâmetros podem ser alterados por variável de ambiente:

```bash
BENCH_TIME=0.1 \
WRITE_INTERVAL=0.05 \
CHECK_INTERVAL=10 \
TIMEOUT_LIMIT=20m \
./benchmark.sh
```

---

# 15. Comandos mais importantes

Na prática, você vai usar principalmente:

```bash
# Gerar condições
./Allrun condicoes 35

# Rodar tudo
./Allrun full 35 petsc_cpu

# Teste rápido
./Allrun run5 petsc_cpu

# Pós-processar
./Allrun post

# Comparar
./Allrun compare

# Ver status
./Allrun status

# Limpar
./Allrun clean

# Benchmark
./benchmark.sh
```

## Fluxo recomendado

Para uma nova vazão:

```bash
./Allrun full 35 petsc_cpu
```

Depois, para outra vazão:

```bash
./Allrun full 20 petsc_cpu
```

e:

```bash
./Allrun full 50 petsc_cpu
```

Não é necessário executar manualmente `calcular_condicoes.py`, `master.sh`, `run_pipeline.sh`, `run_until.sh` ou `compare_analytic.sh`.

---

## Arquivos antigos que podem ser removidos depois de testar

Após confirmar que a versão consolidada funciona no caso, estes scripts deixam de ser necessários:

```text
master.sh
run_pipeline.sh
run_until.sh
calculadora_anular.py
calcular_condicoes.py
analisar_resultados.py
compare_analytic.sh
debug_perfil_meio.py
diagnostico_vof_perfil_meio.py
diagnostico_vof_perfil_meio_v2.py
Allrun_bench
analisar_benchmark.sh
```

Não apague imediatamente. Rode primeiro alguns casos e compare os resultados com a versão antiga.


## Atualização 2026-09-20 — Registro da configuração Q19

Foi adicionada uma configuração física experimental com duas subentradas:

- `inlet_oil`, com `alpha.oil` prescrito como 1 e velocidade fixa;
- `inlet_air`, com condição `inletOutlet` para a fase e condição de velocidade apropriada.

A rodada é executada com 6 MPI e passa pelo fluxo de reconstrução de malha, inicialização, execução, reconstrução e pós-processamento.

**Importante:** Q19 não deve ser promovido automaticamente a configuração oficial. Antes disso, devem ser verificados:
- sintaxe dos campos;
- vazão total e vazão de óleo;
- conservação de massa;
- evolução de `h_L`;
- estabilidade numérica;
- consistência com a vazão e a geometria do experimento.

Os comentários de vazão nos arquivos de campo devem ser atualizados para evitar mistura entre os casos Q10, Q15 e Q19.



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
## Configuração de referência atual

- Solver: GAMG_OPT
- MPI: 6 processos
- Oversubscribe: desativado
- Status: candidato de desempenho
- Validação física: não concluída

A configuração Q19 é experimental e não deve ser considerada
configuração oficial sem análise de estabilidade, conservação
de massa e consistência das vazões.