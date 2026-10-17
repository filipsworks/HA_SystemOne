"""decide init | sync | index | eval | serve [--host H] [--port P] | decide "<polecenie>" [--execute] [--verbose]"""

import argparse
import sys
import time

import yaml

from decision_ha.config import (CATALOG_PATH, CHROMA_DIR, Settings, aliases_path, api_token,
                                eval_path, get_session, require_typesafe_key)
from decision_ha.catalog import aliases_skeleton, build_catalog, load_aliases, load_catalog, save_catalog
from decision_ha.ha_client import HAAuthError, HAClient

SUBCOMMANDS = {"init", "sync", "index", "eval", "serve"}


def ha_client():
    return HAClient(*get_session())


def cmd_init(args):
    path = aliases_path()
    if path.exists():
        sys.exit(f"{path} już istnieje — nie nadpisuję. Usuń go lub ustaw DECISION_ALIASES.")
    ha = ha_client()
    states = ha.states()
    areas = ha.areas_for([s["entity_id"] for s in states])
    path.write_text(aliases_skeleton(states, ha.areas(), areas))
    print(f"Zapisano szkielet {path}. Uzupełnij polskie nazwy obszarów i aliasy, potem `decide sync`.")


def cmd_sync(args):
    path = aliases_path()
    if not path.exists():
        print(f"Brak {path} — używam nazw z HA. `decide init` utworzy szkielet do uzupełnienia.")
    ha = ha_client()
    states = ha.states()
    areas = ha.areas_for([s["entity_id"] for s in states])
    catalog = build_catalog(states, areas, load_aliases(path))
    save_catalog(catalog, CATALOG_PATH)
    print(f"Zapisano {len(catalog)} encji do {CATALOG_PATH}")
    for e in catalog:
        print(f"  {e.entity_id:55} {e.area or '-':12} {e.name}  [{', '.join(e.intents)}]")


def cmd_index(args):
    from decision_ha.index import ActionIndex
    settings = Settings.from_env()
    catalog = load_catalog(CATALOG_PATH).values()
    started = time.perf_counter()
    count = ActionIndex(CHROMA_DIR, settings.embed_model).build(catalog)
    print(f"Zaindeksowano {count} dokumentów ({time.perf_counter() - started:.1f}s) w {CHROMA_DIR}")


def make_pipeline(with_ha=True):
    from typesafe_sdk import TypeSafeClient
    from decision_ha.pipeline import Pipeline
    require_typesafe_key()
    settings = Settings.from_env()
    return Pipeline(settings, TypeSafeClient(), ha_client() if with_ha else None)


def print_result(result, verbose):
    if verbose:
        print("Retrieval (top 10):")
        for c in result.retrieved[:10]:
            print(f"  {c.retrieval_score:.3f}  {c.key}")
        print("Rerank:")
        for c in result.reranked:
            print(f"  {c.rerank_score:.3f}  {c.key}")
        d = result.decision
        if d:
            print(f"TypeSafe: choice={d.choice} confidence={d.confidence:.2f} gate={d.gate:.2f}")
            for key, p in sorted(d.probabilities.items(), key=lambda kv: -kv[1]):
                print(f"  p={p:.3f} fits={d.fits.get(key, float('nan')):.2f}  {key}")
    if result.call:
        prefix = "Wykonano" if result.executed else "Dry-run (dodaj --execute)"
        print(f"{prefix}: {result.call}")
    if result.answer:
        print(result.answer)


def cmd_ask(text, execute, verbose):
    pipeline = make_pipeline()
    started = time.perf_counter()
    result = pipeline.run(text, execute=execute)
    print_result(result, verbose)
    if verbose:
        print(f"({time.perf_counter() - started:.2f}s)")
    return 0 if result.decision and result.decision.accepted else 1


def cmd_eval(args):
    path = eval_path()
    if not path.exists():
        sys.exit(f"Brak {path}. Skopiuj eval/commands.example.yaml i wpisz polecenia dla swoich encji.")
    cases = yaml.safe_load(path.read_text())
    pipeline = make_pipeline(with_ha=False)
    stats = {"retrieval": 0, "rerank_top1": 0, "rerank_in_k": 0, "final": 0, "wrong_accepted": 0, "abstained": 0}
    failures = []
    for case in cases:
        expected = None if case.get("expect") == "none" else (case["entity"], case["intent"])
        result = pipeline.run(case["text"])
        keys = [(c.entity_id, c.intent) for c in result.retrieved]
        reranked = [(c.entity_id, c.intent) for c in result.reranked]
        got = result.entity_intent
        if expected:
            stats["retrieval"] += expected in keys
            stats["rerank_top1"] += bool(reranked) and reranked[0] == expected
            stats["rerank_in_k"] += expected in reranked
        if got is None:
            stats["abstained"] += 1
        ok = got == expected
        if expected and case.get("data") and result.call:
            ok = ok and all(result.call.data.get(k) == v for k, v in case["data"].items())
        stats["final"] += ok
        if got is not None and not ok:
            stats["wrong_accepted"] += 1
        if not ok:
            failures.append((case["text"], expected, got, result.decision and round(result.decision.confidence, 2),
                             result.call and result.call.data))
    n = len(cases)
    n_pos = sum(1 for c in cases if c.get("expect") != "none")
    print(f"Przypadków: {n} (z akcją: {n_pos})")
    print(f"  retrieval recall@{pipeline.settings.retrieve_k}: {stats['retrieval']}/{n_pos}")
    print(f"  rerank w top-{pipeline.settings.rerank_k}:      {stats['rerank_in_k']}/{n_pos}")
    print(f"  rerank top-1:             {stats['rerank_top1']}/{n_pos}")
    print(f"  wynik końcowy poprawny:   {stats['final']}/{n}  ({stats['final'] / n:.0%})")
    print(f"  błędna akcja zaakceptowana: {stats['wrong_accepted']}")
    print(f"  wstrzymane (abstain):     {stats['abstained']}")
    for text, expected, got, conf, data in failures:
        print(f"  ✗ {text!r}: oczekiwano {expected}, jest {got} (conf={conf}, data={data})")
    return 0 if stats["wrong_accepted"] == 0 else 1


def cmd_serve(args):
    import uvicorn
    from decision_ha.server import create_app
    if not CATALOG_PATH.exists() or not CHROMA_DIR.exists():
        sys.exit(f"Brak {CATALOG_PATH} lub {CHROMA_DIR}. Najpierw `decide sync` i `decide index`.")
    token = api_token()
    if token is None:
        print("Brak DECISION_API_TOKEN — serwer działa tylko w trybie dry-run (execute → 403).")
    uvicorn.run(create_app(make_pipeline, token), host=args.host, port=args.port)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        return run(argv)
    except HAAuthError as error:
        sys.exit(str(error))


def run(argv):
    if argv and argv[0] in SUBCOMMANDS:
        parser = argparse.ArgumentParser(prog="decide")
        parser.add_argument("command", choices=sorted(SUBCOMMANDS))
        parser.add_argument("--host", default="127.0.0.1", help="serve: adres nasłuchu")
        parser.add_argument("--port", type=int, default=8765, help="serve: port")
        args = parser.parse_args(argv)
        handler = {"init": cmd_init, "sync": cmd_sync, "index": cmd_index, "eval": cmd_eval,
                   "serve": cmd_serve}[args.command]
        return handler(args) or 0
    parser = argparse.ArgumentParser(prog="decide", description=__doc__)
    parser.add_argument("text", nargs="+", help="polecenie po polsku")
    parser.add_argument("--execute", action="store_true", help="naprawdę wywołaj usługę HA")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    return cmd_ask(" ".join(args.text), args.execute, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
