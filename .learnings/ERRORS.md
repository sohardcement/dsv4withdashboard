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
