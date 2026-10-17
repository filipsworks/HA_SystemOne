# HA_SystemOne

Polish text commands → Home Assistant service calls. Package and CLI are named `decision_ha` / `decide`.

```
text → bge-m3 embeddings + ChromaDB (top 30 action docs, grouped to (entity, intent))
     → bge-reranker-v2-m3 cross-encoder (top 5)
     → TypeSafe AI system_one: Choice over candidates + "none", per-candidate fits Noul, home-command gate Noul
     → gate → allow-listed POST /api/services/<domain>/<service>   (or a state read for query_state)
```

TypeSafe (`typesafe-sdk`, model Jev) is a calibrated **classifier**, not a generator: it can only pick from the candidates we pass, so retrieval must surface the right (entity, intent) pair. Response API: `r.choices[k].choice / .confidence / .probabilities`, `r.nouls[k].noul`. Docs via context7: `/typesafe-docs/typesafeai`, SDK `/typesafe-ai/typesafe-sdk-python`.

## Commands

```bash
uv sync                                   # PyPI torch (CUDA on Linux); no GPU: --extra cpu (then also uv run --extra cpu)
uv run pytest                             # unit tests, HA and TypeSafe mocked — no network
uv run decide init                        # first run in a new home: aliases.yaml skeleton from HA
uv run decide sync                        # HA states + areas (template API) → data/catalog.json
uv run decide index                       # catalog → data/chroma/
uv run decide "włącz światło w sypialni" -v    # dry-run with retrieval/rerank/TypeSafe details
uv run decide eval                        # accuracy on eval/commands.yaml (calls TypeSafe, no HA writes)
uv run decide serve [--host 0.0.0.0] [--port 8765]   # FastAPI: POST /decide {"text", "execute"}, GET /health
```

After editing `aliases.yaml` or `templates.py`: `decide sync && decide index && decide eval`.

## Claude tooling (`.claude/`)

- **`ha-api-poll` skill** — read-only HA REST queries for development: `.venv/bin/python .claude/skills/ha-api-poll/scripts/poll.py states <entity_id>` (also `history`, `logbook`, `services`, `config`, `get <path>`). Use it to inspect `supported_features`/attributes when an intent is missing, and to confirm the state change and logbook entry after an `--execute`. Not imported by `decision_ha` — the app uses `ha_client.py`. Its tests: `uv run --with pytest pytest .claude/skills/ha-api-poll/scripts/test_poll.py`.
- **PreToolUse hook** (`settings.json`) — denies any Bash command that looks like an HTTP DELETE (it matches the command text, so even a test string containing one is blocked).

## Rules

- **Never run `--execute` (or `"execute": true` against `decide serve`) without the user's explicit OK for that specific command** — it changes real devices. Dry-run, `sync`, `eval` and state questions are read-only.
- Anything new the tool may send must be added to `ALLOWED` in `src/decision_ha/actions.py`; locks, alarms, gates and covers are deliberately absent.
- Home-specific notes (devices, IPs, eval baseline) are in `CLAUDE.local.md` (gitignored), when present.
- Credentials live only in this project's `.env` (`HA_URL`, `HA_TOKEN`, `TYPESAFE_API_KEY`, optional `TYPESAFE_MODEL`, `DECISION_MIN_CONFIDENCE`, `DECISION_API_TOKEN`). Never print their values. The SDK does not read `.env` itself; `config.load_env_file()` does.
- `data/` is generated and gitignored — rebuild, don't hand-edit.
- Conventions: code, comments and TypeSafe instructions in English; user-facing CLI output, README, templates and aliases in Polish.

## Decisions backed by eval (don't undo without re-running `decide eval`)

- **Gate = Choice confidence ≥ 0.8 and choice ≠ "none".** The Choice with a "none" option carries the decision. Per-candidate `fits` nouls ran low for brand-name aliases and never caught a wrong action, so `min_fits = 0.0` (shown in `-v` only). The home-command gate only vetoes clear chit-chat (`min_gate = 0.2`).
- Intent labels in `templates.INTENT_LABELS` include example verbs — that raised reranker top-1 noticeably.
- The metric that matters is **0 wrong actions accepted**. Keep eval sets honest — fix ambiguity with aliases, not by tuning thresholds to one home's cases.

## Per-home configuration (the repo is generic)

- `aliases.yaml` and `eval/commands.yaml` are per-home and **gitignored**; the committed templates are `aliases.example.yaml` and `eval/commands.example.yaml`. `DECISION_ALIASES` / `DECISION_EVAL` override the paths.
- `decide init` writes a starting `aliases.yaml` from the HA instance (every area + commented list of controllable entities); it never overwrites.
- Never commit anything home-specific (entity IDs, IPs, device names) to tracked files — that goes into the gitignored `CLAUDE.local.md`, `aliases.yaml` or the eval set.
- Polish only for now: `templates`, `params`, `execute`, `server.speech_for` and the `areas` locatives are all Polish.
- media_player intents are derived from `supported_features` bits (`catalog.py`), so devices differ per home.

## Deployment

- `decide serve --host 0.0.0.0` (port 8765), called from HA via `rest_command` + an Assist automation — the YAML is in README and lives in HA, not in this repo.
- After changing server code, the user must restart `decide serve`. `/decide` with `execute: true` changes real devices — the `--execute` rule applies.
- `speech` (`server.speech_for`): choice `none` → "Nie mam urządzenia…" (no alternatives — they misled); low confidence → "Czy chodziło o: <names>?"; gate < `min_gate` → "Nie rozumiem polecenia."

## Layout

`src/decision_ha/`: `config` (env, paths, thresholds) · `ha_client` (REST; areas via `/api/template`) · `catalog` (filter, intents, aliases) · `templates` (Polish sentences, candidate descriptions, fits questions) · `index` (bge-m3 + Chroma) · `rerank` · `decide` (TypeSafe questions + `apply_gate`) · `params` (numbers, colours, options) · `actions` (service mapping + allowlist) · `execute` (Polish state answers) · `pipeline` · `server` (FastAPI; no `DECISION_API_TOKEN` → execute refused with 403) · `cli`.

## Known limits / next steps

- Each CLI run loads both models (~10 s); `decide serve` loads them once at startup (`Pipeline.warm_up`, ~12 s), then ≈ 0.3 s per query. HA calls it via `rest_command` (example in README). Queries are serialized with a lock — fine for one home.
- `HAClient` raises `HAAuthError` on 401 (the CLI turns it into an exit message, the server into 502) — never `sys.exit` in code the server runs.
- Next steps the user was offered: (1) read-only sensors (`sensor`/`binary_sensor`/`climate`, `query_state` only, filtered to temperature/humidity etc.; answer with value + unit; add eval cases) — list the user's sensors before choosing; (2) systemd user service for `decide serve`.
- Several numbers in one sentence → extra TypeSafe Choice (`decide.choose_value`); relative brightness/volume ("przyciemnij", "ścisz") uses ±20% steps / volume_up/down.
