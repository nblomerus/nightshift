"""Run seat-written code in a sandbox (ROADMAP item 5). Part of the frozen judge: seats never edit it.

A plugin is Python source defining `features(view) -> np.ndarray`. It runs in a separate interpreter (`python -I`)
that, before importing the plugin:
  - caps CPU time (RLIMIT_CPU) and, where the OS supports it, memory (RLIMIT_AS); the parent also enforces a
    wall-clock timeout and kills the process;
  - installs a Python audit hook (PEP 578: it cannot be removed) that refuses sockets, subprocesses, process
    replacement and forking, loading C libraries by hand, and any file access outside the plugin's scratch
    directory and the Python installation (read-only);
  - on macOS, also runs under `sandbox-exec` with network access denied by the OS.
Views go in and features come out as .npz files in the scratch directory, which is deleted afterwards.

The audit hook is a strong guard against an LLM writing code that reaches for the network or the data files; it is not
a boundary against a determined attacker (that needs a container or VM). The judge only ever passes point-in-time
views, so the data a plugin can see is already safe to see.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile

import numpy as np


class SandboxError(Exception):
    """The plugin failed, timed out, broke a rule, or returned something unusable."""


RUNNER = r"""
import os, sys, resource
cpu, mem, scratch = int(sys.argv[1]), int(sys.argv[2]), os.path.realpath(sys.argv[3])
resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
if sys.platform.startswith("linux"):
    resource.setrlimit(resource.RLIMIT_AS, (mem * 2**20, mem * 2**20))
import numpy as np  # before the hook: numpy's own files load from the installation
roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, scratch} | set(sys.path)
readable = tuple(os.path.realpath(p) for p in roots if p)
BLOCKED = ("socket.", "subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork",
           "os.forkpty", "ctypes.dlopen", "ctypes.dlsym", "os.kill", "os.putenv", "os.chdir", "urllib.Request",
           "http.client.connect", "ftplib.", "smtplib.", "webbrowser.open")
def hook(event, args):
    if event.startswith(BLOCKED):
        raise PermissionError(f"sandbox: {event} is not allowed")
    if event == "open":
        path, mode = args[0], args[1] if len(args) > 1 else "r"
        if isinstance(path, int):
            return
        real = os.path.realpath(os.fsdecode(path))
        writing = mode is not None and any(c in str(mode) for c in "wax+")
        if real.startswith(scratch + os.sep) or real == scratch:
            return
        if writing or not real.startswith(readable):
            raise PermissionError(f"sandbox: may not open {real}")
    if event in ("os.remove", "os.rename", "os.rmdir", "os.mkdir", "shutil.rmtree", "os.unlink"):
        target = os.path.realpath(os.fsdecode(args[0]))
        if not target.startswith(scratch):
            raise PermissionError(f"sandbox: {event} outside the scratch directory")
views = dict(np.load(os.path.join(scratch, "views.npz")))
n = int(views.pop("__n__"))
sys.addaudithook(hook)
ns = {"__name__": "plugin"}
exec(compile(open(os.path.join(scratch, "plugin.py")).read(), "plugin.py", "exec"), ns)
if "features" not in ns:
    raise SystemExit("plugin defines no features(view)")
out = {}
for i in range(n):
    view = {k.split("__", 1)[1]: v for k, v in views.items() if k.startswith(f"v{i}__")}
    out[f"f{i}"] = np.asarray(ns["features"](view), dtype=np.float64)
np.savez(os.path.join(scratch, "features.npz"), **out)
"""


def _command(runner, cpu, mem, scratch):
    cmd = [sys.executable, "-I", runner, str(cpu), str(mem), scratch]
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        cmd = ["sandbox-exec", "-p", "(version 1)(allow default)(deny network*)"] + cmd
    return cmd


def run_plugin(
    source: str, views: list[dict], timeout: float = 60.0, mem_mb: int = 2048, max_cols: int = 8
) -> list[np.ndarray]:
    """features(view) for each view, computed in the sandbox. Each result is (rows,) or (rows, k<=max_cols), finite,
    with `rows` equal to the view's `n_rows`."""
    scratch = os.path.realpath(tempfile.mkdtemp(prefix="nightshift-plugin-"))
    try:
        with open(os.path.join(scratch, "plugin.py"), "w") as f:
            f.write(source)
        runner = os.path.join(scratch, "runner.py")
        with open(runner, "w") as f:
            f.write(RUNNER)
        flat = {"__n__": np.array(len(views))}
        for i, v in enumerate(views):
            for k, a in v.items():
                flat[f"v{i}__{k}"] = np.asarray(a)
        np.savez(os.path.join(scratch, "views.npz"), **flat)
        try:
            proc = subprocess.run(
                _command(runner, int(timeout) + 1, mem_mb, scratch),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=scratch,
                env={"PATH": "/usr/bin:/bin", "HOME": scratch, "PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1"},
            )
        except subprocess.TimeoutExpired as e:
            raise SandboxError(f"timed out after {timeout:.0f} s") from e
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip().splitlines()
            raise SandboxError(err[-1] if err else f"exit code {proc.returncode}")
        with np.load(os.path.join(scratch, "features.npz")) as z:
            out = [z[f"f{i}"] for i in range(len(views))]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    for i, (a, v) in enumerate(zip(out, views, strict=True)):
        rows = int(np.asarray(v["n_rows"])) if "n_rows" in v else a.shape[0]
        if a.ndim == 1:
            a = a[:, None]
        if a.ndim != 2 or a.shape[0] != rows or not 1 <= a.shape[1] <= max_cols:
            raise SandboxError(f"view {i}: features must be (rows={rows},) or (rows, k<={max_cols}); got {a.shape}")
        if not np.all(np.isfinite(a)):
            raise SandboxError(f"view {i}: features contain NaN or infinity")
        out[i] = a
    return out


def purelib() -> str:
    return sysconfig.get_paths()["purelib"]
