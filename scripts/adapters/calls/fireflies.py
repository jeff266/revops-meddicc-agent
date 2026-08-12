"""
Fireflies API Client for MEDDICC Agent

Extends base Fireflies client with company-based search for MEDDICC analysis.
"""
import os
import sys
import requests
from typing import List, Dict, Optional
from datetime import datetime

from .base import CallAdapter


class FirefliesClient(CallAdapter):
    """Client for Fireflies GraphQL API with company search."""

    BASE_URL = "https://api.fireflies.ai/graphql"

    def __init__(self, api_key: str = None):
        """Initialize with API key."""
        self.api_key = api_key or os.getenv("FIREFLIES_API_KEY", "5313ce93-256a-4bd7-840e-864941fa3e81")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def _query(self, query: str, variables: dict = None) -> dict:
        """Execute GraphQL query."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        response = self.session.post(self.BASE_URL, json=payload)
        response.raise_for_status()
        return response.json()

    def get_transcripts(self, limit: int = 50, skip: int = 0) -> List[dict]:
        """Get recent transcripts with summaries (not full text)."""
        query = """
        query Transcripts($limit: Int, $skip: Int) {
            transcripts(limit: $limit, skip: $skip) {
                id
                title
                date
                duration
                organizer_email
                participants
                meeting_attendees {
                    displayName
                    email
                    name
                }
                summary {
                    keywords
                    action_items
                    short_summary
                    overview
                }
            }
        }
        """
        result = self._query(query, {"limit": limit, "skip": skip})
        return result.get("data", {}).get("transcripts") or []

    def search_by_contact_emails(self, contact_emails: List[str], max_results: int = 100, since_date: Optional[datetime] = None) -> List[dict]:
        """
        Search transcripts by matching participant emails to deal contacts.

        Args:
            contact_emails: List of email addresses from HubSpot deal contacts
            max_results: Maximum number of results to return
            since_date: Optional datetime to filter calls after this date

        Returns summaries only (not full transcripts) sorted by date ascending.
        """
        all_matches = []
        skip = 0
        limit = 50  # Fireflies max reliable limit

        # Normalize emails to lowercase for matching
        contact_emails_lower = [email.lower() for email in contact_emails if email]

        if not contact_emails_lower:
            return []

        while len(all_matches) < max_results:
            batch = self.get_transcripts(limit=limit, skip=skip)

            if not batch:
                break

            # Filter by participant email match
            for t in batch:
                organizer = (t.get('organizer_email') or '').lower()
                participants = t.get('participants') or []

                # Collect all participant emails
                participant_emails = []
                if organizer:
                    participant_emails.append(organizer)

                # Participants might be emails or names with emails
                for p in participants:
                    if isinstance(p, str):
                        # Extract email if format is "Name <email@domain.com>"
                        if '<' in p and '>' in p:
                            email = p.split('<')[1].split('>')[0].lower()
                            participant_emails.append(email)
                        elif '@' in p:
                            participant_emails.append(p.lower())

                # Match if ANY participant email matches ANY contact email
                if any(email in contact_emails_lower for email in participant_emails):
                    # Apply date filter if specified
                    if since_date:
                        call_date = t.get('date', 0)
                        if isinstance(call_date, (int, float)):
                            since_timestamp = since_date.timestamp() * 1000
                            if call_date < since_timestamp:
                                continue  # Skip calls before since_date

                    all_matches.append(t)

                    if len(all_matches) >= max_results:
                        break

            # Pagination
            if len(batch) < limit:
                break
            skip += limit

        # Sort by date ascending (oldest first) for cumulative context building
        all_matches.sort(key=lambda x: x.get('date', 0) if isinstance(x.get('date'), (int, float)) else 0)

        return all_matches[:max_results]

    def search_by_company(self, company_name: str, max_results: int = 100, since_date: Optional[datetime] = None) -> List[dict]:
        """
        Search transcripts by company name in title or participants.

        Args:
            company_name: Company name to search for
            max_results: Maximum number of results to return
            since_date: Optional datetime to filter calls after this date

        Returns summaries only (not full transcripts) sorted by date ascending.
        """
        all_matches = []
        skip = 0
        limit = 50  # Fireflies max reliable limit

        company_lower = company_name.lower()
        since_timestamp = since_date.timestamp() * 1000 if since_date else None

        while len(all_matches) < max_results:
            batch = self.get_transcripts(limit=limit, skip=skip)

            if not batch:
                break

            # Filter by company name and date
            for t in batch:
                title = (t.get('title') or '').lower()
                participants = t.get('participants') or []

                # Flatten participants if comma-separated string
                if participants and isinstance(participants[0], str):
                    participants_str = ','.join(participants).lower()
                else:
                    participants_str = str(participants).lower()

                # Match company name in title or participants
                if company_lower in title or company_lower in participants_str:
                    # Apply date filter if specified
                    if since_timestamp:
                        call_date = t.get('date', 0)
                        if isinstance(call_date, (int, float)) and call_date < since_timestamp:
                            continue  # Skip calls before since_date

                    all_matches.append(t)

                    if len(all_matches) >= max_results:
                        break

            # Pagination
            if len(batch) < limit:
                break
            skip += limit

        # Sort by date ascending (oldest first) for cumulative context building
        all_matches.sort(key=lambda x: x.get('date', 0) if isinstance(x.get('date'), (int, float)) else 0)

        return all_matches[:max_results]

    def get_meeting_attendees(self, transcript_id: str) -> list:
        """Fetch meeting_attendees for a specific transcript by ID."""
        query = """
        query Transcript($transcriptId: String!) {
            transcript(id: $transcriptId) {
                meeting_attendees {
                    displayName
                    email
                    name
                }
            }
        }
        """
        result = self._query(query, {"transcriptId": transcript_id})
        transcript = result.get("data", {}).get("transcript") or {}
        return transcript.get("meeting_attendees") or []

    def format_summary(self, transcript: dict) -> str:
        """Format a transcript summary for analysis."""
        title = transcript.get('title', 'Untitled')
        date_raw = transcript.get('date')

        # Parse date (millisecond timestamp or ISO string)
        if isinstance(date_raw, (int, float)):
            date_obj = datetime.fromtimestamp(date_raw / 1000)
            date_str = date_obj.strftime('%Y-%m-%d')
        elif isinstance(date_raw, str):
            try:
                date_obj = datetime.fromisoformat(date_raw.replace('Z', '+00:00'))
                date_str = date_obj.strftime('%Y-%m-%d')
            except:
                date_str = date_raw
        else:
            date_str = 'Unknown'

        duration = transcript.get('duration', 0)
        duration_min = f"{duration}m" if duration else "Unknown"

        summary_obj = transcript.get('summary') or {}
        short_summary = summary_obj.get('short_summary', '')
        overview = summary_obj.get('overview', '')
        keywords = summary_obj.get('keywords', []) or []
        action_items = summary_obj.get('action_items', '') or ''

        # Build formatted summary
        parts = [
            f"# {title}",
            f"Date: {date_str} | Duration: {duration_min}",
            "",
            "## Summary",
            short_summary or overview or "No summary available",
        ]

        if keywords:
            parts.extend([
                "",
                "## Keywords",
                ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
            ])

        if action_items:
            parts.extend([
                "",
                "## Action Items",
                action_items
            ])

        return "\n".join(parts)

    def format_summary_for_meddicc(self, transcript: dict) -> str:
        """Deprecated alias for format_summary."""
        return self.format_summary(transcript)

    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            query = "query { user { email } }"
            result = self._query(query)
            return bool(result.get("data", {}).get("user", {}).get("email"))
        except Exception as e:
            print(f"Connection failed: {e}")
            return False


def get_fireflies_client(api_key: str = None) -> FirefliesClient:
    """Get configured Fireflies client."""
    return FirefliesClient(api_key)


if __name__ == "__main__":
    # Test company search
    client = get_fireflies_client()

    print("Testing Fireflies connection...")
    if not client.test_connection():
        print("❌ Failed to connect")
        sys.exit(1)

    print("✓ Connected to Fireflies")

    # Test search
    test_company = "YourCompany"  # Use a known company
    print(f"\nSearching for calls with '{test_company}'...")

    results = client.search_by_company(test_company, max_results=5)
    print(f"Found {len(results)} calls")

    if results:
        print("\nFormatted summary example:")
        print("=" * 80)
        print(client.format_summary_for_meddicc(results[0]))
        print("=" * 80)
