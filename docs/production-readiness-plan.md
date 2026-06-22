# Production Readiness Plan

This page is the roadmap for taking video2doc-ai from its current
**Proof of Value (PoV)** state to a production deployment, organized around
the main milestones rather than a granular task list.

Related reading: [Architecture](architecture.md#limitations-poc-scope) for
the underlying trade-offs, [Infrastructure](infrastructure.md) for the
current Bicep template, [Deployment](deployment.md) for the manual deploy
process Milestone 1 automates end-to-end.

---

## Milestones

| # | Milestone | Goal | Depends on |
|---|---|---|---|
| 1 | **CI/CD & foundations** | Every change to `main` is built, tested, and deployed automatically to a real environment | — |
| 2 | **Reliability & scale** | Jobs survive a crash/restart and run concurrently; long videos are supported | M1 |
| 3 | **Security & compliance** | API is authenticated, CORS locked down, data retention/residency defined | M1 (parallel with M2) |
| 4 | **Observability** | Failures and performance are visible without tailing logs | M1 (parallel with M2/M3) |
| 5 | **Performance & cost** | Capacity and spend match real usage, not PoV guesses | M2 |
| 6 | **Go-live** | Pilot → GA, with a rollback plan in place | M1–M5 |

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

### M3 — Security & compliance

- Authenticated access in front of the API (Entra ID via SWA or APIM)
- Restrict `corsPolicy.allowedOrigins` in `infra/main.bicep` to the
  production frontend only
- Blob lifecycle/retention policy on the `jobs` container
- Confirm data-residency needs (`DataZoneStandard` SKU if required)

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

---

## Rough timeline

| Milestone | Effort |
|---|---|
| 1 — CI/CD & foundations | 1–2 weeks |
| 2 — Reliability & scale | 2–4 weeks |
| 3 — Security & compliance | 2–3 weeks (parallel with M2) |
| 4 — Observability | 1–2 weeks (parallel with M2/M3) |
| 5 — Performance & cost | 1 week + ongoing tuning |
| 6 — Go-live | 1–2 weeks (pilot ramp) |

**Total: roughly 8–12 weeks** to a production-ready GA, assuming one backend
engineer plus part-time DevOps support, with M2–M4 parallelizable across more
than one engineer.

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
