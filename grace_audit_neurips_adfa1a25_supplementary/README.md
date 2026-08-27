# Supplementary material: "All Checks Passed" (AI for Science workshop, NeurIPS 2026)

Everything needed to rebuild every number, table, and figure in the paper.

    paper/                         tex source, style, figures, compiled PDF,
                                   optional filled NeurIPS checklist (not required by the workshop)
    grace_audit_adfa1a25/          the audit pipeline named by its source hash
      audit_pipeline/              five stages + injection harness + frozen outputs (*_full.txt, reexec_*.txt)
      audit_pipeline/frozen_v1/    outputs of the first pipeline version, for comparison only
      figures/                     figure scripts and rendered figures
      README.md                    stage-by-stage instructions and where each finding lives
    fetch_corpus.sh                clones the audited corpus at the pinned commit
    reproduce.sh                   runs every stage, diffs against frozen outputs, rebuilds table and figures

## Pins
- Corpus: github.com/just5034/GRACE_whitepaper_data @ 7d28c4da0fe2850a654eff0b31a5ea02ac150c8a (1,248 tracked files)
- Pipeline: sha256 over the eight stage scripts begins adfa1a251afd (reproduce.sh checks this first)
- Backbone of the audited agent: claude-sonnet-4-20250514 (pinned in the corpus run names)

## Quick start
    ./fetch_corpus.sh            # ~500 MB clone
    ./reproduce.sh               # 30-60 min; prints "identical" per frozen output

## Requirements
Python 3.10+, numpy, pandas, pyarrow, matplotlib, uproot. No GPU, no network beyond the clone.

## Where each claim in the paper lives
| Paper | File |
|---|---|
| Table 1, Appendix A | audit_pipeline/audit_corpus_table.txt (.tex) |
| Table 2 | audit_pipeline/inject_full.txt (summary block) |
| Fig. 1 | figures/fig_phantom.pdf, audit_pipeline/prefix_enum_out.txt |
| Fig. 2 | figures/fig_nullcal.pdf |
| 4491.29 diagnosis, quenching corroboration | audit_pipeline/mechsearch_full.txt (grep CORROBORATED, 4491) |
| Silent skips, hardcoded outputs | audit_pipeline/dataflow_full.txt |
| Batching 0.47/0.47/0.22, linearity | audit_pipeline/invariants_full.txt |
| Re-execution (25 ran, 21 match, 4 diverge) | audit_pipeline/reexec_opticks_v5.txt, reexec_opticks_v9.txt |
