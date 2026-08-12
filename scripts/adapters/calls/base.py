from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime


class CallAdapter(ABC):
    """
    Contract for all call intelligence adapters.
    Every tool (Fireflies, Gong, Apollo, Fathom, Avoma...)
    implements exactly this interface. Method names are
    methodology-agnostic on purpose.
    """

    @abstractmethod
    def search_by_company(self, company_name: str,
                          since_date: Optional[datetime] = None
                          ) -> List[dict]:
        """Return call dicts for a company, newest data included."""

    @abstractmethod
    def format_summary(self, call: dict) -> str:
        """Format one call dict into an analysis-ready text
        summary. Must return >100 chars for real calls
        (Guard 3 in the nightly agent)."""

    @abstractmethod
    def get_meeting_attendees(self, call_id: str) -> List[dict]:
        """Return attendees with email where available:
        [{'name': ..., 'email': ...}, ...]. Return [] if the
        tool cannot provide attendees."""

    def test_connection(self) -> bool:
        """Optional override. Default: True."""
        return True
