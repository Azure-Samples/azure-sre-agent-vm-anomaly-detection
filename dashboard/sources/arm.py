"""Azure Resource Manager source: VM power state and Azure Monitor alert state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from dashboard.config import Config
from dashboard.model import AlertStatus

ARM = "https://management.azure.com"
Get = Callable[[str], object]


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


class ArmSource:
    name = "arm"

    def __init__(self, config: Config, get: Get, interval_s: float = 30.0) -> None:
        self.interval_s = interval_s
        self._c = config
        self._get = get

    def poll(self) -> dict[str, object]:
        return {"power_state": self._power_state(), "alerts": self._alerts()}

    def _power_state(self) -> str | None:
        view = _dict(self._get(f"{ARM}{self._c.vm_id}/instanceView?api-version=2024-07-01"))
        for status in _list(view.get("statuses")):
            code = str(_dict(status).get("code", ""))
            if code.startswith("PowerState/"):
                return code.removeprefix("PowerState/")
        return None

    def _alerts(self) -> tuple[AlertStatus, ...]:
        url = (
            f"{ARM}/subscriptions/{self._c.subscription_id}/providers/Microsoft.AlertsManagement/alerts"
            f"?targetResourceGroup={self._c.resource_group}&timeRange=1d&api-version=2019-03-01"
        )
        latest: dict[str, tuple[str, AlertStatus]] = {}
        rules: dict[str, Literal["ml", "memlow"]] = {
            self._c.ml_alert_rule.lower(): "ml",
            self._c.memlow_alert_rule.lower(): "memlow",
        }
        for item in _list(_dict(self._get(url)).get("value")):
            alert = _dict(item)
            essentials = _dict(_dict(alert.get("properties")).get("essentials"))
            rule = str(essentials.get("alertRule", "")).rsplit("/", 1)[-1]
            key = rules.get(rule.lower())
            raw = essentials.get("monitorCondition")
            if key is None or raw not in ("Fired", "Resolved"):
                continue
            condition: Literal["Fired", "Resolved"] = "Fired" if raw == "Fired" else "Resolved"
            started = str(essentials.get("startDateTime", ""))
            if key not in latest or started > latest[key][0]:
                status = AlertStatus(
                    key,
                    rule,
                    condition,
                    str(essentials.get("severity")),
                    started,
                    str(alert.get("id")),
                )
                latest[key] = (started, status)
        return tuple(
            latest[key][1] if key in latest else AlertStatus(key, name, "None")
            for name, key in rules.items()
        )
