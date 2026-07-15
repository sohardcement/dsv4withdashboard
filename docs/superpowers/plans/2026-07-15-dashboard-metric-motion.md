# Dashboard Metric Motion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add B-style directional double-layer scrolling to the five numeric monitor-mode headline metrics, document the original repository in README, verify the change, and publish it as a pull request.

**Architecture:** Keep the dashboard embedded in `ds4_server.c`. Add a fixed metric viewport with outgoing/incoming value layers, and pass raw snapshot values to a helper that assigns `increase` or `decrease`; the phase/service metric remains a normal text update. Extend the existing fixture-driven browser test, then add the upstream repository note to README.

**Tech Stack:** Embedded HTML/CSS/JavaScript in C99, vanilla browser APIs, CSS keyframes, Node/Playwright dashboard tests, Markdown.

---

### Task 1: Specify the failing browser contract

**Files:**
- Modify: `tests/dashboard_ui_test.js` next to the existing monitor metric assertions.
- Test fixture: `tests/dashboard_fixture.py` already supports `status_patch` and needs no change.

- [ ] **Step 1: Add assertions for initial state, increase, decrease, and layer cleanup.**

Add this after the existing baseline assertion that checks `52.7 t/s` and `75.0%`:

```js
const motionIds=['monitorPrefill','monitorDecode','monitorCacheHit','monitorContext','monitorQueue'];
const patchMonitor=async patch=>{await cfg({status_patch:patch});await page.waitForFunction(ids=>ids.every(id=>document.getElementById(id).dataset.motionDirection),motionIds)};
await cfg({reset:true});
await page.waitForFunction(()=>document.getElementById('monitorPrefill').dataset.motionDirection==='none');
await patchMonitor({queue_depth:3,prefill:{avg_tps:1900.4},decode:{avg_tps:60.7},request:{cached_tokens:28672},context:{utilization:.40}});
for(const id of motionIds){await page.waitForFunction(id=>document.getElementById(id).dataset.motionDirection==='increase',id);assert(await page.locator('#'+id+' .metric-value-layer').count()<=2,id+' accumulated increase layers')}
await patchMonitor({queue_depth:1,prefill:{avg_tps:1700.4},decode:{avg_tps:44.7},request:{cached_tokens:16384},context:{utilization:.20}});
for(const id of motionIds){await page.waitForFunction(id=>document.getElementById(id).dataset.motionDirection==='decrease',id);assert(await page.locator('#'+id+' .metric-value-layer').count()<=2,id+' accumulated decrease layers')}
assert(await page.locator('#monitorPhase').getAttribute('data-motion-direction')===null,'phase text must not use numeric motion');
```

Keep the existing reset cleanup. The test covers the five numeric cards; `monitorPhase` is explicitly excluded. Existing mobile viewport checks remain the overflow contract.

- [ ] **Step 2: Run the browser test and verify the new contract fails.**

Run `./tests/run_dashboard_ui_test.sh`.

Expected: FAIL because the current markup has no `data-motion-direction` or `.metric-value-layer` contract.

- [ ] **Step 3: Commit only the failing test.**

```bash
git add tests/dashboard_ui_test.js
git commit -m "test(dashboard): specify directional metric motion"
```

### Task 2: Implement directional double-layer motion

**Files:**
- Modify: `ds4_server.c:8212-8233` for CSS, monitor metric markup, and the update helper.
- Modify: `ds4_server.c:8251` for raw metric values passed from `paintMonitor()`.

- [ ] **Step 1: Replace the old fade rule with fixed-layer keyframes and markup.**

Replace `.value-changing` / `@keyframes metric-value-change` with:

```css
.metric-value-window{display:block;position:relative;min-height:1.2em;overflow:hidden}
.metric-value-layer{display:block;white-space:inherit;will-change:transform,opacity}
.metric-value-layer-out-increase{animation:metric-value-out-increase 420ms cubic-bezier(.22,.8,.24,1) both}
.metric-value-layer-in-increase{animation:metric-value-in-increase 420ms cubic-bezier(.22,.8,.24,1) both}
.metric-value-layer-out-decrease{animation:metric-value-out-decrease 420ms cubic-bezier(.22,.8,.24,1) both}
.metric-value-layer-in-decrease{animation:metric-value-in-decrease 420ms cubic-bezier(.22,.8,.24,1) both}
@keyframes metric-value-out-increase{to{opacity:0;transform:translateY(-100%) scale(.94)}}
@keyframes metric-value-in-increase{from{opacity:0;transform:translateY(-100%) scale(1.08)}to{opacity:1;transform:translateY(0) scale(1)}}
@keyframes metric-value-out-decrease{to{opacity:0;transform:translateY(100%) scale(1.04)}}
@keyframes metric-value-in-decrease{from{opacity:0;transform:translateY(100%) scale(.92)}to{opacity:1;transform:translateY(0) scale(1)}}
```

Use this structure for `monitorPrefill`, `monitorDecode`, `monitorCacheHit`, `monitorContext`, and `monitorQueue`, preserving each id:

```html
<strong id="monitorPrefill" class="mono metric-value" data-motion-direction="none" aria-live="polite"><span class="metric-value-window"><span class="metric-value-layer">—</span></span></strong>
```

Keep `monitorPhase` as a plain text node. The existing reduced-motion rule must continue to disable animations.

- [ ] **Step 2: Add a helper that compares raw values and replaces at most two layers.**

Keep `text(id,value)` for ordinary fields. Add this vanilla-JS state and helper near it:

```js
const metricMotionValues=Object.create(null),metricMotionText=Object.create(null);
const metricText=(id,value,raw)=>{const node=$(id),window=node&&node.querySelector('.metric-value-window'),next=String(value);if(!node||!window)return;const numeric=finite(raw)?Number(raw):null,previous=metricMotionValues[id],direction=numeric!=null&&previous!=null&&numeric!==previous?(numeric>previous?'increase':'decrease'):'none';node.dataset.motionDirection=direction;if(numeric==null)delete metricMotionValues[id];else metricMotionValues[id]=numeric;if(metricMotionText[id]===next)return;const incoming=document.createElement('span');incoming.className='metric-value-layer';incoming.textContent=next;const token=(node.__metricMotionToken||0)+1;node.__metricMotionToken=token;const finish=()=>{if(node.__metricMotionToken!==token)return;window.replaceChildren(incoming);incoming.className='metric-value-layer';incoming.removeAttribute('aria-hidden')};if(direction==='none'||window.matchMedia('(prefers-reduced-motion: reduce)').matches){window.replaceChildren(incoming);metricMotionText[id]=next;return}const outgoing=document.createElement('span');outgoing.className='metric-value-layer metric-value-layer-out-'+direction;outgoing.textContent=metricMotionText[id]||window.textContent||'—';outgoing.setAttribute('aria-hidden','true');incoming.className='metric-value-layer metric-value-layer-in-'+direction;window.replaceChildren(outgoing,incoming);incoming.addEventListener('animationend',finish,{once:true});window.setTimeout(finish,460);metricMotionText[id]=next};
```

Use `textContent` only. An unavailable raw value sets direction to `none` and clears its previous numeric value, so recovery cannot invent a direction across a gap. Replace the window on every update; stale animation callbacks must be ignored by the token.

- [ ] **Step 3: Pass the exact raw values from `paintMonitor()`.**

Keep the current formatted display strings and progress bars, but call `metricText()` with average prefill TPS, average decode TPS, request cache-hit ratio, context utilization, and queue depth:

```js
metricText('monitorPrefill',prefillDisplay,finite(p.avg_tps)?p.avg_tps:null);
metricText('monitorDecode',decodeDisplay,finite(d.avg_tps)?d.avg_tps:null);
metricText('monitorCacheHit',cacheDisplay,cacheRatio);
metricText('monitorContext',contextDisplay,finite(x.utilization)?x.utilization:null);
metricText('monitorQueue',queueDisplay,finite(s.queue_depth)?s.queue_depth:null);
```

Use local display variables if preferred; do not parse formatted strings. Leave `monitorPhase` on `text()`.

- [ ] **Step 4: Run the browser test and commit the implementation.**

Run `./tests/run_dashboard_ui_test.sh`; expected: PASS with increase/decrease direction, no layer accumulation, excluded phase animation, and existing responsive assertions. Then run:

```bash
git add ds4_server.c tests/dashboard_ui_test.js
git commit -m "dashboard: add directional metric motion"
```

### Task 3: Mark the upstream repository in README

**Files:**
- Modify: `README.md` after the opening project description.

- [ ] **Step 1: Add the exact attribution without renaming the project.**

Insert:

```markdown
> 原始仓库：[antirez/ds4](https://github.com/antirez/ds4)。
```

- [ ] **Step 2: Verify and commit the README change.**

Run `rg -n "原始仓库|https://github.com/antirez/ds4" README.md` and `git diff --check -- README.md`; expected: one attribution and no whitespace errors. Then run:

```bash
git add README.md
git commit -m "docs: identify upstream ds4 repository"
```

### Task 4: Verify, review scope, and publish the PR

**Files:**
- Verify: `ds4_server.c`, `tests/dashboard_ui_test.js`, `README.md`.

- [ ] **Step 1: Run dashboard and C server regressions.**

Run `./tests/run_dashboard_ui_test.sh`, `make ds4_test`, and `./ds4_test --server`; expected: all browser assertions pass, the C test binary builds, and server tests pass. Inspect the monitor screenshot for directional scrolling, fixed metric height, and no mobile overflow.

- [ ] **Step 2: Check final scope before publishing.**

Run `git status --short`, `git diff --check HEAD~4..HEAD`, and `git diff --stat HEAD~4..HEAD`; expected: recent commits contain only the approved design/plan docs, dashboard implementation/test changes, and README attribution. Pre-existing untracked files remain untouched and unstaged.

- [ ] **Step 3: Create the pull request.**

Read and follow `superpowers:verification-before-completion`, `superpowers:requesting-code-review`, and `github:yeet` before publishing. Push the current branch and open a draft PR with the motion summary, README attribution, exact tests run, and known limitations. Do not add pre-existing untracked artifacts.
