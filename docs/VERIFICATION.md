# Product verification

## Automated release gate

CI must prove:

- Python compilation;
- browser JavaScript syntax;
- unit, security, policy, rule, contract and adversarial tests;
- dependency vulnerability audit;
- clean container build;
- live container liveness and authenticated homepage access.

## Staging acceptance

Use only synthetic material.

1. Verify unauthenticated application routes fail and liveness exposes no configuration.
2. Upload valid TXT, PDF and DOCX examples; verify oversize, encrypted, macro-bearing and invalid-signature files are rejected.
3. Correct extracted hypotheses and confirm the corrected values reach the report.
4. Run quick brief analysis and instrument audit with the approved model.
5. Confirm assurance is limited where web evidence is absent.
6. Confirm each material finding shows its basis.
7. Accept, reject and amend findings with meaningful rationales.
8. Verify another identity cannot read or adjudicate the job.
9. Export Word, PDF and JSON; inspect content, attribution and limitations.
10. Run two concurrent jobs and verify the next request is rejected at capacity.
11. Restart during a job and confirm the documented pilot-loss behaviour.
12. Enable web grounding only in a permitted profile; open and verify every consequential citation.
13. Confirm no raw prompt, response or document appears in application logs or the filesystem.
14. Verify OpenAI project usage and cost telemetry reconcile with application metadata.

## Methodological acceptance

Automated tests do not validate research quality. A separate blinded expert-panel study must meet thresholds agreed before evaluation. At minimum report per-label precision/recall, false-negative severity, inter-rater agreement, repeat stability, multilingual performance and reviewer usefulness.

## Release decision

A passing CI run permits staging. Staging permits a restricted pilot only after security, data-governance and research-methodology owners sign off. It does not by itself permit production or regulated-data use.
