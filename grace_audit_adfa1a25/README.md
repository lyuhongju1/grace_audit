# grace_audit_adfa1a25 (formerly "audit_verification_bundle", version 2, pipeline hash adfa1a251afd): "All Checks Passed" audit of the GRACE artifact corpus

Everything needed to reproduce the audit, the figures, and the manuscript.
The audited corpus itself (478 MB) is not included; step 1 fetches it.

## 1. Corpus (pinned commit 7d28c4da0fe2850a654eff0b31a5ea02ac150c8a; see ../fetch_corpus.sh)
    git clone https://github.com/just5034/GRACE_whitepaper_data
Either clone it beside this README (the default location) or point the
environment variable `GRACE_CORPUS` at the clone. Every stage, the injection
harness, and the figure script locate the corpus through `common.ROOT`; there
are no other hardcoded paths.

## 2. Environment
Python 3.10+ with
    pip install numpy pandas pyarrow matplotlib uproot

## 3. Run the audit
    cd audit_pipeline
    python3 run_audit.py all        # every stage fresh, ~30-60 min
    python3 run_audit.py table      # claim-accounting table (txt + tex)
Individual stages run standalone, and each module docstring states its
method and acceptance rules. The frozen outputs from the paper's run are
included as *_full.txt / reexec_*.txt for direct comparison.

Determinism: the decoy null calibration in mechsearch.py is seeded per target
(SEED in the module; AUDIT_DECOYS sets the decoy count, default 100, so null
rates are reported at 1% granularity). Fault injection is seeded (seed 7).
Re-execution of scripts that use unseeded RNG is inherently nondeterministic;
those show up as DIVERGE with the reason noted.

## 4. Key findings -> where to verify them
- Verified claims and diagnosed mechanisms (paper Sec. 3): mechsearch_full.txt
  and the docstrings in mechsearch.py; every number re-derives from the logs.
- 61 literal-only physics outputs and 6 silent skips: dataflow_full.txt,
  with file names and line numbers for source inspection.
- Batching suppression 0.47 / 0.47 / 0.22: invariants_full.txt (I3 lines),
  or one-line log arithmetic per the paper.
- Re-execution matches and the four divergences: reexec_opticks_v9.txt,
  reexec_opticks_v5.txt, reexec_celev.txt.
- Stale-input contamination (both runs): python3 prefix_enum.py, which
  performs the moment inversion and the exhaustive subset/prefix exclusion,
  output frozen in prefix_enum_out.txt. The ProtoDUNE instance is visible
  directly by comparing baseline_optical_performance.json (num_events 5000,
  yield 653.199 at 5 MeV) against the 5 MeV logs (4944 events, 307.3).
- Fault-injection calibration: python3 inject.py, frozen in inject_full.txt.
  Three independent instances per defect class; the summary block reports
  instances-detected / instances-injected per detector and per class.
- The DarkSide-v9 optimized yield 4491.29: mechsearch_full.txt now diagnoses
  it as a*(1+b/100) with a = 1474.39 (average_light_yield) and b = 204.62
  (light_yield_percent), i.e. the archived script grace_python_1ac09a87067d.py
  line 20, and dataflow_full.txt flags that script's outputs as literal-only.
  It is NOT a per-event quantity with a lost energy division (the earlier
  reading, which matched only to 0.1%).

## 5. Figures
    cd figures && python3 make_figures.py
Regenerates fig_phantom, fig_accounting, fig_nullcal (PDF+PNG) from the
corpus and audit_corpus_table.txt. Fixed seed; the null-calibration bin
counts are set in the script.

## 6. Manuscript
    cd paper && pdflatex paper2_final.tex && pdflatex paper2_final.tex
The figure PDFs must sit beside the tex (copies included).

## 7. Version check
    cd audit_pipeline && cat common.py dataflow.py inject.py invariants.py mechsearch.py prefix_enum.py reexec.py run_audit.py | sha256sum
should begin adfa1a251afd, matching the directory name. The paper cites this
name and hash; the earlier bundle (audit_verification_bundle, hash
f6f9958a49c8) produces the older numbers (357/1487,
one injection instance per class, 20 unseeded decoys).

## 8. Changes from the first bundle
- Corpus root configurable (GRACE_CORPUS); import paths relative; the bundle
  runs unedited from any directory.
- mechsearch: grammar gains a*(1+b/100); decoy calibration seeded and raised
  from 20 to 100 decoys per target. Verdict counts do not depend on the decoy
  draws, but every null-FP and joint-null figure is now reproducible.
- mechsearch: corroborated value--uncertainty pairs now carry a directly
  measured joint null (decoy mean and std jittered together, same family
  variant must explain both) next to the product-of-marginals figure.
- mechsearch: a JSON-leaf target is removed from the pool before the pair
  formulas run; the first release excluded it only from the identity pass, so
  a leaf could match itself through a/b*1.0 and similar forms.
- inject: three instances per defect class, and every detector is run on
  every instance, so all 75 cells of the calibration table are measured;
  the summary counts classes and instance-detector trials separately.
- make_figures: reads the accounting table from audit_pipeline/ and writes
  figures beside itself.
