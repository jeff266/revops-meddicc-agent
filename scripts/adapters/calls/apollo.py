"""
Apollo API Client for the call intelligence layer.

Note: This is Apollo.io (video meeting platform), used for recording
and transcribing sales calls. Only the call intelligence methods live
here — Apollo.io has no CRM/deals API, so deal management belongs to
the HubSpot client.
"""
import os
import sys
import requests
from typing import List, Dict, Optional
from datetime import datetime

from .base import CallAdapter


class ApolloClient(CallAdapter):
    """Call intelligence adapter for Apollo.io (video meetings)."""

    BASE_URL = "https://api.apollo.io/api/v1"

    def __init__(self, api_key: str = None):
        """Initialize with API key."""
        self.api_key = api_key or os.getenv("APOLLO_API_KEY")
        if not self.api_key:
            raise ValueError("Apollo API key not found. Set APOLLO_API_KEY environment variable.")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key
        })

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Execute GET request."""
        response = self.session.get(f"{self.BASE_URL}{endpoint}", params=params)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: dict = None) -> dict:
        """Execute POST request."""
        response = self.session.post(f"{self.BASE_URL}{endpoint}", json=data or {})
        response.raise_for_status()
        return response.json()

    def _patch(self, endpoint: str, data: dict = None) -> dict:
        """Execute PATCH request."""
        response = self.session.patch(f"{self.BASE_URL}{endpoint}", json=data or {})
        response.raise_for_status()
        return response.json()

    # ─────────────────────────────────────────────────────────────────
    # Conversations (Video Meetings)
    # ─────────────────────────────────────────────────────────────────

    def get_conversations(self, page: int = 1, per_page: int = 100) -> dict:
        """Get list of video conversations with pagination metadata."""
        result = self._post("/conversations/search", {"page": page, "per_page": per_page})
        return {
            "conversations": result.get("conversations", []),
            "pagination": result.get("pagination", {})
        }

    def get_conversation(self, conversation_id: str) -> dict:
        """Get full conversation detail including transcript."""
        return self._get(f"/conversations/{conversation_id}")

    def get_all_conversations(self, max_pages: int = 150) -> List[dict]:
        """Get all conversations with pagination."""
        all_convos = []
        for page in range(1, max_pages + 1):
            result = self.get_conversations(page=page, per_page=100)
            convos = result["conversations"]
            pagination = result["pagination"]

            all_convos.extend(convos)

            if page >= pagination.get("total_pages", 0) or len(convos) == 0:
                break

        return all_convos

    def search_by_company(self, company_name: str, since_date: Optional[datetime] = None) -> List[dict]:
        """
        Search conversations by company name in topic/title.

        Args:
            company_name: Company name to search for
            since_date: Optional datetime to filter conversations after this date

        Returns conversations sorted by date ascending (oldest first).
        Only includes completed/insights_generated states.
        """
        all_convos = self.get_all_conversations()
        company_lower = company_name.lower()

        matches = []
        for c in all_convos:
            # Only include successful recordings
            if c.get('state') not in ['completed', 'insights_generated']:
                continue

            topic = (c.get('topic') or '').lower()
            if company_lower in topic:
                # Apply date filter if specified
                if since_date:
                    start_time_str = c.get('start_time', '')
                    if start_time_str:
                        try:
                            start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            if start_time < since_date:
                                continue  # Skip conversations before since_date
                        except:
                            pass  # If can't parse date, include the conversation

                matches.append(c)

        # Sort by start_time ascending
        matches.sort(key=lambda x: x.get('start_time', ''))

        return matches

    def search_conversations_by_company(self, company_name: str, since_date: Optional[datetime] = None) -> List[dict]:
        """Deprecated alias for search_by_company."""
        return self.search_by_company(company_name, since_date)

    def format_summary(self, conversation: dict) -> str:
        """Format a conversation summary for analysis."""
        topic = conversation.get('topic', 'Untitled')
        start_time = conversation.get('start_time', '')

        try:
            date_obj = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            date_str = date_obj.strftime('%Y-%m-%d')
        except:
            date_str = start_time

        duration_sec = conversation.get('duration', 0) or 0
        duration_min = f"{round(duration_sec / 60, 1)}m" if duration_sec else "Unknown"

        # Get insights/summary
        insights = conversation.get('insights', {}) or {}
        summary = insights.get('summary', 'No summary available')

        # Get key topics
        topics = insights.get('topics', []) or []
        topics_str = ", ".join(topics) if topics else "None"

        # Build formatted summary
        parts = [
            f"# {topic}",
            f"Date: {date_str} | Duration: {duration_min}",
            "",
            "## Summary",
            summary,
            "",
            "## Topics Discussed",
            topics_str
        ]

        return "\n".join(parts)

    def format_conversation_for_meddicc(self, conversation: dict) -> str:
        """Deprecated alias for format_summary."""
        return self.format_summary(conversation)

    def get_meeting_attendees(self, call_id: str) -> List[dict]:
        """
        Apollo.io does not expose structured attendee emails through its
        conversations API, so there is no reliable way to return per-call
        attendees with emails. Always returns [].
        """
        return []

    # ─────────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            result = self.get_conversations(page=1, per_page=1)
            return 'conversations' in result
        except Exception as e:
            print(f"Connection failed: {e}")
            return False


def get_apollo_client(api_key: str = None) -> ApolloClient:
    """Get configured Apollo client."""
    return ApolloClient(api_key)


if __name__ == "__main__":
    # Test Apollo connection
    client = get_apollo_client()

    print("Testing Apollo.io connection...")
    if not client.test_connection():
        print("❌ Failed to connect")
        sys.exit(1)

    print("✓ Connected to Apollo.io")

    # Test company search
    test_company = "YourCompany"
    print(f"\nSearching for conversations with '{test_company}'...")

    results = client.search_by_company(test_company)
    print(f"Found {len(results)} conversations")

    if results:
        print("\nFormatted summary example:")
        print("=" * 80)
        print(client.format_summary(results[0]))
        print("=" * 80)
