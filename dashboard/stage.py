"""Derive the incident stage from observable evidence."""

from __future__ import annotations

from dashboard.model import LiveState, StageName, StageStatus

SCORE_THRESHOLD = 0.8
ORDER: tuple[StageName, ...] = ("healthy", "alerting", "interim", "rca", "permanent", "resolved")


def derive_stage(state: LiveState, mitigation_seen: bool) -> StageStatus:
    """mitigation_seen: an approval was requested earlier in the current incident."""
    ticket, agent = state.ticket, state.agent
    issue, pull = ticket.issue, ticket.pull
    if issue is not None:
        ref = f"issue #{issue.number}"
        if issue.state == "closed":
            return StageStatus("resolved", "none", "Incident closed", (f"{ref} closed",))
        if pull is not None and pull.merged:
            deploy = ticket.run("deploy-app")
            if deploy and deploy.conclusion == "success" and deploy.head_sha == pull.merge_sha:
                return StageStatus(
                    "permanent",
                    "system",
                    "Verifying recovery",
                    (f"deploy-app {deploy.head_sha[:7]}",),
                )
            return StageStatus(
                "permanent", "system", "Deploying fix", (f"PR #{pull.number} merged",)
            )
        if pull is not None:
            return StageStatus(
                "permanent", "human", f"Review and merge PR #{pull.number}", (f"PR #{pull.number}",)
            )
        if "approved" in issue.labels:
            return StageStatus("permanent", "system", "Coding agent preparing fix", (ref,))
        return StageStatus("permanent", "human", f"Approve fix plan on {ref}", (f"{ref} opened",))
    if agent.thread_id is not None:
        if agent.approvals:
            action = agent.approvals[0].action
            return StageStatus("interim", "human", f"Approve: {action}", ("approval pending",))
        if mitigation_seen:
            return StageStatus("rca", "system", "Investigating root cause", ("mitigation decided",))
        return StageStatus("interim", "system", "Triage", ("agent thread started",))
    alert = state.alert("ml")
    if alert is not None and alert.condition == "Fired":
        return StageStatus(
            "alerting", "system", "Alert sent to SRE Agent", (f"{alert.rule} Fired",)
        )
    score = state.detector.score
    if score is not None and score >= SCORE_THRESHOLD:
        return StageStatus("alerting", "system", "Anomaly sustained", (f"Score {score:.2f}",))
    return StageStatus("healthy", "none", "All systems normal")


def latch(new: StageStatus, previous: StageStatus) -> StageStatus:
    """Within one incident the stage only moves forward; healthy ends the incident."""
    if new.current == "healthy" or ORDER.index(new.current) >= ORDER.index(previous.current):
        return new
    return previous
