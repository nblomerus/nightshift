"""Nightshift CLI, run from the repo root: ``python -m ops.nightshift run|floor ...`` (the Makefile wraps these)."""

from __future__ import annotations

import argparse
import os


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ops.nightshift")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run campaigns of the rig")
    r.add_argument("--root", default="runs/latest")
    r.add_argument("--campaigns", type=int, default=3)
    r.add_argument("--rigspec", default=None, help="path to a rigspec JSON (default: bundled forecast-lab)")
    r.add_argument("--fake-llm", action="store_true", help="deterministic offline stand-in (for demos/tests)")
    r.add_argument("--knowledge", default=None, help="knowledge graph path (default: knowledge/<rig>.db)")
    r.add_argument("--no-knowledge", action="store_true", help="run without the lab's memory (demos, experiments)")
    kn = sub.add_parser("knowledge", help="what the lab knows: the brief the PI plans from")
    kn.add_argument("--rigspec", default=None)
    kn.add_argument("--knowledge", default=None)
    kn.add_argument("--json", action="store_true", help="the whole graph as JSON")
    kn.add_argument("--import", dest="import_run", default=None, help="backfill the graph from a finished run directory")
    kn.add_argument("--regrade", default=None, metavar="RUNS_DIR", help="re-read grade-B tests from their proof files")
    rp = sub.add_parser("reply", help="answer the lab: the PI reads it in its next plan")
    rp.add_argument("message")
    rp.add_argument("--request", default=None, help="the request this answers (closes it); see `requests`")
    rp.add_argument("--rigspec", default=None)
    rp.add_argument("--knowledge", default=None)
    rq = sub.add_parser("requests", help="what the PI has asked the owner")
    rq.add_argument("--all", action="store_true", help="answered requests too")
    rq.add_argument("--rigspec", default=None)
    rq.add_argument("--knowledge", default=None)
    f = sub.add_parser("floor", help="lab floor dashboard")
    f.add_argument("mode", choices=["serve", "build"])
    f.add_argument("root")
    f.add_argument("out", nargs="?", default="lab_floor_replay.html")
    f.add_argument("--port", type=int, default=18765)
    a = ap.parse_args(argv)

    def kg_path(spec):
        return a.knowledge or os.path.join("knowledge", f"{spec.get('rig', 'rig')}.db")

    if a.cmd == "reply":
        from harness.daemon import load_rigspec
        from state.knowledge import Knowledge

        if not a.message.strip():
            ap.error("reply: the message is empty")
        spec = load_rigspec(a.rigspec)
        try:
            Knowledge(kg_path(spec), spec.get("rig", "rig")).reply(a.message.strip(), a.request)
        except KeyError as e:
            ap.error(f"reply: {e.args[0]}")
        print(f"sent to the {spec.get('rig', 'rig')} PI; it reads it from its next plan")
        return

    if a.cmd == "requests":
        from harness.daemon import load_rigspec
        from state.knowledge import Knowledge

        spec = load_rigspec(a.rigspec)
        reqs = Knowledge(kg_path(spec), spec.get("rig", "rig")).requests(None if a.all else "open")
        print("\n\n".join(request_text(r) for r in reqs) or "No open requests.")
        return

    if a.cmd == "knowledge":
        import json

        from agents.common import describe_config, load_judge
        from harness.daemon import load_rigspec
        from state.knowledge import Knowledge

        spec = load_rigspec(a.rigspec)
        judge = load_judge(spec)
        kg = Knowledge(kg_path(spec), spec.get("rig", "rig"))
        if a.import_run:
            from harness.knowledge_import import import_run

            print(f"imported {a.import_run}: {import_run(kg, a.import_run, judge)}")
        if a.regrade:
            from harness.knowledge_import import regrade

            changed = regrade(kg, a.regrade)
            print(f"regraded {len(changed)} test(s)")
            for tid, grade in changed.items():
                print(f"  {tid}: {grade}")
            return
        if a.json:
            print(json.dumps(kg.export(), indent=1, default=str))
            return
        champ = kg.current_champion() or (judge.BASELINE, describe_config(judge, judge.BASELINE))
        print(kg.brief(champ[0], champ[1], []))
        return

    if a.cmd == "run":
        from harness.daemon import run

        if a.fake_llm:
            from agents.common import load_judge
            from harness.daemon import load_rigspec
            from harness.fake_llm import make_fake_llm

            llm = make_fake_llm(load_judge(load_rigspec(a.rigspec)).MENU)
        else:
            from harness.llm import openai_compatible_llm

            llm = openai_compatible_llm(
                os.environ["LLM_BASE_URL"],
                os.environ["REASONING_MODEL"],
                os.environ.get("UTILITY_MODEL", os.environ["REASONING_MODEL"]),
                os.environ.get("LLM_API_KEY", "none"),
            )
        from harness.daemon import load_rigspec

        knowledge = None if a.no_knowledge else kg_path(load_rigspec(a.rigspec))
        run(llm, root=a.root, n_campaigns=a.campaigns, rigspec=a.rigspec, knowledge=knowledge)
        print(f"done: {a.root}   (view: make replay RUN={a.root})")
    else:
        from api.floor import build_static, serve

        if a.mode == "serve":
            serve(a.root, a.port)
        else:
            print(build_static(a.root, a.out))


def request_text(r):
    """A request as a brief the owner can act on, or paste to someone who will."""
    lines = [f"[{r['status']}] {r['id']} (asked {r['asks']}x)", f"What: {r['what']}"]
    lines += [f"{k.title()}: {r[k]}" for k in ("why", "how", "done") if r.get(k)]
    if r.get("reply"):
        lines.append(f"Owner's reply: {r['reply']}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
