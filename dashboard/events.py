"""Turn differences between two observations into timeline events."""

from __future__ import annotations

from dashboard.model import Event, LiveState, StageStatus
from dashboard.stage import SCORE_THRESHOLD

STAGE_LABELS = {
    "healthy": "Healthy",
    "alerting": "1 Alerting",
    "interim": "2 Interim action",
    "rca": "3 Root cause analysis",
    "permanent": "4 Permanent action",
    "resolved": "Resolved",
}


def diff(
    old: LiveState, new: LiveState, old_stage: StageStatus, new_stage: StageStatus, time: str
) -> list[Event]:
    events: list[Event] = []

    def add(source: str, message: str, link_id: str | None) -> None:
        events.append(Event(time, source, message, link_id))

    ref = new.service.deployed_ref
    if ref and ref != old.service.deployed_ref:
        add("Syslog", f"deploy {ref}", "syslog")
    replay = new.service.replay_started_at
    if replay and replay != old.service.replay_started_at:
        add("Syslog", "history replay started (batch /report?at= traffic)", "syslog")
    score, before = new.detector.score, old.detector.score
    if score is not None and score >= SCORE_THRESHOLD > (before or 0):
        add(
            "Detector",
            f"Score {score:.2f} crossed {SCORE_THRESHOLD:.2f} · {new.detector.top_feature}",
            "detector",
        )
    for alert in new.alerts:
        previous = old.alert(alert.key)
        if alert.condition != "None" and (
            previous is None or previous.condition != alert.condition
        ):
            add(
                "Azure Monitor",
                f"{alert.rule} {alert.condition} · {alert.severity}",
                f"alert:{alert.key}",
            )
    if new.agent.thread_id and new.agent.thread_id != old.agent.thread_id:
        add("SRE Agent", f"thread started · {new.agent.title or new.agent.thread_id}", "agent")
    known = {a.id for a in old.agent.approvals}
    for approval in new.agent.approvals:
        if approval.id not in known:
            add("SRE Agent", f"approval requested · {approval.action}", "approval")
    issue, prev_issue = new.ticket.issue, old.ticket.issue
    if issue and (prev_issue is None or prev_issue.number != issue.number):
        add("GitHub", f"issue #{issue.number} opened · {issue.title}", "issue")
    elif issue and prev_issue:
        for label in set(issue.labels) - set(prev_issue.labels):
            add("GitHub", f"label {label} added to #{issue.number}", "issue")
        if issue.state != prev_issue.state:
            add("GitHub", f"issue #{issue.number} {issue.state}", "issue")
    pull, prev_pull = new.ticket.pull, old.ticket.pull
    if pull and (prev_pull is None or prev_pull.number != pull.number):
        add("GitHub", f"PR #{pull.number} opened · {pull.title}", "pull")
    if pull and pull.merged and not (prev_pull and prev_pull.merged):
        add("GitHub", f"PR #{pull.number} merged", "pull")
    for run in new.ticket.runs:
        prev_run = old.ticket.run(run.workflow)
        changed = prev_run is None or (prev_run.url, prev_run.conclusion) != (
            run.url,
            run.conclusion,
        )
        if changed and run.conclusion:
            add(
                "GitHub Actions",
                f"{run.workflow}.yml {run.conclusion} · {run.head_sha[:7]}",
                f"run:{run.workflow}",
            )
    if new_stage.current != old_stage.current:
        add(
            "Dashboard",
            f"stage → {STAGE_LABELS[new_stage.current]} · {new_stage.detail}",
            f"stage:{new_stage.current}",
        )
    return events
