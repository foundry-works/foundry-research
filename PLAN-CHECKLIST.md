# Implementation Checklist (v2)

Tracks progress on the 8 improvements from PLAN.md v2.

---

## 1. Tavily Connectivity Test and WebSearch Fallback (HIGH)

- [ ] **Edit `agents/source-acquisition.md`** — Add connectivity test at start of initial-mode workflow:
  - [ ] Run a single test tavily search before round 1
  - [ ] If it fails, log journal entry and set a `tavily_available: false` flag in the manifest
- [ ] **Edit `skills/deep-research/SKILL.md`** — In step 4 (acquisition handoff):
  - [ ] Add: "If manifest reports tavily failure, run 2-3 `WebSearch` queries per web-dependent question immediately"
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 2. Unpaywall API Integration (HIGH)

- [ ] **Edit `skills/deep-research/scripts/_shared/config.py`** — Add `UNPAYWALL_EMAIL` config variable
- [ ] **Edit `skills/deep-research/scripts/download.py`** — Add Unpaywall cascade step:
  - [ ] Query `https://api.unpaywall.org/v2/{doi}?email={email}` for sources with DOIs
  - [ ] If `best_oa_location.url_for_pdf` is non-null, download from there
  - [ ] Insert in cascade before CORE and tavily recovery
- [ ] **Test** — Run download on a known paywalled paper with DOI (e.g., Gray & Wegner 2012) and verify Unpaywall finds an OA copy if one exists
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 3. Web-First Source Mode (HIGH)

- [ ] **Edit `agents/source-acquisition.md`** — Add "web-first questions" concept:
  - [ ] Define how the orchestrator flags recency-dependent questions
  - [ ] Add triage rules for web sources: rank by date > domain authority > keyword relevance
- [ ] **Edit `skills/deep-research/SKILL.md`** — In step 4:
  - [ ] Add guidance on flagging recency-dependent questions in the acquisition handoff
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 4. Lower Abstract-Only Utilization Threshold (MEDIUM)

- [ ] **Edit `skills/deep-research/SKILL.md`** — Change step 11b trigger:
  - [ ] Remove "< 5 findings" threshold
  - [ ] Replace with: "If an abstract-only source directly addresses a research question with an empirical result, log it regardless of finding count"
  - [ ] Keep the 2-3 per question cap
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 5. Orchestrator Prompt Layering (MEDIUM)

- [ ] **Create `skills/deep-research/REFERENCE.md`** — Move from SKILL.md:
  - [ ] Provider selection guidance section
  - [ ] Session structure section
  - [ ] Adaptive guardrails table
  - [ ] Output format template
- [ ] **Edit `skills/deep-research/SKILL.md`** — Trim to ~200 lines:
  - [ ] Keep: command execution rules, 15-step workflow, delegation patterns, citation rules
  - [ ] Replace removed sections with: "See REFERENCE.md for provider guidance, session structure, and output format"
  - [ ] Simplify gap-mode decision to: "Coverage gap → full. Recency gap → light."
- [ ] **Update agent prompts** that need reference material to read REFERENCE.md explicitly
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 6. Cross-Source Contradiction Detection (MEDIUM)

- [ ] **Option B first (simpler):** Edit `skills/deep-research/SKILL.md` — Add step after dedup (11c):
  - [ ] "Review the full findings list. For any pair of findings that reach opposite conclusions about the same construct from different sources, log the contradiction in journal.md and include it in the synthesis handoff narrative."
- [ ] **Later (option A):** If option B proves too manual:
  - [ ] Edit `skills/deep-research/scripts/state.py` — Add `--contradicts finding-NN` to `log-finding`
  - [ ] Add `state contradictions` command
  - [ ] Edit `agents/findings-logger.md` — Add contradiction flagging instruction
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 7. Metadata Enrichment Before Synthesis (LOW)

- [ ] **Edit `skills/deep-research/scripts/state.py`** — Add `state enrich-metadata` command:
  - [ ] Query Crossref API by title for sources with missing DOI/author/venue
  - [ ] Update metadata JSON files on disk
  - [ ] Return count of enriched sources
- [ ] **Edit `skills/deep-research/SKILL.md`** — Add step before synthesis handoff:
  - [ ] "Run `state enrich-metadata` to fill in missing DOIs and author lists from Crossref"
- [ ] **Test** — Run on uncanny-valley session, verify metadata files updated
- [ ] **Run `./copy-to-skills.sh`** to deploy

---

## Integration Testing

- [ ] Run a small research session (~5 sources, simple factual query) after implementing items 1-3 (HIGH priority)
- [ ] Verify tavily test fires and fallback works when tavily is unavailable
- [ ] Verify Unpaywall cascade finds OA copies for known paywalled DOIs
- [ ] Verify web-first flagging produces different triage behavior for recency-dependent questions
- [ ] Run a medium session (~15 sources) after all items to verify end-to-end pipeline
- [ ] Verify `copy-to-skills.sh` correctly deploys all changed files to `.claude/`
