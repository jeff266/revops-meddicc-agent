from abc import ABC, abstractmethod
from typing import List, Optional


class CRMAdapter(ABC):
    """
    Contract for all CRM adapters. HubSpot today; Salesforce
    or others later implement the same interface.
    """

    @abstractmethod
    def get_active_deals(self) -> List[dict]:
        """Return active deals per config/client.yaml pipeline
        and stage exclusion rules."""

    @abstractmethod
    def get_deal_contacts(self, deal_id: str) -> List[dict]:
        """Return contacts associated with a deal:
        [{'name':..., 'email':..., 'title':...}, ...]"""

    @abstractmethod
    def write_analysis(self, deal_id: str, scores: dict,
                       analysis_content: str,
                       calls_count: int = 0) -> dict:
        """Write analysis scores + summary back to the CRM.
        scores must include 'overall_score', 'status', and
        one <component_key>_score per configured component."""

    @abstractmethod
    def setup_properties(self) -> bool:
        """Create/verify the custom fields this adapter writes
        to. Idempotent — safe to run repeatedly."""

    def test_connection(self) -> bool:
        """Optional override. Default: True."""
        return True
