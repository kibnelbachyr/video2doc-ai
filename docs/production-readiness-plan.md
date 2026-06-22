# Production Readiness Plan

This page is the roadmap for taking video2doc-ai from its current
**Proof of Value (PoV)** state to a production deployment, organized around
the main milestones rather than a granular task list.

Two phases:

- **Phase 1 — Production-ready (M1–M6)**: gets a single pilot/GA deployment
  live safely. Sufficient for one team or one business unit.
- **Phase 2 — Enterprise scale (M7–M10)**: required before rolling out across
  multiple tenants/business units, or to any customer with security,
  compliance, or FinOps requirements beyond a single pilot.

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
| 5 | 1 | **Performance & cost** | Capacity and spend match real usage, not PoV guesses | M2 |
| 6 | 1 | **Go-live** | Pilot → GA, with a rollback plan in place | M1–M5 |
| 7 | 2 | **Multi-tenancy & enterprise identity** | Multiple business units/customers run isolated, with a full audit trail | M6 |
| 8 | 2 | **Data governance & disaster recovery** | Defined RTO/RPO, per-tenant retention, encryption with customer-managed keys | M6 |
| 9 | 2 | **AI safety & content governance** | Uploaded content and LLM output are moderated and rate-limited per tenant | M6 |
| 10 | 2 | **FinOps at scale** | Cost is tagged, charged back, and capped per tenant/business unit | M6, M5 |

### M1 — CI/CD & foundations

The blocking milestone — nothing else here can roll out safely without it.

- Fix the GitHub Actions Azure login (federated credentials,
  `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_SUBSCRIPTION_ID` secrets) so
  `deploy-app.yml` / `deploy-infra.yml` actually run
  ([setup details](deployment.md#cicd-with-github-actions-optional))
- Separate `staging` and `prod` environments with their own resource groups
- A minimal automated test suite (unit tests for `src/`, one mock-mode smoke
  test) gating merges to `main`

### M2 — Reliability & scale

- Replace the in-process background thread
  (`api/pipeline_runner.py`) with a durable queue + worker model, so a
  Container App restart doesn't silently kill an in-flight job
- Move long-video transcription to the Azure AI Speech **Batch
  Transcription API** to remove the practical ~10 min ceiling
- Revisit content-aware frame selection now that timestamp-sync exists
- **Load-test the queue/worker model at projected enterprise peak**
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
- Third-party penetration test before any enterprise-wide rollout

### M4 — Observability

- Application Insights traces + Log Analytics, replacing `print()` logs
- SLOs (job success rate, P50/P95 duration) and alerts (failure rate,
  GPT-4.1 throttling, Container App health, budget)

### M5 — Performance & cost

- Size GPT-4.1 capacity for real load (PTU vs. `GlobalStandard`), ending the
  manual TPM-bump cycle (see the real incident in
  [Pipeline → retry on rate limiting](pipeline.md#retry-on-rate-limiting))
- `minReplicas: 1` in prod to remove cold starts; tune `FRAMES_PER_MINUTE`
  against pilot feedback

### M6 — Go-live

- Internal pilot → limited external pilot → GA
- Rollback plan tested once before the first real pilot
- Gate GA on the checklist below

---

## Phase 2 — Enterprise scale

Phase 1 gets one team to GA safely. None of M7–M10 is needed for that — they
become required once the solution serves **multiple tenants, business
units, or any customer with formal security/compliance/cost requirements**.

### M7 — Multi-tenancy & enterprise identity

- Full Entra ID integration (not just basic auth): SSO, RBAC roles
  (Admin / Uploader / Viewer), tenant-aware token validation
- Per-tenant resource isolation — separate Blob containers/prefixes at
  minimum; separate resource groups for tenants with stricter compliance
  needs
- Audit log of every job submission and result access (who, what, when) —
  currently nothing records this beyond ephemeral container logs

### M8 — Data governance & disaster recovery

- Move Storage redundancy from `Standard_LRS` (single-datacenter, no
  failover) to `ZRS`/`GRS` based on the tenant's actual SLA
- Customer-managed keys (CMK) in Key Vault for encryption at rest, where
  contractually required
- Per-tenant Blob retention policy and a "right to delete" workflow (the
  PoV currently has neither — see M3)
- Defined and **tested** RTO/RPO — a documented DR drill, not just a
  written plan
- Data residency confirmed per tenant contract (`DataZoneStandard` vs
  regional pinning — see `infra/main.bicep` comment on `aiFoundry`)

### M9 — AI safety & content governance

- Content moderation on uploaded video/audio before processing (e.g.
  Azure AI Content Safety) — nothing screens input today
- Guardrails against prompt injection via OCR/caption text that flows
  directly into the GPT-4.1 prompt (`src/generate_docs.py`) — captions and
  on-screen text are attacker-controllable if a malicious video is uploaded
- Per-tenant rate limiting / abuse detection to cap runaway GPT-4.1 spend
  from a single bad actor or misconfigured integration
- Responsible AI sign-off before enterprise GA

### M10 — FinOps at scale

- Per-tenant cost tagging and chargeback/showback dashboards (see
  [Cost Estimation](cost-estimation.md) for the current single-tenant model)
- Revisit GPT-4.1 Provisioned Throughput (PTU) once real multi-tenant
  volume is known — the 15-PTU minimum (~$3,900/month) only pays off well
  above pilot-scale usage
- Budget alerts with an automatic circuit breaker (pause new job intake if
  a tenant or the subscription crosses its monthly threshold)

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
| 8 | Rollback procedure documented and tested once | M6 |

## Enterprise-readiness checklist (Phase 2)

| # | Item | Milestone |
|---|------|-----------|
| 9 | SSO/Entra ID with RBAC roles; per-tenant resource isolation | M7 |
| 10 | Audit log live for job submission + result access | M7 |
| 11 | Storage redundancy upgraded (ZRS/GRS) per tenant SLA; RTO/RPO tested via a real DR drill | M8 |
| 12 | Per-tenant retention + right-to-delete workflow live | M8 |
| 13 | Content moderation on uploads; prompt-injection guardrails on OCR/caption text | M9 |
| 14 | Per-tenant rate limiting and budget circuit breaker live | M9, M10 |
| 15 | Network isolation (private endpoints) + WAF/APIM in front of the API; pen test passed | M3 |
| 16 | Per-tenant cost tagging and chargeback dashboard live | M10 |

---

## Rough timeline

| Milestone | Effort |
|---|---|
| 1 — CI/CD & foundations | 1–2 weeks |
| 2 — Reliability & scale | 2–4 weeks |
| 3 — Security & compliance | 3–5 weeks (parallel with M2; network isolation/WAF/pen-test add time vs. Phase 1 alone) |
| 4 — Observability | 1–2 weeks (parallel with M2/M3) |
| 5 — Performance & cost | 1 week + ongoing tuning |
| 6 — Go-live | 1–2 weeks (pilot ramp) |
| **Phase 1 subtotal** | **≈ 9–14 weeks** |
| 7 — Multi-tenancy & enterprise identity | 3–5 weeks |
| 8 — Data governance & DR | 3–4 weeks (parallel with M7) |
| 9 — AI safety & content governance | 2–3 weeks (parallel with M7/M8) |
| 10 — FinOps at scale | 1–2 weeks |
| **Phase 2 subtotal** | **≈ 6–9 weeks** (M7–M9 parallelizable) |

**Total: roughly 15–23 weeks** end-to-end (Phase 1 + Phase 2), assuming one
backend engineer plus part-time DevOps/security support, with M2–M4 and
M7–M9 each parallelizable across more than one engineer. Phase 1 alone
(8–12 weeks, single-pilot scale) remains accurate if enterprise rollout
isn't on the immediate roadmap.

---

## What can stay as-is

- **Bicep IaC** — the parameterized template already supports
  multi-environment deployment; M1 just wires it into CI/CD per environment.
- **Key Vault + Managed Identity** — no plaintext credentials anywhere;
  extends cleanly to RBAC-only access in M3.
- **Blob-backed job state** — stateless API design scales horizontally
  without code changes once the worker model lands in M2.
- **Diátaxis prompt design and timestamp-sync architecture** — the
  documentation quality logic (`src/generate_docs.py`) needs no rework for
  production.
