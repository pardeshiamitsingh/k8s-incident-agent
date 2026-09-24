"""Fuzzy-matches a free-text mention against live Deployment names, and
resolves a match down to one object the same way spec 005 already does
(spec 008).

Deliberately deterministic, not LLM-ranked: this step decides which real
object gets diagnosed, and that needs to stay explainable and testable --
same reasoning as `agent/classification.py` staying LLM-free.
"""

import difflib
import logging

from collectors.k8s_client import build_apps_api_client
from collectors.models import ObjectRef
from intake.models import IntakeRequest, ResolutionError
from intake.resolve import deployment_unhealthy, resolve_intake

from .models import AmbiguousMatch, DetectedMention, NotFound

logger = logging.getLogger(__name__)

FUZZY_MATCH_CUTOFF = 0.6


def fuzzy_candidates(
    mention: str, namespace_scope: list[str] | None = None
) -> list[ObjectRef]:
    """Public, test-facing surface: the matched Deployments as `ObjectRef`s,
    with no health tie-break applied. `resolve_mention` is what actually
    decides between them."""
    return [_to_ref(d) for d in _match_deployments(mention, _list_deployments(namespace_scope))]


def resolve_mention(
    mention: DetectedMention, namespace_scope: list[str] | None = None
) -> ObjectRef | AmbiguousMatch | NotFound:
    matches = _match_deployments(mention.mentioned_service, _list_deployments(namespace_scope))
    if not matches:
        return NotFound()

    chosen = matches[0] if len(matches) == 1 else _tie_break_by_health(matches)
    if chosen is None:
        logger.info(
            "mention %r ambiguous: %d candidate(s), health didn't disambiguate",
            mention.mentioned_service, len(matches),
        )
        return AmbiguousMatch(candidates=[_to_ref(d) for d in matches])

    # Re-verify through the canonical resolution path rather than trusting
    # the listing snapshot -- also naturally handles the object having been
    # deleted between listing and resolving.
    result = resolve_intake(
        IntakeRequest(namespace=chosen.metadata.namespace, name=chosen.metadata.name, kind="Deployment")
    )
    if isinstance(result, ResolutionError):
        logger.info(
            "mention %r matched %s/%s but resolve_intake rejected it: %s",
            mention.mentioned_service, chosen.metadata.namespace,
            chosen.metadata.name, result.message,
        )
        return NotFound()

    logger.info(
        "mention %r resolved to %s/%s",
        mention.mentioned_service, result.namespace, result.name,
    )
    return result


def _list_deployments(namespace_scope: list[str] | None):
    apps_api = build_apps_api_client()
    if namespace_scope:
        items = []
        for namespace in namespace_scope:
            items.extend(apps_api.list_namespaced_deployment(namespace).items)
        return items
    return apps_api.list_deployment_for_all_namespaces().items


def _match_deployments(mention: str, deployments) -> list:
    by_name: dict[str, list] = {}
    for deployment in deployments:
        by_name.setdefault(deployment.metadata.name, []).append(deployment)

    names = list(by_name.keys())
    substring_matches = [n for n in names if mention.lower() in n.lower()]
    matched_names = substring_matches or difflib.get_close_matches(
        mention, names, n=5, cutoff=FUZZY_MATCH_CUTOFF
    )

    matched = []
    for name in matched_names:
        matched.extend(by_name[name])
    return matched


def _tie_break_by_health(deployments):
    unhealthy = [d for d in deployments if deployment_unhealthy(d)]
    return unhealthy[0] if len(unhealthy) == 1 else None


def _to_ref(deployment) -> ObjectRef:
    return ObjectRef(
        kind="Deployment", namespace=deployment.metadata.namespace, name=deployment.metadata.name
    )
