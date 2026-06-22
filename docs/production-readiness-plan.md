# Production Readiness Plan

This page is the roadmap for taking video2doc-ai from its current
**Proof of Value (PoV)** state to a production deployment, organized around
the main milestones rather than a granular task list.

This is a single-customer, internal-use deployment — there is no multi-tenancy
requirement. Two phases:

- **Phase 1 — Production-ready (M1–M6)**: gets the deployment live safely for
  internal pilot → GA use.
- **Phase 2 — Enterprise hardening (M7–M10)**: identity, data governance, AI
  safety, and UI maturity expected of an internal enterprise tool, scoped to
  one organization — no per-tenant isolation, chargeback, or multi-tenant UI.

Related reading: [Architecture](architecture.md#limitations-poc-scope) for
the underlying trade-offs, [Infrastructure](infrastructure.md) for the
current Bicep template, [Deployment](deployment.md) for the manual deploy
process Milestone 1 automates end-to-end.

---

## Milestones

| # | Phase | Milestone | Goal | Depends on |
|---|---|---|---|---|
| 1 | 1 | **CI/CD & foundations** | Every change to `main` is built, tested, and deployed automatically to a real environment | — |
| 2 | 1 | **Reliability & scale** | Jobs survive a crash/restart and run concurrently; long videos are supported; load-tested at projected peak | M1 |
| 3 | 1 | **Security & compliance** | API is authenticated, CORS locked down, network isolated, data retention/residency defined | M1 (parallel with M2) |
| 4 | 1 | **Observability** | Failures and performance are visible without tailing logs | M1 (parallel with M2/M3) |
| 5 | 1 | **Performance, cost & output quality** | Capacity, spend, and documentation quality match real usage, not PoV guesses | M2 |
| 6 | 1 | **Go-live** | Pilot → GA, with support, rollback, and user-facing docs in place | M1–M5 |
| 7 | 2 | **Identity & access governance** | SSO via the org's own Entra ID, RBAC roles, and a full audit trail | M6 |
| 8 | 2 | **Data governance & disaster recovery** | Defined RTO/RPO, retention policy, encryption with customer-managed keys | M6 |
| 9 | 2 | **AI safety & content governance** | Uploaded content and LLM output are moderated and rate-limited | M6 |
| 10 | 2 | **UI/UX modernization** | The frontend is a maintainable, accessible product — not a single static page | M7 |

### M1 — CI/CD & foundations

The blocking milestone — nothing else here can roll out safely without it.

- Fix the GitHub Actions Azure login (federated credentials,
  `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_SUBSCRIPTION_ID` secrets) so
  `deploy-app.yml` / `deploy-infra.yml` actually run
  ([setup details](deployment.md#cicd-with-github-actions-optional))
- Separate `staging` and `prod` environments with their own resource groups
  and parameter files (`main.staging.bicepparam`, `main.prod.bicepparam`)
  instead of the single `main.bicepparam` today
- A minimal automated test suite (unit tests for `src/`, one mock-mode smoke
  test) gating merges to `main`
- IaC validation gate in CI: `az bicep lint` + `what-if` against the target
  environment before any `deploy-infra.yml` apply — `infra/main.bicep`
  deploys directly today with no preview/validation step
- Drift detection: a scheduled `what-if` run against each deployed
  environment, alerting if manual portal changes diverge from the template

### M2 — Reliability & scale

- Replace the in-process background thread
  (`api/pipeline_runner.py`) with a durable queue + worker model, so a
  Container App restart doesn't silently kill an in-flight job
- Move long-video transcription to the Azure AI Speech **Batch
  Transcription API** to remove the practical ~10 min ceiling
- Revisit content-aware frame selection now that timestamp-sync exists
- **Load-test the queue/worker model at projected internal peak**
  (concurrent uploads, queue backpressure, autoscale behavior under burst)
  before trusting it beyond a single pilot's volume

### M3 — Security & compliance

- Authenticated access in front of the API (Entra ID via SWA or APIM)
- Restrict `corsPolicy.allowedOrigins` in `infra/main.bicep` to the
  production frontend only
- Blob lifecycle/retention policy on the `jobs` container
- Confirm data-residency needs (`DataZoneStandard` SKU if required)
- **Network isolation**: VNet integration + private endpoints for Storage,
  Key Vault, and the AI services — public network access is `Enabled` on
  all of them today (`infra/main.bicep`)
- **WAF/API gateway** (Azure API Management or Front Door) in front of the
  Container App, replacing the current open public ingress
- Container image scanning gate in CI (Defender for Containers or
  equivalent) before pushing to ACR
- Third-party penetration test before GA

### M4 — Observability

- Application Insights traces + Log Analytics, replacing `print()` logs
- SLOs (job success rate, P50/P95 duration) and alerts (failure rate,
  GPT-4.1 throttling, Container App health, budget)

### M5 — Performance, cost & output quality

- Size GPT-4.1 capacity for real load (PTU vs. `GlobalStandard`), ending the
  manual TPM-bump cycle (see the real incident in
  [Pipeline → retry on rate limiting](pipeline.md#retry-on-rate-limiting))
- `minReplicas: 1` in prod to remove cold starts; tune `FRAMES_PER_MINUTE`
  against pilot feedback
- A golden-set evaluation: a held-out batch of representative videos with
  human-scored expected documentation quality, re-run whenever the prompt
  or model changes — there is currently no regression check on output
  quality, only on whether the pipeline runs without error
- Pilot user feedback loop (a simple rating per generated doc) feeding back
  into prompt iteration in `src/generate_docs.py`
- Track model lifecycle risk: the GPT-4.1 deployment uses
  `versionUpgradeOption: 'OnceNewDefaultVersionAvailable'`
  (`infra/main.bicep`), so Microsoft can auto-upgrade the model version
  under a live pilot — decide whether to pin a version before GA
- Budget alert with an automatic circuit breaker (pause new job intake if
  the subscription crosses its monthly threshold) — see
  [Cost Estimation](cost-estimation.md) for the current pay-as-you-go model
- Revisit GPT-4.1 Provisioned Throughput (PTU) once real internal volume is
  known — the 15-PTU minimum (~$3,900/month) only pays off well above
  pilot-scale usage

### M6 — Go-live

- Pilot with one team → broader internal rollout → GA
- Rollback plan tested once before the first real pilot
- On-call rotation and an incident response runbook in place before the
  first pilot user — today an outage is only visible to whoever happens to
  be tailing logs
- End-user/admin guide published — `docs/` today is entirely developer-
  facing (architecture, API, deployment); pilot users need their own
  getting-started and troubleshooting doc
- Gate GA on the checklist below

---

## Phase 2 — Enterprise hardening

Phase 1 gets the team to GA safely for internal use. M7–M10 are what an
internal enterprise tool still needs beyond that — identity, governance,
safety, and a maintainable UI — scoped to **one organization, not multiple
tenants**, so there's no per-tenant isolation, chargeback, or tenant
management surface here.

### M7 — Identity & access governance

- Full Entra ID integration (not just basic auth): SSO against the org's
  own tenant, RBAC roles (Admin / Uploader / Viewer)
- Audit log of every job submission and result access (who, what, when) —
  currently nothing records this beyond ephemeral container logs
- API versioning (`/api/v1/jobs`, …) with a deprecation policy —
  [`docs/api.md`](api.md) has no version prefix today, so any breaking
  change to the contract has no safe rollout path

### M8 — Data governance & disaster recovery

- Move Storage redundancy from `Standard_LRS` (single-datacenter, no
  failover) to `ZRS`/`GRS` based on the org's actual SLA
- Customer-managed keys (CMK) in Key Vault for encryption at rest, where
  required by internal security policy
- A Blob retention policy and a "right to delete" workflow (the PoV
  currently has neither — see M3)
- Defined and **tested** RTO/RPO — a documented DR drill, not just a
  written plan
- Data residency confirmed (`DataZoneStandard` vs regional pinning — see
  `infra/main.bicep` comment on `aiFoundry`)

### M9 — AI safety & content governance

- Content moderation on uploaded video/audio before processing (e.g.
  Azure AI Content Safety) — nothing screens input today
- Guardrails against prompt injection via OCR/caption text that flows
  directly into the GPT-4.1 prompt (`src/generate_docs.py`) — captions and
  on-screen text are attacker-controllable if a malicious video is uploaded
- Rate limiting / abuse detection to cap runaway GPT-4.1 spend from a
  misconfigured integration or a single bad actor
- Responsible AI sign-off before GA

### M10 — UI/UX modernization

`ui/` is a single hand-written `index.html` + `app.js` (no framework,
French-only — `<html lang="fr">`), fine for a PoV demo, not for a
maintainable internal product surface.

- Migrate to a component framework (React/Vue) once the UI needs more than
  upload → poll → render
- Job history / management view (list past jobs, re-download results,
  re-run failed jobs) — today a job is only visible while its `job_id` is
  in the browser's URL/state
- Internationalization — UI is hardcoded French today, despite the
  generated documentation already supporting French/English output
  (see [Pipeline](pipeline.md))
- Accessibility (WCAG 2.1 AA) and responsive/mobile layout pass

---

## Go-live checklist

| # | Item | Milestone |
|---|------|-----------|
| 1 | CI/CD green on `main`, auto-deploys to staging | M1 |
| 2 | Automated test suite passing in CI | M1 |
| 3 | Job processing durable across a Container App restart | M2 |
| 4 | Authenticated access + restricted CORS enforced | M3 |
| 5 | Data retention/residency requirements applied | M3 |
| 6 | App Insights dashboards + failure alerts live | M4 |
| 7 | GPT-4.1 capacity sized (or PTU) for expected pilot volume | M5 |
| 8 | Output quality evaluated against a golden set; model version pinned or upgrade risk accepted | M5 |
| 9 | Rollback procedure documented and tested once | M6 |
| 10 | On-call rotation and incident response runbook in place | M6 |
| 11 | End-user/admin guide published | M6 |

## Enterprise-readiness checklist (Phase 2)

| # | Item | Milestone |
|---|------|-----------|
| 12 | SSO/Entra ID with RBAC roles live | M7 |
| 13 | Audit log live for job submission + result access | M7 |
| 14 | API versioned with a deprecation policy | M7 |
| 15 | Storage redundancy upgraded (ZRS/GRS) per SLA; RTO/RPO tested via a real DR drill | M8 |
| 16 | Retention + right-to-delete workflow live | M8 |
| 17 | Content moderation on uploads; prompt-injection guardrails on OCR/caption text | M9 |
| 18 | Rate limiting and budget circuit breaker live | M9 |
| 19 | Network isolation (private endpoints) + WAF/APIM in front of the API; pen test passed | M3 |
| 20 | UI on a maintainable framework with job history and i18n | M10 |

---

## Rough timeline

| Milestone | Effort |
|---|---|
| 1 — CI/CD & foundations | 1–2 weeks |
| 2 — Reliability & scale | 2–4 weeks |
| 3 — Security & compliance | 3–5 weeks (parallel with M2; network isolation/WAF/pen-test add time vs. Phase 1 alone) |
| 4 — Observability | 1–2 weeks (parallel with M2/M3) |
| 5 — Performance, cost & output quality | 1–2 weeks + ongoing tuning (golden-set eval adds time vs. tuning alone) |
| 6 — Go-live | 2–3 weeks (pilot ramp, on-call setup, end-user docs) |
| **Phase 1 subtotal** | **≈ 10–16 weeks** |
| 7 — Identity & access governance | 2–3 weeks |
| 8 — Data governance & DR | 2–3 weeks (parallel with M7) |
| 9 — AI safety & content governance | 2–3 weeks (parallel with M7/M8) |
| 10 — UI/UX modernization | 3–4 weeks (needs a frontend engineer) |
| **Phase 2 subtotal** | **≈ 6–9 weeks** (M7–M9 parallelizable across two engineers) |

**Total: roughly 16–25 weeks** end-to-end (Phase 1 + Phase 2), assuming one
backend engineer plus part-time DevOps/security support, with a frontend
engineer added for M10. M2–M4 and M7–M9 are each parallelizable across more
than one engineer. Phase 1 alone (10–16 weeks, current vanilla-JS UI kept)
remains accurate if the M7–M10 hardening work isn't on the immediate roadmap.

---

## What can stay as-is

- **Bicep as the IaC tool** — no need to switch to Terraform/Pulumi; M1
  wires the existing template into CI/CD per environment with its own
  parameter files, it doesn't replace it.
- **Key Vault + Managed Identity** — no plaintext credentials anywhere;
  extends cleanly to RBAC-only access in M3.
- **Blob-backed job state** — stateless API design scales horizontally
  without code changes once the worker model lands in M2.
- **Diátaxis prompt design and timestamp-sync architecture** — the
  documentation quality logic (`src/generate_docs.py`) needs no rework for
  production.
- **Upload → poll → render interaction model** — M10 changes the
  implementation (framework, i18n) but not this core UX flow, which
  already works well for the PoV's single-job use case.
