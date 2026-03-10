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

- [ ] **4. Gap resolution guidance**
  - [ ] Strengthen SKILL.md step 13: minimum 2 searches per gap
  - [ ] Add: "gap resolved after 1 search is suspicious"
  - [ ] Add: journal entry for unresolvable gaps must cite specific failed strategies
  - [ ] _(Optional)_ Add `state gap-search-plan` command

- [ ] **5. Citation chasing guidance**
  - [ ] Add SKILL.md guidance: prefer `--references` for foundational papers
  - [ ] Add SKILL.md guidance: `--cited-by` returns recency-biased results for high-citation papers
  - [ ] _(Optional)_ Add `--min-citations N` filter to `semantic_scholar.py` `--cited-by` mode

- [ ] **6. Reader allocation guidance**
  - [ ] Add SKILL.md triage step after downloads: rank by citation count + title relevance
  - [ ] Add: check `quality` field before spawning readers (skip mismatched/degraded)
  - [ ] Update `agents/research-reader.md`: check source quality metadata before reading

- [ ] **7. Synthesis handoff**
  - [ ] Update SKILL.md step 15a: include raw `state summary` findings array in writer handoff
  - [ ] Add: writer should see structured findings with source IDs, not just narrative

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
- [ ] **Reader quality check** — add quality gate to `agents/research-reader.md`
