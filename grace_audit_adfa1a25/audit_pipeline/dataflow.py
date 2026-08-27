"""AST dataflow: is each script OUTPUT reachable from a FILE read, or only from literals?

Taints: LIT (constant expressions), FILE (open/json.load/pd.read_*/glob/np.load/Path.read),
propagated name-level, flow-insensitive, to a fixpoint. Outputs are names formatted into
print('RESULT:...') f-strings and values written via json.dump. Verdict per output:
  HARDCODED  taint == {LIT}
  DATA       FILE in taint
  MIXED      LIT and computed, no FILE (suspicious constants blended in)
Also flags exists-guarded continue/return (silent skip) at any loop feeding outputs.
"""
import ast, sys, glob, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import runs

FILE_CALLS = {'open', 'load', 'loads', 'read_parquet', 'read_csv', 'read_json',
              'glob', 'loadtxt', 'genfromtxt', 'read_text', 'read'}

def callee_name(c):
    f = c.func
    if isinstance(f, ast.Name): return f.id
    if isinstance(f, ast.Attribute): return f.attr
    return ''

class Analyzer(ast.NodeVisitor):
    def __init__(self):
        self.taint = {}           # name -> set of taints; names also taint 'ret:<func>'
        self.deps = []            # (target_names, source_names, has_lit, has_file, lineno)
        self.outputs = []         # (kind, name_or_expr_names, lineno, label)
        self.skips = []           # lineno of exists-guarded continue/return
        self.func = None

    def names_in(self, node):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

    def expr_flags(self, node):
        has_file = any(isinstance(c, ast.Call) and callee_name(c) in FILE_CALLS
                       for c in ast.walk(node))
        consts = [c for c in ast.walk(node) if isinstance(c, ast.Constant)
                  and isinstance(c.value, (int, float)) and not isinstance(c.value, bool)]
        calls = {callee_name(c) for c in ast.walk(node) if isinstance(c, ast.Call)}
        return has_file, bool(consts), calls

    def visit_FunctionDef(self, node):
        old = self.func; self.func = node.name
        self.generic_visit(node); self.func = old

    def visit_Return(self, node):
        if node.value is not None and self.func:
            hf, hl, calls = self.expr_flags(node.value)
            self.deps.append(({f'ret:{self.func}'},
                              self.names_in(node.value) | {f'ret:{c}' for c in calls},
                              hl, hf, node.lineno))
        self.generic_visit(node)

    def visit_Assign(self, node):
        tgts = set()
        for t in node.targets:
            tgts |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
        hf, hl, calls = self.expr_flags(node.value)
        src = self.names_in(node.value) - tgts
        src |= {f'ret:{c}' for c in calls}
        pure_lit = (not src and not hf and
                    isinstance(node.value, (ast.Constant, ast.UnaryOp, ast.BinOp, ast.List, ast.Dict))
                    and not any(isinstance(n, ast.Name) for n in ast.walk(node.value)))
        self.deps.append((tgts, src, hl or pure_lit, hf, node.lineno))
        self.generic_visit(node)

    visit_AugAssign = lambda self, node: (self.deps.append(
        ({node.target.id} if isinstance(node.target, ast.Name) else set(),
         self.names_in(node.value), True, False, node.lineno)), self.generic_visit(node))[-1]

    def visit_Call(self, node):
        cn = callee_name(node)
        # mutation taint: x.append(e), x.extend(e), x.update(e), x[k]=... handled in Assign
        if cn in ('append', 'extend', 'update', 'add', 'insert', 'setdefault') and \
                isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            tgt = node.func.value.id
            hf, hl, calls = self.expr_flags(node)
            src_names = set()
            for a in node.args: src_names |= self.names_in(a)
            src_names |= {f'ret:{c}' for c in calls if c not in ('append','extend','update','add','insert','setdefault')}
            self.deps.append(({tgt}, src_names - {tgt}, hl, hf, node.lineno))
        if cn == 'print' and node.args:
            a = node.args[0]
            if isinstance(a, ast.JoinedStr):
                txt = ''.join(v.value for v in a.values if isinstance(v, ast.Constant))
                if 'RESULT:' in txt:
                    for v in a.values:
                        if isinstance(v, ast.FormattedValue):
                            self.outputs.append(('RESULT', self.names_in(v.value) |
                                                 {f'ret:{c}' for c in
                                                  {callee_name(x) for x in ast.walk(v.value)
                                                   if isinstance(x, ast.Call)}},
                                                 node.lineno, txt.strip()[:60]))
        if cn == 'dump':
            if node.args:
                self.outputs.append(('JSONDUMP', self.names_in(node.args[0]), node.lineno, 'json.dump'))
        self.generic_visit(node)

    def visit_If(self, node):
        test_src = ast.unparse(node.test) if hasattr(ast, 'unparse') else ''
        if 'exists' in test_src:
            for st in ast.walk(node):
                if isinstance(st, (ast.Continue, ast.Return)) or (
                        isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
                        and callee_name(st.value) == 'print'):
                    if isinstance(st, (ast.Continue, ast.Return)):
                        self.skips.append((node.lineno, test_src[:70]))
                        break
        self.generic_visit(node)

def fixpoint(deps):
    taint = {}
    changed = True
    while changed:
        changed = False
        for tgts, src, hl, hf, ln in deps:
            t = set()
            if hl: t.add('LIT')
            if hf: t.add('FILE')
            for s in src: t |= taint.get(s, {'EXT'} if s.startswith('ret:') else set())
            for g in tgts:
                cur = taint.setdefault(g, set())
                if not t <= cur:
                    cur |= t; changed = True
    return taint

def analyze(path):
    try: tree = ast.parse(open(path, errors='ignore').read())
    except SyntaxError: return None
    A = Analyzer(); A.visit(tree)
    taint = fixpoint(A.deps)
    assign_line = {}
    for tgts, src, hl, hf, ln in A.deps:
        for g in tgts: assign_line.setdefault(g, ln)
    findings = []
    for kind, names, ln, label in A.outputs:
        t = set()
        for n in names: t |= taint.get(n, set())
        if not names: continue
        if t == {'LIT'} or (t <= {'LIT'} and t):
            findings.append(('HARDCODED', kind, ln, label, sorted(names)[:4],
                             [assign_line.get(n) for n in sorted(names)[:4]]))
        elif 'FILE' not in t and 'EXT' not in t and 'LIT' in t:
            findings.append(('LIT-ONLY-CHAIN', kind, ln, label, sorted(names)[:4], []))
    return {'findings': findings, 'skips': A.skips}

if __name__ == '__main__':
    tot_hc = tot_sk = tot_scripts = 0
    for tag, p in runs():
        rows = []
        for s in sorted(glob.glob(f'{p}/grace_python_*.py')):
            tot_scripts += 1
            r = analyze(s)
            if not r: continue
            for f in r['findings']:
                rows.append((os.path.basename(s), f))
            for ln, cond in r['skips']:
                rows.append((os.path.basename(s), ('SILENT-SKIP', '', ln, cond, [], [])))
        if rows:
            print(f'\n### {tag}')
            for fn, (verdict, kind, ln, label, names, alines) in rows:
                extra = f' names={names} assigned@{alines}' if names else ''
                print(f'  {verdict:<15} {fn[:34]} L{ln:<5} {label[:58]}{extra}')
                tot_hc += verdict in ('HARDCODED', 'LIT-ONLY-CHAIN')
                tot_sk += verdict == 'SILENT-SKIP'
    print(f'\nTOTAL: {tot_scripts} scripts; {tot_hc} literal-only outputs; {tot_sk} exists-guarded silent skips')
