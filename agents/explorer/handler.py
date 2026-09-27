"""Explorer (code): cheap exploratory screen. Ranks candidates; never changes a claim's status."""

from __future__ import annotations

from agents.common import EXPLORATION_SEEDS, MENU, evaluate_arm


def explorer_screen(ctx):
    """Cheap exploratory screen (code): every untested change vs the champion on exploration panels.
    Output is marked exploratory and can only influence WHAT is tested, never a claim's status."""
    screen = {}
    for k, (_desc, change) in MENU.items():
        if all(ctx["champion"].get(a) == b for a, b in change.items()):
            continue
        num = den = 0.0
        for s in EXPLORATION_SEEDS:
            num += evaluate_arm(dict(ctx["champion"], **change), "A", s, ctx["cache"])["abs_err"].sum()
            den += evaluate_arm(ctx["champion"], "A", s, ctx["cache"])["abs_err"].sum()
        screen[k] = 1 - num / den
    ctx["screen"] = dict(sorted(screen.items(), key=lambda x: -x[1]))
    return ctx["screen"]
