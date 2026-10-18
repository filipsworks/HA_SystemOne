# HA_SystemOne

Polish text commands → Home Assistant service calls. Package and CLI are named `decision_ha` / `decide`.
Public repo: https://github.com/jarekmor/HA_SystemOne (MIT), `origin` over SSH.

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

Docker: `docker compose build` / `up -d` / `run --rm decide <args>` (same subcommands); `compose.gpu.yaml` is the NVIDIA overlay. A local `compose.override.yaml` (gitignored) is auto-merged.

**torch variants:** extras `cpu` and `cuda` are declared as `conflicts` in `pyproject.toml` — without that, the extra-scoped cpu index leaks into the default resolution and *every* install gets CPU torch. Since `2.14.1+cpu` satisfies `==2.14.1`, `uv sync` won't swap an installed CPU build back; use `uv sync --reinstall-package torch`. Check with `python -c "import torch; print(torch.__version__)"`.

## Claude tooling (`.claude/`)

- **`ha-api-poll` skill** — read-only HA REST queries for development: `.venv/bin/python .claude/skills/ha-api-poll/scripts/poll.py states <entity_id>` (also `history`, `logbook`, `services`, `config`, `get <path>`). Use it to inspect `supported_features`/attributes when an intent is missing, and to confirm the state change and logbook entry after an `--execute`. Not imported by `decision_ha` — the app uses `ha_client.py`. Its tests: `uv run --with pytest pytest .claude/skills/ha-api-poll/scripts/test_poll.py`.
- **PreToolUse hook** (`settings.json`) — denies any Bash command that looks like an HTTP DELETE (it matches the command text, so even a test string containing one is blocked).

## Rules

- **Never run `--execute` (or `"execute": true` against `decide serve`) without the user's explicit OK for that specific command** — it changes real devices. Dry-run, `sync`, `eval` and state questions are read-only.
- Anything new the tool may send must be added to `ALLOWED` in `src/decision_ha/actions.py`; locks, alarms, gates and covers are deliberately absent.
- Home-specific notes (devices, IPs, eval baseline) are in `CLAUDE.local.md` (gitignored), when present.
- Credentials live only in this project's `.env` (`HA_URL`, `HA_TOKEN`, `TYPESAFE_API_KEY`, optional `TYPESAFE_MODEL`, `DECISION_MIN_CONFIDENCE`, `DECISION_API_TOKEN`, `LMSTUDIO_URL`, `LMSTUDIO_API_KEY`). Never print their values. The SDK does not read `.env` itself; `config.load_env_file()` does.
- `data/` is generated and gitignored — rebuild, don't hand-edit.
- Conventions: code, comments and TypeSafe instructions in English; user-facing CLI output, README, templates and aliases in Polish.

## Decisions backed by eval (don't undo without re-running `decide eval`)

- **Gate = Choice confidence ≥ 0.8 and choice ≠ "none".** The Choice with a "none" option carries the decision. Per-candidate `fits` nouls ran low for brand-name aliases and never caught a wrong action, so `min_fits = 0.0` (shown in `-v` only). The home-command gate only vetoes clear chit-chat (`min_gate = 0.2`).
- Intent labels in `templates.INTENT_LABELS` include example verbs — that raised reranker top-1 noticeably.
- The metric that matters is **0 wrong actions accepted**. Keep eval sets honest — fix ambiguity with aliases, not by tuning thresholds to one home's cases.

## Per-home configuration (the repo is generic)

- `aliases.yaml` and `eval/commands.yaml` are per-home and **gitignored**; the committed templates are `aliases.example.yaml` and `eval/commands.example.yaml`. `DECISION_ALIASES` / `DECISION_EVAL` override the paths.
- `decide init` writes a starting `aliases.yaml` from the HA instance (every area + commented list of controllable entities); it never overwrites.
- **The repo is public: everything committed is published.** Never commit anything home-specific (entity IDs, IPs, device names, tokens) — that goes into the gitignored `CLAUDE.local.md`, `aliases.yaml` or the eval set. Before each push, check the diff (`git diff origin/main`) for such data.
- Polish only for now: `templates`, `params`, `execute`, `server.speech_for` and the `areas` locatives are all Polish.
- media_player intents are derived from `supported_features` bits (`catalog.py`), so devices differ per home.

## Deployment

- `decide serve --host 0.0.0.0` (port 8765), normally the `decide` service of `compose.yaml`; called from HA via `rest_command` + an Assist automation — the YAML is in README and lives in HA, not in this repo.
- Image: `Dockerfile` with `--build-arg TORCH=cpu|cuda` (= the uv extra); `DECISION_DIR=/config` (project dir mounted) and `HF_HOME=/models`; runs as uid 1000; HEALTHCHECK waits for `/health` → `"ok"`. Published by `.github/workflows/docker.yml` to `ghcr.io/jarekmor/ha_systemone:{cpu,cuda,latest}`; `tests.yml` runs pytest with `--extra cpu`.
- Docker-published ports bypass ufw — README documents `network_mode: host` in `compose.override.yaml` to keep a firewall rule effective.
- After changing server code, rebuild the image and `docker compose up -d` (or restart a hand-started `decide serve`). `/decide` with `execute: true` changes real devices — the `--execute` rule applies.
- `speech` (`server.speech_for`): choice `none` → "Nie mam urządzenia…" (no alternatives — they misled); low confidence → "Czy chodziło o: <names>?"; gate < `min_gate` → "Nie rozumiem polecenia."

## Layout

`src/decision_ha/`: `config` (env, paths, thresholds) · `ha_client` (REST; areas via `/api/template`) · `catalog` (filter, intents, aliases) · `templates` (Polish sentences, candidate descriptions, fits questions) · `index` (bge-m3 + Chroma) · `rerank` · `decide` (TypeSafe questions + `apply_gate`) · `compat` (`LMSTUDIO_URL` set → `TypeSafeClient` pointed at LM Studio's Jev-compatible `POST /v1/systemone`; `TYPESAFE_MODEL` = the loaded decision model) · `params` (numbers, colours, options) · `actions` (service mapping + allowlist) · `execute` (Polish state answers) · `pipeline` · `server` (FastAPI; no `DECISION_API_TOKEN` → execute refused with 403) · `cli`.

## Known limits / next steps

- Each CLI run loads both models (~10 s); `decide serve` loads them once at startup (`Pipeline.warm_up`, ~12 s), then ≈ 0.3 s per query on a GPU, 0.7–1.4 s on CPU (Ryzen 7 7800X3D, CPU image). Queries are serialized with a lock — fine for one home.
- `HAClient` raises `HAAuthError` on 401 (the CLI turns it into an exit message, the server into 502) — never `sys.exit` in code the server runs.
- Untested so far: macOS/Windows, the GitHub Actions workflows before their first run, and any HA install other than the author's (the example eval uses made-up entity IDs).
- Roadmap: (1) read-only sensors (`sensor`/`binary_sensor`/`climate`, `query_state` only, filtered to temperature/humidity etc.; answer with value + unit; add eval cases) — list the home's sensors before choosing; (2) a local decision server as an alternative to TypeSafe — LM Studio via `compat` is wired but not yet run against `decide eval`; (3) keep the catalog in sync with HA without manual `sync`/`index`/restart; (4) a native HA conversation agent (HACS); (5) languages other than Polish, later.
- Several numbers in one sentence → extra TypeSafe Choice (`decide.choose_value`); relative brightness/volume ("przyciemnij", "ścisz") uses ±20% steps / volume_up/down.
