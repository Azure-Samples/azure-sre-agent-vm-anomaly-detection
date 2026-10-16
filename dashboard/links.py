"""Deep links from dashboard items to the Azure portal, the SRE Agent portal and GitHub.

Resource overview links use the stable portal form. The Log Analytics query link has no
published contract; keep every format here so it can be replaced in one place.
"""

from __future__ import annotations

import base64
import gzip
from urllib.parse import quote

from dashboard import queries
from dashboard.config import Config
from dashboard.model import Link, LiveState, StageStatus

PORTAL = "https://portal.azure.com/#@{tenant}"
# Thread URL format as produced by "Copy link to thread" in the SRE Agent portal.
SRE_PORTAL = "https://sre.azure.com/agents"


def _safe(link: Link | None) -> Link | None:
    return link if link is not None and link.url.startswith("https://") else None


class LinkBuilder:
    def __init__(self, config: Config) -> None:
        self._c = config
        self._portal = PORTAL.format(tenant=config.tenant_id)

    def resource(self, resource_id: str, label: str, exact: bool = True) -> Link:
        return Link(f"{self._portal}/resource{resource_id}/overview", label, exact)

    def logs(self, query: str, label: str) -> Link:
        packed = base64.b64encode(gzip.compress(query.encode())).decode()
        url = (
            f"{self._portal}/blade/Microsoft_Azure_Monitoring_Logs/LogsBlade/resourceId/"
            f"{quote(self._c.workspace_id, safe='')}/source/LogsBlade.AnalyticsShareLinkToQuery/"
            f"q/{quote(packed, safe='')}/timespan/PT1H"
        )
        return Link(url, label)

    def _agent(self, thread_id: str | None) -> Link:
        template = self._c.sre_thread_url_template
        if thread_id and template:
            return Link(
                template.format(thread_id=quote(thread_id, safe="")),
                "Open thread in SRE Agent portal",
            )
        agent = f"{SRE_PORTAL}{self._c.agent_id}"
        if thread_id:
            return Link(
                f"{agent}/views/thread/{quote(thread_id, safe='')}",
                "Open thread in SRE Agent portal",
            )
        return Link(agent, "Open SRE Agent portal")

    def build(self, state: LiveState, stage: StageStatus) -> dict[str, Link]:
        c, vm = self._c, self._c.vm_name
        repo = f"https://github.com/{c.repo}"
        agent = self._agent(state.agent.thread_id)
        links: dict[str, Link | None] = {
            "vm": self.resource(c.vm_id, f"Open {vm} in Azure portal"),
            "law": self.resource(c.workspace_id, "Open Log Analytics workspace"),
            "perf": self.logs(queries.metrics(vm), "Open Perf query in Log Analytics"),
            "syslog": self.logs(queries.service(vm), "Open demo-app Syslog in Log Analytics"),
            "detector": self.logs(queries.scores(vm), "Open VMAnomalyScore_CL in Log Analytics"),
            "function": self.resource(c.function_id, "Open detector Function App")
            if c.function_app
            else self.resource(c.rg_id, "Open resource group (overview)", exact=False),
            "alert:ml": self.resource(c.alert_rule_id(c.ml_alert_rule), "Open ML alert rule"),
            "alert:memlow": self.resource(
                c.alert_rule_id(c.memlow_alert_rule), "Open memory alert rule"
            ),
            "agent": agent,
            "repo": Link(repo, "Open repository on GitHub"),
        }
        if state.agent.approvals:
            links["approval"] = Link(agent.url, "Approve in SRE Agent portal", agent.exact)
        ticket = state.ticket
        if ticket.issue:
            links["issue"] = Link(ticket.issue.url, f"Open issue #{ticket.issue.number} on GitHub")
        if ticket.pull:
            links["pull"] = Link(ticket.pull.url, f"Open PR #{ticket.pull.number} on GitHub")
        for workflow in ("deploy-app", "incident-approved"):
            run = ticket.run(workflow)
            links[f"run:{workflow}"] = (
                Link(run.url, f"Open {workflow}.yml run")
                if run
                else Link(f"{repo}/actions/workflows/{workflow}.yml", f"Open {workflow}.yml runs")
            )
        safe = {key: link for key, value in links.items() if (link := _safe(value))}
        stage_targets = {
            "alerting": "alert:ml",
            "interim": "approval" if "approval" in safe else "agent",
            "rca": "agent",
            "permanent": "pull" if "pull" in safe else "issue",
            "resolved": "issue",
        }
        for name, target in stage_targets.items():
            if target in safe:
                safe[f"stage:{name}"] = safe[target]
        if stage.current == "permanent" and ticket.pull and ticket.pull.merged:
            safe["stage:permanent"] = safe["run:deploy-app"]
        return safe
