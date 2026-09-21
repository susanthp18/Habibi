"""Dashboard CSV is the same payload, without the widget LIMIT 6."""

from __future__ import annotations

import pytest

import db_dashboard
import invite_mail


def test_dashboard_to_csv_includes_the_lists() -> None:
    csv = db_dashboard.dashboard_to_csv(
        {
            "heroKpis": [{"label": "AHT", "value": "1m", "delta": None}],
            "kpis": [{"key": "recovered", "label": "Recovered", "value": "₹1", "delta": 1.0}],
            "atRiskAccounts": [
                {
                    "id": "c1",
                    "name": "A",
                    "account": "AC-1",
                    "outstanding": 10,
                    "daysPastDue": 5,
                    "risk": "high",
                    "lastContact": "2026-09-01",
                    "product": "Card",
                }
            ],
            "leaderboard": [
                {
                    "rank": 1,
                    "name": "Priya",
                    "team": "Delta",
                    "calls": 2,
                    "aht": "1m",
                    "upsell": None,
                    "csat": None,
                }
            ],
            "callVolumeStacked": [{"date": "2026-09-01", "voice": 1, "whatsapp": 0, "chat": 0}],
            "recoveryTrend": [{"date": "2026-09-01", "value": 10}],
        }
    )
    assert "kpi,recovered,Recovered" in csv
    assert "at_risk,c1,A,AC-1" in csv
    assert "leaderboard,1,Priya" in csv


def test_dashboard_json_endpoint_stays_capped(monkeypatch) -> None:
    """GET /dashboard still asks for six rows; CSV asks for the list cap."""
    seen: list[int] = []

    def fake_get_dashboard(*_a, list_limit: int = 6, **_k):
        seen.append(list_limit)
        return {"kpis": [], "heroKpis": [], "atRiskAccounts": [], "leaderboard": [],
                "callVolumeStacked": [], "recoveryTrend": []}

    monkeypatch.setattr(db_dashboard, "get_dashboard", fake_get_dashboard)
    db_dashboard.get_dashboard_csv("30d", "all", "all")
    assert seen == [db_dashboard.MAX_LIST_LIMIT]


def test_dashboard_mail_is_skipped_when_smtp_is_unset(monkeypatch) -> None:
    monkeypatch.setattr(invite_mail, "smtp_configured", lambda: False)
    err = invite_mail.send_dashboard_report_email(
        to_email="ops@example.com",
        download_url="http://localhost/export-jobs/EX1/download",
        range_key="7d",
    )
    assert err == "smtp_disabled"


def test_dashboard_export_job_create_does_not_need_redaction_ids() -> None:
    from pydantic import ValidationError

    from schemas.billing import ExportJobCreateRequest

    body = ExportJobCreateRequest(kind="dashboard", range="7d", segment="card")
    assert body.recordIds == []
    assert body.format == "csv"
    with pytest.raises(ValidationError):
        ExportJobCreateRequest(kind="redaction")
