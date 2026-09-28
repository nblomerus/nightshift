"""Explorer (code): cheap exploratory screen. Ranks candidates; never changes a claim's status."""

from __future__ import annotations


def explorer_screen(ctx):
    """Cheap exploratory screen (code): every untested change vs the champion on exploration panels.
    Output is marked exploratory and can only influence WHAT is tested, never a claim's status."""
    J, screen = ctx["judge"], {}
    for k, (_desc, change) in J.MENU.items():
        if all(ctx["champion"].get(a) == b for a, b in change.items()):
            continue
        num = den = 0.0
        for s in J.data_keys("exploration"):
            num += J.evaluate(dict(ctx["champion"], **change), "A", s, ctx["cache"])["abs_err"].sum()
            den += J.evaluate(ctx["champion"], "A", s, ctx["cache"])["abs_err"].sum()
        screen[k] = 1 - num / den
    ctx["screen"] = dict(sorted(screen.items(), key=lambda x: -x[1]))
    return ctx["screen"]
