# Implementation Checklist

## state.py changes

- [ ] **`sources --compact`**: Add `--compact` flag. When set, SELECT only `id, title, quality, content_file`. Add parser arg to `sources` subcommand.
- [ ] **`sources --fields`**: Add `--fields` flag (comma-separated). When set, SELECT only the specified columns. Validate against allowed column names. `--compact` is sugar for `--fields id,title,quality,content_file`.
- [ ] **`summary --compact`**: Add `--compact` flag. When set, return `findings_by_question` as count map instead of full findings list. Omit `sources` array. Omit `findings` array. Omit `metrics` array. Keep `brief.questions`, `search_count`, `source_count`, distribution maps, `gaps`.
- [ ] **`summary --write-handoff`**: Add `--write-handoff` flag. Write full summary JSON to `synthesis-handoff.json` in session dir. Return `{"path": "<relative_path>", "findings_count": N, "gaps_count": N}`.
- [ ] **`audit --brief`**: Add `--brief` flag. When set, replace `downloaded_ids` with count (already in `sources_downloaded`), replace `notes_ids` with count (already in `sources_with_notes`), replace `no_content` with `no_content_count`, replace `abstract_only` with `abstract_only_count`. Keep `degraded_quality` and `mismatched_content` as arrays.

## SKILL.md changes

- [ ] **CLI reference table**: Add `--compact`, `--fields`, `--write-handoff`, `--brief` to the command reference block.
- [ ] **Step 12** (audit): Recommend `audit --brief` as the default for pre-synthesis coverage checks. Full `audit` (with ID lists) only needed when debugging specific sources.
- [ ] **Step 14a** (synthesis handoff): Replace `state summary` with `state summary --write-handoff`. Pass the returned file path to the synthesis-writer agent. The orchestrator still writes its narrative key-findings summary from memory/journal — it just doesn't hold the structured findings in context.
- [ ] **"Keep in your context" section**: Note that `--compact` variants exist and should be preferred for orchestrator-level queries. Full variants are for agents that need complete data (source-acquisition, synthesis-writer).

## Testing

- [ ] Run `state sources --compact` on an existing session dir — verify 4-field output
- [ ] Run `state sources --fields id,doi,citation_count` — verify arbitrary field selection
- [ ] Run `state summary --compact` — verify count-only findings, no source array
- [ ] Run `state summary --write-handoff` — verify file written, response is path-only
- [ ] Run `state audit --brief` — verify no ID arrays except degraded/mismatched
- [ ] Run full workflow on a test query to verify nothing breaks end-to-end

## Deployment

- [ ] Run `./copy-to-skills.sh` to deploy changes to `.claude/`
