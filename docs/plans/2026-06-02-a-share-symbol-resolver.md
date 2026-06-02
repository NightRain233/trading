# A-Share Symbol Resolver Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add safe A-share numeric-code resolution to the watchlist add flow.

**Architecture:** Backend `main.py` exposes a resolver endpoint and reuses the same normalization when adding to the watchlist. Frontend `Header` calls the resolver, displays ordered candidates, and submits the selected Yahoo symbol. Symbols remain persisted in Yahoo Finance format.

**Tech Stack:** FastAPI, Pydantic, Python unittest, React 19, TypeScript, Vite, Tailwind CSS, lucide-react.

---

### Task 1: Backend Resolver Tests

**Files:**
- Modify: `backend/tests/test_watchlist_path.py`
- Modify: `backend/main.py`

**Step 1: Write failing tests**

Add tests for:

- `resolve_symbol_candidates("600519")` returns `600519.SS` with display code `600519.SH`.
- `resolve_symbol_candidates("159915")` returns `159915.SZ`.
- `resolve_symbol_candidates("000001")` returns `000001.SS` first and `000001.SZ` second.
- `normalize_watchlist_symbol("600519.SH")` returns `600519.SS`.

**Step 2: Run test to verify it fails**

Run:

```bash
cd backend
uv run python -m unittest tests.test_watchlist_path -v
```

Expected: failure because resolver helpers do not exist.

**Step 3: Implement backend helpers and endpoint**

In `backend/main.py`, add:

- `SymbolResolveCandidate` Pydantic model.
- Prefix constants and name map.
- `resolve_symbol_candidates(raw: str) -> List[dict]`.
- `normalize_watchlist_symbol(raw: str) -> str`.
- `GET /api/symbol/resolve`.

**Step 4: Use normalization in add watchlist**

Change `/api/watchlist` POST to call `normalize_watchlist_symbol(request.symbol)` before duplicate checks and persistence.

**Step 5: Run tests**

Run:

```bash
cd backend
uv run python -m unittest tests.test_watchlist_path -v
```

Expected: pass.

### Task 2: Frontend Resolver Client

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/utils.ts`

**Step 1: Add TypeScript type**

Add `SymbolResolveCandidate` with `symbol`, `displayCode`, `name`, `market`, and `confidence`.

**Step 2: Add API function**

Add `resolveSymbolCandidates(query: string): Promise<SymbolResolveCandidate[]>` to `frontend/src/utils.ts`.

**Step 3: Build frontend**

Run:

```bash
cd frontend
pnpm build
```

Expected: TypeScript compile succeeds after UI task is complete.

### Task 3: Header Dropdown UI

**Files:**
- Modify: `frontend/src/components/Header.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: Add state and callback wiring**

`App.tsx` owns resolver state near `newTicker`: candidates, loading state, selected candidate, dropdown visibility. It passes candidates and select handler to `Header`.

**Step 2: Fetch candidates on numeric input**

Use a debounced `useEffect` to call `resolveSymbolCandidates(newTicker)` for non-empty inputs. Clear candidates when input is empty.

**Step 3: Submit selected symbol**

When a candidate is selected, set `newTicker` to the candidate `symbol`. `handleAddStock` submits that value.

**Step 4: Render dropdown**

`Header.tsx` renders a compact absolute-positioned list under the input:

- primary line: name or display code
- secondary line: display code and Yahoo symbol
- active/hover state
- empty hidden state

**Step 5: Build and smoke test**

Run:

```bash
cd frontend
pnpm build
```

Then start dev server and verify the dropdown in browser.

### Task 4: Final Verification

**Files:**
- Review: `backend/main.py`
- Review: `frontend/src/App.tsx`
- Review: `frontend/src/components/Header.tsx`

**Step 1: Run targeted backend tests**

```bash
cd backend
uv run python -m unittest tests.test_watchlist_path -v
```

**Step 2: Run frontend build**

```bash
cd frontend
pnpm build
```

**Step 3: Inspect diff**

```bash
git diff --stat
git diff -- backend/main.py frontend/src/App.tsx frontend/src/components/Header.tsx frontend/src/types.ts frontend/src/utils.ts backend/tests/test_watchlist_path.py
```
