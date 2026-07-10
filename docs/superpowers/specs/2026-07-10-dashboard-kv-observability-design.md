# DS4 Dashboard KV Observability and Capacity Controls

## Goal

Replace the current card-heavy status page with an information-first dashboard that serves two jobs:

1. Show whether inference is healthy and how the active request is progressing.
2. Explain KV cache effectiveness and capacity for the current request and for the lifetime of the server process.

The dashboard also lets a local operator change the disk KV cache size limit either immediately or for the next server start.

## Scope

This change covers the embedded dashboard, `/ds4/status`, new local management endpoints, process-lifetime cache counters, disk KV capacity reporting, persistent dashboard configuration, and focused server tests.

It does not add historical time-series storage, authentication, remote administration, or an estimate of in-memory KV bytes. The live in-memory state is reported honestly as tokens and context utilization because its byte size is backend- and representation-dependent.

## Visual Direction

The selected direction is an information-architecture layout inspired by scientific editorial design:

- warm off-white page background;
- near-black text and one vermilion status accent;
- typography and rules establish hierarchy instead of a wall of cards;
- the active request's KV token hit rate is the primary number;
- operational speed remains visible without competing with cache effectiveness;
- no decorative icons, glass effects, gradients, or large shadows;
- responsive stacking preserves the same reading order on narrow screens.

The first viewport contains:

1. Model, backend, context size, phase, queue depth, and connected clients.
2. Current request KV hit rate and decode speed.
3. Current request cache details and prefill/decode progress.
4. Process-lifetime hit rates and request totals.
5. Disk KV capacity and live session context utilization.

## Metric Definitions

### Current Request

- `token_hit_rate = cached_tokens / prompt_tokens`.
- `cached_tokens` remains the number of prompt tokens restored from any cache source.
- `cache_write_tokens` remains the newly evaluated prompt portion eligible for reporting as written work.
- When `prompt_tokens` is zero, the hit rate is unavailable rather than `0%`.

### Process Lifetime

The server status tracks unsigned 64-bit counters:

- total prompt tokens;
- total cached prompt tokens;
- requests with a non-empty prompt;
- requests with at least one cached token;
- existing total, completed, and failed requests.

Derived values are:

- `token_hit_rate = total_cached_tokens / total_prompt_tokens`;
- `request_hit_rate = cache_hit_requests / prompt_requests`.

These counters reset when the server process restarts. A request contributes once, when cache selection and prompt token counts are final. Failed generation still contributes because cache effectiveness was already observed.

### Capacity

Disk KV reporting includes:

- enabled state;
- configured directory;
- current budget in bytes;
- actual bytes represented by indexed cache entries;
- indexed entry count;
- utilization percent when a non-zero budget exists.

Live in-memory KV reporting includes session position, context length, and their ratio. It does not claim a byte count.

## Backend Design

### Status Snapshot

Extend `server_status` and `/ds4/status` with process cache counters and a `kv_cache` object. Status responses remain snapshots protected by the existing status mutex.

The KV store exposes a small stats snapshot API rather than leaking entry internals into the server. The snapshot returns budget, indexed bytes, and entry count. Cache mutations update these values while holding KV store synchronization, so the HTTP status thread never races directory refresh, lookup, store, or eviction.

### Runtime Budget Change

Add a KV store operation that changes `budget_bytes` under synchronization and optionally runs the existing eviction policy immediately. It returns:

- previous and new budgets;
- bytes before and after;
- entry count before and after;
- whether eviction ran.

Growing the budget never evicts. Shrinking below current usage invokes the existing eviction policy until the new budget is satisfied. Active/live-prefix protection remains part of the existing eviction semantics.

### Persistent Budget Change

The dashboard stores its next-start override in a small DS4-owned configuration file under the existing user DS4 directory. The start script reads this override after profile defaults and before explicit environment overrides. Explicit `DS4_KV_SPACE` continues to have highest priority.

Writing uses a temporary file followed by atomic rename. The management response distinguishes runtime success from persistence failure so the UI cannot claim both succeeded when only one did.

### Management API

Use JSON POST endpoints under `/ds4/admin/kv-cache`:

- an inspection/dry-run request validates a proposed size and reports whether eviction is required;
- an apply request can update runtime state, persistent state, or both.

Mutation requests are accepted only when the peer socket address is loopback (`127.0.0.1` or `::1`). The dashboard remains readable from any address allowed by the existing server bind configuration, but remote mutation returns HTTP 403.

Only `POST` mutates state. Requests require `Content-Type: application/json`, enforce the existing request-size limits, reject unknown modes and malformed numbers, and use bytes internally. The minimum accepted non-zero budget is documented and validated. A disabled/unconfigured disk cache cannot be enabled solely through this endpoint because doing so would require opening a new cache directory at runtime.

## Dashboard Interaction

The KV capacity row shows actual usage, the active limit, entry count, and a utilization bar. Selecting the limit opens an inline editor accepting MB or GB.

Two actions are available:

- **Save for restart**: writes the persistent override without changing the running budget.
- **Apply now**: first requests a dry-run. If the new budget is below current usage, the UI shows the expected pressure and requires a second confirmation before applying.

The UI reports the server's returned before/after values rather than assuming the requested value took effect. Controls are read-only when the dashboard is not connected through loopback or when disk KV is disabled.

The page uses semantic text for all states:

- unavailable ratios render as an em dash;
- disabled disk cache renders as `Disabled`;
- offline status preserves the last values but marks them stale;
- mutation errors remain visible until dismissed or superseded;
- polling pauses while the capacity input is being edited so user input is not overwritten.

## Error Handling and Concurrency

- Invalid or overflowed sizes return HTTP 400 with a stable error code and message.
- Remote mutation returns HTTP 403.
- Runtime cache errors return HTTP 409 or 500 depending on whether state prevents the operation or an internal action failed.
- Persistent write failures do not roll back a successful runtime change; the response reports each result separately.
- KV store stats and mutation share store-level synchronization.
- Status polling never performs a directory scan. Indexed byte totals are maintained when the cache index changes.

## Testing

Focused C tests cover:

1. Current and cumulative token/request hit-rate counters.
2. Zero denominators and requests with empty prompts.
3. Status JSON fields for enabled and disabled disk KV.
4. KV store byte and entry accounting after open, store, eviction, and close.
5. Runtime budget growth without eviction.
6. Runtime shrink with eviction and accurate before/after results.
7. Management request validation, loopback authorization, dry-run, apply, and persistence failure reporting.
8. Dashboard HTML contains the new data bindings and administrative controls.

Verification includes the focused server test target, the complete test suite, a CPU build, and browser inspection at desktop and narrow viewport widths.

## Compatibility

Existing inference APIs and usage fields remain unchanged. `/ds4/status` only gains fields. The dashboard continues to be served at `/` and `/dashboard`. Explicit command-line and environment configuration retain precedence over the dashboard's saved next-start override.
