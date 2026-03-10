# Deep Research Improvement Checklist

Track implementation progress for each item in PLAN.md.

---

## Tier 1: High impact, low effort

- [x] **1. PubMed auto-fetch metadata**
  - [x] Change `pubmed.py` `_keyword_search` to auto-fetch when session is active
  - [x] Change `pubmed.py` `_mesh_search` to auto-fetch when session is active
  - [x] Verify `_efetch_papers` output includes title/abstract/DOI so `_add_sources_to_state` picks them up
  - [ ] Test: PubMed keyword search with active session → sources appear in state.db with titles

- [x] **2. Crossref sort warning**
  - [x] Add warning log in `crossref.py` when `--sort is-referenced-by-count` used without `--subject`
  - [x] Add SKILL.md note: pair citation sort with `--subject` filter

- [x] **3. Download batch IndexError guard**
  - [x] Find the IndexError-prone code path in `state.py` download-pending handler
  - [x] Add empty-list guard before indexing
  - [x] Review batch loop for edge cases (all sources fail, list exhausted mid-iteration)

---

## Tier 2: Medium impact, medium effort

- [x] **4. Gap resolution guidance**
  - [x] Strengthen SKILL.md step 14: minimum 2 searches per gap
  - [x] Add: "gap resolved after 1 search is suspicious"
  - [x] Add: journal entry for unresolvable gaps must cite specific failed strategies
  - [x] Add `state gap-search-plan` command

- [x] **5. Citation chasing guidance**
  - [x] Add SKILL.md guidance: prefer `--references` for foundational papers
  - [x] Add SKILL.md guidance: `--cited-by` returns recency-biased results for high-citation papers
  - [x] `--min-citations N` filter already existed in `semantic_scholar.py`; added to SKILL.md provider table and citation chasing guidance

- [x] **6. Reader allocation guidance**
  - [x] Add SKILL.md triage step after downloads (new step 8): rank by citation count + title relevance
  - [x] Add: check `quality` field before spawning readers (skip mismatched/degraded)
  - [x] Update `agents/research-reader.md`: check source quality metadata before reading

- [x] **7. Synthesis handoff**
  - [x] Update SKILL.md step 16a: include raw `state summary` findings array in writer handoff
  - [x] Add: writer should see both structured findings with source IDs AND narrative summary

---

## Tier 3: Nice-to-have / longer-term

- [ ] **8. Metadata triage step**
  - [ ] Design scoring heuristic (citation count × title keyword relevance)
  - [ ] _(Optional)_ Add `state triage` command
  - [ ] Add SKILL.md triage step between search and download

- [ ] **9. Failed source recovery**
  - [ ] Design `download --recover-high-priority` flag
  - [ ] Implement CORE title search fallback
  - [ ] Implement Tavily "title pdf" fallback
  - [ ] Implement DOI landing page web download fallback

- [ ] **10. Structured search journaling**
  - [ ] Add SKILL.md journal template for search rounds
  - [ ] _(Optional)_ Auto-append structured journal entries in `search.py`

---

## Verify only (no new code)

- [ ] **Content mismatch detection** — confirm `download.py:756-770` sets `quality: "mismatched"` correctly
- [x] **Reader quality check** — add quality gate to `agents/research-reader.md`
