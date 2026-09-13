# Security policy

## Supported version

Only the current default branch is supported.

## Reporting a vulnerability

Do not open a public issue. Report suspected vulnerabilities privately to the repository owner through GitHub's private vulnerability reporting facility. Include reproduction steps, affected versions and potential data exposure. Do not include real client data or credentials.

## Deployment boundary

BRIEF processes potentially confidential research material. Production deployments must use organisational identity controls, a dedicated OpenAI project credential held in a secret manager, restricted outbound networking, payload logging disabled by default, explicit retention settings, workload limits and encrypted governed storage where retention is approved.

The shared Basic-authentication option is a pilot fallback only. It is not an organisational identity or authorisation system.

## Data handling defaults

- Raw prompt and response logging is disabled.
- OpenAI Responses requests set `store=False`.
- Web grounding is disabled until explicitly enabled.
- Uploaded originals and generated exports are handled in memory.
- Operators must independently confirm their OpenAI project retention and regional-processing controls.

## Operational response

If exposure is suspected: disable ingress, revoke the OpenAI service credential, preserve redacted operational evidence, identify affected jobs and users, follow the organisation's incident process, and notify the data owner before restoring service.
