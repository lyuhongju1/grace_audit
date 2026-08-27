"""Automated mechanism search.

For each target number (report claim or results-JSON leaf), search a bounded
formula grammar over the run's quantity pool and accept only formulas that
reproduce the target to all printed digits. Report every match with a
simplicity rank and the total multiplicity, so a unique complex match is
distinguishable from combinatorial noise.

Grammar (rank = complexity):
  1  identity            v
  2  family mean/std     mean(F), std(F), mean(F+[1.0]), std(F+[1.0])
  3  ratio               a/b
  4  scaled ratio        a/b/E, a/b*E   for E in MEV_SCALES (unit-loss class)
  5  percent/diff        a/b*100, (a-b)/b*100, a-b, a*(1+b/100)

The last rank-5 form (a value scaled by a percentage) is the mechanism by which
the DarkSide-v9 comparison script derives its optimized yield
(1474.39 * (1 + 204.62/100) = 4491.2868); it was absent from the grammar in the
first release, which left that leaf UNEXPLAINED and led to a mis-diagnosis.

Decoy null calibration is seeded per target (SEED below), so null-FP rates are
reproducible run to run; N_DECOYS sets the granularity (100 -> 1%).
"""
import sys, math, json, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (runs, log_quantities, json_leaves, report_claims,
                    decimals, fmt_match)

MEV_SCALES = [0.1, 1.0, 2.0, 5.0]
MAX_MATCHES_SHOWN = 3
MAX_MULTIPLICITY = 5      # above this, matches are chance-level -> AMBIGUOUS
SEED = 20260811           # decoy RNG seed (per-target stream derived from it)
N_DECOYS = int(os.environ.get('AUDIT_DECOYS', '100'))
PCT_RULE = os.environ.get('AUDIT_PCT_RULE', '1') != '0'   # a*(1+b/100) grammar rule
NOISE_PATH = __import__('re').compile(r'pmt_positions|positions\.[xyz]|\.[xyz]\[')

def sigfigs(s):
    return len(s.replace('.', '').replace('-', '').lstrip('0'))

def log_ratio_families(logq):
    import re as _re
    from collections import defaultdict as _dd
    mus = _dd(dict)
    for k, v in logq.items():
        m = _re.match(r'log:(.+)/(\w+|-?\w+)/([\d.]+|None):mu$', k)
        if m: mus[(m.group(1), m.group(3))][m.group(2)] = v
    fams = _dd(list)
    for (g, en), d in sorted(mus.items()):
        for pa, v in d.items():
            if pa != 'electron' and 'electron' in d and d['electron'] > 0:
                fams[f'logfam:{g}:{pa}/electron_ratio'].append(v / d['electron'])
    return {k: v for k, v in fams.items() if len(v) >= 2}

def build_pool(run_path):
    logq = log_quantities(run_path)
    jl, fams = json_leaves(run_path)
    fams.update(log_ratio_families(logq))
    pool = dict(logq); pool.update(jl)
    names = list(pool); vals = np.array([pool[n] for n in names], float)
    ok = np.isfinite(vals) & (np.abs(vals) > 1e-12) & (np.abs(vals) < 1e12)
    names = [n for n, k in zip(names, ok) if k]; vals = vals[ok]
    keep = [not NOISE_PATH.search(n) for n in names]
    names = [n for n, k in zip(names, keep) if k]; vals = vals[keep]
    # dedupe by 10-sig-fig value, keep LOG-provenance name when available
    seen = {}
    for n, v in sorted(zip(names, vals), key=lambda t: not t[0].startswith('log:')):
        seen.setdefault(f'{v:.10g}', (n, v))
    names = [n for n, _ in seen.values()]
    vals = np.array([v for _, v in seen.values()])
    return names, vals, fams, logq, jl

def search_target(text, names, vals, fams, exclude_name=None):
    p = decimals(text); tgt = float(text)
    matches = []
    def rec(rank, desc, v):
        if fmt_match(v, text): matches.append((rank, desc))
    # r1 identity: LOG names count as provenance; JSON names only as 'copy' notes
    copies = []
    for n, v in zip(names, vals):
        if n == exclude_name: continue
        if fmt_match(v, text):
            if n.startswith('log:'): matches.append((1, n))
            else: copies.append(n)
    # r2 family mean/std (with fallback-1.0 variants)
    for fn, F in fams.items():
        variants = [('', F), ('+[1.0]', F + [1.0])]
        if len(F) >= 3:
            for i in range(len(F)):
                variants.append((f'drop[{i}]+[1.0]', F[:i] + F[i+1:] + [1.0]))
        for tag, G in variants:
            m = float(np.mean(G)); rec(2, f'mean({fn}{tag})', m)
            rec(2, f'std({fn}{tag})', float(np.sqrt(np.mean((np.array(G) - m) ** 2))))
    if matches:  # log-identity or family mean/std found; don't dredge deeper
        return p, sorted(matches), copies
    if copies:   # verbatim copy of a results-JSON leaf is the minimal explanation
        return p, [], copies
    if sigfigs(text) < 4:  # pair formulas are unfalsifiable at low precision
        return p, [], copies
    # vectorized pair formulas
    lo = tgt - 0.5 * 10 ** -p if p else tgt - 0.5
    hi = tgt + 0.5 * 10 ** -p if p else tgt + 0.5
    # the target's own leaf must not feed the pair formulas (a/b with b=1,
    # a-b with tiny b, ... are self-matches); first release only excluded it
    # from the identity pass, which inflated multiplicity on JSON-leaf targets
    if exclude_name is not None and exclude_name in names:
        keep = [n != exclude_name for n in names]
        names = [n for n, k in zip(names, keep) if k]; vals = vals[keep]
    V = vals; n = len(V)
    R = V[:, None] / V[None, :]                       # a/b
    cand = [(3, 'a/b', R)]
    for E in MEV_SCALES:
        cand.append((4, f'a/b/{E}', R / E)); cand.append((4, f'a/b*{E}', R * E))
    cand.append((5, 'a/b*100', R * 100))
    cand.append((5, '(a-b)/b*100', (R - 1) * 100))
    cand.append((5, 'a-b', V[:, None] - V[None, :]))
    if PCT_RULE:
        cand.append((5, 'a*(1+b/100)', V[:, None] * (1 + V[None, :] / 100)))
    for rank, form, M in cand:
        ii, jj = np.where((M >= lo) & (M <= hi))
        for i, j in zip(ii[:200], jj[:200]):
            if i == j: continue
            if fmt_match(float(M[i, j]), text):
                matches.append((rank, f'{form}  a={names[i]}  b={names[j]}'))
    return p, sorted(matches), copies

def null_rate(text, names, vals, fams, n_decoys=None):
    '''False-diagnosis calibration: same search on jittered decoys of equal precision.
    Deterministic: the decoy stream is seeded from (SEED, target text).'''
    import random
    n_decoys = n_decoys or N_DECOYS
    rng = random.Random(f'{SEED}|{text}')
    tgt = float(text); p = decimals(text); hits = 0
    for k in range(n_decoys):
        d = tgt * (1 + rng.uniform(0.004, 0.05) * rng.choice([-1, 1]))
        dt = f'{d:.{p}f}'
        if float(dt) == tgt: continue
        _, m, _ = search_target(dt, names, vals, fams)
        hits += bool(m)
    return hits / n_decoys

def joint_null(mean_text, std_text, names, vals, fams, n_decoys=None):
    """Direct joint calibration for a corroborated pair: jitter the reported mean
    and std independently (equal precision) and count decoy pairs for which the
    SAME family variant explains both. Replaces the independence assumption
    behind the product of marginal rates."""
    import random, re as _re
    n_decoys = n_decoys or N_DECOYS
    rng = random.Random(f'{SEED}|{mean_text}|{std_text}')
    hits = 0
    def variants(text, kind):
        _, m, _ = search_target(text, names, vals, fams)
        return {d.split('(', 1)[1] for r, d in m if r == 2 and d.startswith(kind + '(')}
    for k in range(n_decoys):
        dm = float(mean_text) * (1 + rng.uniform(0.004, 0.05) * rng.choice([-1, 1]))
        ds = float(std_text) * (1 + rng.uniform(0.004, 0.05) * rng.choice([-1, 1]))
        tm = f'{dm:.{decimals(mean_text)}f}'; ts = f'{ds:.{decimals(std_text)}f}'
        if float(tm) == float(mean_text) or float(ts) == float(std_text): continue
        if variants(tm, 'mean') & variants(ts, 'std'): hits += 1
    return hits / n_decoys

def run_search(run_tag, run_path, targets):
    names, vals, fams, logq, jl = build_pool(run_path)
    print(f'\n### {run_tag}: pool={len(vals)} quantities '
          f'({sum(n.startswith("log:") for n in names)} log-derived), '
          f'{len(fams)} families, {len(targets)} targets')
    n_ident = n_expl = n_unex = 0
    n_copy = 0
    for t in targets:
        p, m, copies = search_target(t['text'], names, vals, fams, t.get('exclude'))
        if m and m[0][0] == 1: n_ident += 1; t['verdict'] = ('LOG-VERIFIED', m[0][1]); continue
        if m and len(m) > MAX_MULTIPLICITY:
            n_unex += 1; t['verdict'] = ('AMBIGUOUS', len(m)); continue
        if m:
            fp = null_rate(t['text'], names, vals, fams) if m[0][0] >= 2 else 0.0
            n_expl += 1
            t['verdict'] = ('DIAGNOSED', m[:MAX_MATCHES_SHOWN], len(m), fp)
            print(f"  [{t['id']}] {t['text']}  null-FP={fp:.0%}  ({t.get('ctx','')[:52]})")
            for rank, d in m[:MAX_MATCHES_SHOWN]:
                print(f'        r{rank}: {d}')
            if len(m) > MAX_MATCHES_SHOWN:
                print(f'        ... multiplicity={len(m)}')
        elif copies:
            n_copy += 1; t['verdict'] = ('COPY', copies[0])
        else:
            n_unex += 1; t['verdict'] = ('UNEXPLAINED',)
    # corroboration pass: mean(X) and std(X) of the same variant matching two targets
    fam_hits = {}
    for t in targets:
        v = t.get('verdict', ())
        if v and v[0] == 'DIAGNOSED':
            for rank, d in v[1]:
                if rank == 2 and (d.startswith('mean(') or d.startswith('std(')):
                    kind, expr = d.split('(', 1)
                    fam_hits.setdefault(expr, {}).setdefault(kind, []).append(t)
    for expr, kinds in fam_hits.items():
        if 'mean' in kinds and 'std' in kinds:
            fps = []
            for kind in ('mean', 'std'):
                for t in kinds[kind]:
                    t['verdict'] = ('CORROBORATED',) + t['verdict'][1:]
                    fps.append(t['verdict'][3])
            joint = 1.0
            for f in fps[:2]: joint *= max(f, 0.01)
            measured = joint_null(kinds['mean'][0]['text'], kinds['std'][0]['text'],
                                  names, vals, fams)
            print(f'  CORROBORATED family: {expr[:80]}  joint-null<={joint:.1%} '
                  f'(product of marginals)  measured joint-null={measured:.1%}')
            for kind in ('mean', 'std'):
                for t in kinds[kind]:
                    print(f"      {kind}: [{t['id']}] {t['text']}  ({t.get('ctx','')[:48]})")
    # table-row consistency: rows fully unexplained inside mostly-verified tables
    rp = os.path.join(run_path, 'academic_report.md')
    lines = open(rp, errors='ignore').read().splitlines() if os.path.exists(rp) else []
    bytext = {}
    for t in targets:
        if t['id'].startswith('R'): bytext.setdefault(t['text'], []).append(t)
    import re as _re
    for ln in lines:
        if not ln.strip().startswith('|') or '---' in ln: continue
        nums_in = [m.replace(',', '') for m in _re.findall(r'\d+\.\d+', ln)]
        hp = [s for s in nums_in if sigfigs(s) >= 4]
        if len(hp) < 2: continue
        ver = sum(any(t.get('verdict', ('',))[0] in ('LOG-VERIFIED', 'COPY')
                      for t in bytext.get(s, [])) for s in hp)
        if ver == 0:
            print(f'  TABLE-ROW UNSOURCED ({len(hp)} high-precision cells, 0 verified): {ln.strip()[:96]}')
    print(f'  summary: {n_ident} log-verified, {n_copy} json-copies, {n_expl} diagnosed-by-formula, {n_unex} unexplained/ambiguous')
    return targets

if __name__ == '__main__':
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for tag, p in runs():
        if only and only not in tag: continue
        # targets = report claims + results-JSON leaves that are not log-identities
        targets = report_claims(p)
        jl, _ = json_leaves(p)
        for k, v in jl.items():
            s = f'{v:.6g}'
            if '.' in s and 'e' not in s and abs(v) not in (0.0, 1.0):
                targets.append({'id': 'J:' + k.split(':', 1)[1][:60], 'text': s,
                                'ctx': k, 'exclude': k})
        run_search(tag, p, targets)
