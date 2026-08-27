#!/usr/bin/env bash
# Full reproduction: verify pipeline hash, run every stage, diff against the
# frozen outputs, rebuild the accounting table and the figures.
# Usage: ./fetch_corpus.sh && ./reproduce.sh          (30-60 min, mostly re-execution)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export GRACE_CORPUS="${GRACE_CORPUS:-$HERE/GRACE_whitepaper_data}"
P="$HERE/grace_audit_adfa1a25/audit_pipeline"
cd "$P"
H=$(cat common.py dataflow.py inject.py invariants.py mechsearch.py prefix_enum.py reexec.py run_audit.py | sha256sum | cut -c1-12)
echo "pipeline hash: $H (paper cites adfa1a251afd)"
[ "$H" = adfa1a251afd ] || { echo "hash mismatch: this is not the pipeline the paper describes"; exit 1; }
pip install --quiet numpy pandas pyarrow matplotlib uproot 2>/dev/null || true
mkdir -p rerun && cd rerun
for s in dataflow invariants mechsearch prefix_enum inject; do
  echo "== $s"; python3 ../$s.py > ${s}.txt 2>&1
done
python3 ../reexec.py optiv9 > reexec_opticks_v9.txt 2>&1
python3 ../reexec.py optiv5 > reexec_opticks_v5.txt 2>&1
python3 ../reexec.py celev7/calorimeter > reexec_celev.txt 2>&1
cp mechsearch.txt mechsearch_full.txt; cp dataflow.txt dataflow_full.txt; cp invariants.txt invariants_full.txt
python3 ../run_audit.py table > /dev/null
echo "== diffs against frozen outputs (empty = identical)"
for pair in "dataflow.txt dataflow_full.txt" "invariants.txt invariants_full.txt" "mechsearch.txt mechsearch_full.txt" \
            "prefix_enum.txt prefix_enum_out.txt" "inject.txt inject_full.txt" "audit_corpus_table.txt audit_corpus_table.txt"; do
  set -- $pair
  if diff -q "$1" "../$2" > /dev/null; then echo "  $2: identical"; else echo "  $2: DIFFERS"; diff "$1" "../$2" | head -5; fi
done
for f in reexec_opticks_v9.txt reexec_opticks_v5.txt reexec_celev.txt; do
  if diff -q <(sed 's#/tmp/reexec_[a-z0-9]*#T#g' "$f") <(sed 's#/tmp/reexec_[a-z0-9]*#T#g' "../$f") > /dev/null; then echo "  $f: identical"; else echo "  $f: differs (seedless-RNG divergence values are expected to vary)"; fi
done
echo "== figures"; cd "$HERE/grace_audit_adfa1a25/figures" && python3 make_figures.py
echo "done; rerun outputs in $P/rerun"
