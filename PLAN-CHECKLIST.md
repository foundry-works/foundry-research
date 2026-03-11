# Refactoring Checklist

## 1. Deduplicate Term Extraction in state.py
- [ ] Read `cmd_audit()` and `cmd_triage()` term extraction blocks
- [ ] Write `_extract_question_terms(questions)` helper
- [ ] Replace inline logic in `cmd_audit()` with helper call
- [ ] Replace inline logic in `cmd_triage()` with helper call
- [ ] Verify both commands produce identical output before/after

## 2. Consistent Subprocess Error Logging
- [ ] Add `log_subprocess_failure(name, proc)` to `_shared/output.py`
- [ ] Replace inline logging in `download.py`
- [ ] Replace inline logging in `search.py` (add missing exit code)
- [ ] Replace inline logging in `state.py`
- [ ] Grep for any other `proc.returncode` patterns that should use the helper

## 3. Remove Global Mutable State in enrich.py
- [ ] Identify all reads of `_OC_BATCH_TIMEOUT`
- [ ] Add `timeout` parameter to `_enrich_with_opencitations()` and any other consumers
- [ ] Thread `args.timeout` through from `main()`
- [ ] Remove `global _OC_BATCH_TIMEOUT` declaration and module-level variable

## 4. Canonical Error Codes
- [ ] Add error code constants to `_shared/output.py` with a comment listing valid codes
- [ ] Update `dblp.py` to use `"rate_limited"` instead of `f"http_429"`
- [ ] Update `edgar.py` to use standard error codes in error responses
- [ ] Grep all providers for `error_code=` to audit other outliers

## 5. Fix biorxiv Raw Requests Bypass
- [ ] Find the `requests.get()` call in `biorxiv.py` category listing
- [ ] Replace with `client.get()` using the existing session
- [ ] Verify category listing still works

## 6. Verify EDGAR Rate Limit
- [ ] Test current 10.0 req/s setting against SEC endpoints
- [ ] Check for 403/429 responses in practice
- [ ] Adjust rate limit or add comment documenting findings
