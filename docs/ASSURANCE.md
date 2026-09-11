# Methodological assurance

## Intended use

BRIEF is an internal research quality-assurance assistant. It helps a qualified researcher identify assumptions, wording risks, sample mismatches and questions that warrant review. It also generates an internal workflow recommendation: proceed to research planning, proceed after changes, or hold before fieldwork. That recommendation is not organisational authorisation. BRIEF does not establish truth, diagnose bias objectively, replace ethics review, or approve a research design.

## Evidence classes

Every report distinguishes:

1. **Deterministic facts** — counts, configured models, completed/failed stages and formula-derived indicators.
2. **Model judgements** — extracted hypotheses, issue labels, rewrites, themes and recommendations.
3. **Published evidence** — claims returned through web grounding with citations that a reviewer must verify.
4. **Human decisions** — acceptance, rejection or amendment of findings before fieldwork.

Model stages are not independent expert reviewers. Agreement between related models is evidence of model convergence, not evidence that a proposition is true.

## Indicator interpretation

The research-design and wording indicators are heuristics. Their thresholds are product rules, not validated psychometric scales. They must not be presented as measures of contamination, bias, validity or expected project success.

A run receives at most **moderate** assurance. It becomes **limited** when quick mode is used, stages fail, too few probe answers are available, or public evidence is absent.

## Required human review

Before using an output, the responsible researcher must:

- confirm the extracted brief and hypotheses;
- accept, reject or amend each material issue with a reason;
- open and verify consequential cited sources;
- approve changes to sample, method, screener or instrument;
- apply separate legal, ethics, safeguarding and accessibility review where relevant.

## Validation programme

Production claims require a versioned, non-sensitive benchmark:

- independently label cases with at least three experienced researchers;
- define the construct and annotation guide before viewing model outputs;
- measure per-label precision, recall and F1;
- measure human inter-rater agreement and model-to-panel agreement;
- assess false-negative severity separately from aggregate accuracy;
- repeat each case to quantify run-to-run stability;
- compare supported model snapshots and prompt versions;
- test prompt-injection, multilingual, sparse, contradictory and out-of-domain inputs;
- record whether recommendations improve blinded expert review outcomes.

CI should enforce deterministic contracts. Model-quality evaluation should run separately on a controlled schedule because it incurs API cost and can vary over time.

## Change control

Each report records the prompt version and probe models. A model, prompt, scoring-rule or threshold change requires a new evaluation result and reviewer approval. Historical results must not be compared across versions without an explicit caveat.
