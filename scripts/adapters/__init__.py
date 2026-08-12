"""
Adapter factories. Read config/client.yaml and return the
right implementation. All repos (nightly agent, CRO agent)
import from here — never from tool modules directly.
"""
import yaml
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent


def _load_config() -> dict:
    p = _REPO_ROOT / 'config' / 'client.yaml'
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def get_call_adapter(tool: str = None):
    """Return the primary call adapter (or a named one)."""
    config = _load_config()
    tool = (tool or config.get('call_tools', {})
                        .get('primary', 'fireflies')).lower()
    if tool == 'fireflies':
        from .calls.fireflies import FirefliesClient
        return FirefliesClient()
    if tool == 'gong':
        from .calls.gong import GongAdapter
        return GongAdapter()
    if tool == 'apollo':
        from .calls.apollo import ApolloClient
        return ApolloClient()
    raise ValueError(
        f"Unknown call tool '{tool}'. Add an adapter at "
        f"scripts/adapters/calls/{tool}.py implementing "
        f"CallAdapter (see calls/base.py), then register it here.")


def get_crm_adapter(kind: str = None):
    """Return the CRM adapter for this client."""
    config = _load_config()
    kind = (kind or config.get('organization', {})
                          .get('crm', 'hubspot')).lower()
    if kind == 'hubspot':
        from .crm.hubspot import HubSpotDealsClient
        return HubSpotDealsClient()
    raise ValueError(
        f"Unknown CRM '{kind}'. Add an adapter at "
        f"scripts/adapters/crm/{kind}.py implementing "
        f"CRMAdapter (see crm/base.py), then register it here.")


def get_storage_adapter(kind: str = None):
    """Return the storage adapter for this client."""
    config = _load_config()
    kind = (kind or config.get('storage', {})
                          .get('backend', 'supabase')).lower()
    if kind == 'supabase':
        from .storage.supabase import SupabaseWriter
        return SupabaseWriter()
    raise ValueError(
        f"Unknown storage backend '{kind}'. Add an adapter at "
        f"scripts/adapters/storage/{kind}.py implementing "
        f"StorageAdapter (see storage/base.py), then register "
        f"it here.")
