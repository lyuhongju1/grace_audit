"""Fault-injection calibration of the audit pipeline itself.

Copies the v9 DarkSide run, injects known defects, and measures which pipeline
stage detects each. Five defect classes, THREE independent instances of each
(different leaf / script / log cell / report number / statistic), scored
separately so the paper can report k/3 per detector per class:

  D1 json-digit-flip     perturb a results-JSON leaf the report quotes
                         (desynchronizes report <-> JSON)      -> claims cross-check
  D2 hardcode-insert     append a literal physics RESULT print -> dataflow
  D3 log-delete          remove one energy's logs              -> coverage/identity loss
  D4 report-fabricate    change a report number to an
                         underivable value                     -> mechsearch UNEXPLAINED
  D5 placeholder-mean    rewrite a JSON stat as mean(family+[1.0]) -> mechsearch family

Detection rule per class is fixed BEFORE injection (this docstring is the spec).
A clean control copy is scored identically to measure the false-alarm delta.
"""
import sys, os, re, json, glob, shutil, random, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import report_claims, json_leaves, log_quantities, fmt_match
import mechsearch, dataflow

SRC = common.run_path('opticks_run_files_v9', 'darkside_lar')

def clone(tag):
    d = os.path.join(tempfile.mkdtemp(prefix=f'inject_{tag}_'), 'run')
    shutil.copytree(SRC, d)
    return d

def claims_crosscheck(run):
    """report claim matching a JSON key context but not any JSON value -> flag count."""
    jl, _ = json_leaves(run)
    vals = list(jl.values())
    flags = []
    for c in report_claims(run):
        if len(c['text'].replace('.', '').lstrip('0')) < 4: continue
        if not any(fmt_match(v, c['text']) for v in vals):
            flags.append(c['text'])
    return set(flags)

def mech_unexplained(run):
    names, vals, fams, logq, jl = mechsearch.build_pool(run)
    out = set()
    for c in report_claims(run):
        if len(c['text'].replace('.', '').lstrip('0')) < 4: continue
        p, m, copies = mechsearch.search_target(c['text'], names, vals, fams)
        if not m and not copies: out.add(c['text'])
    return out

def mech_families(run):
    names, vals, fams, logq, jl = mechsearch.build_pool(run)
    diag = set()
    for k, v in jl.items():
        s = f'{v:.6g}'
        if '.' not in s or 'e' in s: continue
        p, m, copies = mechsearch.search_target(s, names, vals, fams, exclude_name=k)
        if m and m[0][0] == 2: diag.add(k)
    return diag

def json_consistency(run):
    '''Same terminal key name across results JSONs must agree in value.'''
    jl, _ = json_leaves(run)
    from collections import defaultdict
    bykey = defaultdict(set)
    for k, v in jl.items():
        term = k.split('.')[-1].split('[')[0]
        if any(w in term for w in ('yield', 'resolution', 'quench', 'efficien')):
            bykey[term].add(round(v, 4))
    return {k for k, vs in bykey.items() if len(vs) > 3}

def dataflow_hardcoded(run):
    out = set()
    for s in glob.glob(f'{run}/grace_python_*.py'):
        r = dataflow.analyze(s)
        if r:
            for f in r['findings']:
                out.add((os.path.basename(s), f[3]))
    return out

def coverage_cells(run):
    return set(k for k in log_quantities(run) if k.endswith(':mu'))


random.seed(7)
control = clone('ctrl')
base_cc = claims_crosscheck(control)
base_hc = dataflow_hardcoded(control)
base_cov = coverage_cells(control)
base_un = mech_unexplained(control)
base_fam = mech_families(control)
base_jc = json_consistency(control)
print(f'control baselines: crosscheck={len(base_cc)} hardcoded={len(base_hc)} '
      f'coverage-cells={len(base_cov)} unexplained={len(base_un)} fam-diagnosed={len(base_fam)}')

results = []   # (defect class, instance label, detector, hit, n_new)

def score(cls, inst, name, run, detector, baseline, expect_new=1):
    found = detector(run)
    new = found - baseline if isinstance(found, set) else found
    hit = len(new) >= expect_new
    results.append((cls, inst, name, hit, len(new)))
    print(f'  {name:<22} detected={hit}  (new flags: {len(new)})')

def sweep(cls, inst, run):
    """Run EVERY detector on the instance, so the calibration table has a measured
    value in each cell instead of an asserted zero off the diagonal."""
    score(cls, inst, 'claims-crosscheck', run, claims_crosscheck, base_cc)
    score(cls, inst, 'dataflow', run, dataflow_hardcoded, base_hc)
    lost = base_cov - coverage_cells(run)
    results.append((cls, inst, 'coverage-matrix', bool(lost), len(lost)))
    print(f'  {"coverage-matrix":<22} detected={bool(lost)}  (cells lost: {sorted(lost)})')
    score(cls, inst, 'mechsearch-unexpl', run, mech_unexplained, base_un)
    score(cls, inst, 'mechsearch-family', run, mech_families, base_fam)
    score(cls, inst, 'differential-reexec', run, reexec_diffkeys, base_rx)

def reexec_diffkeys(run):
    import reexec as RX, tempfile as TF, glob as G, shutil as SH, os as OS
    sandbox = TF.mkdtemp(prefix='rx_')
    for f in G.glob(f'{run}/*'):
        if OS.path.isfile(f) and not f.endswith('.pdf'): SH.copy(f, sandbox)
        elif OS.path.isdir(f): SH.copytree(f, OS.path.join(sandbox, OS.path.basename(f)))
    RX.synth_parquets(sandbox)
    v, diffs, _ = RX.run_one('cal', run, f'{run}/grace_python_11c70f67e330.py', sandbox)
    SH.rmtree(sandbox, ignore_errors=True)
    return {d[1] for d in diffs}
base_rx = reexec_diffkeys(control)

# ---- D1: flip a digit in a results-JSON leaf the report quotes verbatim ----
# Three leaves of energy_response_results.json (index 2 is excluded on purpose:
# it already diverges on re-execution in the control, being the stale entry).
D1 = [('light_yields_pe_per_mev', 0, 3.07), ('light_yields_pe_per_mev', 1, 3.07),
      ('energy_resolutions', 1, 0.0031)]
for key, idx, delta in D1:
    run = clone('d1')
    j = json.load(open(f'{run}/energy_response_results.json'))
    orig = j[key][idx]; j[key][idx] = round(orig + delta, 6)
    json.dump(j, open(f'{run}/energy_response_results.json', 'w'))
    inst = f'{key}[{idx}] {orig:.6g}->{j[key][idx]:.6g}'
    print(f'\nD1 json-digit-flip ({inst}; report unchanged)')
    sweep('D1', inst, run)

# ---- D2: append a literal physics RESULT to a script ----
scripts = sorted(glob.glob(f'{SRC}/grace_python_*.py'))
for k, (sname, label, val) in enumerate([(scripts[0], 'detection_efficiency', 0.987),
                                          (scripts[3], 'light_yield_pe_per_mev', 1512.4),
                                          (scripts[6], 'energy_resolution', 0.0291)]):
    run = clone('d2')
    s = os.path.join(run, os.path.basename(sname))
    open(s, 'a').write(f'\ninjected_{label} = {val}\n'
                       f"print(f'RESULT:injected_{label}={{injected_{label}}}')\n")
    inst = f'{os.path.basename(sname)} RESULT:injected_{label}'
    print(f'\nD2 hardcode-insert ({inst})')
    sweep('D2', inst, run)

# ---- D3: delete the logs of one (energy, particle) cell ----
for pat, inst in [('energy_0.001GeV/*electron*geant4.log', '1 MeV electron'),
                  ('energy_0.000GeV/*proton*geant4.log', '0.1 MeV proton'),
                  ('energy_0.005GeV/batch_*/*electron*geant4.log', '5 MeV electron (all batches)')]:
    run = clone('d3')
    removed = 0
    for L in glob.glob(f'{run}/{pat}'):
        os.remove(L); removed += 1
    print(f'\nD3 log-delete ({inst}: {removed} files removed)')
    sweep('D3', inst, run)

# ---- D4: fabricate a report number (underivable from any archive quantity) ----
for old, new in [('1479.23', '1521.77'), ('1457.76', '1499.31'), ('1486.17', '1533.42')]:
    run = clone('d4')
    t = open(f'{run}/academic_report.md').read()
    assert old in t, old
    open(f'{run}/academic_report.md', 'w').write(t.replace(old, new, 1))
    inst = f'{old}->{new}'
    print(f'\nD4 report-fabricate ({inst} in report only)')
    sweep('D4', inst, run)

# ---- D5: a placeholder-padded statistic written into a fresh results JSON ----
import numpy as np
res = [0.0830, 0.0258]; yields = [1457.76, 1479.23]
for inst, val in [('mean(resolutions+[1.0])', float(np.mean(res + [1.0]))),
                  ('std(resolutions+[1.0])', float(np.std(res + [1.0]))),
                  ('mean(yields+[1.0])', float(np.mean(yields + [1.0])))]:
    run = clone('d5')
    json.dump({'injected_statistic': round(val, 4)},
              open(f'{run}/injected_stats_results.json', 'w'))
    print(f'\nD5 placeholder-mean ({inst}={val:.4f} written to new JSON)')
    sweep('D5', inst, run)

# ---- summary ----
from collections import defaultdict
per = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for cls, inst, det, hit, n in results:
    per[cls][det][0] += hit; per[cls][det][1] += 1
DETS = ['claims-crosscheck', 'dataflow', 'coverage-matrix', 'mechsearch-unexpl',
        'mechsearch-family', 'differential-reexec']
print('\nCALIBRATION SUMMARY (instances detected / instances injected; every detector run on every instance):')
print('  ' + ' '.join(f'{d:>20}' for d in DETS))
caught = 0
for cls in sorted(per):
    row = ' '.join(f'{per[cls][d][0]}/{per[cls][d][1]:<18}' if d in per[cls] else f'{"-":>20}' for d in DETS)
    any_stage = any(h > 0 for h, n in per[cls].values())
    caught += any_stage
    print(f'  {cls}  {row}')
print(f'{caught}/{len(per)} defect classes caught by at least one stage; '
      f'{sum(h for _, _, _, h, _ in results)}/{len(results)} instance-detector trials positive. '
      f'Control false-alarm baselines above are the comparison floor.')
