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
    f = sub.add_parser("floor", help="lab floor dashboard")
    f.add_argument("mode", choices=["serve", "build"])
    f.add_argument("root")
    f.add_argument("out", nargs="?", default="lab_floor_replay.html")
    f.add_argument("--port", type=int, default=18765)
    a = ap.parse_args(argv)

    def kg_path(spec):
        return a.knowledge or os.path.join("knowledge", f"{spec.get('rig', 'rig')}.db")

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


if __name__ == "__main__":
    main()
