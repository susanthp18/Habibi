"""Closed clerk workflow allowlist tied to contract versions and action families."""

from __future__ import annotations

from bank_boundary import ACTION_CONTRACT_VERSION, OUTBOUND

ALLOWED_WORKFLOWS = frozenset(
    {
        "bounce_chase",
        "broken_ptp",
        "doc_sla",
        "callback_diary",
        "authority_hitl",
        "a2a_remote",
        "self_service_plan",
        "emi_date_change",
        "lms_workitem",
        "o1_send_message",
        "o2_rail_submit",
        "o3_cdr_writeback",
        "o4_consent_writeback",
        "o5_complaint_filing",
        "o6_lms_workitem",
    }
)

ACTION_FAMILIES = {
    "o1_send_message": "O1",
    "o2_rail_submit": "O2",
    "o3_cdr_writeback": "O3",
    "o4_consent_writeback": "O4",
    "o5_complaint_filing": "O5",
    "o6_lms_workitem": "O6",
    "lms_workitem": "O6",
}


def allow(workflow_type: str, *, contract_version: str | None = None) -> str | None:
    """Return a park reason, or None if the workflow may run."""
    wf = str(workflow_type or "")
    if wf not in ALLOWED_WORKFLOWS:
        return "unknown_workflow"
    if wf in ACTION_FAMILIES:
        if not contract_version:
            return "missing_contract_version"
        if contract_version != ACTION_CONTRACT_VERSION:
            return "unsupported_contract_version"
        if ACTION_FAMILIES[wf] not in OUTBOUND:
            return "unknown_action_family"
    return None
