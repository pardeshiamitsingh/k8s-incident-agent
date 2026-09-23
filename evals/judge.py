"""Optional LLM-as-judge scoring (spec 006).

A complementary signal to keyword scoring, not a replacement -- reuses
the same local model as the Diagnose/Plan nodes, no external call and no
new constitution exception needed. Only invoked when the runner is passed
`--llm-judge`; keyword scoring alone stays the default so a full pass over
the golden set is fast.
"""

import logging

from pydantic import BaseModel, Field

from agent.llm import get_llm
from agent.state import AgentState

from .models import GoldenCase

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are grading a Kubernetes incident diagnosis against an expected \
outcome description. You are NOT diagnosing the incident yourself -- you \
are rating how well someone else's diagnosis and remediation plan match \
the concepts an expert would expect to see.

Score 1-5:
- 5: covers essentially all expected concepts, correct and complete.
- 3: covers some expected concepts but misses others, or is partially off.
- 1: does not address the expected concepts at all.

Give a one or two sentence rationale explaining the score.
"""


class JudgeVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    rationale: str


def judge_case(case: GoldenCase, state: AgentState) -> JudgeVerdict:
    user_prompt = (
        f"Expected failure class(es): {case.expected_failure_classes}\n"
        f"Expected root-cause concepts: {case.root_cause_keywords}\n"
        f"Expected remediation concepts: {case.remediation_keywords}\n\n"
        f"Actual root cause given: {state.diagnosis.root_cause}\n"
        f"Actual remediation steps given: {state.remediation_plan.steps}\n\n"
        "Rate how well the actual diagnosis and plan match the expected "
        "concepts."
    )
    structured_llm = get_llm().with_structured_output(JudgeVerdict)
    verdict = structured_llm.invoke(
        [("system", SYSTEM_PROMPT), ("user", user_prompt)]
    )
    logger.info("judge: case=%s score=%d", case.id, verdict.score)
    return verdict
