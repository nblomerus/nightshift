"""One package per seat (mirrors lab-foundry's agents/). The daemon reads HANDLERS / MESSAGE_HANDLERS."""

from agents.common import *  # noqa: F401,F403
from agents.common import fh  # noqa: F401
from agents.critic.handler import critic_review
from agents.experimenter.handler import experimenter_check, experimenter_run
from agents.explorer.handler import explorer_screen  # noqa: F401
from agents.methodologist.handler import methodologist_answer, methodologist_draft
from agents.pi.handler import pi_plan, pi_read
from agents.replicator.handler import replicator_replicate
from agents.statistician.handler import promote_champion, statistician_analyse, statistician_power_controls  # noqa: F401
from agents.writer.handler import writer_write

HANDLERS = {
    "plan": pi_plan,
    "draft_prereg": methodologist_draft,
    "review_design": critic_review,
    "check_implementation": experimenter_check,
    "power_controls": statistician_power_controls,
    "run_experiment": experimenter_run,
    "analyse": statistician_analyse,
    "replicate": replicator_replicate,
    "write": writer_write,
}
MESSAGE_HANDLERS = {"methodologist": methodologist_answer, "pi": pi_read}
