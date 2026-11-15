"""Biblioteca comum do pós-processamento do Duto Anular.

Módulos:
  modelo_anular     modelo analítico h_L(Q) e geração das condições OpenFOAM
  casos             nomes dos casos, malhas e constantes físicas
  funcoes_openfoam  seleção das function objects (usada / descartada e por quê)
  leitura_openfoam  leitura dos .dat de postProcessing e dos perfis de linha
  atrito            atrito nas paredes a partir dos campos e da malha
  estatistica       médias temporais e GCI (Celik et al., 2008)
  dados             leitura dos CSVs gerados por 01_extrair_dados.py
"""
