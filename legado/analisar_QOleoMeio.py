import csv
import re
import glob
import os
import statistics

linhas = []
resumos = []

padrao_vetor = re.compile(
    r"weightedAreaIntegrate\(plano_meio\) of U = "
    r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)"
)

for arquivo in sorted(glob.glob("**/log.QOleoMeio", recursive=True)):
    caso = os.path.dirname(arquivo)
    tempo = None
    dados = []

    with open(arquivo, errors="replace") as f:
        for linha in f:
            m_tempo = re.search(r"Time = ([0-9.eE+-]+)", linha)
            if m_tempo:
                tempo = float(m_tempo.group(1))

            m = padrao_vetor.search(linha)
            if m and tempo is not None:
                ux, uy, uz = map(float, m.groups())
                q = uy * 60000.0

                dados.append((tempo, ux, uy, uz, q))
                linhas.append([caso, tempo, ux, uy, uz, q])

    if not dados:
        resumos.append([caso, 0, "", "", "", "", "", "SEM DADOS"])
        continue

    dados.sort(key=lambda x: x[0])
    vazoes = [x[4] for x in dados]

    def estatisticas(n):
        valores = vazoes[-min(n, len(vazoes)):]
        media = statistics.mean(valores)
        cv = (
            statistics.stdev(valores) / media * 100
            if len(valores) > 1 and media != 0 else 0
        )
        amplitude = max(valores) - min(valores)
        return media, cv, amplitude

    media5, cv5, amp5 = estatisticas(5)
    media10, cv10, amp10 = estatisticas(10)

    resumos.append([
        caso,
        len(dados),
        dados[-1][0],
        vazoes[-1],
        media5,
        cv5,
        amp5,
        "OK"
    ])

with open("resultados_QOleoMeio.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow([
        "caso", "tempo_s", "Ux_m3_s", "Qy_m3_s",
        "Uz_m3_s", "Qoleo_L_min"
    ])
    w.writerows(linhas)

with open("resumo_QOleoMeio.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow([
        "caso", "numero_amostras", "tempo_final_s",
        "Q_final_L_min", "media_ultimos_5_L_min",
        "CV_ultimos_5_pct", "amplitude_ultimos_5_L_min",
        "status"
    ])
    w.writerows(resumos)

print("\nRESUMO — VAZÃO DE ÓLEO NO PLANO CENTRAL")
print("-" * 90)

for r in resumos:
    if r[-1] == "OK":
        print(
            f"{r[0]:18s} | N={r[1]:3} | "
            f"Q final={float(r[3]):8.3f} L/min | "
            f"Média 5={float(r[4]):8.3f} L/min | "
            f"CV 5={float(r[5]):7.4f}%"
        )
    else:
        print(f"{r[0]:18s} | {r[-1]}")

print("\nArquivos gerados:")
print("  resultados_QOleoMeio.csv")
print("  resumo_QOleoMeio.csv")
