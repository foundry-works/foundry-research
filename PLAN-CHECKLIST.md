# Plan Checklist: SKILL.md Improvements

## Pre-flight

- [ ] Read current SKILL.md in full to confirm line numbers from PLAN.md are still accurate
- [ ] Verify no other pending changes to SKILL.md on this branch

## Changes

### 1. Mandate brief questions (Quick-Start step 2)
- [ ] Expand step 2 to require 3-7 research questions in the brief
- [ ] Add inline JSON example showing `{"scope": "...", "questions": ["Q1: ...", "Q2: ..."], "completeness_criteria": "..."}`
- [ ] Verify the example uses `--from-stdin` or `--from-json` correctly

### 2. Add gap-check step (Quick-Start steps 8-9)
- [ ] Insert new step between log-finding and audit: "Review each research question — `log-gap` for any with < 2 sources"
- [ ] Renumber subsequent steps (audit becomes step 10, report becomes step 11)
- [ ] Strengthen "Structured coverage tracking" paragraph — make `log-gap` required, not optional

### 3. Reader subagents call `mark-read` (Delegation + Quick-Start)
- [ ] Add post-reader step in Quick-Start (after step 7): "After readers complete, `mark-read` for each source with a note"
- [ ] Update Delegation section source summarization bullet to mention `mark-read`
- [ ] Renumber subsequent steps after insertion

### 4. Query specificity guidance (What Good Research Looks Like)
- [ ] Add "Search Query Crafting" content after "Iterative search across multiple providers" paragraph
- [ ] Include rule: always include core topic term in every query
- [ ] Include rule: >500 results = too broad, add qualifying terms
- [ ] Include rule: spot-check last few results for relevance

### 5. Web source consideration prompt (Quick-Start + Provider Selection)
- [ ] Add sentence to steps 3-4: evaluate whether topic warrants web sources
- [ ] Add heuristic to Provider Selection Guidance: "at least 3 providers including one web source when unsure"

### 6. Default search limit guidance (Search section + What Good Research Looks Like)
- [ ] Add limit defaults to Common flags line: `--limit 50` broad, `--limit 20` targeted
- [ ] Add note that OpenAlex/Semantic Scholar can return thousands without explicit `--limit`
- [ ] Add limit guidance to "Iterative search" paragraph

## Post-flight

- [ ] Re-read final SKILL.md for consistency — no contradictions between sections
- [ ] Confirm total line count hasn't bloated excessively (target: < 30 lines added net)
- [ ] Run a session init + set-brief to verify the example JSON works
- [ ] Commit changes
