"""Buying signals from what customers say: extraction, the sweep, and reads.

Kept apart from ``agent_core.perception`` on purpose. Perception holds
servicing facts (hardship, dispute, consent withdrawal) that can only ever
suppress contact; a sales signal must never reach that table or the
collections veto stack, and a servicing fact must never become a sales lead.
"""
