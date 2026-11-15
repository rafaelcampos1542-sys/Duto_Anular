#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Consolidação pós-processamento CFD — duto anular (OpenFOAM v2312).

Não modifica casos OpenFOAM. Lê, quando disponíveis:
  * atrito_M{0,1,2}_Q{10,35,60}.csv;
  * ZIPs M*_Q*_sampling.zip com perfil_meio/perfil_saida;
  * pastas Mx/Mx_Qy/postProcessing com QOleoOutlet, QOleoInlet,
    volumeOleo e outros functionObjects;
  * opcionalmente dados_gci_temporais.tar.gz (estrutura Mx/Mx_Qy/postProcessing).

Gera CSVs em resultados_consolidados/.

IMPORTANTE SOBRE O BALANÇO:
Q nominal, vazão ponderada no outlet e dV_oleo/dt são mantidos separados.
O resíduo Qnom-Qout-dV/dt NÃO é chamado de erro de conservação, pois a
abertura inlet_air permite troca de fases/óleo com o ambiente e sua contribuição
precisa ser contabilizada com sinal consistente. weightedSum(phi) com
weightField alpha.oil também é preservado como saída do functionObject, sem
assumir que seja automaticamente o fluxo de fase exato em faces com reversão.
"""
from __future__ import annotations
import argparse, csv, math, re, zipfile, tarfile
from pathlib import Path
from collections import defaultdict

MESHES = ('M0','M1','M2')
FLOWS = ('Q10','Q35','Q60')
NOMINAL_LMIN = {'Q10':10.0,'Q35':35.0,'Q60':60.0}
NUM = re.compile(r'[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?')
MULTIPLICITY_CASES = tuple(f'M1_Q{q}_R{r}' for q in (20, 55) for r in (1, 2, 3))
CASE_IDS = tuple(f'{mesh}_{flow}' for mesh in MESHES for flow in FLOWS) + MULTIPLICITY_CASES
NOMINAL_LMIN.update({'Q20': 20.0, 'Q55': 55.0})


def case_metadata(case_id):
    m = re.fullmatch(r'(M[012])_Q(10|20|35|55|60)(?:_R([123]))?', case_id)
    if not m:
        return {'malha': None, 'vazao_nominal_L_min': None, 'replica': None}
    return {'malha': m.group(1), 'vazao_nominal_L_min': float(m.group(2)),
            'replica': f'R{m.group(3)}' if m.group(3) else None}



def case_locations(root, case_id):
    """Localiza caso ativo na raiz ou arquivado dentro da pasta da malha."""
    mesh = case_metadata(case_id)['malha']
    candidates = [root / case_id]
    if mesh:
        candidates.append(root / mesh / case_id)
    existing = [p for p in candidates if p.is_dir()]
    return (existing[0] if existing else None), existing


def fnum(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError): return None


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows and not fields: return
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)


def read_friction(root):
    rows = []
    for cid in CASE_IDS:
        meta = case_metadata(cid)
        candidates = [root / f'atrito_{cid}.csv', root / cid / 'atrito_paredes.csv']
        if meta['malha']:
            candidates.append(root / meta['malha'] / cid / 'atrito_paredes.csv')
        p = next((x for x in candidates if x.exists()), None)
        if p is None:
            continue
        with p.open(newline='', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                row = {'caso_id': cid, 'malha': meta['malha'],
                       'caso': cid.split('_')[1], 'replica': meta['replica'],
                       'tempo_s': fnum(r.get('tempo_s'))}
                for k, v in r.items():
                    if k != 'tempo_s':
                        row[k] = fnum(v)
                ai = row.get('area_ponderada_oleo_interna_m2') or 0.0
                ae = row.get('area_ponderada_oleo_externa_m2') or 0.0
                if ai < 1e-8: row['tau_media_interna_Pa'] = None
                if ae < 1e-8: row['tau_media_externa_Pa'] = None
                agi = row.get('area_geometrica_interna_m2') or 0.0
                age = row.get('area_geometrica_externa_m2') or 0.0
                row['fracao_molhada_interna_pct'] = 100*ai/agi if agi > 0 else None
                row['fracao_molhada_externa_pct'] = 100*ae/age if age > 0 else None
                rows.append(row)
    return rows


def split_branches(points, gap=0.01):
    pts=sorted(points,key=lambda x:x[0]); branches=[]; cur=[]
    for p in pts:
        if cur and p[0]-cur[-1][0] > gap:
            branches.append(cur); cur=[]
        cur.append(p)
    if cur: branches.append(cur)
    return branches


def trap_mean(x,y):
    if len(x)<2 or x[-1]<=x[0]: return sum(y)/len(y) if y else None
    integ=sum((y[i]+y[i+1])*0.5*(x[i+1]-x[i]) for i in range(len(x)-1))
    return integ/(x[-1]-x[0])


def crossings(points, level=0.5):
    """Retorna cruzamentos, incluindo pontos exatamente no nível solicitado."""
    out=[]
    for (z0,a0,*_), (z1,a1,*_) in zip(points,points[1:]):
        if a0 == level:
            out.append(z0)
        if (a0-level)*(a1-level)<0:
            out.append(z0+(level-a0)*(z1-z0)/(a1-a0))
    if points and points[-1][1] == level:
        out.append(points[-1][0])
    # Remove duplicatas consecutivas/numéricas em vértices da interface.
    clean=[]
    for z in sorted(out):
        if not clean or abs(z-clean[-1])>1e-10: clean.append(z)
    return clean


def phase_velocity_means(points, level=0.5):
    """Médias de U1 por fase ao longo da linha, com corte linear em alpha=level.

    Os segmentos são divididos no cruzamento interpolado. A classificação é
    óleo se alpha>level e ar se alpha<level; pontos/trechos exatamente no nível
    ficam na interface e não entram nas médias de óleo/ar.
    """
    accum={'oleo':[0.0,0.0], 'ar':[0.0,0.0], 'interface':[0.0,0.0]}
    valid=[(z,a,u) for z,a,u in points if u is not None]
    for (z0,a0,u0),(z1,a1,u1) in zip(valid,valid[1:]):
        dz=abs(z1-z0)
        if dz<=0: continue
        cuts=[(0.0,a0,u0),(1.0,a1,u1)]
        if (a0-level)*(a1-level)<0:
            f=(level-a0)/(a1-a0)
            cuts.insert(1,(f,level,u0+f*(u1-u0)))
        for (f0,aa0,uu0),(f1,aa1,uu1) in zip(cuts,cuts[1:]):
            length=dz*(f1-f0)
            amid=(aa0+aa1)*0.5
            phase='oleo' if amid>level else ('ar' if amid<level else 'interface')
            accum[phase][0] += 0.5*(uu0+uu1)*length
            accum[phase][1] += length
    return {f'U1_media_{k}_m_s': (v[0]/v[1] if v[1]>0 else None)
            for k,v in accum.items()} | {f'comprimento_{k}_m':v[1] for k,v in accum.items()}


def parse_profile_csv(raw, case, time_s, profile_name):
    text=raw.decode('utf-8-sig',errors='replace').splitlines()
    if not text: return []
    reader=csv.DictReader(text)
    pts=[]
    for r in reader:
        z=fnum(r.get('z')); a=fnum(r.get('alpha.oil'))
        u=fnum(r.get('U_1'))
        if z is not None and a is not None: pts.append((z,a,u))
    out=[]
    for ib,b in enumerate(split_branches(pts),1):
        z=[p[0] for p in b]; a=[p[1] for p in b]
        valid_u=[(p[0],p[1],p[2]) for p in b if p[2] is not None]
        aw=[p[1] for p in valid_u]; uw=[p[2] for p in valid_u]
        denom=trap_mean([p[0] for p in valid_u],aw) if valid_u else None
        u_weighted=None
        if valid_u:
            # Média de U ponderada por alpha ao longo da linha: integral(alpha*U)/integral(alpha)
            xx=[p[0] for p in valid_u]; num=[p[1]*p[2] for p in valid_u]
            den=[p[1] for p in valid_u]
            d=trap_mean(xx,den); n=trap_mean(xx,num)
            u_weighted=n/d if d and d>0 else None
        cross=crossings(b)
        phase_stats=phase_velocity_means(b)
        u_line=trap_mean([p[0] for p in valid_u],[p[2] for p in valid_u]) if valid_u else None
        out.append({
          'caso':case,'tempo_s':time_s,'perfil':profile_name,'ramo':ib,
          'z_min_m':min(z),'z_max_m':max(z),
          'alpha_medio_linha':trap_mean(z,a),
          'z_interface_alpha05_m':cross[0] if cross else None,
          'numero_cruzamentos_alpha05':len(cross),
          'U1_media_ponderada_alpha_m_s':u_weighted,
          'U1_media_linha_m_s':u_line,
          **phase_stats,
          'n_pontos':len(b),
          'interpretacao_limite':'Perfil unidimensional amostrado; não representa área de seção.'
        })
    return out


def read_sampling_zips(root):
    rows=[]
    for zp in sorted(root.glob('M*_Q*_sampling.zip')):
      stem=zp.stem.replace('_sampling','')
      try: zf=zipfile.ZipFile(zp)
      except Exception: continue
      for name in zf.namelist():
        base=Path(name).name
        if base not in ('perfil_meio_alpha.oil_U.csv','perfil_saida_alpha.oil_U.csv'): continue
        parts=Path(name).parts
        ts=next((fnum(x) for x in reversed(parts[:-1]) if fnum(x) is not None),None)
        if ts is None: continue
        profile='meio' if 'meio' in base else 'saida'
        try: raw=zf.read(name)
        except Exception: continue
        rows.extend(parse_profile_csv(raw,stem,ts,profile))
    return rows


def parse_foam_data_text(text, vector_component=None):
    """Lê dados OpenFOAM; vector_component usa x=0, y=1, z=2."""
    out=[]
    for line in text.splitlines():
        s=line.strip()
        if not s or s.startswith('#'): continue
        nums=[float(x) for x in NUM.findall(s)]
        if len(nums)<2: continue
        t=nums[0]
        # Vetor: tempo + x + y + z. Sem componente solicitada, ignora vetores.
        if len(nums)>=4:
            if vector_component is None or vector_component not in (0,1,2):
                continue
            val=nums[1+vector_component]
        else:
            val=nums[1]
        if math.isfinite(t) and math.isfinite(val): out.append((t,val))
    return out


def scan_postprocessing_dir(case_dir, case_id):
    """Lê todos os arquivos de série do postProcessing, inclusive arquivos
    segmentados com sufixo de tempo. Registra arquivos vazios e conflitos.
    """
    rows = []
    inventory = []
    conflicts = []
    pp = case_dir / 'postProcessing'
    if not pp.exists():
        return rows, inventory, conflicts

    for fn in sorted(p for p in pp.iterdir() if p.is_dir()):
        metric = fn.name
        # QOleoMeio é weightedAreaIntegrate(U), vetor; eixo axial = Y.
        component = 1 if metric.lower().replace('_', '') == 'qoleomeio' else None

        patterns = (
            ('surfaceFieldValue', 'surfaceFieldValue*.dat', component),
            ('volFieldValue', 'volFieldValue*.dat', None),
        )
        for kind, pattern, vector_component in patterns:
            for dat in sorted(fn.glob(f'*/{pattern}')):
                try:
                    txt = dat.read_text(errors='replace')
                except Exception as exc:
                    inventory.append({
                        'caso': case_id, 'funcao': metric, 'tipo_arquivo': kind,
                        'arquivo': str(dat), 'status': 'erro_leitura',
                        'n_registros': 0, 'detalhe': str(exc)
                    })
                    continue

                parsed = parse_foam_data_text(txt, vector_component=vector_component)
                inventory.append({
                    'caso': case_id, 'funcao': metric, 'tipo_arquivo': kind,
                    'arquivo': str(dat),
                    'status': 'valido' if parsed else ('vazio' if not txt.strip() else 'sem_dados_parseaveis'),
                    'n_registros': len(parsed), 'detalhe': ''
                })

                for t, value in parsed:
                    rows.append({
                        'caso': case_id, 'funcao': metric, 'tempo_s': t,
                        'valor_bruto': value,
                        'componente': 'y' if vector_component == 1 else 'escalar',
                        'origem': str(dat)
                    })

    # Deduplica somente registros numericamente iguais da mesma função/tempo.
    # Se houver valores diferentes no mesmo instante, mantém ambos e registra conflito.
    grouped = defaultdict(list)
    for row in rows:
        key = (row['caso'], row['funcao'], row['componente'], row['tempo_s'])
        grouped[key].append(row)

    unique_rows = []
    for key, group in sorted(grouped.items()):
        values = [r['valor_bruto'] for r in group]
        reference = values[0]
        equal = all(math.isclose(v, reference, rel_tol=1e-10, abs_tol=1e-14)
                    for v in values[1:])
        if equal:
            kept = dict(group[0])
            kept['origem'] = ';'.join(sorted({r['origem'] for r in group}))
            unique_rows.append(kept)
        else:
            conflicts.append({
                'caso': key[0], 'funcao': key[1], 'componente': key[2],
                'tempo_s': key[3], 'valores_encontrados': ';'.join(map(str, values)),
                'arquivos_origem': ';'.join(r['origem'] for r in group),
                'acao': 'Valores conflitantes mantidos separadamente; revisar manualmente.'
            })
            unique_rows.extend(group)

    return unique_rows, inventory, conflicts


def scan_cases(root):
    rows, inventory, conflicts = [], [], []
    locations, duplicates = {}, []
    for cid in CASE_IDS:
        chosen, existing = case_locations(root, cid)
        locations[cid] = str(chosen) if chosen else ''
        if len(existing) > 1: duplicates.append(cid)
        if chosen is not None:
            cr, ci, cc = scan_postprocessing_dir(chosen, cid)
            rows.extend(cr); inventory.extend(ci); conflicts.extend(cc)
    return rows, locations, duplicates, inventory, conflicts


def read_sampling_case_dirs(root):
    """Lê perfis CSV de todos os casos, incluindo réplicas Q20/Q55."""
    rows, locations, duplicates = [], {}, []
    wanted = {'perfil_meio_alpha.oil_U.csv': 'meio',
              'perfil_saida_alpha.oil_U.csv': 'saida'}
    for cid in CASE_IDS:
        chosen, existing = case_locations(root, cid)
        locations[cid] = str(chosen) if chosen else ''
        if len(existing) > 1: duplicates.append(cid)
        if chosen is None: continue
        sampling = chosen / 'postProcessing' / 'sampling'
        if not sampling.exists(): continue
        for f in sampling.rglob('*.csv'):
            profile = wanted.get(f.name)
            ts = fnum(f.parent.name)
            if profile is None or ts is None: continue
            try: raw = f.read_bytes()
            except Exception: continue
            rows.extend(parse_profile_csv(raw, cid, ts, profile))
    return rows, locations, duplicates


def summarize_friction(rows, window):
    out = []
    t0, t1 = window
    metrics = ['tau_media_interna_Pa', 'tau_media_externa_Pa', 'tau_media_global_Pa',
               'area_ponderada_oleo_interna_m2', 'area_ponderada_oleo_externa_m2',
               'area_ponderada_oleo_total_m2', 'integral_tau_ponderada_interna_N',
               'integral_tau_ponderada_externa_N', 'integral_tau_ponderada_total_N',
               'fracao_molhada_interna_pct', 'fracao_molhada_externa_pct']
    groups = defaultdict(list)
    for r in rows:
        if r.get('tempo_s') is not None and t0 <= r['tempo_s'] <= t1:
            # case_id preserva R1/R2/R3; não agrega as três inicializações.
            groups[r.get('caso_id', f"{r['malha']}_{r['caso']}")].append(r)
    for cid, rs in sorted(groups.items()):
        meta = case_metadata(cid)
        row = {'caso_id': cid, 'malha': meta['malha'], 'vazao_nominal_L_min': meta['vazao_nominal_L_min'],
               'replica': meta['replica'], 'janela_s': f'{t0:g}-{t1:g}', 'n_amostras': len(rs)}
        for m in metrics:
            vals = [r[m] for r in rs if r.get(m) is not None]
            row[m+'_media_temporal'] = sum(vals)/len(vals) if vals else None
        out.append(row)
    return out


def summarize_profiles(rows, window):
    t0,t1=window; groups=defaultdict(list)
    for r in rows:
      if r.get('tempo_s') is not None and t0<=r['tempo_s']<=t1:
        groups[(r['caso'],r['perfil'],r['ramo'])].append(r)
    out=[]
    metrics=('z_interface_alpha05_m','h_interface_alpha05_mm','U1_media_linha_m_s',
             'U1_media_oleo_m_s','U1_media_ar_m_s','U1_media_interface_m_s',
             'U1_media_ponderada_alpha_m_s')
    for (case,profile,branch),rs in sorted(groups.items()):
      row={'caso':case,'perfil':profile,'ramo':branch,'janela_s':f'{t0:g}-{t1:g}',
           'n_tempos':len(set(x['tempo_s'] for x in rs))}
      for key in metrics:
        vals=[x[key] for x in rs if x.get(key) is not None]
        row[key+'_media_temporal']=sum(vals)/len(vals) if vals else None
        row[key+'_desvio_padrao_temporal']= (math.sqrt(sum((v-row[key+'_media_temporal'])**2 for v in vals)/len(vals)) if vals else None)
        row[key+'_amplitude_temporal']=max(vals)-min(vals) if vals else None
      crossings_n=sum(1 for x in rs if x.get('z_interface_alpha05_m') is not None)
      row['n_tempos_com_interface']=crossings_n
      row['cobertura_interface_pct']=100*crossings_n/row['n_tempos'] if row['n_tempos'] else None
      row['observacao']='Estatísticas temporais de amostras de linha; não representam média de seção.'
      out.append(row)
    return out


def read_optional_timeseries_csvs(root):
    """Lê séries externas opcionais para todos os 15 casos."""
    rows = []
    patterns = [('vazao_saida', 'QOleoOutlet'), ('QOleoOutlet', 'QOleoOutlet'),
                ('volume_oleo', 'volumeOleo'), ('volumeOleo', 'volumeOleo')]
    for cid in CASE_IDS:
        meta = case_metadata(cid)
        candidates = []
        for prefix, metric in patterns:
            candidates.extend([(root / f'{prefix}_{cid}.csv', metric),
                               (root / cid / f'{prefix}.csv', metric)])
            if meta['malha']:
                candidates.append((root / meta['malha'] / cid / f'{prefix}.csv', metric))
        for path, metric in candidates:
            if not path.exists(): continue
            try:
                with path.open(newline='', encoding='utf-8-sig') as f:
                    for r in csv.DictReader(f):
                        t = fnum(r.get('tempo_s') or r.get('time') or r.get('Time'))
                        if t is None: continue
                        keys = ('QOleoOutlet_m3_s', 'QOleoOutlet', 'vazao_m3_s',
                                'Q_m3_s', 'volume_m3', 'volIntegrate_alpha.oil', 'valor')
                        val = next((fnum(r[k]) for k in keys
                                    if k in r and fnum(r[k]) is not None), None)
                        if val is None:
                            val = next((fnum(v) for k, v in r.items()
                                        if k not in ('tempo_s', 'time', 'Time')
                                        and fnum(v) is not None), None)
                        if val is not None:
                            rows.append({'caso': cid, 'funcao': metric, 'tempo_s': t,
                                         'valor_bruto': val, 'origem': str(path),
                                         'valor_L_min': val*60000 if metric == 'QOleoOutlet' else None,
                                         'volume_m3': val if metric == 'volumeOleo' else None})
            except Exception:
                pass
            break
    return rows


def interpolate_series(series, t):
    """Interpola uma série escalar em t; não extrapola fora do intervalo."""
    pts=sorted((x,y) for x,y in series if x is not None and y is not None)
    if not pts: return None
    for tt,vv in pts:
        if abs(tt-t)<1e-9: return vv
    for (t0,v0),(t1,v1) in zip(pts,pts[1:]):
        if t0<=t<=t1 and t1>t0:
            return v0+(v1-v0)*(t-t0)/(t1-t0)
    return None


def compare_center_outlet(foam):
    """Compara QOleoMeio (principal) e QOleoOutlet (complementar), sem misturar sinais."""
    groups=defaultdict(lambda: defaultdict(list))
    for r in foam:
        name=r['funcao'].lower().replace('_','')
        if 'qoleomeio' in name:
            groups[r['caso']]['meio'].append((r['tempo_s'],r['valor_bruto']))
        elif 'qoleooutlet' in name:
            groups[r['caso']]['saida'].append((r['tempo_s'],r['valor_bruto']))
    out=[]
    for cid,series in sorted(groups.items()):
        meio=sorted(series['meio']); saida=series['saida']
        # O plano central define os instantes da tabela; saída é interpolada apenas
        # quando há amostras que delimitam o instante central.
        for t,qm in meio:
            qs=interpolate_series(saida,t)
            out.append({'caso':cid,'tempo_s':t,
                'QOleoMeio_principal_assinado_m3_s':qm,
                'QOleoMeio_L_min':qm*60000.0,
                'QOleoOutlet_complementar_assinado_m3_s':qs,
                'QOleoOutlet_L_min':qs*60000.0 if qs is not None else None,
                'diferenca_meio_menos_saida_L_min':(qm-qs)*60000.0 if qs is not None else None,
                'observacao':'Meio é a referência da região de interesse; saída é comparação. Valores assinados; verificar orientação da normal e weightedSum(phi).'})
    return out

def partial_balance_rows(foam):
    """Monta balanço temporal assinado, mantendo separadas as três contribuições.

    Convenção adotada para o diagnóstico:
      - phi positivo: fluxo saindo do domínio pela face do patch;
      - conservação: dV_oleo/dt + soma dos fluxos de fronteira assinados = 0.

    O resíduo é diagnóstico, não prova de conservação exata: weightedSum(phi)
    ponderado por alpha.oil é uma estimativa algébrica da vazão de óleo.
    """
    bycase=defaultdict(lambda: defaultdict(list))
    for r in foam:
        bycase[r['caso']][r['funcao'].lower().replace('_','')].append(
            (r['tempo_s'],r['valor_bruto'])
        )

    out=[]
    for cid,funcs in sorted(bycase.items()):
        flow=cid.split('_')[-1]
        qnom=NOMINAL_LMIN.get(flow)

        def find_key(token):
            return next((k for k in funcs if token in k),None)

        qout_key=find_key('qoleooutlet')
        qin_air_key=find_key('qoleoinletair')
        qin_oil_key=next((k for k in funcs if 'qoleoinlet' in k and 'qoleoinletair' not in k),None)
        vol_key=find_key('volumeoleo')

        # QOleoInletAir não pode ser confundido com QOleoInlet.
        if not any((qout_key,qin_air_key,qin_oil_key,vol_key)):
            continue

        def clean_series(key):
            if not key:
                return []
            # Remove tempos repetidos apenas quando os valores são iguais.
            grouped=defaultdict(list)
            for t,v in funcs[key]:
                grouped[t].append(v)
            result=[]
            for t,values in grouped.items():
                if all(math.isclose(v,values[0],rel_tol=1e-10,abs_tol=1e-14)
                       for v in values[1:]):
                    result.append((t,values[0]))
                else:
                    # Mantém o primeiro aqui; conflitos de origem já são
                    # reportados separadamente por scan_postprocessing_dir.
                    result.append((t,values[0]))
            return sorted(result)

        qout_series=clean_series(qout_key)
        qin_oil_series=clean_series(qin_oil_key)
        qin_air_series=clean_series(qin_air_key)
        vols=clean_series(vol_key)

        def vol_at(t):
            if len(vols)<2:
                return (None,None)
            for (t0,v0),(t1,v1) in zip(vols,vols[1:]):
                if t0<=t<=t1 and t1>t0:
                    frac=(t-t0)/(t1-t0)
                    return v0+frac*(v1-v0),(v1-v0)/(t1-t0)
            return (None,None)

        # Usa a união dos instantes de fluxo; cada série é interpolada sem extrapolar.
        times=sorted(set(
            [t for series in (qout_series,qin_oil_series,qin_air_series)
             for t,v in series]
        ))
        if not times:
            times=sorted(set(t for t,v in vols))

        for t in times:
            qout=interpolate_series(qout_series,t)
            qin_oil=interpolate_series(qin_oil_series,t)
            qin_air=interpolate_series(qin_air_series,t)
            vol,dv=vol_at(t)

            # Continuidade integral: dV/dt + sum(fluxos assinados para fora) = 0.
            boundary_sum = (
                (qin_oil if qin_oil is not None else 0.0)
                + (qin_air if qin_air is not None else 0.0)
                + (qout if qout is not None else 0.0)
            )
            complete = all(v is not None for v in (qin_oil,qin_air,qout,dv))
            residual = dv + boundary_sum if complete else None

            out.append({
                'caso':cid,
                'tempo_s':t,
                'Q_nominal_L_min':qnom,
                'QOleoInlet_assinado_m3_s':qin_oil,
                'QOleoInlet_assinado_L_min':qin_oil*60000 if qin_oil is not None else None,
                'QOleoInletAir_assinado_m3_s':qin_air,
                'QOleoInletAir_assinado_L_min':qin_air*60000 if qin_air is not None else None,
                'QOleoOutlet_assinado_m3_s':qout,
                'QOleoOutlet_assinado_L_min':qout*60000 if qout is not None else None,
                'volume_oleo_m3':vol,
                'dVoleo_dt_m3_s':dv,
                'dVoleo_dt_L_min_equivalente':dv*60000 if dv is not None else None,
                'soma_fluxos_fronteira_assinados_m3_s':boundary_sum,
                'residuo_balanco_assinado_m3_s':residual,
                'residuo_balanco_assinado_L_min':residual*60000 if residual is not None else None,
                'balanco_completo_no_tempo':complete,
                'observacao':(
                    'Diagnóstico: dV/dt + QOleoInlet + QOleoInletAir + QOleoOutlet, '
                    'com fluxos assinados e phi positivo para fora. '
                    'WeightedSum(phi) ponderado por alpha.oil é estimativa algébrica; '
                    'não equivale automaticamente ao fluxo geométrico exato da fase.'
                )
            })
    return out

def summarize_function_objects(foam, window):
    t0, t1 = window
    groups = defaultdict(list)
    for r in foam:
        t, v = r.get('tempo_s'), r.get('valor_bruto')
        if t is not None and v is not None and t0 <= t <= t1:
            groups[(r['caso'], r['funcao'])].append(v)
    out = []
    for (cid, func), vals in sorted(groups.items()):
        mean = sum(vals)/len(vals)
        sd = math.sqrt(sum((v-mean)**2 for v in vals)/len(vals))
        meta = case_metadata(cid)
        out.append({'caso': cid, 'malha': meta['malha'],
                    'vazao_nominal_L_min': meta['vazao_nominal_L_min'],
                    'replica': meta['replica'], 'funcao': func,
                    'janela_s': f'{t0:g}-{t1:g}', 'n_amostras': len(vals),
                    'media_temporal': mean, 'desvio_padrao_temporal': sd,
                    'CV_temporal_pct': 100*sd/abs(mean) if mean else None,
                    'minimo': min(vals), 'maximo': max(vals),
                    'amplitude': max(vals)-min(vals)})
    return out


def summarize_repeatability(foam, window):
    """CV entre médias de R1/R2/R3; informa quantas réplicas existem por função."""
    t0, t1 = window
    groups = defaultdict(lambda: defaultdict(list))
    for r in foam:
        meta = case_metadata(r['caso'])
        if meta['replica'] is None or meta['vazao_nominal_L_min'] not in (20.0, 55.0):
            continue
        t, v = r.get('tempo_s'), r.get('valor_bruto')
        if t is not None and v is not None and t0 <= t <= t1:
            groups[(meta['vazao_nominal_L_min'], r['funcao'])][meta['replica']].append(v)
    out = []
    for (qnom, func), reps in sorted(groups.items()):
        means = {rep: sum(v)/len(v) for rep, v in reps.items() if v}
        vals = list(means.values())
        mean = sum(vals)/len(vals) if vals else None
        sd = math.sqrt(sum((v-mean)**2 for v in vals)/len(vals)) if vals else None
        out.append({'vazao_nominal_L_min': qnom, 'funcao': func,
                    'janela_s': f'{t0:g}-{t1:g}', 'n_replicas_disponiveis': len(means),
                    'media_R1': means.get('R1'), 'media_R2': means.get('R2'),
                    'media_R3': means.get('R3'), 'media_entre_replicas': mean,
                    'desvio_padrao_entre_replicas': sd,
                    'CV_repetibilidade_pct': 100*sd/abs(mean) if mean else None,
                    'amplitude_entre_replicas': max(vals)-min(vals) if vals else None,
                    'replicas_incluidas': ';'.join(sorted(means))})
    return out


def summarize_profile_repeatability(profile_summary):
    groups = defaultdict(list)
    for r in profile_summary:
        meta = case_metadata(r['caso'])
        if meta['replica'] and meta['vazao_nominal_L_min'] in (20.0, 55.0):
            groups[(meta['vazao_nominal_L_min'], r['perfil'], r['ramo'])].append((meta['replica'], r))
    metrics = ['z_interface_alpha05_m_media_temporal', 'U1_media_linha_m_s_media_temporal',
               'U1_media_ponderada_alpha_m_s_media_temporal', 'U1_media_oleo_m_s_media_temporal',
               'U1_media_ar_m_s_media_temporal']
    out = []
    for (qnom, profile, branch), items in sorted(groups.items()):
        byrep = {rep: row for rep, row in items}
        for metric in metrics:
            vals = {rep: row.get(metric) for rep, row in byrep.items()
                    if row.get(metric) is not None}
            arr = list(vals.values())
            mean = sum(arr)/len(arr) if arr else None
            sd = math.sqrt(sum((v-mean)**2 for v in arr)/len(arr)) if arr else None
            out.append({'vazao_nominal_L_min': qnom, 'perfil': profile, 'ramo': branch,
                        'grandeza': metric, 'n_replicas_disponiveis': len(arr),
                        'media_R1': vals.get('R1'), 'media_R2': vals.get('R2'),
                        'media_R3': vals.get('R3'), 'media_entre_replicas': mean,
                        'desvio_padrao_entre_replicas': sd,
                        'CV_repetibilidade_pct': 100*sd/abs(mean) if mean else None,
                        'replicas_incluidas': ';'.join(sorted(vals))})
    return out


def summarize_friction_repeatability(friction_summary):
    metrics = [k for k in (friction_summary[0].keys() if friction_summary else [])
               if k.endswith('_media_temporal')]
    groups = defaultdict(list)
    for row in friction_summary:
        if row.get('replica') and row.get('vazao_nominal_L_min') in (20.0, 55.0):
            for metric in metrics:
                value = row.get(metric)
                if value is not None:
                    groups[(row['vazao_nominal_L_min'], metric)].append((row['replica'], value))
    out = []
    for (qnom, metric), items in sorted(groups.items()):
        vals = dict(items)
        arr = list(vals.values())
        mean = sum(arr)/len(arr) if arr else None
        sd = math.sqrt(sum((v-mean)**2 for v in arr)/len(arr)) if arr else None
        out.append({'vazao_nominal_L_min': qnom, 'grandeza': metric,
                    'n_replicas_disponiveis': len(arr), 'media_R1': vals.get('R1'),
                    'media_R2': vals.get('R2'), 'media_R3': vals.get('R3'),
                    'media_entre_replicas': mean, 'desvio_padrao_entre_replicas': sd,
                    'CV_repetibilidade_pct': 100*sd/abs(mean) if mean else None})
    return out


def main():
    ap=argparse.ArgumentParser(description='Consolida atrito, perfis e functionObjects sem alterar os casos.')
    ap.add_argument('--root',default='.',help='Pasta raiz contendo M0/, M1/, M2/, Q20/Q55 R1-R3, CSVs e ZIPs (padrão: .)')
    ap.add_argument('--out',default='resultados_consolidados',help='Pasta de saída')
    ap.add_argument('--tmin',type=float,default=3.0); ap.add_argument('--tmax',type=float,default=6.0)
    args=ap.parse_args(); root=Path(args.root).resolve(); out=Path(args.out).resolve()
    if args.tmax<=args.tmin: ap.error('--tmax precisa ser maior que --tmin')
    friction=read_friction(root)
    # Prioriza perfis nas pastas dos casos; ZIPs ficam como fallback.
    profiles,profile_locations,profile_duplicates=read_sampling_case_dirs(root)
    zip_profiles=read_sampling_zips(root)
    direct_cases={r['caso'] for r in profiles}
    profiles.extend(r for r in zip_profiles if r['caso'] not in direct_cases)
    foam,case_dirs,case_duplicates,pp_inventory,pp_conflicts=scan_cases(root)
    foam.extend(read_optional_timeseries_csvs(root))
    summary=summarize_friction(friction,(args.tmin,args.tmax))
    profile_summary=summarize_profiles(profiles,(args.tmin,args.tmax))
    partial_balance=partial_balance_rows(foam)
    center_outlet=compare_center_outlet(foam)
    function_summary=summarize_function_objects(foam,(args.tmin,args.tmax))
    repeatability=summarize_repeatability(foam,(args.tmin,args.tmax))
    profile_repeatability=summarize_profile_repeatability(profile_summary)
    friction_repeatability=summarize_friction_repeatability(summary)

    # Enriquecer functionObjects sem presumir convenção de sinal ou fase exata.
    qrows=[]
    for r in foam:
      fn=r['funcao'].lower(); val=r['valor_bruto']
      rr=dict(r)
      if 'qoleo' in fn or 'fluxo' in fn:
        rr['valor_L_min']=val*60000.0
        rr['nota']='Valor assinado do functionObject; conferir operação, weightField e orientação da normal.'
      if 'volume' in fn:
        rr['volume_m3']=val
      qrows.append(rr)

    write_csv(out/'atrito_temporal_casos.csv',friction)
    write_csv(out/'resumo_atrito_janela.csv',summary)
    write_csv(out/'perfis_interface_temporais.csv',profiles)
    write_csv(out/'velocidade_perfis_temporais.csv', profiles, fields=['caso','tempo_s','perfil','ramo','U1_media_linha_m_s','U1_media_ponderada_alpha_m_s','U1_media_oleo_m_s','U1_media_ar_m_s','U1_media_interface_m_s','comprimento_oleo_m','comprimento_ar_m','comprimento_interface_m'])
    write_csv(out/'resumo_perfis_janela.csv',profile_summary)
    write_csv(out/'estabilidade_interface_velocidade.csv',profile_summary)
    write_csv(out/'functionObjects_temporais.csv',qrows, fields=['caso','funcao','tempo_s','valor_bruto','valor_L_min','volume_m3','componente','origem','nota'])
    write_csv(out/'inventario_postProcessing.csv', pp_inventory)
    write_csv(out/'conflitos_postProcessing.csv', pp_conflicts, fields=['caso','funcao','componente','tempo_s','valores_encontrados','arquivos_origem','acao'])
    write_csv(out/'balanco_parcial_temporal.csv',partial_balance)
    write_csv(out/'comparacao_vazao_meio_saida.csv',center_outlet)
    write_csv(out/'resumo_temporal_por_caso_funcao.csv',function_summary)
    write_csv(out/'repetibilidade_Q20_Q55_R1_R2_R3.csv',repeatability)
    write_csv(out/'repetibilidade_perfis_Q20_Q55_R1_R2_R3.csv',profile_repeatability)
    write_csv(out/'repetibilidade_atrito_Q20_Q55_R1_R2_R3.csv',friction_repeatability)

    # Relatório de cobertura dos nove casos de malha e seis réplicas.
    coverage = []
    for cid in CASE_IDS:
        meta = case_metadata(cid)
        fs = [r for r in friction if r.get('caso_id') == cid]
        ps = [r for r in profiles if r['caso'] == cid]
        qs = [r for r in foam if r['caso'] == cid]
        funcs = sorted(set(r['funcao'] for r in qs))
        coverage.append({
            'caso': cid, 'malha': meta['malha'],
            'vazao_nominal_L_min': meta['vazao_nominal_L_min'],
            'replica': meta['replica'], 'pasta_caso_utilizada': case_dirs.get(cid, ''),
            'duplicidade_pastas_caso': cid in case_duplicates,
            'csv_atrito': bool(fs), 'n_atrito': len(fs),
            'perfis_encontrados': bool(ps), 'n_registros_perfis': len(ps),
            'postProcessing_encontrado': bool(qs),
            'functionObjects_encontrados': ';'.join(funcs),
            'tem_QOleoMeio': any('qoleomeio' in x.lower() for x in funcs),
            'tem_QOleoOutlet': any('qoleooutlet' in x.lower() for x in funcs),
            'tem_QOleoInletAir': any('qoleoinletair' in x.lower().replace('_', '') for x in funcs),
            'tem_volumeOleo': any('volumeoleo' in x.lower() for x in funcs)})
    write_csv(out/'cobertura_dados.csv', coverage)

    print(f'Raiz: {root}')
    print(f'Saída: {out}')
    print(f'Linhas atrito: {len(friction)}; registros de perfis: {len(profiles)}; functionObjects: {len(foam)}')
    if case_duplicates:
        print('AVISO: casos duplicados na raiz e em Mx/: '+', '.join(sorted(set(case_duplicates))))
        print('Foi usada a cópia da raiz; confira antes de interpretar os resultados.')
    print(f'Arquivos postProcessing inventariados: {len(pp_inventory)}; conflitos: {len(pp_conflicts)}')
    print('Arquivos gerados:')
    for p in sorted(out.glob('*.csv')): print(' -',p.name)
    print('\nATENÇÃO: vazão nominal, QOleoOutlet e dV/dt não foram somados em um resíduo automático.')
    print('QOleoMeio é a referência principal; QOleoOutlet é comparação complementar.')
    print('QOleoInletAir é tratado separadamente de QOleoInlet no balanço temporal.')
    print('Q20/Q55 R1-R3 são consolidados individualmente e comparados por repetibilidade.')
    print('Perfis são amostras de linha, não médias de seção nem áreas transversais.')

if __name__=='__main__': main()
