from abc import ABC, abstractmethod
from typing import List, Optional


class StorageAdapter(ABC):
    """
    Contract for all storage adapters. Supabase today;
    Snowflake/BigQuery/Postgres later implement the same
    interface. This is the API between the nightly agent,
    the CRO query agent, and whatever runs the ETL.
    """

    @abstractmethod
    def upsert_deal(self, deal: dict) -> None:
        """Write or update a deal record."""

    @abstractmethod
    def upsert_call(self, call: dict, company_name: str) -> None:
        """Write or update a call record."""

    @abstractmethod
    def insert_analysis(self, deal_id: str, company_name: str,
                        result: dict, scores: dict,
                        output_file: str = '') -> None:
        """Insert one analysis row.

        result: the full agent output dict from run_agent()
                (draft, iterations, passed, evaluation, etc.)
                — implementations may pull whatever fields
                they need from this (e.g. result['draft'] as
                the analysis text, result['iterations'] for
                a metadata column).
        scores: flat dict of scores. Must include
                'component_scores' (JSONB-ready dict) and,
                when the methodology is MEDDICC, the seven
                legacy score columns for backward compat.
        output_file: relative path to the written .md file,
                     or '' if not applicable.
        """

    @abstractmethod
    def query(self, sql: str, params: Optional[dict] = None
             ) -> List[dict]:
        """Execute a read query, return list of dicts."""

    def test_connection(self) -> bool:
        """Optional override. Default: True."""
        return True
