"""Physics-invariant battery over the archive. A binding verifier, run retrospectively.

I1 bounds:      efficiency/quenching/fraction-type JSON leaves must lie in [0, 1]
I2 poisson:     reported energy resolution cannot beat the photostatistics floor
                1/sqrt(mean PE), computed from the per-event logs
I3 batch-ratio: log-derived yield/MeV at batched energies vs unbatched reference;
                suppression ratio < 0.7 at a batched energy = instrumental artifact
I4 linearity:   log-derived total-PE vs energy should be ~linear; large sublinearity
                localized to batched points corroborates I3
"""
import sys, re, math, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import runs, log_quantities, json_leaves

BOUND_KEY = re.compile(r'efficien|quench|fraction|acceptance|purity|coverage', re.I)
RES_KEY = re.compile(r'resolution', re.I)

def battery(tag, path):
    logq = log_quantities(path)
    jl, _ = json_leaves(path)
    out = []
    # I1 bounds
    for k, v in jl.items():
        if BOUND_KEY.search(k) and not any(s in k.lower() for s in ('mm', 'area', 'improvement', 'percent', 'count', 'ratio_')):
            if not (0.0 <= v <= 1.0) and abs(v) < 1e6:
                out.append(f'I1 BOUND    {k.split(":",1)[1][:80]} = {v}')
    # organize log mu by (geom, particle) -> {E: mu}
    mus, ns = {}, {}
    for k, v in logq.items():
        m = re.match(r'log:(.+)/(\w+|-\w+)/([\d.]+):mu$', k)
        if m and m.group(3) != 'None':
            mus.setdefault((m.group(1), m.group(2)), {})[float(m.group(3))] = v
    # I2 poisson floor: best reported resolution vs 1/sqrt(max mu) across the run
    best_mu = max([v for k, v in logq.items() if k.endswith(':mu')] or [0])
    floor = 1 / math.sqrt(best_mu) if best_mu > 1 else None
    if floor:
        for k, v in jl.items():
            kl = k.lower()
            if 'energy' not in kl and 'pe_resolution' not in kl and not re.search(r':resolution\b', kl): continue
            if RES_KEY.search(k) and 0 < v < 1 and not any(s in kl for s in ('mm', 'err', 'improvement', 'position', 'spatial', 'timing')):
                if v < 0.8 * floor:
                    out.append(f'I2 POISSON  {k.split(":",1)[1][:70]} = {v:.4f} < floor 1/sqrt({best_mu:.0f})={floor:.4f}')
    # I3 batch-ratio suppression
    batched_E = set()
    for edir in glob.glob(f'{path}/energy_*'):
        if os.path.isdir(edir) and any(os.path.isdir(os.path.join(edir, x)) for x in os.listdir(edir)):
            m = re.search(r'energy_([\d.]+)GeV', edir)
            if m: batched_E.add(float(m.group(1)))
    for (g, pa), d in mus.items():
        if len(d) < 2: continue
        Es = sorted(d)
        ref = next((E for E in Es if E not in batched_E and E > 0), None)
        if ref is None: continue
        for E in Es:
            if E in batched_E and E > 0:
                r = (d[E] / E) / (d[ref] / ref)
                flag = 'ARTIFACT' if r < 0.7 else 'ok'
                out.append(f'I3 BATCH    {g}/{pa}: yield/MeV @{E*1000:.0f}MeV / @{ref*1000:.0f}MeV = {r:.2f}  [{flag}]')
    # I4 linearity residual (only where >=3 energies)
    for (g, pa), d in mus.items():
        if len(d) >= 3:
            Es = sorted(d); xs = Es; ys = [d[E] for E in Es]
            sx = sum(xs); sy = sum(ys); sxx = sum(x * x for x in xs); sxy = sum(x * y for x, y in zip(xs, ys))
            n = len(xs); den = n * sxx - sx * sx
            if den == 0: continue
            b = (n * sxy - sx * sy) / den; a = (sy - b * sx) / n
            worst = max(abs(a + b * x - y) / max(y, 1e-9) for x, y in zip(xs, ys))
            if worst > 0.25:
                out.append(f'I4 NONLIN   {g}/{pa}: worst linear-fit residual {worst:.0%} over E={[f"{e*1000:.0f}MeV" for e in Es]}')
    return out

if __name__ == '__main__':
    total = 0
    for tag, p in runs():
        rows = battery(tag, p)
        if rows:
            print(f'\n### {tag}')
            for r in rows: print('  ' + r); total += 1
    print(f'\nTOTAL invariant flags: {total}')
