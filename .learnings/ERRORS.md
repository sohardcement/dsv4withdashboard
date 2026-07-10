# Errors

## [ERR-20260627-001] dry_run_side_effect

**Logged**: 2026-06-27T22:15:00+08:00
**Priority**: high
**Status**: fixed
**Area**: config

### Summary
`DS4_DRY_RUN=1 DS4_TRACE_RESET=1 ./start-server.sh` truncated the live trace because trace reset happened before the dry-run exit.

### Error
```text
/tmp/ds4-trace.jsonl became size=0 after a dry-run verification command.
```

### Context
- Command shape: `DS4_DRY_RUN=1 DS4_TRACE_RESET=1 ./start-server.sh`
- The startup script performed side effects before checking `DS4_DRY_RUN`.
- This erased the current trace data, though prior summary output remained in the conversation and KV files were unaffected.

### Suggested Fix
Keep all dry-run paths side-effect free. Perform trace reset only after the dry-run branch exits and immediately before the real `exec`.

### Metadata
- Reproducible: yes
- Related Files: `start-server.sh`

---

## [ERR-20260710-001] nonexistent_server_test_target

**Logged**: 2026-07-10T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
The dashboard implementation plan named a `ds4_server_test` Make target that the repository does not define.

### Error
```text
make: *** No rule to make target `ds4_server_test'.  Stop.
```

### Context
- Attempted baseline command: `make ds4_server_test && ./ds4_server_test`.
- `ds4_server_test` appears only in the Makefile clean list.
- Server unit tests are compiled into `ds4_test` and selected with `./ds4_test --server`.

### Suggested Fix
Use `make ds4_test && ./ds4_test --server` for focused server tests and keep implementation plans aligned with actual Makefile targets.

### Metadata
- Reproducible: yes
- Related Files: `Makefile`, `tests/ds4_test.c`, `docs/superpowers/plans/2026-07-10-dashboard-kv-observability.md`

### Resolution
- **Resolved**: 2026-07-10T00:00:00+08:00
- **Notes**: Corrected the implementation plan before dispatching Task 1.

---
