# Evaluation framework

The checked-in cases are synthetic smoke tests, not an expert-labelled validation benchmark. They test deterministic rules and adversarial input handling without sending content to an API.

A claim-bearing benchmark must be approved separately and contain at least three independent expert labels per item, adjudication notes, sector/language metadata, expected severity, and a versioned annotation guide. Report precision, recall, F1, false-negative severity, inter-rater agreement and repeated-run stability.

`labelled_cases.json` contains targeted regression cases and `synthetic_research_cases.json` adds a broader set of research scenarios, including a clean negative example. `evaluate.py` searches only an explicit whitelist of analytical finding fields, reports precision and recall, and
returns a failing exit status when either threshold is missed, a convergence or structural expectation fails, or
an analysis stage errors. Structural checks cover deterministic states such as preserved but unassessed hypotheses. It never searches parsed client hypotheses, screener criteria, hypothesis wording or the submitted brief.

These cases remain synthetic. Never add real client material to this directory.
