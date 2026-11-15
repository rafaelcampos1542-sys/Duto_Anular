# Function objects do OpenFOAM (v2312)

## `controlDict` — funções gravadas durante a simulação

| Função | Usada? | Coluna em `series_temporais.csv` |
|---|---|---|
| `QOleoInlet`, `QOleoOutlet`, `QOleoInletAir` | sim | `Q_in_L_min`, `Q_out_L_min`, `Q_inlet_air_L_min` |
| `QOleoMeio` | sim | `Q_meio_L_min` |
| `areaOleoInlet`, `areaOleoMeio`, `areaOleoSaida` | sim | `A_oleo_*_m2` e `h_*_mm` |
| `velocidadePonderada` | sim | `V_meio_m_s` |
| `volumeOleo` | sim | `volume_oleo_m3` |
| `areaOleoExterna`, `areaOleoInterno` | sim | `A_molhada_*_fo_m2` |
| `atritoExterno`, `atritoInterno` | sim | `tau_fo_*_Pa` |
| `wallShear` | o campo, sim | grava `wallShearStress` em cada tempo (entrada do cálculo de atrito) |
| `sampling` | diagnóstico | `perfis_resumo.csv` |
| `atritoPonderado` | não | duplicata de `atritoExterno` |
| `atritoParedeExterna` | não | média sem `weightField` |
| `velocidadeMediaMeio` | não | média sem `weightField` |

## `funcoes_pos_processamento/` — rodadas depois, sobre os tempos já gravados

Arquivos para a pasta `system/` do caso. Servem para gerar uma grandeza que não
estava no `controlDict` quando a simulação rodou.

| Arquivo | Gera |
|---|---|
| `QOleoMeio`, `QOleoProximo` | vazão de óleo nos planos y = 0 e y = −0,15 m |
| `areaOleoMeio`, `areaOleoProximo` | área de óleo nos mesmos planos |
| `areaOleoExterna`, `areaOleoInterna` | área molhada de cada parede |
| `atritoExterno`, `atritoInterno` | tensão média ponderada em cada parede |
| `velocidadePonderada` | velocidade média do óleo no plano central |
| `fluxoOleoInletAir` | vazão de óleo por `inlet_air` (`QOleoInletAir`) |
| `postProcessPerfilLateral` | perfil na linha lateral (`perfil_lateral`) |
| `readAlpha`, `readWallShearStress` | carregam `alpha.oil` e `wallShearStress` antes das funções acima |

Forma geral de uso (confira com os comandos que você usou):

```bash
# arquivo sem bloco "functions { }"
postProcess -funcs '(readAlpha readWallShearStress atritoExterno atritoInterno)'
postProcess -func QOleoProximo

# arquivo com bloco "functions { }"
postProcess -dict system/fluxoOleoInletAir
```

## `nao_usadas/`

| Arquivo | Motivo |
|---|---|
| `atritoPonderado` | igual a `atritoExterno` |
| `alphaStats` | média volumétrica de `alpha.oil`; redundante com `volumeOleo` |
| `posProcessAtrito` | cria os campos `tauWallMag` e `tauWallMagOil`; o atrito final é calculado em `duto_anular/atrito.py` |
