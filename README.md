# Pós-processamento — Duto Anular (OpenFOAM)

Três scripts, rodados em ordem. O primeiro lê os casos do OpenFOAM e grava CSVs.
Os outros dois leem só esses CSVs.

| Script | O que faz | Lê | Grava |
|---|---|---|---|
| `01_extrair_dados.py` | Extrai e trata os dados dos casos | pastas dos casos | `dados_extraidos/` |
| `02_analise_gci.py` | Convergência de malha (GCI) | `dados_extraidos/` | `resultados/gci/` |
| `03_comparar_analitico_cfd.py` | Modelo analítico x CFD (base e multiplicidade) | `dados_extraidos/` | `resultados/analitico_cfd/` |

## Como rodar

```bash
pip install -r requirements.txt

python 01_extrair_dados.py --raiz /caminho/dos/casos
python 02_analise_gci.py
python 03_comparar_analitico_cfd.py
```

O script 01 não altera nada dentro dos casos. Os scripts 02 e 03 não precisam
do OpenFOAM nem dos casos: bastam os CSVs de `dados_extraidos/`.

Opções úteis:

| Comando | Para quê |
|---|---|
| `01_extrair_dados.py --sem-atrito` | pula a leitura dos campos (rápido) |
| `01_extrair_dados.py --atrito-csv dados_extraidos/atrito_paredes.csv` | reaproveita um atrito já calculado (quando os campos não estão mais no disco) |
| `02_analise_gci.py --janela 4 5` | muda a janela das médias temporais |
| `03_comparar_analitico_cfd.py --parte multiplicidade` | roda só uma parte (`base`, `multiplicidade` ou `tudo`) |

## Estrutura

```
01_extrair_dados.py
02_analise_gci.py
03_comparar_analitico_cfd.py
duto_anular/                 biblioteca usada pelos três scripts
    modelo_anular.py         modelo analítico h_L(Q) e condições do OpenFOAM
    casos.py                 nomes dos casos, malhas, janelas padrão
    funcoes_openfoam.py      SELEÇÃO das function objects (usada / descartada)
    leitura_openfoam.py      leitura dos .dat e dos perfis de linha
    atrito.py                atrito nas paredes a partir dos campos
    estatistica.py           médias temporais e GCI
    dados.py                 leitura dos CSVs extraídos, h_L por área, Re e Fr
openfoam/                    controlDict e function objects (ver README da pasta)
legado/                      scripts antigos, só para consulta (ver README da pasta)
dados_extraidos/             gerado pelo script 01
resultados/                  gerado pelos scripts 02 e 03
```

## Organização dos casos

Um caso é uma pasta chamada `M<malha>_Q<vazão>` ou `M<malha>_Q<vazão>_R<raiz>`,
em qualquer nível abaixo de `--raiz`:

```
M0/M0_Q10   M0/M0_Q35   M0/M0_Q60
M1/M1_Q10   M1/M1_Q35   M1/M1_Q60
M2/M2_Q10   M2/M2_Q35   M2/M2_Q60
M1_Q20_R1   M1_Q20_R2   M1_Q20_R3
M1_Q55_R1   M1_Q55_R2   M1_Q55_R3
```

Cada caso precisa de `postProcessing/`. Para o atrito, precisa também de
`constant/polyMesh/` e dos campos `alpha.oil` e `wallShearStress` em cada tempo
(formato ascii). Pastas `backup*`, `resultados*` e `processor*` são ignoradas.

## O que sai de cada script

### `dados_extraidos/` (script 01)

| Arquivo | Conteúdo |
|---|---|
| `series_temporais.csv` | **tabela principal**: uma linha por caso e por tempo |
| `casos.csv` | casos encontrados, número de células, tempos, origem do atrito |
| `atrito_paredes.csv` | atrito calculado dos campos, com todas as colunas |
| `perfis_resumo.csv` | linhas de amostragem: interface e velocidade por fase |
| `brutos/functionObjects.csv` | todo registro lido, com arquivo e linha de origem |
| `auditoria/selecao_funcoes.csv` | funções usadas e descartadas, com o motivo |
| `auditoria/cobertura.csv` | quantos registros há de cada grandeza em cada caso |
| `auditoria/ocorrencias.csv` | o que está faltando ou precisa de revisão |
| `auditoria/inventario_arquivos.csv` | cada arquivo lido, com cabeçalho e hash |

Colunas de `series_temporais.csv`:

| Coluna | Origem | Observação |
|---|---|---|
| `Q_in_L_min` | QOleoInlet | positivo = entra por `inlet_oil` |
| `Q_out_L_min` | QOleoOutlet | positivo = sai por `outlet` |
| `Q_inlet_air_L_min` | QOleoInletAir | positivo = sai por `inlet_air` |
| `Q_meio_L_min`, `Q_proximo_L_min` | QOleoMeio, QOleoProximo | planos y = 0 e y = −0,15 m |
| `A_oleo_*_m2` | areaOleoInlet/Meio/Saida/Proximo | área de óleo na seção |
| `h_entrada_mm`, `h_meio_mm`, `h_saida_mm`, `h_proximo_mm` | calculada | inversão de A_L(h_L) do modelo |
| `V_meio_m_s` | velocidadePonderada | componente axial (y) |
| `volume_oleo_m3` | volumeOleo | |
| `A_molhada_*_fo_m2`, `tau_fo_*_Pa` | areaOleoExterna/Interna, atritoExterno/Interno | function objects; conferência |
| `integral_tau_ponderada_*_N` | campos + malha | **forças de atrito do TCC** |
| `area_ponderada_oleo_*_m2` | campos + malha | **área ponderada do TCC** |
| `tau_media_*_Pa` | campos + malha | tensão média (Figura C.1) |

### `resultados/gci/` (script 02)

| Arquivo | No TCC |
|---|---|
| `tabela_gci.csv` | Tabelas 2, 3, A.1 e B.1 |
| `relatorio_gci_completo.csv` | todos os indicadores (R, p, GCI, razão assintótica, CV, deriva) |
| `medias_por_malha.csv` | médias temporais por malha |
| `taxas_de_variacao.csv` | Tabela C.1 (taxas entre 5 e 6 s) |
| `figuras/Q10_atrito_total.png` … | Figura C.1 |

### `resultados/analitico_cfd/` (script 03)

| Arquivo | No TCC |
|---|---|
| `base/tabela4_parametros.csv` | Tabela 4 e velocidades, Re, Fr da Seção 4.2 |
| `base/tabela5_balanco.csv` | Tabela 5 |
| `base/tabela6_analitico_cfd.csv` | Tabela 6 |
| `base/altura_central_por_malha.csv` | variação de h_L entre malhas (Seção 4.3) |
| `base/diagnostico_perfil_central.csv` | ar em contracorrente na linha central (Seção 4.3) |
| `base/figuras/comparacao_analitico_cfd_M1.png` | Figura 7 |
| `multiplicidade/tabela7_estatisticas.csv` | Tabela 7 |
| `multiplicidade/analitico_cfd.csv` | diferenças de altura da Seção 4.4 |
| `multiplicidade/repetibilidade.csv` | CV_r |
| `multiplicidade/estabilidade.csv` | estável / transiente |
| `multiplicidade/figuras/evolucao_temporal_M1.png` | Figura 8 |
| `multiplicidade/figuras/repetibilidade_M1_Q20.png`, `…_Q55.png` | Apêndice 9 |

## Seleção das function objects

A lista fica em `duto_anular/funcoes_openfoam.py`. Para incluir uma função nova,
basta acrescentar uma linha lá.

**Usadas:** QOleoInlet, QOleoOutlet, QOleoInletAir, QOleoMeio, QOleoProximo,
areaOleoInlet, areaOleoMeio, areaOleoSaida, areaOleoProximo, velocidadePonderada,
volumeOleo, areaOleoExterna, areaOleoInterna, atritoExterno, atritoInterno.

**Descartadas** (ficam só em `brutos/`):

| Função | Motivo |
|---|---|
| `atritoPonderado` | duplicata exata de `atritoExterno` |
| `atritoParedeExterna` | média sem peso: mistura parede molhada e seca |
| `velocidadeMediaMeio` | média sem peso: dominada pelo ar (≈ −5,9 m/s em M1_Q10) |
| `wallShear` | guarda só mínimo e máximo |
| `alphaStats` | redundante com `volumeOleo` |

O cabeçalho de cada `.dat` também é conferido (patch, operação e campo de peso).
Arquivo com cabeçalho diferente do esperado fica fora dos dados tratados e
aparece como erro em `auditoria/ocorrencias.csv`. Isso pega, por exemplo, um
atrito gravado antes de o `weightField` ser incluído.

## Diferenças em relação aos scripts antigos

As contas (média trapezoidal, GCI, estatísticas de Q20/Q55, CV_r, atrito) são as
mesmas. O que mudou foi a leitura dos dados:

1. **Trechos de reinício.** Todos os trechos (`0/`, `0.249825/`, `4.9997…/`) são
   unidos. O `analise.py` antigo lia um arquivo só de `areaOleoMeio` e usava o
   tempo mais próximo; com isso, a altura `h_L_meio_mm` de `resultados_hL.csv`
   podia ficar repetida depois do fim desse arquivo.
2. **Uma fonte só para h_L.** Antes havia `resultados_hL.csv` (Tabelas 6 e 7,
   Figuras 7 e 8) e `comparar_planos_axiais.py` (CV_r). Agora tudo usa `h_meio_mm`.
3. **Tempos com valores diferentes em dois trechos.** Vale o reinício mais
   recente, e o conflito é registrado. Antes cada script tinha uma regra.
4. **Tensão média em parede seca** (área molhada < 1e-8 m²) fica vazia.
5. **Itens não migrados** de `analise.py`: `TauParedeInterna/Externa` (funções
   que não existem no `controlDict`) e `tau_CFD_eq_Pa` (usava L = 3,0 m; o
   domínio tem 0,60 m).

## Modelo analítico

`duto_anular/modelo_anular.py` é o mesmo arquivo de antes. Para gerar as
condições de um caso:

```bash
python -m duto_anular.modelo_anular condicoes 35 --case M1/M1_Q35
python -m duto_anular.modelo_anular condicoes 20 --raiz 2 --case M1_Q20_R2
```
