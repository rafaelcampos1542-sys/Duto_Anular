#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""

Gera gráficos temporais de três grandezas do OpenFOAM.



Grandezas:

1. Atrito total ponderado por óleo (N), obtido do CSV consolidado.

2. Velocidade axial no plano central (m/s), obtida dos functionObjects.

3. Volume integrado de óleo (m³), obtido dos functionObjects.



Comparação: M0, M1 e M2 para Q10, Q35 e Q60.



Execute na pasta principal Duto_Anular:

    ./venv/bin/python graficos_temporais.py



Saída:

    graficos_temporais/

        Q10_atrito_total.png

        Q10_velocidade.png

        Q10_volume_oleo.png

        ... (9 gráficos)

        series_temporais.csv

        resumo_3a6s.csv

"""



from __future__ import annotations



import math

import re

from pathlib import Path



import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

import pandas as pd





# ---------------------------- CONFIGURAÇÃO -----------------------------------



MESHES = ("M0", "M1", "M2")

CASES = ("Q10", "Q35", "Q60")



FRICTION_CSV = Path(

    "resultados_consolidados/"

    "atrito_temporal_nove_casos_reconstruido.csv"

)



OUTPUT_DIR = Path("graficos_temporais")



METRICS = {

    "atritoTotal": {

        "ylabel": "Tensão de cisalhamento (Pa)",

        "filename": "atrito_total",

        "component": None,

    },

    "velocidadePonderada": {

        "ylabel": "Velocidade axial (m/s)",

        "filename": "velocidade",

        "component": 1,

    },

    "volumeOleo": {

        "ylabel": "Volume de óleo (m³)",

        "filename": "volume_oleo",

        "component": None,

    },

}



T_FINAL_PLOT = 6.05

TIME_MIN_SUMMARY = 3.0

TIME_MAX_SUMMARY = 6.0



# O ponto decimal precisa ser escapado. Sem isso, o regex também captura
# parênteses e espaços das linhas vetoriais do OpenFOAM, impedindo a leitura.
FLOAT_RE = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)





# ---------------------------- LEITURA DOS DADOS ------------------------------



def parse_data_file(

    path: Path,

    component: int | None = None

) -> list[tuple[float, float]]:

    """Lê linhas 'tempo valor' ou 'tempo (x y z)'."""



    rows = []



    try:

        lines = path.read_text(

            encoding="utf-8",

            errors="ignore"

        ).splitlines()

    except OSError as exc:

        print(f"[AVISO] Não consegui ler {path}: {exc}")

        return rows



    for line in lines:

        line = line.strip()



        if not line or line.startswith("#"):

            continue



        nums = FLOAT_RE.findall(line)



        if len(nums) not in (2, 4):

            continue



        try:

            values = [float(x) for x in nums]

        except ValueError:

            continue



        t, data = values[0], values[1:]



        if not math.isfinite(t):

            continue



        if not all(math.isfinite(x) for x in data):

            continue



        if len(data) == 3:

            if component is None:

                value = math.sqrt(sum(x * x for x in data))

            else:

                value = data[component]

        else:

            value = data[0]



        rows.append((t, value))



    return rows





def read_function_series(

    mesh: str,

    case: str,

    metric: str,

    component: int | None = None

) -> pd.DataFrame:

    """Lê os arquivos .dat dos functionObjects."""



    folder = (

        Path(mesh)

        / f"{mesh}_{case}"

        / "postProcessing"

        / metric

    )



    if not folder.is_dir():

        print(f"[AVISO] Pasta não encontrada: {folder}")

        return pd.DataFrame(columns=["tempo_s", "valor"])



    rows: dict[float, tuple[int, float]] = {}



    for file in sorted(folder.rglob("*.dat")):

        for time_value, value in parse_data_file(file, component):



            score = 2 if file.parent.name == "0" else 1

            previous = rows.get(time_value)



            if previous is None or score >= previous[0]:

                rows[time_value] = (score, value)



    data = [

        {"tempo_s": t, "valor": entry[1]}

        for t, entry in sorted(rows.items())

    ]



    return pd.DataFrame(data, columns=["tempo_s", "valor"])





def read_friction_series(

    csv_data: pd.DataFrame,

    mesh: str,

    case: str

) -> pd.DataFrame:

    """Obtém o atrito total diretamente do CSV consolidado."""



    sub = csv_data[

        (csv_data["malha"] == mesh)

        & (csv_data["caso"] == case)

    ][["tempo_s", "tau_media_global_Pa"]].copy()



    sub = sub.rename(

        columns={"tau_media_global_Pa": "valor"}

    )



    sub["tempo_s"] = pd.to_numeric(

        sub["tempo_s"], errors="coerce"

    )

    sub["valor"] = pd.to_numeric(

        sub["valor"], errors="coerce"

    )



    sub = sub.dropna()

    sub = sub.sort_values("tempo_s")

    sub = sub.drop_duplicates("tempo_s", keep="last")



    return sub.reset_index(drop=True)





# ---------------------------- RESUMO TEMPORAL -------------------------------



def summarize_interval(df: pd.DataFrame) -> dict | None:



    sub = df[

        (df["tempo_s"] >= TIME_MIN_SUMMARY)

        & (df["tempo_s"] <= TIME_MAX_SUMMARY)

    ].copy()



    if len(sub) < 2:

        return None



    mean_abs = abs(sub["valor"].mean())



    amplitude = (

        (sub["valor"].max() - sub["valor"].min())

        / mean_abs * 100

        if mean_abs > 0 else float("nan")

    )



    return {

        "n_registros": len(sub),

        "tempo_inicial_s": sub["tempo_s"].min(),

        "tempo_final_s": sub["tempo_s"].max(),

        "minimo": sub["valor"].min(),

        "maximo": sub["valor"].max(),

        "media": sub["valor"].mean(),

        "amplitude_relativa_pct": amplitude,

        "valor_final": df.iloc[-1]["valor"],

    }





# ---------------------------- EXECUÇÃO ---------------------------------------



def main() -> int:



    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)



    if not FRICTION_CSV.is_file():

        print(f"[ERRO] CSV de atrito não encontrado: {FRICTION_CSV}")

        return 1



    try:

        friction_data = pd.read_csv(FRICTION_CSV)

    except Exception as exc:

        print(f"[ERRO] Falha ao ler CSV de atrito: {exc}")

        return 1



    required_columns = {

        "malha",

        "caso",

        "tempo_s",

        "integral_tau_ponderada_total_N",

    }



    missing = required_columns - set(friction_data.columns)



    if missing:

        print(f"[ERRO] Colunas ausentes no CSV: {sorted(missing)}")

        return 1



    series_rows = []

    summary_rows = []

    plots_created = 0



    for case in CASES:



        for metric, cfg in METRICS.items():



            # Figura compacta: aumenta o tamanho relativo dos textos e da área útil
            # quando o PNG é reduzido para caber em uma coluna da grade 3x3.
            fig, ax = plt.subplots(figsize=(6.0, 4.0))

            plotted = 0



            for mesh in MESHES:



                if metric == "atritoTotal":

                    df = read_friction_series(

                        friction_data, mesh, case

                    )

                else:

                    df = read_function_series(

                        mesh,

                        case,

                        metric,

                        cfg["component"],

                    )



                df = df[df["tempo_s"] <= T_FINAL_PLOT].copy()



                if df.empty:

                    print(

                        f"[AVISO] Sem dados: "

                        f"{mesh}/{case}/{metric}"

                    )

                    continue



                plotted += 1



                for row in df.itertuples(index=False):

                    series_rows.append({

                        "caso": case,

                        "malha": mesh,

                        "grandeza": metric,

                        "tempo_s": row.tempo_s,

                        "valor": row.valor,

                    })



                nome_malha = {

                    "M0": "grossa",

                    "M1": "intermediária",

                    "M2": "fina",

                }[mesh]



                ax.plot(

                    df["tempo_s"],

                    df["valor"],

                    marker="o",
                    markersize=3.0,
                    linewidth=1.7,
                    label=mesh,

                )



                summary = summarize_interval(df)



                if summary is not None:

                    summary_rows.append({

                        "caso": case,

                        "malha": mesh,

                        "grandeza": metric,

                        **summary,

                    })



            if plotted:





                # Os títulos das linhas da figura LaTeX identificam a grandeza
                # e sua unidade; o eixo horizontal comum é tempo (s), indicado
                # na legenda da figura. Mantêm-se os valores numéricos dos eixos.
                ax.set_xlim(left=0, right=T_FINAL_PLOT)
                ax.tick_params(axis="both", labelsize=9, pad=2)
                ax.grid(True, alpha=0.28, linewidth=0.6)

                # Legenda curta para não ocupar a área útil de cada painel.
                ax.legend(
                    fontsize=8,
                    loc="best",
                    frameon=True,
                    framealpha=0.85,
                    borderpad=0.25,
                    labelspacing=0.2,
                    handlelength=1.5,
                    handletextpad=0.4,
                )

                # Margens menores aumentam a área efetiva do gráfico no PNG.
                fig.subplots_adjust(
                    left=0.13, right=0.985, bottom=0.11, top=0.985
                )



                filename = (

                    OUTPUT_DIR

                    / f"{case}_{cfg['filename']}.png"

                )



                fig.savefig(filename, dpi=300, bbox_inches="tight", pad_inches=0.03)

                plots_created += 1



                print(f"[OK] Gráfico salvo: {filename}")



            else:

                print(

                    f"[AVISO] Nenhum dado para "

                    f"{case} / {metric}"

                )



            plt.close(fig)



    if series_rows:

        series_file = OUTPUT_DIR / "series_temporais.csv"



        pd.DataFrame(series_rows).to_csv(

            series_file,

            index=False,

        )



        print(f"[OK] Séries temporais: {series_file}")



    if summary_rows:

        summary_file = OUTPUT_DIR / "resumo_3a6s.csv"



        pd.DataFrame(summary_rows).to_csv(

            summary_file,

            index=False,

        )



        print(f"[OK] Resumo temporal: {summary_file}")



    print(

        f"\nConcluído: {plots_created} de 9 gráficos gerados."

    )

    print(f"Resultados em: {OUTPUT_DIR.resolve()}")



    if plots_created == 0:

        return 1



    return 0





if __name__ == "__main__":

    raise SystemExit(main())
