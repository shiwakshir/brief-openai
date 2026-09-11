# Operational runbook

## Before deployment

1. Select and record the data policy profile.
2. Configure corporate ingress and verify it removes inbound copies of the identity header.
3. Put the OpenAI project service credential in the platform secret manager.
4. Confirm retention, residency, model allowlist, web-search eligibility and spend limits.
5. Keep raw payload logging disabled unless a separate retention approval exists.
6. Run CI against the exact commit and record the image digest.
7. Perform the synthetic end-to-end acceptance checklist in docs/VERIFICATION.md.

## Monitoring

Monitor liveness, job start/completion/failure counts, average duration, HTTP 401/413/429/5xx rates, OpenAI token/cost budgets and degraded/invalid report rates. Metrics must never include document or model content.

## Incident response

- Disable ingress if confidential content may be exposed.
- Revoke the OpenAI service credential.
- Preserve only approved, redacted operational evidence.
- Identify affected users and job windows.
- Follow the organisation's incident and data-owner notification process.
- Restore from a reviewed image and rotate credentials before reopening.

## Rollback

Retain the previously approved image digest. Stop new admissions, allow or cancel active pilot jobs, deploy the previous image, verify liveness and authenticated homepage access, then record the rollback reason.

## Known pilot behaviour

Active jobs and adjudication state are lost on process restart. Do not run more than one web process. Production rollout requires a durable external queue and ownership store approved for the input classification.
