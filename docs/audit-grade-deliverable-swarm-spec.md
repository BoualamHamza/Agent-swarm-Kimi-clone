# Audit-Grade Deliverable Swarm Specification

## 1. Executive Summary

Agent Swarm should evolve from a general multi-agent demo into an
audit-grade deliverable engine: a local-first system that turns messy research,
analysis, and business tasks into verified artifacts such as spreadsheets,
decks, reports, datasets, charts, and briefs.

The system should not compete primarily as another agent framework. Existing
solutions already cover broad orchestration patterns: code-first agent SDKs,
graph workflows, multi-agent crews, hosted tools, MCP connectors, tracing, and
human review. The stronger opportunity is to own the layer those frameworks
still leave painful: producing concrete deliverables that can be trusted,
inspected, replayed, validated, and improved.

The product thesis:

> Agent Swarm should become a mission-control system for verified deliverables:
> parallel specialists gather evidence, builders create artifacts, validators
> audit the result, and the user receives both the deliverable and the proof
> trail.

The first high-value wedge should be:

> Research or data task -> verified spreadsheet, deck, report, or dataset.

Examples:

- Compare competitors and produce a cited market landscape deck.
- Scrape pricing pages and generate an Excel comparison workbook.
- Analyze a CSV and produce a clean memo with charts.
- Build an investor-ready market model with assumptions and sources.
- Audit a spreadsheet and produce a corrected workbook plus explanation.

This direction fits the current repo because it already has:

- An orchestrator that spawns parallel worker cohorts.
- Shared memory for cross-agent findings.
- A shared E2B sandbox for file, Python, and shell work.
- Procedural skills for xlsx, pptx, analysis, scraping, finance, and files.
- Artifact harvesting.
- A Textual TUI that already exposes live agent state.
- Tests around orchestration, tool loops, memory, sandbox, artifacts, and TUI
  event routing.

The next version should make trust, validation, provenance, and artifact quality
the product center of gravity.

## 2. Market Context

### 2.1 Existing Solutions

The agent ecosystem is crowded and moving quickly.

OpenAI Agents SDK focuses on code-first agents where the application owns
orchestration, tools, approvals, state, tracing, and runtime behavior. It is a
good fit for developers building agent apps directly into their product logic.

Microsoft Agent Framework combines agent abstractions with enterprise workflow
features such as type-safe routing, telemetry, state management, graph-based
workflows, and human-in-the-loop patterns.

LangGraph provides durable graph execution, checkpointing, state history,
replay, persistence, and explicit workflow control. It is strong when the
developer wants precise graph-level behavior.

CrewAI popularized role-based multi-agent crews and workflow flows. It is
accessible for teams thinking in terms of agent roles and repeated automations.

MCP is becoming the interoperability layer for tools, resources, and prompts.
It makes tool/context integration more portable across model vendors and agent
clients.

These platforms solve much of the "how do I wire agents together?" problem.
They do not fully solve the "how do I know the deliverable is correct,
complete, source-backed, cheap enough, and safe to use?" problem.

### 2.2 Current Pain Points

Agent systems still fail in recognizable ways:

- They produce plausible prose but weak artifacts.
- They cite sources inconsistently or lose provenance during synthesis.
- Parallel agents duplicate work or conflict without reconciliation.
- Builder agents run before upstream research is available.
- Long-horizon tasks fail because small errors compound.
- Tool calls are hard to audit after the run.
- Costs are opaque until the bill arrives.
- Security and permissions are too coarse.
- Human-in-the-loop often means a final approval button instead of meaningful
  intervention at decision points.
- Evaluation is usually accuracy-only, ignoring cost, latency, reliability,
  security, and policy compliance.
- Users cannot easily replay a failed run from a meaningful checkpoint.

Agent Swarm can create value by designing directly against those failures.

## 3. Positioning

### 3.1 One-Sentence Positioning

Agent Swarm is an observable multi-agent workspace for producing verified
business and research artifacts with evidence, validation, and replayable
execution.

### 3.2 What It Is

- A deliverable-focused multi-agent runtime.
- A local-first analyst/consultant/research ops machine.
- A system for parallel evidence gathering followed by controlled artifact
  building and validation.
- A traceable workspace that shows what each agent did and why the final output
  can be trusted.

### 3.3 What It Is Not

- Not a generic replacement for LangGraph, CrewAI, AutoGen, or OpenAI Agents
  SDK.
- Not primarily a coding agent.
- Not a general chatbot.
- Not a "more agents is better" demo.
- Not a web-search summarizer.
- Not a black-box automation platform.

### 3.4 Differentiation

The differentiator should be:

- Verified artifacts, not just text.
- Evidence manifests, not just answers.
- Cohort discipline, not chaotic agent chatter.
- Skill-driven builders and validators, not generic tool loops.
- Source-backed shared memory, not transient context.
- Cost-aware orchestration, not unbounded autonomy.
- Replayable runs, not one-shot traces.

## 4. Target Users

### 4.1 Primary Persona: Independent Analyst or Founder

This user needs high-quality research and artifacts quickly. They may be making
investor decks, pricing comparisons, market maps, financial models, product
briefs, or competitive research.

Pain points:

- Manual research takes too long.
- AI gives useful drafts but weak evidence.
- Spreadsheets and decks require tedious cleanup.
- The user still needs to inspect assumptions and sources.

Success looks like:

- A useful first-pass deliverable in minutes.
- A clear list of assumptions and source URLs.
- An editable artifact in a common format.
- Confidence about which parts are verified and which parts need review.

### 4.2 Secondary Persona: Data or Ops Team

This user repeats similar workflows: weekly analysis, pricing refreshes,
vendor comparisons, internal reports, dashboard extracts, or spreadsheet QA.

Pain points:

- Repetitive workflows vary slightly each time.
- Existing automation is brittle.
- Manual QA is slow.
- Tool credentials and data boundaries matter.

Success looks like:

- Reusable workflow templates.
- Configurable validation gates.
- Session memory and artifact history.
- Permissioned tools and activity logs.

### 4.3 Tertiary Persona: Developer Building Agent Workflows

This user wants to experiment with multi-agent systems without losing
observability or artifact quality.

Pain points:

- Agent frameworks can feel abstract.
- Debugging multi-agent behavior is painful.
- It is hard to know which prompt or tool call caused an artifact defect.

Success looks like:

- Clear event stream.
- Inspectable shared memory.
- Artifact QA hooks.
- Easy extension through skills and tools.

## 5. Product Principles

### 5.1 Deliverables Over Dialogue

The system should optimize for useful outputs the user can open, edit, send,
or build on. Conversation is a control surface, not the product.

### 5.2 Evidence Is A First-Class Output

Every meaningful claim should be traceable to a source, calculation, uploaded
file, or explicit assumption. Missing evidence should be visible, not hidden in
polished prose.

### 5.3 Cohorts Encode Dependencies

Workers in the same cohort run in parallel and cannot depend on each other's
writes. Work that depends on upstream outputs must run in later cohorts. This
should remain a core architectural rule.

### 5.4 Skills Are Contracts

Skills should be treated as procedural contracts with expected inputs,
outputs, validation steps, and failure modes. A worker assigned the xlsx skill
should not merely "know about spreadsheets"; it should follow a repeatable
workbook production protocol.

### 5.5 Validation Is Part Of The Workflow

Builders should not be the final step. Validators should inspect artifacts,
run scripts, check placeholders, verify formulas, inspect source coverage, and
produce an explicit validation result.

### 5.6 Human Review Should Happen At Meaningful Gates

The system should ask for human input before high-impact actions, ambiguous
scoping decisions, expensive execution, or publishing/exporting. Human review
should not be only a final approve button.

### 5.7 Cheap Failures Are Better Than Expensive Drift

The runtime should detect missing evidence, empty memory, artifact absence,
tool overuse, and iteration caps early. It should stop or reroute before
producing polished nonsense.

### 5.8 Local-First, Portable Later

The system should work well as a local CLI/TUI first, then expose API surfaces
for hosted use. Local-first keeps iteration fast and helps developers trust the
execution model.

## 6. Core Use Cases

### 6.1 Competitive Pricing Workbook

Input:

- A natural-language task such as "Compare Orange, Free, Bouygues, and SFR
  home internet pricing in France and create an Excel comparison dashboard."

Workflow:

1. Orchestrator classifies the task as research -> xlsx.
2. Research cohort spawns one worker per vendor.
3. Each worker writes structured offers, fees, URLs, dates, caveats, and raw
   source extracts to shared memory.
4. Orchestrator verifies memory keys exist.
5. Builder worker reads all vendor findings and creates workbook artifacts.
6. Validator worker runs recalc, chart lint, placeholder scan, and source
   coverage checks.
7. Final answer links workbook, manifest, and validation result.

Outputs:

- `.xlsx` comparison workbook.
- `manifest.json` listing claims, sources, assumptions, and workers.
- `validation.md` explaining checks and remaining risks.

### 6.2 Market Landscape Deck

Input:

- "Build a 10-slide market landscape deck for AI-powered procurement tools."

Workflow:

1. Research workers split by market sizing, competitors, customer pain,
   pricing, and trends.
2. Synthesis worker reconciles overlapping findings.
3. Deck builder produces PPTX.
4. Deck validator renders thumbnails, checks slide count, detects placeholders,
   checks citations, and flags weak claims.

Outputs:

- `.pptx` deck.
- Slide thumbnails.
- Source manifest.
- Validation report.

### 6.3 Data Analysis Memo

Input:

- A CSV uploaded into the sandbox or already in the workspace.

Workflow:

1. File profiler inspects schema, missingness, outliers, and row counts.
2. Analyst worker computes descriptive stats and hypotheses.
3. Chart worker generates figures.
4. Memo builder writes markdown or docx.
5. Validator checks that reported numbers match computed values.

Outputs:

- Markdown or docx memo.
- Cleaned dataset if requested.
- Charts.
- Calculation manifest.

### 6.4 Spreadsheet Audit

Input:

- Existing workbook.

Workflow:

1. Workbook inspector maps sheets, formulas, ranges, charts, and external links.
2. Formula auditor checks broken references, suspicious constants, and formula
   inconsistencies.
3. Recalc validator opens/recalculates workbook.
4. Report builder produces an issue report and optionally a corrected workbook.

Outputs:

- Audit report.
- Corrected workbook if authorized.
- List of risky formulas and assumptions.

### 6.5 Repeatable Research Refresh

Input:

- A saved workflow template with target sites and expected outputs.

Workflow:

1. Orchestrator loads a prior session template.
2. Research workers refresh known sources.
3. Diff worker compares old and new findings.
4. Builder updates artifacts.
5. Validator flags material changes.

Outputs:

- Updated artifact.
- Change log.
- Source freshness report.

## 7. User Experience Specification

### 7.1 Main User Flow

1. User enters a task in the TUI or API.
2. System classifies task type and expected deliverables.
3. System shows an execution plan:
   - proposed cohorts
   - expected artifact types
   - tools/skills required
   - estimated cost range
   - validation gates
4. User can approve, edit, or run with defaults.
5. Agents execute in visible cohorts.
6. The TUI shows:
   - current phase
   - worker roster
   - memory writes
   - tool calls
   - artifact status
   - validation status
7. Final result includes:
   - artifact links
   - validation result
   - source/evidence manifest
   - caveats
   - suggested next actions

### 7.2 TUI Navigation

The current TUI can evolve into four primary panels:

- Mission: task, plan, current phase, final answer.
- Agents: roster, per-agent trace, tool calls, status.
- Evidence: shared memory, source claims, assumptions, citations.
- Artifacts: files, previews, validation results, manifests.

The user should be able to answer these questions from the UI:

- What is the swarm doing right now?
- Which worker produced this claim?
- Which source supports this number?
- Which artifacts were created?
- Which validation checks passed or failed?
- What still needs human review?

### 7.3 Artifact View

Artifact rows should show:

- filename
- artifact type
- producing worker
- created timestamp
- size
- validation status: pending, passed, warning, failed
- quick preview if possible
- local path
- sandbox path

### 7.4 Evidence View

Evidence rows should show:

- claim ID
- claim text
- value type: fact, quote, calculation, assumption, inference
- source URL or file path
- source timestamp
- confidence
- producing agent
- downstream artifact references

### 7.5 Human Review Gates

The system should pause for review when:

- A task has ambiguous deliverable type.
- A workflow is likely to exceed a cost or time budget.
- A worker wants to write or overwrite a user-provided file.
- A source conflict cannot be reconciled automatically.
- A validator fails a required check.
- A tool is high-risk, such as network write, credentials, shell execution
  outside expected paths, or publish/export.

## 8. System Architecture

### 8.1 Current Architecture

Current components:

- `app/orchestrator.py`: iterative orchestrator loop and `spawn_workers`.
- `app/worker.py`: worker prompt and worker execution.
- `app/loop.py`: OpenAI-compatible tool-use loop.
- `app/tools.py`: worker tool schemas and executor.
- `app/memory.py`: in-memory and SQLite shared memory stores.
- `app/sandbox.py`: E2B sandbox wrapper.
- `app/swarm.py`: conductor that creates sandbox, uploads skills, streams
  events, and harvests artifacts.
- `app/skills_loader.py`: skill discovery and upload.
- `app/tui/`: Textual UI and event router.
- `app/api.py`: FastAPI SSE stream.

### 8.2 Proposed Architecture

Add five product layers around the existing runtime:

1. Mission Planner
2. Evidence Store
3. Artifact Manifest
4. Validation Engine
5. Replay and Run History

The runtime should remain conceptually simple:

```text
User Task
  -> Mission Planner
  -> Orchestrator
  -> Cohort 1: evidence workers
  -> Evidence Store + Shared Memory
  -> Cohort 2: builder workers
  -> Artifact Manifest
  -> Cohort 3: validator workers
  -> Validation Report
  -> Final Answer + Artifacts + Evidence
```

### 8.3 Mission Planner

Purpose:

- Convert a raw user task into a structured mission plan before spawning
  workers.

Inputs:

- user task
- optional uploaded files
- available skills
- configured budgets
- prior session memory

Outputs:

- mission ID
- deliverable type
- required skills
- cohort plan
- expected memory keys
- expected artifacts
- validation gates
- cost and time limits
- risk flags

The mission plan should be explicit enough for the UI to display and for tests
to assert against.

### 8.4 Evidence Store

Purpose:

- Preserve source-backed findings in a structured form instead of relying only
  on free-text shared memory.

Evidence records should include:

- ID
- mission ID
- worker ID
- key
- claim text
- claim type
- value
- source URL or file path
- source quote or extracted snippet when allowed
- retrieved timestamp
- confidence
- caveats
- downstream artifact IDs

Shared memory can remain the low-latency coordination layer. The evidence store
is the durable audit layer.

### 8.5 Artifact Manifest

Purpose:

- Track every produced deliverable and connect it back to workers, evidence,
  and validation results.

Artifact records should include:

- ID
- mission ID
- filename
- type
- local path
- sandbox path
- producing worker ID
- source evidence IDs
- created timestamp
- size
- checksum
- validation status
- validation report path

### 8.6 Validation Engine

Purpose:

- Run deterministic and model-assisted checks on produced artifacts.

Validation should be skill-specific:

- xlsx:
  - file opens
  - workbook recalculates
  - formulas are not broken
  - required sheets exist
  - charts reference valid ranges
  - placeholder scan passes
  - source sheet exists when required

- pptx:
  - file opens
  - thumbnails render
  - required slide count or structure exists
  - no placeholder text remains
  - slide titles fit
  - citations or source notes exist when required

- report/markdown/docx:
  - no placeholders
  - required sections exist
  - numeric claims match evidence/calculations
  - citations exist for factual claims
  - generated file renders cleanly

- dataset/csv:
  - row count nonzero
  - schema matches expected columns
  - encoding readable
  - missingness profile recorded
  - transformations documented

Validation should produce:

- pass/fail/warn status
- list of checks
- evidence references
- actionable repair suggestions

### 8.7 Replay and Run History

Purpose:

- Make failed or imperfect runs recoverable.

The system should store:

- mission plan
- orchestrator messages
- worker specs
- cohort boundaries
- tool calls
- tool results
- memory writes
- artifacts
- validation results
- final answer

Replay modes:

- replay from start
- replay from cohort N
- replay only builder
- replay only validator
- repair artifact using existing evidence

This should eventually behave like lightweight checkpointing. Full LangGraph
style checkpointing is not required for the first version, but the data model
should not block it.

## 9. Agent Roles

### 9.1 Orchestrator

Responsibilities:

- Own the final answer.
- Decide cohort boundaries.
- Prevent dependency violations.
- Inspect worker summaries.
- Read shared memory and evidence.
- Trigger validators before final response.
- Surface caveats and unresolved risks.

The orchestrator should not:

- Produce artifacts directly unless the task is trivial.
- Spawn builder workers before required evidence exists.
- Hide failed validators.

### 9.2 Mission Planner

Responsibilities:

- Classify task.
- Select workflow template.
- Estimate budget.
- Select skills.
- Define expected outputs.
- Define validation gates.

This can initially be deterministic plus LLM-assisted.

### 9.3 Evidence Workers

Responsibilities:

- Gather facts, source excerpts, calculations, and assumptions.
- Persist findings early and often.
- Write structured evidence records.
- Include source URLs, file paths, dates, and caveats.

Evidence workers should be scoped narrowly. For example, one competitor per
worker is usually better than one broad "market researcher" when sources are
independent.

### 9.4 Builder Workers

Responsibilities:

- Read evidence and shared memory.
- Produce artifacts using relevant skills.
- Save user-facing outputs under the artifact directory.
- Save intermediate scripts when useful.
- Write artifact manifests.

Builder workers should not perform primary research unless explicitly asked.

### 9.5 Validator Workers

Responsibilities:

- Run deterministic validation scripts.
- Inspect artifact structure.
- Check source coverage.
- Flag missing evidence, broken files, placeholders, and weak assumptions.
- Produce validation reports.

Validators should be independent from builders when possible.

### 9.6 Reconciler Workers

Responsibilities:

- Resolve conflicting evidence.
- Compare worker outputs.
- Normalize schemas and terminology.
- Decide which source is more authoritative.
- Record unresolved conflicts.

Reconcilers are useful after parallel research cohorts.

## 10. Skills Specification

### 10.1 Current Skill Model

The repo ships skills as `SKILL.md` packages under `app/skills/`. Workers see a
catalog and are instructed to read relevant skill files from the sandbox.

Current skills include:

- data-analyst
- financial-analyst
- file-manager
- pptx
- xlsx
- web-scraper
- python-runner
- data-vulgariser

### 10.2 Future Skill Contract

Each skill should become a structured contract:

- name
- description
- when to use
- required inputs
- expected outputs
- artifact types produced
- validation scripts
- common failure modes
- safe tool permissions
- cost profile
- examples

### 10.3 Per-Agent Skill Assignment

The system should reintroduce explicit per-agent skill assignment only when it
enforces behavior.

Recommended future fields:

```python
skills: list[str]
tool_allowlist: list[str]
expected_outputs: list[str]
validation_required: bool
```

Rules:

- If an agent has assigned skills, the worker prompt should show those skills
  first.
- If tool scoping exists, the executor should enforce the allowed tools.
- If a required skill is unavailable, worker spawn should fail early.
- If a worker skips a required skill read, the loop should nudge or fail.

Rationale:

- Inert metadata looks like dead code.
- Enforced skill contracts create real product value.
- Tool scoping improves cost, reliability, and security.

### 10.4 Skill-Specific Validators

Each artifact-producing skill should expose validation commands:

- xlsx: recalc and chart lint
- pptx: thumbnail rendering and placeholder scan
- data analysis: numeric consistency checks
- web scraper: source freshness and citation coverage
- financial analyst: formula, units, and assumption checks

The orchestrator should know which validators are mandatory for a deliverable.

## 11. Data Model

### 11.1 Mission

Fields:

- `mission_id`
- `created_at`
- `task`
- `status`
- `deliverable_type`
- `workflow_template`
- `budget_max_tokens`
- `budget_max_cost`
- `budget_max_seconds`
- `risk_level`
- `expected_artifacts`
- `validation_policy`

Statuses:

- `planned`
- `running`
- `awaiting_review`
- `validating`
- `complete`
- `failed`
- `cancelled`

### 11.2 Cohort

Fields:

- `cohort_id`
- `mission_id`
- `index`
- `purpose`
- `depends_on`
- `worker_ids`
- `started_at`
- `finished_at`
- `status`

Purposes:

- `research`
- `reconcile`
- `build`
- `validate`
- `repair`

### 11.3 Worker

Fields:

- `worker_id`
- `mission_id`
- `cohort_id`
- `name`
- `role`
- `task`
- `skills`
- `tool_allowlist`
- `status`
- `started_at`
- `finished_at`
- `token_usage`
- `cost_estimate`
- `summary`

### 11.4 Evidence Record

Fields:

- `evidence_id`
- `mission_id`
- `worker_id`
- `key`
- `claim_type`
- `claim`
- `value`
- `unit`
- `source_type`
- `source_url`
- `source_path`
- `source_title`
- `source_date`
- `retrieved_at`
- `quote`
- `confidence`
- `caveats`
- `tags`

Claim types:

- `fact`
- `quote`
- `calculation`
- `assumption`
- `inference`
- `file_observation`

### 11.5 Artifact Record

Fields:

- `artifact_id`
- `mission_id`
- `worker_id`
- `filename`
- `mime_type`
- `local_path`
- `sandbox_path`
- `size_bytes`
- `checksum`
- `created_at`
- `source_evidence_ids`
- `validation_status`
- `validation_report_id`

### 11.6 Validation Result

Fields:

- `validation_id`
- `mission_id`
- `artifact_id`
- `validator_worker_id`
- `status`
- `checks`
- `warnings`
- `failures`
- `repair_suggestions`
- `created_at`

Statuses:

- `passed`
- `warning`
- `failed`
- `skipped`

### 11.7 Tool Call Record

Fields:

- `tool_call_id`
- `mission_id`
- `worker_id`
- `cohort_id`
- `tool_name`
- `input`
- `result_preview`
- `started_at`
- `finished_at`
- `status`
- `error`
- `token_cost_context`

## 12. Workflow Templates

### 12.1 Research To Report

Phases:

1. Plan
2. Research
3. Reconcile
4. Build report
5. Validate report
6. Final response

Required outputs:

- report
- evidence manifest
- validation report

### 12.2 Research To Spreadsheet

Phases:

1. Plan
2. Research by entity/topic
3. Normalize evidence
4. Build workbook
5. Run xlsx validators
6. Repair if validator fails
7. Final response

Required outputs:

- workbook
- source sheet or manifest
- validation report

### 12.3 Research To Deck

Phases:

1. Plan
2. Research
3. Storyline synthesis
4. Build deck
5. Render thumbnails
6. Validate deck
7. Final response

Required outputs:

- deck
- thumbnails
- evidence manifest
- validation report

### 12.4 Data To Memo

Phases:

1. Profile data
2. Analyze
3. Generate charts
4. Build memo
5. Validate numbers
6. Final response

Required outputs:

- memo
- charts
- calculation manifest
- validation report

## 13. Validation Policies

### 13.1 Strict Policy

Use for finance, legal-adjacent, business-critical, or user-facing artifacts.

Rules:

- No final answer if required artifact is missing.
- No final answer if validation fails.
- Source coverage required for all factual claims.
- Assumptions must be labeled.
- Human review required before publishing or overwriting files.

### 13.2 Standard Policy

Use for normal research and internal artifacts.

Rules:

- Final answer allowed with warnings.
- Missing citations must be called out.
- Artifact must exist and open.
- Placeholders are failures.
- Validation warnings are summarized.

### 13.3 Exploratory Policy

Use for brainstorming, rough analysis, or early drafts.

Rules:

- Artifact validation can be partial.
- Caveats must be explicit.
- Evidence manifest can contain assumptions.
- System should avoid overstating certainty.

## 14. Cost And Budget Controls

### 14.1 Current Controls

The repo already has caps for:

- max orchestrator iterations
- max total workers
- max workers per spawn
- worker concurrency
- worker max tokens
- scrape max chars
- read file max lines

### 14.2 Proposed Controls

Add:

- per-mission token budget
- per-cohort token budget
- per-worker token budget
- web search budget
- scrape budget
- sandbox command budget
- cost estimate before run
- hard stop on budget exhaustion
- graceful final response when budget prevents completion

### 14.3 Cost Display

The UI should show:

- estimated cost before run
- live token/cost estimate per worker
- total cost estimate at completion
- expensive tool warnings

## 15. Security And Permissions

### 15.1 Tool Permission Model

Each worker should eventually receive a tool policy:

- allowed tools
- blocked tools
- writeable paths
- network permissions
- max command timeout
- high-risk actions requiring review

Example:

- Research worker:
  - allowed: web_search, scrape_url, map_website, read_shared_memory,
    write_to_shared_memory
  - blocked: write_file except evidence snapshots

- Builder worker:
  - allowed: read_shared_memory, read_file, write_file, run_python, run_shell
  - blocked: web_search by default

- Validator worker:
  - allowed: read_file, run_python, run_shell, write_file
  - blocked: web_search unless checking source freshness

### 15.2 MCP Direction

MCP should be treated as a future integration boundary, not a rushed dependency.

Potential MCP support:

- expose Agent Swarm tools as an MCP server
- consume external MCP servers for tools/resources
- map MCP tool definitions into worker tool schemas
- enforce allowlists for MCP tools

Security requirements:

- MCP tools must be allowlisted.
- Tool descriptions must be reviewed.
- External servers must be scoped by mission.
- High-risk tools require approval.
- Tool output should be treated as untrusted input.

## 16. Reliability Requirements

### 16.1 Dependency Discipline

The orchestrator must never place dependent workers in the same cohort.

Required checks:

- Builder cannot start if required evidence keys are missing.
- Validator cannot start if expected artifacts are missing.
- Final answer cannot claim an artifact exists unless artifact harvesting sees
  it.

### 16.2 Persistence Discipline

Workers must persist early and often.

Required checks:

- Research workers must write evidence records.
- Builder workers must write artifact records.
- Validator workers must write validation records.
- Workers that finish without required persistence should be marked failed or
  warning depending on policy.

### 16.3 Repair Loops

If validation fails, the orchestrator should decide:

- repair artifact using existing evidence
- rerun builder
- rerun research
- ask user for clarification
- return partial result with warnings

The repair loop should have strict caps to avoid runaway cost.

## 17. API Specification

### 17.1 Existing API

Current endpoints:

- `GET /health`
- `POST /run`
- `POST /run-collect`

### 17.2 Proposed API Additions

Future endpoints:

- `POST /missions/plan`
- `POST /missions/run`
- `GET /missions/{mission_id}`
- `GET /missions/{mission_id}/events`
- `GET /missions/{mission_id}/evidence`
- `GET /missions/{mission_id}/artifacts`
- `GET /missions/{mission_id}/validation`
- `POST /missions/{mission_id}/replay`
- `POST /missions/{mission_id}/cancel`

### 17.3 Event Types

Current events should remain compatible, with additions:

- `mission_planned`
- `cohort_started`
- `cohort_completed`
- `evidence_written`
- `artifact_registered`
- `validation_started`
- `validation_completed`
- `budget_updated`
- `review_requested`
- `replay_started`

## 18. Storage Strategy

### 18.1 Short Term

Use SQLite for durable local storage:

- missions
- cohorts
- workers
- evidence
- artifacts
- validation results
- tool calls

Keep the in-process dict for fast shared memory during a run.

### 18.2 Medium Term

Support Postgres for hosted or multi-user deployments.

### 18.3 File Storage

Artifacts should be stored under a local root such as:

```text
~/.agent-swarm/artifacts/{mission_id}/
```

For tests and demo mode, local repo-scoped temporary artifact roots should be
used to avoid writing outside permitted paths.

## 19. Testing Strategy

### 19.1 Unit Tests

Cover:

- mission planning schemas
- evidence record validation
- artifact manifest creation
- validation result parsing
- budget accounting
- tool policy enforcement
- replay plan selection

### 19.2 Integration Tests

Cover:

- research -> builder -> validator flow
- missing evidence prevents builder
- missing artifact prevents validator
- failed validator triggers repair or warning
- artifact manifest links evidence IDs
- API event stream includes new events

### 19.3 Golden Workflow Tests

Create small deterministic workflows:

- CSV -> memo
- small research fixture -> markdown report
- simple workbook -> xlsx validation
- simple deck -> pptx validation

Avoid relying on live web or model calls in CI.

### 19.4 Artifact QA Tests

For each artifact skill:

- generated files open
- placeholder scan passes
- validation scripts produce machine-readable output
- manifest exists
- final answer references real filenames

## 20. Roadmap

### Phase 1: Spec And Cleanup

Goal:

- Align repo direction and remove stale concepts.

Work:

- Add this spec.
- Keep README aligned with current architecture.
- Add CI.
- Preserve green tests.

Exit criteria:

- Spec reviewed.
- Tests pass in CI.
- No stale references to removed runtime concepts.

### Phase 2: Artifact Manifests And Validation Reports

Goal:

- Make every deliverable traceable.

Work:

- Add artifact manifest schema.
- Add validation result schema.
- Update artifact harvesting to register manifests.
- Add validator hooks for xlsx and basic text artifacts.
- Show validation status in TUI artifact panel.

Exit criteria:

- Every artifact has a record.
- Validation status is visible.
- Tests cover happy path and missing artifact path.

### Phase 3: Structured Evidence Store

Goal:

- Move source-backed findings out of free-text memory only.

Work:

- Add evidence record schema.
- Add `write_evidence` tool or structured wrapper around memory writes.
- Update worker prompts for evidence records.
- Add evidence panel or evidence export.
- Add source coverage validator.

Exit criteria:

- Research workers produce evidence records.
- Final artifacts can reference evidence IDs.
- Missing citations are detectable.

### Phase 4: Mission Planner

Goal:

- Turn raw tasks into explicit execution plans.

Work:

- Add mission plan schema.
- Add deliverable classification.
- Add workflow templates.
- Add expected memory keys and artifacts.
- Add user-visible plan before execution.

Exit criteria:

- Mission plan is visible before run.
- Orchestrator follows the plan or explains deviations.
- Tests verify research/build dependency enforcement.

### Phase 5: Skill Contracts And Tool Policies

Goal:

- Make skills enforceable runtime contracts.

Work:

- Add structured skill metadata.
- Reintroduce per-worker `skills` as enforced metadata.
- Add tool allowlists.
- Add skill required-read checks.
- Add validator mapping by skill.

Exit criteria:

- Worker with xlsx skill receives xlsx-specific instructions and validators.
- Worker cannot call blocked tools.
- Missing required skill fails early.

### Phase 6: Replay And Repair

Goal:

- Make failed runs recoverable.

Work:

- Persist cohorts, workers, tool calls, and memory writes.
- Add replay from cohort.
- Add validator-driven repair loop.
- Add TUI controls for rerun builder/validator.

Exit criteria:

- User can rerun validation without rerunning research.
- User can repair artifact using existing evidence.
- Run history is inspectable.

### Phase 7: MCP And External Integrations

Goal:

- Connect safely to external tool ecosystems.

Work:

- Add MCP client support behind allowlists.
- Expose selected Agent Swarm capabilities as MCP tools.
- Add permission UI for external tools.
- Add security tests for tool scoping.

Exit criteria:

- MCP tools are scoped per mission.
- External tool calls are logged.
- Risky tool calls require approval.

## 21. Success Metrics

### 21.1 Product Metrics

- Artifact completion rate.
- Validation pass rate.
- Source coverage rate.
- User repair rate.
- Rerun rate by phase.
- Time to first usable artifact.
- Cost per successful artifact.

### 21.2 Quality Metrics

- Percentage of factual claims with evidence.
- Percentage of artifacts with manifests.
- Validator false-positive rate.
- Validator false-negative rate.
- Number of placeholder leaks.
- Number of missing artifact claims.

### 21.3 Reliability Metrics

- Worker failure rate.
- Workers that finish without persistence.
- Cohorts rerun due to missing dependencies.
- Runs stopped by budget caps.
- Runs requiring human clarification.

## 22. Open Questions

1. Should the first production-grade workflow be spreadsheet-first, deck-first,
   or report-first?
2. Should the mission planner be LLM-led initially, or mostly deterministic
   with LLM assistance?
3. Should evidence records be stored in SQLite immediately, or first emitted as
   JSON files under artifacts?
4. Should validators be workers, deterministic runtime hooks, or both?
5. How much UI should remain in the terminal versus moving to a browser app?
6. Should MCP support wait until the internal tool policy model is mature?
7. Should per-agent skill contracts be enforced through tool allowlists,
   prompt checks, or both?

## 23. Recommended First Implementation Slice

The first slice should be small but product-defining:

> Add artifact manifests and validation reports for generated artifacts.

Why:

- It builds on existing artifact harvesting.
- It makes the product immediately more trustworthy.
- It does not require a full storage redesign.
- It creates a foundation for evidence, replay, and UI improvements.

Scope:

- Add `ArtifactManifest` and `ValidationResult` models.
- Harvest artifacts into a manifest file.
- Add basic validators:
  - artifact exists
  - file size greater than zero
  - placeholder scan for text-like files
  - xlsx recalc/chart lint when xlsx skill outputs are present
- Emit validation events.
- Show validation status in TUI artifact rows.
- Include validation summary in final answer.

Out of scope for first slice:

- MCP.
- Full replay.
- Postgres.
- Browser UI.
- Complete source-claim graph.
- Hosted multi-user deployment.

This first slice turns "the system created a file" into "the system created a
file, checked it, and can tell you what it knows about it." That is the right
direction of travel.

## 24. Reference Links

- OpenAI Agents SDK: https://developers.openai.com/api/docs/guides/agents
- Microsoft Agent Framework: https://learn.microsoft.com/en-us/agent-framework/overview/
- Model Context Protocol: https://modelcontextprotocol.io/docs/learn/server-concepts
- Anthropic MCP announcement: https://www.anthropic.com/news/model-context-protocol
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- METR long-task paper: https://arxiv.org/abs/2503.14499
- Enterprise agent evaluation paper: https://arxiv.org/abs/2511.14136
- Multi-agent systems study: https://arxiv.org/abs/2601.07136
