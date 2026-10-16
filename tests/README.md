---
title: Tests
description: Run the offline sample test suite
---

## Run

From the repository root:

```bash
uv sync --python 3.11 --extra dev --extra detector --extra dashboard
uv run pytest -q
```

Tests cover the application, detector, model features, dashboard, configuration,
and workflow contracts. Live Azure resources and GitHub write access are not
required.
