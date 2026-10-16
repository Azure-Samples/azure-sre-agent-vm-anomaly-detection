"""Dashboard settings read from environment variables; tokens are never part of Config."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields

PREFIX = "DASHBOARD_"


@dataclass(frozen=True)
class Config:
    tenant_id: str = ""
    subscription_id: str = ""
    resource_group: str = "rg-vm-anomaly-demo"
    vm_name: str = "vm-app-01"
    workspace_name: str = "law-vm-anomaly-demo"
    agent_name: str = "sreagent-vm-anomaly"
    function_app: str = ""
    ml_alert_rule: str = "alert-ml-anomaly-vm-app-01"
    memlow_alert_rule: str = "alert-mem-low-vm-app-01"
    repo: str = ""
    sre_thread_url_template: str = ""
    window_hours: float = 6.0

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        """Override defaults with DASHBOARD_<FIELD> variables, e.g. DASHBOARD_VM_NAME."""
        values: dict[str, str | float] = {}
        for item in fields(cls):
            raw = env.get(PREFIX + item.name.upper())
            if raw is not None:
                values[item.name] = float(raw) if isinstance(item.default, float) else raw
        return cls(**values)

    @property
    def rg_id(self) -> str:
        return f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"

    @property
    def vm_id(self) -> str:
        return f"{self.rg_id}/providers/Microsoft.Compute/virtualMachines/{self.vm_name}"

    @property
    def workspace_id(self) -> str:
        return (
            f"{self.rg_id}/providers/Microsoft.OperationalInsights/workspaces/{self.workspace_name}"
        )

    @property
    def agent_id(self) -> str:
        return f"{self.rg_id}/providers/Microsoft.App/agents/{self.agent_name}"

    @property
    def function_id(self) -> str:
        return f"{self.rg_id}/providers/Microsoft.Web/sites/{self.function_app}"

    def alert_rule_id(self, rule: str) -> str:
        return f"{self.rg_id}/providers/Microsoft.Insights/scheduledQueryRules/{rule}"
