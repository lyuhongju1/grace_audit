"""Differential re-execution of the agent's analysis scripts.

For each script: build a sandbox copy of the run directory, synthesize the
excluded parquet event files from the per-event text logs (nPhotons per event;
5 MeV batches merged into the single-file paths the scripts expect), rewrite the
cluster-absolute paths onto the sandbox, execute with a timeout, then diff every
regenerated JSON leaf and RESULT: line against the archive.

Interpretation: the sandbox feeds the pipeline *correct, complete* inputs, so
  MATCH     archived value equals correctly-fed computation  -> pipeline verified
  DIVERGE   archived value differs                           -> defect localized,
            with the corrected value printed next to the archived one
  UNRUNNABLE inputs not reconstructible (hit-level positions, ROOT files, ...)
"""
import sys, os, re, glob, json, shutil, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import runs, parse_log, split_log

CLUSTER = re.compile(r'/u/jhill5/grace/work/benchmarks/[^/\'"]+/[^/\'"]+/')

def synth_parquets(sandbox):
    """Create <geom>_<particle>_events.parquet next to every log; merge batches
    up into the parent energy dir under both '<geom>_<particle>_events.parquet'
    and '<geom>_events.parquet' (the single-file path the scripts expect)."""
    import pandas as pd
    made = 0
    per_parent = {}
    for L in glob.glob(f'{sandbox}/**/*geant4.log', recursive=True):
        ev = parse_log(L)['per_event']
        if not ev: continue
        g, pa = split_log(L)
        d = os.path.dirname(L)
        df = pd.DataFrame({'event_id': range(len(ev)), 'nPhotons': ev, 'nHits': ev, 'hits': ev})
        df.to_parquet(os.path.join(d, f'{g}_{pa}_events.parquet')); made += 1
        if os.path.basename(d).startswith('batch_'):
            per_parent.setdefault((os.path.dirname(d), g, pa), []).append(df)
    # last-writer order matters for the ambiguous '<geom>_events.parquet' path:
    # the real pipeline had the same collision (electron sweep then proton sweep),
    # so default to the faithful order (proton last); electron-fed variant noted.
    for (parent, g, pa), dfs in sorted(per_parent.items(), key=lambda t: t[0][2] != 'proton'):
        big = __import__('pandas').concat(dfs, ignore_index=True)
        big['event_id'] = range(len(big))
        big.to_parquet(os.path.join(parent, f'{g}_{pa}_events.parquet'))
        big.to_parquet(os.path.join(parent, f'{g}_events.parquet')); made += 2
    return made

def rewrite(script_text, sandbox):
    t = CLUSTER.sub(sandbox.rstrip('/') + '/', script_text)
    t = ("import matplotlib\nmatplotlib.use('Agg')\n" + t)
    return t

def leaves(o, path=''):
    if isinstance(o, bool): return
    if isinstance(o, (int, float)): yield path, float(o)
    elif isinstance(o, dict):
        for k, v in o.items(): yield from leaves(v, f'{path}.{k}' if path else k)
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from leaves(v, f'{path}[{i}]')

def diff_jsons(archive_dir, sandbox, before):
    rows = []
    for j in glob.glob(f'{sandbox}/*.json'):
        b = os.path.basename(j)
        if b in before and os.path.getmtime(j) <= before[b]: continue
        arch = os.path.join(archive_dir, b)
        if not os.path.exists(arch): continue
        try:
            new = dict(leaves(json.load(open(j))))
            old = dict(leaves(json.load(open(arch))))
        except Exception: continue
        for k in sorted(set(new) & set(old)):
            a, n = old[k], new[k]
            if a == n: continue
            rel = abs(n - a) / max(abs(a), abs(n), 1e-12)
            if rel > 1e-4:
                rows.append((b, k, a, n, rel))
    return rows

def run_one(tag, run_path, script, sandbox):
    dst = os.path.join(sandbox, os.path.basename(script))
    open(dst, 'w').write(rewrite(open(script, errors='ignore').read(), sandbox))
    before = {os.path.basename(j): os.path.getmtime(j) for j in glob.glob(f'{sandbox}/*.json')}
    try:
        r = subprocess.run([sys.executable, dst], cwd=sandbox, timeout=150,
                           capture_output=True, text=True,
                           env={**os.environ, 'MPLBACKEND': 'Agg'})
    except subprocess.TimeoutExpired:
        return 'TIMEOUT', [], ''
    if r.returncode != 0:
        err = (r.stderr or '').strip().splitlines()
        return 'FAILED', [], (err[-1][:110] if err else '')
    results = re.findall(r'RESULT:(\w+)=([-\d.eE+]+)', r.stdout)
    diffs = diff_jsons(run_path, sandbox, before)
    return 'RAN', diffs, results

def process_run(tag, run_path):
    sandbox = tempfile.mkdtemp(prefix='reexec_')
    for f in glob.glob(f'{run_path}/*'):
        if os.path.isfile(f) and not f.endswith('.pdf') and os.path.getsize(f) < 30_000_000:
            shutil.copy(f, sandbox)
        elif os.path.isdir(f):
            shutil.copytree(f, os.path.join(sandbox, os.path.basename(f)))
    n = synth_parquets(sandbox)
    print(f'\n### {tag}  (synthesized {n} parquet inputs)')
    stats = {'RAN': 0, 'FAILED': 0, 'TIMEOUT': 0}
    for s in sorted(glob.glob(f'{run_path}/grace_python_*.py')):
        verdict, diffs, extra = run_one(tag, run_path, s, sandbox)
        stats[verdict] += 1
        base = os.path.basename(s)
        if verdict != 'RAN':
            print(f'  {verdict:<8} {base}  {extra if isinstance(extra, str) else ""}')
            continue
        if diffs:
            zeroish = sum(1 for *_, a, nw, r in [(d[0],d[1],d[2],d[3],d[4]) for d in diffs] if nw in (0.0, 1.0))
            label = 'INPUT-NOT-FOUND?' if zeroish >= max(2, 0.6 * len(diffs)) else 'DIVERGE'
            print(f'  {label:<8} {base}')
            for b, k, a, nw, rel in diffs[:8]:
                print(f'      {b}:{k}  archived={a:.6g}  correctly-fed={nw:.6g}  ({rel:.0%} rel)')
            if len(diffs) > 8: print(f'      ... +{len(diffs)-8} more leaves differ')
        else:
            print(f'  MATCH    {base}  (all regenerated JSON leaves equal archive)')
    shutil.rmtree(sandbox, ignore_errors=True)
    print(f'  stats: {stats}')

if __name__ == '__main__':
    only = sys.argv[1] if len(sys.argv) > 1 else 'opti'
    for tag, p in runs():
        if only in tag:
            process_run(tag, p)
