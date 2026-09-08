"""W5 bank boundary — versioned contracts, not MCP connectors."""

from __future__ import annotations

INBOUND = ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "F8")
OUTBOUND = ("O1", "O2", "O3", "O4", "O5", "O6")
FAIRNESS = ("F9",)
ALL_CODES = INBOUND + OUTBOUND + FAIRNESS

DAY1_INBOUND = ("C1", "C2", "C6", "C8", "C10")
MANDATE_CODES = ("C3", "C4", "C5", "O2", "O6")
CONTACT_CODES = ("C7",)
FIELD_CODES = ("C9",)
PROMOTION_CODES = ("F9",)

CONTRACT_VERSION = "bank-boundary.v1"
ACTION_CONTRACT_VERSION = "action-contract.v1"

# Freshness thresholds from engines-production-design §7.8, in hours.
C6_NON_CONTACTING_HOURS = 4
C6_WAIT_ONLY_HOURS = 24
C1_WAIT_ONLY_HOURS = 48
C5_MANDATE_HOURS = 72
C8_ENDPOINT_HOURS = 24
C7_RESERVED_CAP_HOURS = 6
C9_ROSTER_HOURS = 7 * 24
SHADOW_STREAK_DAYS = 5
