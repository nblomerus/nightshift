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
    f = sub.add_parser("floor", help="lab floor dashboard")
    f.add_argument("mode", choices=["serve", "build"])
    f.add_argument("root")
    f.add_argument("out", nargs="?", default="lab_floor_replay.html")
    f.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)

    if a.cmd == "run":
        from harness.daemon import run

        if a.fake_llm:
            from harness.fake_llm import fake_llm as llm
        else:
            from harness.llm import openai_compatible_llm

            llm = openai_compatible_llm(
                os.environ["LLM_BASE_URL"],
                os.environ["REASONING_MODEL"],
                os.environ.get("UTILITY_MODEL", os.environ["REASONING_MODEL"]),
                os.environ.get("LLM_API_KEY", "none"),
            )
        run(llm, root=a.root, n_campaigns=a.campaigns, rigspec=a.rigspec)
        print(f"done: {a.root}   (view: make replay RUN={a.root})")
    else:
        from api.floor import build_static, serve

        if a.mode == "serve":
            serve(a.root, a.port)
        else:
            print(build_static(a.root, a.out))


if __name__ == "__main__":
    main()
