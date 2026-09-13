# Threat model

## Protected assets

Research briefs, participant-facing instruments, hypotheses, generated analysis, citations, reviewer decisions, user identity, OpenAI credentials and usage budget.

## Trust boundaries

- User browser to organisational ingress.
- Ingress to BRIEF web service.
- BRIEF to the approved OpenAI endpoint or internal gateway.
- Optional OpenAI web-search processing of public sources.
- Application memory and any explicitly enabled trace volume.
- Exported files leaving the application.

## Principal threats and controls

| Threat | Control | Residual risk |
|---|---|---|
| Unauthenticated access | Fail-closed startup/authentication; trusted proxy identity | Proxy must strip spoofed identity headers |
| Cross-user job access | 128-bit job IDs plus owner checks | Basic pilot password is not strong identity |
| Prompt injection | Global untrusted-data boundary; schema and contract validation | Model behaviour is probabilistic |
| Data over-retention | Raw traces off; in-memory expiry; OpenAI storage disabled | OpenAI account controls require operator verification |
| Denial of wallet | Bounded concurrent jobs, sessions and request size | Per-user quotas and external gateway budgets remain deployment controls |
| Malicious documents | Type signatures, archive expansion limits, page limits, encrypted/macro rejection | Full malware scanning and parser isolation require external services |
| Misleading certainty | Assurance cap, provenance, limitations and human adjudication | Human reviewers can still accept weak findings |
| Citation laundering | Citations marked unverified and turned into review findings | Source content and interpretation require human checking |
| Supply-chain compromise | Pinned dependencies, vulnerability audit and clean container CI | Image signing/SBOM publication remain release-platform tasks |

## Out of scope for the single-process pilot

High availability, restart recovery, horizontal scaling, regulated or participant-special-category data, anonymous public access and unattended research approval.
