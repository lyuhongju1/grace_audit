"""Closing the 1486.17 question by exhaustion.

The archived index-2 leaves of energy_response_results.json overdetermine the
moments of whatever file was analyzed:
    resolution_err = resolution / sqrt(2n)   ->  n
    light_yield    = mean / 5                ->  mean
    resolution     = std / mean              ->  std
    light_yield_err= std / (sqrt(n)*5)       ->  consistency check
Hypothesis space (sequential batch writes / partial merge / collision):
    every subset of electron batches, every subset of proton batches,
    every event-level prefix and suffix of each stream in batch order,
    plus each stream's full data. A hit must reproduce ALL FOUR leaves.
"""
import glob, json, math, itertools, re, sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import parse_log, run_path

RUN = run_path('opticks_run_files_v9', 'darkside_lar')
j = json.load(open(f'{RUN}/energy_response_results.json'))
Y, YE, R, RE = (j['light_yields_pe_per_mev'][2], j['light_yield_errors'][2],
                j['energy_resolutions'][2], j['resolution_errors'][2])
n_implied = round((R / RE) ** 2 / 2)
mean_implied = Y * 5.0
std_implied = R * mean_implied
print(f'archived leaves imply: n={n_implied}  mean={mean_implied:.4f}  std={std_implied:.4f}')
print(f'consistency: yield_err from (n,std) = {std_implied/(math.sqrt(n_implied)*5):.10f}  vs archived {YE:.10f}')

def moments(ev):
    n = len(ev); m = sum(ev) / n
    v = sum((x - m) ** 2 for x in ev) / n
    return n, m, math.sqrt(v)

def stats_match(ev, tol=5e-4):
    n, m, s = moments(ev)
    return (abs(m / 5 - Y) / Y < tol and abs(s / m - R) / R < tol and
            abs(s / (math.sqrt(n) * 5) - YE) / YE < tol)

for particle in ('electron', 'proton'):
    batches = []
    for b in sorted(glob.glob(f'{RUN}/energy_0.005GeV/batch_*')):
        for L in sorted(glob.glob(f'{b}/*{particle}*geant4.log')):
            ev = parse_log(L)['per_event']
            if ev: batches.append((b.split('/')[-1], ev))
    if not batches: continue
    allev = [x for _, ev in batches for x in ev]
    n, m, s = moments(allev)
    print(f'\n{particle}: {len(batches)} batches, total n={n}  mean={m:.2f}  std={s:.2f}  '
          f'(archive needs mean {mean_implied:.1f})')
    for name, ev in batches:
        bn, bm, bs = moments(ev)
        print(f'  {name}: n={bn} mean={bm:.2f} std={bs:.2f}')
    hits = []
    idx = range(len(batches))
    for r in range(1, len(batches) + 1):
        for combo in itertools.combinations(idx, r):
            ev = [x for i in combo for x in batches[i][1]]
            if stats_match(ev): hits.append(('subset', combo, moments(ev)))
    # event-level prefixes and suffixes of the concatenated stream
    run_m = 0.0; run_s2 = 0.0
    for k in range(1, len(allev) + 1):
        x = allev[k - 1]; d = x - run_m
        run_m += d / k; run_s2 += d * (x - run_m)
        if k >= 100:
            mm = run_m; ss = math.sqrt(run_s2 / k)
            if (abs(mm / 5 - Y) / Y < 5e-4 and abs(ss / mm - R) / R < 5e-4):
                hits.append(('event-prefix', k, (k, mm, ss)))
    for k in range(100, len(allev)):
        ev = allev[-k:]
        # cheap check on mean first
        if abs(sum(ev) / k / 5 - Y) / Y < 2e-3 and stats_match(ev):
            hits.append(('event-suffix', k, moments(ev)))
    print(f'  -> {len(hits)} hypothesis matches' + (f': {hits}' if hits else '  (space exhausted, no match)'))

print('\n=== does ANY archived dataset in the run have mean PE ~7430 at any energy? ===')
for L in sorted(glob.glob(f'{RUN}/**/*geant4.log', recursive=True)):
    ev = parse_log(L)['per_event']
    if ev:
        n, m, s = moments(ev)
        if abs(m - mean_implied) / mean_implied < 0.05:
            print(f'  CANDIDATE {L.split("darkside_lar")[-1][:70]}  n={n} mean={m:.1f}')
print('(no line above = no archived log matches the implied moments)')
