"""Publication figures for the audit paper, generated from corpus data."""
import sys, re, random, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(os.path.dirname(HERE), 'audit_pipeline')
sys.path.insert(0, PIPE)
OUT = lambda name: os.path.join(HERE, name)

plt.rcParams.update({'font.family': 'serif', 'font.size': 10,
                     'axes.spines.top': False, 'axes.spines.right': False})

# ---------- Figure A: the phantom points --------------------------------
fig, axes = plt.subplots(1, 2, figsize=(9, 3.7))
panels = [
    ('DarkSide (v9)', [(0.1, 145.78), (1.0, 1479.23)], (5.0, 3495.0),
     (5.0, 7430.83), 'logged: 4939 events', 'archived entry:\nexactly 5000 events'),
    ('ProtoDUNE (v9)', [(1.0, 651.38), (2.0, 1306.70)], (5.0, 1536.40),
     (5.0, 3265.99), 'logged: 4944 events', 'archived entry:\nexactly 5000 events'),
]
for ax, (title, genuine, real5, phantom, nlab, plab) in zip(axes, panels):
    gx, gy = zip(*genuine)
    k = sum(x * y for x, y in zip(gx, gy)) / sum(x * x for x in gx)
    xs = np.logspace(np.log10(min(gx) * 0.7), np.log10(7.5), 50)
    ax.plot(xs, k * xs, ls='--', lw=1, color='0.55',
            label='linear response fit to genuine points')
    ax.plot(gx, gy, 'o', color='black', ms=7, label='log-verified points')
    ax.plot(*real5, 's', color='#1f77b4', ms=7,
            label='real 5 MeV data (logs)')
    ax.plot(*phantom, '*', mfc='none', mec='#d62728', ms=15, mew=1.6,
            label='archived 5 MeV entry (phantom)')
    ax.annotate('', xy=(5.0, real5[1]), xytext=(5.0, k * 5.0),
                arrowprops=dict(arrowstyle='->', color='#1f77b4', lw=1.2))
    ax.text(5.45, np.sqrt(real5[1] * k * 5.0),
            f'$\\times${real5[1]/(k*5.0):.2f}\n(batching\nartifact)',
            fontsize=8, color='#1f77b4', va='center')
    ax.text(4.6, phantom[1] * 1.28, plab, fontsize=7.5, color='#d62728',
            ha='right')
    ax.text(4.6, real5[1] * 0.78, nlab, fontsize=7.5, color='#1f77b4',
            ha='right', va='top')
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_xlabel('Beam energy [MeV]')
    ax.set_title(title, fontsize=10)
axes[0].set_ylabel('Mean photoelectrons per event')
axes[0].legend(fontsize=7, loc='lower right', frameon=False)
fig.tight_layout()
fig.savefig(OUT('fig_phantom.pdf')); fig.savefig(OUT('fig_phantom.png'), dpi=200)
print('fig_phantom done')

# ---------- Figure B: claim accounting ----------------------------------
rows = []
for ln in open(os.path.join(PIPE, 'audit_corpus_table.txt')):
    m = re.match(r'(\S+/\S+)\s', ln)
    if m:
        nums = [int(x) for x in re.findall(r'\b\d+\b', ln)]
        rows.append((m.group(1), nums[:4]))  # logv, copy, diag, unex
rows.sort(key=lambda r: -sum(r[1]))
names = [r[0].replace('celev', 'celeritas-v').replace('optiv', 'opticks-v')
          .replace('_lar', '').replace('/', ' ') for r in rows]
data = np.array([r[1] for r in rows])
fig, ax = plt.subplots(figsize=(8, 5.2))
cats = ['log-verified', 'inter-JSON copies', 'formula-diagnosed', 'unexplained / ambiguous']
colors = ['#2e7d32', '#8bc34a', '#ff9800', '#bdbdbd']
left = np.zeros(len(rows))
y = np.arange(len(rows))
for j, (c, col) in enumerate(zip(cats, colors)):
    ax.barh(y, data[:, j], left=left, color=col, label=c, height=0.72)
    left += data[:, j]
ax.set_yticks(y); ax.set_yticklabels(names, fontsize=8)
ax.invert_yaxis()
ax.set_xlabel('Numeric claim targets')
ax.legend(fontsize=8, loc='lower right', frameon=False)
for i, tot in enumerate(data.sum(1)):
    ax.text(tot + 4, i, str(tot), va='center', fontsize=7, color='0.3')
fig.tight_layout()
fig.savefig(OUT('fig_accounting.pdf')); fig.savefig(OUT('fig_accounting.png'), dpi=200)
print('fig_accounting done')

# ---------- Figure C: decoy null calibration ----------------------------
import mechsearch
import common
names_p, vals_p, fams_p, logq, jl = mechsearch.build_pool(
    common.run_path('opticks_run_files_v9', 'darkside_lar'))
mechsearch.sigfigs = lambda s: 99  # disable gate to measure the raw rate
random.seed(3)
sig_bins = [2, 3, 4, 5, 6]
fp_rate, fp_err = [], []
pool_list = [v for v in vals_p if 1e-3 < abs(v) < 1e7]
for s in sig_bins:
    hits = 0; n = 120
    for _ in range(n):
        v = random.choice(pool_list) * random.uniform(1.05, 3.0)
        txt = f'{v:.{s}g}'
        if 'e' in txt or '.' not in txt:
            txt = f'{v:.{max(1, s - len(str(int(abs(v)))))}f}'
        _, m, copies = mechsearch.search_target(txt, names_p, vals_p, fams_p)
        hits += bool(m)
    p = hits / n
    fp_rate.append(p); fp_err.append(np.sqrt(p * (1 - p) / n))
fig, ax = plt.subplots(figsize=(4.4, 3.3))
ax.errorbar(sig_bins, fp_rate, yerr=fp_err, fmt='o-', color='black', lw=1,
            capsize=3, ms=5)
ax.axvline(3.5, ls='--', color='#d62728', lw=1)
ax.text(3.58, 0.85, 'pair-formula gate\n($\\geq 4$ sig. figs.)',
        fontsize=8, color='#d62728')
ax.set_xlabel('Significant figures of decoy target')
ax.set_ylabel('False-diagnosis rate on decoys')
ax.set_ylim(0, 1.02); ax.set_xticks(sig_bins)
fig.tight_layout()
fig.savefig(OUT('fig_nullcal.pdf')); fig.savefig(OUT('fig_nullcal.png'), dpi=200)
print('fig_nullcal done:', dict(zip(sig_bins, [f'{p:.2f}' for p in fp_rate])))
