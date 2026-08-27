"""Audit pipeline foundation: quantity pool with provenance + claim inventory.

Every quantity carries a provenance tag:
  LOG   - derived from per-event execution logs (primitive evidence)
  JSON  - a numeric leaf of a results/analysis/comparison JSON (intermediate)
Claims are numeric strings extracted from reports and JSONs, each with an ID.
"""
import re, os, glob, json, math
from collections import defaultdict

# Corpus location: set GRACE_CORPUS in the environment, or edit the default.
ROOT = os.environ.get('GRACE_CORPUS',
                      os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'GRACE_whitepaper_data'))
if not os.path.isdir(ROOT):
    raise SystemExit(f'corpus not found at {ROOT}; clone GRACE_whitepaper_data and set GRACE_CORPUS')

def run_path(arm, prefix):
    """Directory of one run, e.g. run_path('opticks_run_files_v9', 'darkside_lar')."""
    hits = sorted(glob.glob(os.path.join(ROOT, arm, prefix + '_*')))
    if not hits: raise SystemExit(f'no run {arm}/{prefix}* under {ROOT}')
    return hits[0]
VERSIONS = ['celeritas_run_files_v4', 'celeritas_run_files_v7',
            'opticks_run_files_v5', 'opticks_run_files_v9']

RX_OPT = re.compile(r'(\d+)\s+hits detected')
RX_CEL = re.compile(r'Event\s+(\d+)\s+processed:\s+(\d+)\s+hits,\s+([\d.eE+-]+)\s+MeV')
PARTS = ['electron','proton','neutron','gamma','kaonp','kaonm','kaon','mum','mup','pip','pim','e-','mu-']
RX_TAIL = re.compile(r'^(.*)_(' + '|'.join(PARTS) + r')_geant4\.log$')

def runs():
    for v in VERSIONS:
        for d in sorted(os.listdir(os.path.join(ROOT, v))):
            p = os.path.join(ROOT, v, d)
            if os.path.isdir(p):
                yield f'{v.split("_")[0][:4]}{v[-2:]}/{d.split("_claude")[0]}', p

def read(p):
    try: return open(p, errors='ignore').read()
    except Exception: return ''

def split_log(logname):
    m = RX_TAIL.match(os.path.basename(logname))
    if m: return m.group(1), m.group(2)
    return re.sub(r'_geant4\.log$', '', os.path.basename(logname)), '?'

def parse_log(path):
    t = read(path)
    o = [int(x) for x in RX_OPT.findall(t)]
    if o: return {'fmt': 'opticks', 'per_event': o}
    c = RX_CEL.findall(t)
    if c: return {'fmt': 'celeritas',
                  'per_event': [int(h) for _, h, _ in c],
                  'edep': [float(e) for _, _, e in c]}
    return {'fmt': 'none', 'per_event': []}

def log_quantities(run_path):
    """LOG-provenance pool: per (geom, particle, energy) event stats, batches merged."""
    cells = defaultdict(list)
    for L in glob.glob(f'{run_path}/**/*geant4.log', recursive=True):
        e = re.search(r'energy_([\d.]+)GeV', L)
        en = float(e.group(1)) if e else None
        g, pa = split_log(L)
        cells[(g, pa, en)].extend(parse_log(L)['per_event'])
    out = {}
    for (g, pa, en), ev in cells.items():
        if not ev: continue
        n = len(ev); tot = sum(ev); mu = tot / n
        var = sum((x - mu) ** 2 for x in ev) / n
        key = f'{g}/{pa}/{en}'
        out[f'log:{key}:n_events'] = float(n)
        out[f'log:{key}:total_hits'] = float(tot)
        out[f'log:{key}:mu'] = mu
        if en: out[f'log:{key}:mu_per_mev'] = mu / (en * 1000.0)
        if mu > 0:
            out[f'log:{key}:sigma'] = math.sqrt(var)
            out[f'log:{key}:res'] = math.sqrt(var) / mu
    return out

RESULTS_JSON = lambda p: [j for j in glob.glob(f'{p}/*.json')
                          if not any(k in os.path.basename(j) for k in
                                     ('reasoning', 'memory', 'benchmark', 'metadata', 'extracted', 'profile'))]

def json_leaves(run_path):
    """JSON-provenance pool + numeric arrays (families for mean/std search)."""
    leaves, families = {}, {}
    def walk(o, path, fname):
        if isinstance(o, bool): return
        if isinstance(o, (int, float)):
            leaves[f'json:{fname}:{path}'] = float(o)
        elif isinstance(o, dict):
            for k, v in o.items(): walk(v, f'{path}.{k}' if path else k, fname)
        elif isinstance(o, list):
            nums = [x for x in o if isinstance(x, (int, float)) and not isinstance(x, bool)]
            if 2 <= len(nums) <= 8 and len(nums) == len(o):
                families[f'json:{fname}:{path}[]'] = [float(x) for x in nums]
            for i, v in enumerate(o): walk(v, f'{path}[{i}]', fname)
    for j in RESULTS_JSON(run_path):
        try: walk(json.load(open(j)), '', os.path.basename(j))
        except Exception: pass
    return leaves, families

NUM = re.compile(r'\b\d{1,3}(?:,\d{3})+\.\d{1,6}\b|\b\d+\.\d{1,6}\b|\b\d{2,}\b')
def report_claims(run_path):
    """Numeric claims from the generated report, with IDs and context snippets."""
    rp = os.path.join(run_path, 'academic_report.md')
    t = read(rp)
    out = []
    for i, m in enumerate(NUM.finditer(t)):
        s = m.group(0).replace(',', '')
        if float(s) in (0.0, 1.0, 2.0): continue
        ctx = t[max(0, m.start() - 60):m.end() + 40].replace('\n', ' ')
        out.append({'id': f'R{i:04d}', 'text': s, 'ctx': ctx})
    return out

def decimals(s):
    return len(s.split('.')[1]) if '.' in s else 0

def fmt_match(value, claim_text):
    """Rounding-aware match of a float against a printed claim string."""
    p = decimals(claim_text)
    try: return f'{value:.{p}f}' == claim_text and math.isfinite(value)
    except (ValueError, OverflowError): return False
