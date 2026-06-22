# Production Readiness Plan

This page is the roadmap for taking video2doc-ai from its current
**Proof of Value (PoV)** state to a production deployment. It starts from a
gap analysis against the actual code and infrastructure in this repo today,
then lays out phased work, a go-live checklist, and a rough timeline.

Related reading: [Architecture](architecture.md#limitations-poc-scope) for
the underlying trade-offs, [Infrastructure](infrastructure.md) for the
current Bicep template, [Deployment](deployment.md) for the manual deploy
process this plan eventually automates end-to-end.

---

## 1. Gap analysis — PoV today vs. production requirement

| Area | Current state (PoV) | Production requirement | Risk if unaddressed |
|---|---|---|---|
| **Job execution** | Background `threading.Thread` inside the API process (`api/pipeline_runner.py`) | Durable, queued, horizontally scalable workers | A Container App crash/restart silently kills any in-flight job with no retry |
| **Concurrency** | One job effectively saturates a replica (CPU-bound ffmpeg + serialized AI calls) | Multiple jobs processed in parallel across workers | Pipeline backs up under real usage load |
| **Video length** | Speech REST API in ~55s chunks; practical ceiling ~10 min | Videos of any reasonable training/demo length | Long videos silently degrade in transcript quality or take excessively long |
| **Authentication** | None — `/api/jobs` is open to anyone with the URL | Azure AD (Entra ID) authenticated access | Unauthenticated uploads/cost abuse, exposure of generated docs |
| **CORS** | `allowedOrigins: ['*']` in `infra/main.bicep` | Restricted to the production SWA hostname | Any site can call the API cross-origin |
| **Secrets access** | Cognitive Services accounts have `disableLocalAuth: false` (key-based auth allowed) | Managed-Identity/RBAC-based auth wherever supported, keys disabled | Larger credential blast radius if a key leaks |
| **Automated tests** | None in the repo | Unit tests for `src/` modules (mocked Azure clients) + a CI smoke test in mock mode | Regressions ship straight to production undetected |
| **CI/CD** | Workflows exist (`deploy-app.yml`, `deploy-infra.yml`) but currently **fail at the Azure login step** — missing/invalid `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID` repo secrets | Working OIDC federated credentials, gated promotion across environments | Every deploy today is manual (`az acr build` + `az containerapp update`) |
| **Environments** | Single resource group, no dev/staging/prod separation | Isolated environments with a promotion path | No safe place to validate a change before it reaches real users |
| **Observability** | `print()` statements with step prefixes (`[pipeline]`, `[speech]`, …) read via `az containerapp logs show` | App Insights traces, Log Analytics queries, alerting | Failures are only visible if someone is actively watching the log stream |
| **AI quota management** | Manual `az cognitiveservices account deployment update` (done once already, see incident below) | Monitored quota with headroom alerts, or Provisioned Throughput for predictable load | Recurring `429 RateLimitError` under real traffic |
| **Frame selection** | Uniform time-based sampling (`FRAMES_PER_MINUTE`) | Content-aware key-frame selection (scene-change/diversity-based — already prototyped once in this repo's history and rolled back) | Either misses important screens or floods the doc with near-duplicates |
| **Data retention** | Job videos + state kept indefinitely in the `jobs` Blob container | Lifecycle policy (e.g. auto-delete after N days) | Unbounded storage cost; uploaded videos may contain sensitive screen content with no retention limit |
| **Data residency** | `GlobalStandard` GPT-4.1 SKU may route requests outside `francecentral` | `DataZoneStandard` SKU if strict EU residency is contractually required | Compliance exposure depending on customer data policies |
| **Disaster recovery** | Storage Account is `Standard_LRS` (locally redundant only) | Defined RTO/RPO; `Standard_GRS` or equivalent if required | Regional outage = data loss, not just downtime |

> **Recent real-world signal:** during PoV testing, GPT-4.1 hit its tokens-per-minute
> quota (`429 RateLimitError`) because `FRAMES_PER_MINUTE=12` produces a much
> richer visual context than the original `50K TPM` default anticipated. The
> deployment was bumped to `400K TPM` manually and the code now retries with
> backoff (see [Pipeline](pipeline.md#retry-on-rate-limiting)) — but this was
> a reactive fix under PoV load, not a capacity plan. Production needs the
> latter.

---

## 2. Phased plan

### Phase 0 — Stabilize the foundations (blocking, do first)

Nothing else in this plan can be automated until CI/CD actually works.

- [ ] Fix the GitHub Actions Azure login: create/repair the federated
      service principal and set `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
      `AZURE_SUBSCRIPTION_ID` as repo/environment secrets (see
      [Deployment → CI/CD setup](deployment.md#cicd-with-github-actions-optional))
- [ ] Add a `staging` and `prod` GitHub Environment, each with its own
      `AZURE_RESOURCE_GROUP` variable, so `environmentName`/`namePrefix` in
      `infra/main.bicep` map to genuinely separate resource groups
- [ ] Add a minimal automated test suite:
      - Unit tests for `src/transcribe.py`, `src/extract_frames.py`,
        `src/analyze_images.py`, `src/generate_docs.py` with mocked Azure
        SDK/HTTP calls
      - One CI smoke test that runs the pipeline end-to-end in full mock
        mode (`MOCK_TRANSCRIPTION=true MOCK_VISION=true`)
- [ ] Require CI green + at least one review before merge to `main`

### Phase 1 — Reliability & scale

- [ ] Replace the in-process background thread with a durable worker model:
      Azure Storage Queue (or Service Bus) + a dedicated worker (Azure
      Container Apps Jobs, or a separate always-running worker revision)
      pulling from the queue. A crash no longer loses in-flight jobs, and
      multiple jobs can run concurrently across worker instances.
- [ ] Move long-video transcription from REST chunking to the **Azure AI
      Speech Batch Transcription API** (async, no practical length limit)
- [ ] Make each pipeline step idempotent/resumable so a transient failure in
      step 4 doesn't force re-running steps 1–3
- [ ] Re-evaluate frame selection now that timestamp-sync is in place:
      revisit scene-change/diversity-based key-frame detection (previously
      prototyped on `main` and rolled back — the timestamp architecture this
      plan builds on didn't exist yet at that time)

### Phase 2 — Security & compliance

- [ ] Add authentication in front of the API — Azure Static Web Apps
      built-in auth (Entra ID) or Azure API Management as a gateway
- [ ] Restrict `corsPolicy.allowedOrigins` in `infra/main.bicep` to the
      production SWA hostname only
- [ ] Set `disableLocalAuth: true` on the Speech/Vision/Foundry Cognitive
      Services accounts where the SDKs support Managed-Identity/RBAC auth,
      removing the corresponding Key Vault secrets entirely where possible
- [ ] Define and implement a Blob lifecycle policy on the `jobs` container
      (e.g. delete video + frames after 7 days, keep `result.md` longer)
- [ ] Confirm data-residency requirements with stakeholders; switch to
      `DataZoneStandard` SKU in `main.bicep` if mandated
- [ ] Security review / pen-test pass on the upload endpoint — file
      type/size validation already exists server-side
      (`api/routers/jobs.py`); confirm it's sufficient or add malware
      scanning if required by policy

### Phase 3 — Observability & operations

- [ ] Instrument the API and pipeline with **Application Insights**:
      request traces, dependency calls to Speech/Vision/Foundry, custom
      events per pipeline step
- [ ] Route Container App logs to **Log Analytics**; convert the existing
      `print()` step-prefix logs (`[pipeline]`, `[speech]`, `[frames]`,
      `[vision]`, `[llm]`, `[embed]`) to structured JSON logging
- [ ] Define SLOs: job success rate, P50/P95 duration per step, AI service
      error rate
- [ ] Alerts: job failure rate above threshold, GPT-4.1 throttling rate,
      Container App health/restarts, subscription budget thresholds
- [ ] Extend the existing [Troubleshooting](deployment.md#troubleshooting)
      section into a real on-call runbook with escalation paths

### Phase 4 — Performance & cost optimization

- [ ] Set `minReplicas: 1` in production to avoid the 10–30s cold start on
      every first request after idle (keep `minReplicas: 0` in dev/staging)
- [ ] Evaluate **GPT-4.1 Provisioned Throughput (PTU)** vs. `GlobalStandard`
      pay-as-you-go once real usage volume is known, for predictable latency
      and to stop relying on manual TPM bumps
- [ ] Tune `FRAMES_PER_MINUTE` against pilot feedback — balance
      documentation richness against Vision API cost and pipeline duration
- [ ] Add a Blob lifecycle rule to move completed job artifacts to cool/archive
      tier after a retention window (ties into the Phase 2 retention policy)

### Phase 5 — Go-live

- [ ] Internal pilot (small set of real training/demo videos) → limited
      external pilot → general availability
- [ ] Rollback plan: keep the previous Container App revision pinned and
      ready to re-activate; confirm Bicep redeploys are safe to re-run
- [ ] Run the go-live checklist below before flipping any pilot to GA

---

## 3. Go-live checklist

| # | Item | Owner | Status |
|---|------|-------|--------|
| 1 | CI/CD green on `main`, deploys to staging automatically | DevOps | ☐ |
| 2 | Authenticated access enforced on the API | Backend | ☐ |
| 3 | CORS restricted to the production frontend origin | Backend | ☐ |
| 4 | Job processing durable across a Container App restart | Backend | ☐ |
| 5 | App Insights dashboards + failure alerts live | DevOps | ☐ |
| 6 | GPT-4.1 capacity sized (or PTU) for expected pilot volume | DevOps | ☐ |
| 7 | Blob retention/lifecycle policy applied to the `jobs` container | DevOps | ☐ |
| 8 | Data residency requirement confirmed and SKU set accordingly | Security/Compliance | ☐ |
| 9 | Automated test suite passing in CI | Backend | ☐ |
| 10 | Rollback procedure documented and tested once | DevOps | ☐ |

---

## 4. Rough timeline

T-shirt sizing assuming one backend engineer + part-time DevOps support;
adjust to actual team size.

| Phase | Effort | Depends on |
|---|---|---|
| 0 — Stabilize foundations | 1–2 weeks | — |
| 1 — Reliability & scale | 2–4 weeks | Phase 0 |
| 2 — Security & compliance | 2–3 weeks | Phase 0 (can run in parallel with Phase 1) |
| 3 — Observability & operations | 1–2 weeks | Phase 0 (can run in parallel) |
| 4 — Performance & cost optimization | 1 week + ongoing tuning | Phase 1 (needs real worker model first) |
| 5 — Go-live | 1–2 weeks (pilot ramp) | All above |

**Total: roughly 8–12 weeks** to a production-ready GA, with Phases 1–3
parallelizable across more than one engineer.

---

## 5. What can stay as-is

Not everything needs rework — these PoV decisions are already
production-appropriate:

- **Bicep IaC** — the single-template, parameterized approach
  (`environmentName`, `namePrefix`) already supports multi-environment
  deployment; Phase 0 just needs to wire it into CI/CD per environment.
- **Key Vault + Managed Identity** — no credentials in plaintext anywhere;
  this model extends cleanly to RBAC-only access in Phase 2.
- **Blob-backed job state** — stateless API design scales horizontally
  without code changes once the worker model lands in Phase 1.
- **Diátaxis prompt design and timestamp-sync architecture** — the actual
  documentation quality logic (`src/generate_docs.py`) needs no rework for
  production; it's an execution/ops problem, not a content-quality one.
