# Organisational deployment baseline

## Pilot boundary

Use one private instance for a small named group, behind corporate SSO or an identity-aware proxy. Permit only approved low-sensitivity inputs. Keep web grounding and raw payload logging disabled. Set a global concurrency limit of one or two and an OpenAI project budget.

The proxy must remove any inbound copy of the configured identity header and set the trusted authenticated identity itself. Do not expose the application directly when `BRIEF_TRUST_AUTH_PROXY=true`.

## Data flow

1. An authenticated researcher submits a brief or instrument.
2. The web process validates and extracts text in memory.
3. A bounded local job sends selected text and intermediate model output to the OpenAI API.
4. Optional web grounding asks OpenAI's web-search tool to retrieve public sources.
5. Results remain in process memory until session expiry.
6. Raw inputs and outputs are written only if `BRIEF_LOG_RAW_PAYLOADS=true`; this requires a separately approved encrypted retention location and deletion schedule.

## Required controls

- TLS and corporate authentication at the ingress.
- Per-user authorisation for every job.
- Secrets from the hosting platform's secret manager.
- Restricted egress to the approved OpenAI endpoint or internal AI gateway.
- OpenAI project spend limits and an organisation-owned service credential.
- Confirmed model allowlist, retention controls and processing region.
- Central operational logs without prompt, response or document content.
- Vulnerability scanning, reviewed dependencies and a clean CI build.
- Backups only for explicitly retained governed records.

## Current scaling limit

This branch remains a single-process pilot. Jobs and progress are held in memory, so active work is lost on restart and the service must run one web worker. Do not horizontally scale it.

For production, use a stateless API, PostgreSQL job/ownership records, Redis or a managed durable queue, bounded workers, and encrypted object storage with lifecycle deletion only where artefact retention is approved.

## Health checks

- `GET /health/live`: unauthenticated process liveness; exposes no dependency details.
- `GET /health/ready`: authenticated readiness; verifies required configuration.

## Release evidence

Every release should retain the commit SHA, CI result, dependency scan, container scan, SBOM, approved configuration, model/prompt versions and rollback procedure.
