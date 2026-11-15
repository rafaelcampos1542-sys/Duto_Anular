# Scripts antigos (só para consulta)

Estes arquivos não são mais usados. Ficam aqui para rastrear de onde veio cada
conta. Os três scripts da raiz substituem todos eles.

| Script antigo | O que fazia | Onde está agora |
|---|---|---|
| `consolidar_brutos_final_v1.4.0.py` | extração dos `.dat`, auditoria de patch, atrito dos campos | `01_extrair_dados.py`, `duto_anular/leitura_openfoam.py`, `duto_anular/atrito.py` |
| `consolidar_brutos.py`, `_v1.3.0.py`, `_v1.3.1.py` | versões anteriores do consolidador | substituídas pela v1.4.0 e depois pelo script 01 |
| `calcular_atrito_paredes.py` | atrito de referência (um caso por vez) | `duto_anular/atrito.py` |
| `consolidar_resultados_15_casos_3a6s.py` | consolidação antiga: perfis, balanço, repetibilidade | perfis → script 01; balanço → script 03 (`base/tabela5_balanco.csv`) |
| `analisar_QOleoMeio.py` | lia a vazão central de `log.QOleoMeio` | script 01 lê o `.dat`; o log é só reserva |
| `comparar_planos_axiais.py` | h_L e Q nos planos y = −0,15 m e y = 0 | colunas `*_proximo` e `*_meio` do script 01 |
| `analise_gci_celik_atrito_total.py` | GCI | `02_analise_gci.py`, `duto_anular/estatistica.py` |
| `graficos_temporais.py` | históricos temporais (Figura C.1) | `02_analise_gci.py` |
| `comparar_analitico_cfd_M1.py` | Figura 7 | `03_comparar_analitico_cfd.py --parte base` |
| `comparar_analitico_cfd_R.py` | Tabela 7 e Figura 8 | `03_comparar_analitico_cfd.py --parte multiplicidade` |
| `analise_estabilidade_axial_TCC.py` | CV_r, estável/transiente, figuras do Apêndice 9 | `03_comparar_analitico_cfd.py --parte multiplicidade` |
| `analise.py` | script único antigo (`resultados_hL.csv`, diagnóstico VOF) | h_L por área → script 01; o resto não foi migrado |
| `analisar_atrito_faces.py`, `analisar_atrito_paredes.py`, `analisar_radial.py` | diagnósticos pontuais, fixos em `M1/M1_Q35` | não migrados |

`modelo_anular.py` não está aqui: continua em uso, em `duto_anular/modelo_anular.py`.
