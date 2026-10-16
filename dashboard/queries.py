"""KQL used both for polling and for the Log Analytics deep links."""

from __future__ import annotations

PSEUDO_FS = ("/snap", "/dev", "/run", "/sys", "/proc", "/boot/efi")


def metrics(vm: str) -> str:
    pseudo = " and ".join(f'InstanceName !startswith "{p}"' for p in PSEUDO_FS)
    return f"""Perf
| where TimeGenerated > ago(10m) and Computer startswith "{vm}"
| where CounterName in ("% Used Memory", "% Processor Time", "% Used Space")
| where CounterName != "% Used Space" or ({pseudo})
| summarize arg_max(TimeGenerated, CounterValue) by CounterName, InstanceName
| summarize Avg=avg(CounterValue), Max=max(CounterValue), Time=max(TimeGenerated) by CounterName"""


def service(vm: str) -> str:
    return f"""Syslog
| where TimeGenerated > ago(2h) and Computer startswith "{vm}"
| where ProcessName in ("demo-app", "demo-history-replay")
| where SyslogMessage has "health rss_mb=" or SyslogMessage startswith "deploy "
    or SyslogMessage startswith "history replay"
| project TimeGenerated, SyslogMessage
| top 50 by TimeGenerated desc"""


def scores(vm: str) -> str:
    return f"""VMAnomalyScore_CL
| where TimeGenerated > ago(60m) and Computer startswith "{vm}"
| project TimeGenerated, Score, IsAnomaly, TopFeature, Details
| order by TimeGenerated asc"""
