# Adapter Guide — adding a new call adapter

Every call intelligence tool (Fireflies, Gong, Apollo, Fathom, Avoma…)
is wrapped in an adapter that implements one small interface. The rest
of the system — ETL, nightly agent, CRO agent — only ever talks to that
interface, never to a tool's SDK directly.

## 1. Implement `CallAdapter`

Create `scripts/adapters/calls/<tool_slug>.py` and subclass the contract
in `scripts/adapters/calls/base.py`:

```python
from .base import CallAdapter

class MyToolClient(CallAdapter):
    def search_by_company(self, company_name, since_date=None) -> list:
        """Return a list of call dicts for the company."""

    def format_summary(self, call) -> str:
        """Return an analysis-ready summary. Must be >100 chars for
        real calls (Guard 3 in the nightly agent)."""

    def get_meeting_attendees(self, call_id) -> list:
        """Return [{'name': ..., 'email': ...}, ...] or [] if the
        tool cannot provide attendees."""

    # test_connection() is optional; the default returns True.
```

Guidance:
- Read credentials from environment variables in `__init__` (never
  hardcode keys).
- `format_summary` is the field the cache stores as `formatted_summary`
  — keep it rich enough to clear the 100-char guard.
- If the tool exposes no attendee emails, return `[]` — that is valid.

## 2. Register it in the factory

Add a branch to `get_call_adapter` in `scripts/adapters/__init__.py`:

```python
if tool == 'mytool':
    from .calls.mytool import MyToolClient
    return MyToolClient()
```

Then set `call_tools.primary: mytool` in `config/client.yaml`. Nothing
else imports the tool module directly — the factory is the only entry
point.

## 3. Add credentials to the setup skill

Add the tool's API key(s) to the credentials interview in
`skills/revops-agent-setup/SKILL.md` so fresh forks collect them, and
remind the user to add them as GitHub Secrets.

Once these three steps are done, the ETL and nightly agent pick up the
new tool automatically — no other code changes required.
