"""
Gong API Adapter

Implements the same interface as fireflies_client.py but reads from Gong API.
Used by etl_calls.py when config/client.yaml sets call_tools.primary = gong.

Gong provides richer structured data than Fireflies:
- Speaker-attributed transcript turns
- Talk time ratios per speaker
- Topic detection (pricing, next steps, competition, pain)
- Sentiment signals
- Action items and next steps extracted by Gong's AI
- Deal risk signals

This produces better formatted summaries for MEDDICC analysis.
"""

import os
import base64
import requests
from datetime import datetime
from typing import List, Optional, Dict

from .base import CallAdapter


class GongAdapter(CallAdapter):
    """
    Gong call intelligence adapter.

    Authentication: Basic auth with Access Key + Secret (base64 encoded)
    API docs: https://gong.app.gong.io/settings/api/documentation
    """

    # API access level for this client
    # basic: metadata only (title, date, duration, participants)
    # rich: transcripts, topics, action items available
    # Check with Gong admin: requires Technical Admin role
    # and Transcription feature enabled on account
    ACCESS_LEVEL = 'basic'

    @classmethod
    def enable_rich_access(cls):
        """Enable rich data mode (transcripts, topics, action items)."""
        cls.ACCESS_LEVEL = 'rich'

    def __init__(self):
        """Initialize Gong adapter with API credentials."""
        key = os.getenv('GONG_ACCESS_KEY')
        secret = os.getenv('GONG_ACCESS_KEY_SECRET')

        if not key or not secret:
            raise ValueError(
                'GONG_ACCESS_KEY and GONG_ACCESS_KEY_SECRET environment '
                'variables are required for Gong adapter'
            )

        # Basic auth: base64 encode "key:secret"
        token = base64.b64encode(f'{key}:{secret}'.encode()).decode()

        self.headers = {
            'Authorization': f'Basic {token}',
            'Content-Type': 'application/json'
        }
        self.base_url = 'https://api.gong.io/v2'

        # Note required API scopes
        print("Note: Gong adapter requires scopes api:calls:read:extensive "
              "and api:calls:read:transcript")

    def search_by_company(self, company_name: str,
                          since_date: Optional[datetime] = None) -> List[Dict]:
        """
        Fetch calls mentioning this company name with rich structured data.

        Uses /v2/calls to get call list, then /v2/calls/extensive to batch
        fetch rich data (topics, action items, talk time, etc.).

        Args:
            company_name: Company to search for
            since_date: Only return calls after this date

        Returns:
            List of enriched call dicts with full Gong intelligence data
        """
        # STEP 1: Get call list with basic metadata
        params = {}
        if since_date:
            params['fromDateTime'] = since_date.isoformat()

        response = requests.get(
            f'{self.base_url}/calls',
            headers=self.headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()

        calls = response.json().get('calls', [])

        # STEP 2: Filter by company name in title
        company_lower = company_name.lower()
        matched = [
            call for call in calls
            if company_lower in call.get('title', '').lower()
        ]

        if not matched:
            return []

        # STEP 3: Batch fetch rich data using /v2/calls/extensive
        # Max 20 calls per request
        call_ids = [c['id'] for c in matched]
        enriched = []

        for i in range(0, len(call_ids), 20):
            batch_ids = call_ids[i:i+20]

            # Build request body with contentSelector
            request_body = {
                'filter': {'callIds': batch_ids},
                'contentSelector': {
                    'exposedFields': {
                        'parties': True,
                        'content': {
                            'brief': True,
                            'topics': True,
                            'keyPoints': True,
                            'trackers': True,
                            'outline': True
                        },
                        'interaction': {
                            'speakers': True,
                            'questions': True
                        }
                    }
                }
            }

            try:
                extensive_resp = requests.post(
                    f'{self.base_url}/calls/extensive',
                    headers=self.headers,
                    json=request_body,
                    timeout=30
                )

                if extensive_resp.status_code == 200:
                    batch_calls = extensive_resp.json().get('calls', [])
                    enriched.extend(batch_calls)
            except Exception as e:
                print(f'Warning: Failed to fetch extensive data for batch: {e}')
                continue

        # STEP 4: Merge basic metadata + rich data
        rich_by_id = {
            c.get('metaData', {}).get('id'): c
            for c in enriched
        }

        results = []
        for call in matched:
            call_id = call['id']

            if call_id in rich_by_id:
                rich = rich_by_id[call_id]
                metadata = rich.get('metaData', {})
                content = rich.get('content', {})
                interaction = rich.get('interaction', {})

                # Flatten into format expected by format_summary()
                merged = {
                    'id': call_id,
                    'title': metadata.get('title', call.get('title', '')),
                    'started': metadata.get('started', call.get('started', '')),
                    'duration': metadata.get('duration', call.get('duration', 0)),
                    'brief': content.get('brief', ''),
                    'topics': [t.get('name', '') for t in content.get('topics', [])],
                    'keyPoints': [kp.get('text', '') for kp in content.get('keyPoints', [])],
                    'parties': rich.get('parties', []),
                    'speakers': interaction.get('speakers', []),
                }
                results.append(merged)
            else:
                # Fallback to basic data if extensive fetch failed
                results.append({
                    'id': call_id,
                    'title': call.get('title', ''),
                    'started': call.get('started', ''),
                    'duration': call.get('duration', 0),
                    'brief': '',
                    'topics': [],
                    'keyPoints': [],
                    'parties': [],
                    'speakers': [],
                })

        return results

    def format_summary(self, call: Dict) -> str:
        """
        Format a Gong call dict into an analysis-ready summary.

        Uses Gong's structured data:
        - brief: AI-generated summary
        - topics: Detected conversation topics
        - keyPoints: Action items and next steps
        - parties: Participants with talk time percentages

        Args:
            call: Call dict from Gong API

        Returns:
            Formatted summary string for MEDDICC context builder
        """
        title = call.get('title', 'Untitled')
        started = str(call.get('started', ''))[:10]  # YYYY-MM-DD
        duration = round((call.get('duration') or 0) / 60, 1)  # Convert to minutes

        if self.ACCESS_LEVEL == 'basic':
            # Extract participant names from title if possible
            # Gong titles are often "Prospect Name and Rep Name"
            return (
                f"# {title}\n"
                f"Date: {started} | Duration: {duration}m\n\n"
                f"## Note\n"
                f"Full transcript not available via current "
                f"API access level. Call recorded in Gong — "
                f"contact Gong admin to enable transcript API "
                f"access (Technical Admin role required).\n\n"
                f"## Call Activity\n"
                f"A {duration}-minute call took place on "
                f"{started}. Participants visible in title: "
                f"{title}."
            )

        # Rich path (when ACCESS_LEVEL = 'rich')
        brief = call.get('brief', '')

        # Extract Gong's structured insights
        topics = call.get('topics', [])
        key_points = call.get('keyPoints', [])  # Now a list of strings

        # Talk time analysis - calculate percentages from speakers + parties
        parties = call.get('parties', [])
        speakers = call.get('speakers', [])
        total_duration_secs = call.get('duration', 0)

        talk_time_lines = self._format_talk_time(parties, speakers, total_duration_secs)

        # Build formatted summary
        sections = [
            f'# {title}',
            f'Date: {started} | Duration: {duration}m'
        ]

        if brief:
            sections.extend(['', '## Summary', brief])

        if topics:
            sections.extend(['', '## Topics Discussed'])
            sections.extend([f'- {topic}' for topic in topics])

        if key_points:
            sections.extend(['', '## Key Points'])
            sections.extend([f'- {point}' for point in key_points])

        if talk_time_lines:
            sections.extend(['', '## Talk Time'])
            sections.extend(talk_time_lines)

        return '\n'.join(sections)

    def format_summary_for_meddicc(self, call: Dict) -> str:
        """Deprecated alias for format_summary."""
        return self.format_summary(call)

    def get_meeting_attendees(self, call_id: str) -> List[Dict]:
        """
        Return attendees for a single call using the extensive endpoint.

        Fetches POST /v2/calls/extensive filtered to this call ID with
        parties exposed, then maps Gong parties to the common attendee
        shape [{'name': ..., 'email': ...}, ...].

        Returns [] on 404 or any error.
        """
        request_body = {
            'filter': {'callIds': [call_id]},
            'contentSelector': {
                'exposedFields': {
                    'parties': True
                }
            }
        }

        try:
            response = requests.post(
                f'{self.base_url}/calls/extensive',
                headers=self.headers,
                json=request_body,
                timeout=30
            )

            if response.status_code == 404:
                return []

            response.raise_for_status()

            calls = response.json().get('calls', [])
            if not calls:
                return []

            parties = calls[0].get('parties', []) or []
            return [
                {
                    'name': p.get('name'),
                    'email': p.get('emailAddress') or p.get('email', '')
                }
                for p in parties
            ]
        except Exception:
            return []

    def _format_talk_time(self, parties: List[Dict], speakers: List[Dict],
                          total_duration_secs: int) -> List[str]:
        """
        Format talk time for each party, handling multiple ID mapping strategies.

        External participants may not appear in speakers array or use different
        ID formats. Try multiple fields: speakerId, id, userId.

        Args:
            parties: List of party dicts from Gong API
            speakers: List of speaker dicts with talkTime
            total_duration_secs: Total call duration in seconds

        Returns:
            List of formatted talk time strings
        """
        # Build lookup by multiple ID fields
        speaker_time = {}
        for s in speakers:
            talk_time = s.get('talkTime', 0)
            speaker_time[s.get('id', '')] = talk_time
            speaker_time[s.get('userId', '')] = talk_time

        lines = []
        total_accounted = sum(speaker_time.values())

        for p in parties:
            # Try multiple ID fields to find matching speaker
            secs = (speaker_time.get(p.get('speakerId', ''), 0) or
                    speaker_time.get(p.get('id', ''), 0) or
                    speaker_time.get(p.get('userId', ''), 0))

            if total_duration_secs > 0:
                pct = (secs / total_duration_secs * 100)
            else:
                pct = 0

            name = p.get('name', 'Unknown')
            affil = p.get('affiliation', '?')
            title = p.get('title', '')
            label = f"{name} ({title})" if title else name
            lines.append(f"  {label} [{affil}]: {pct:.0f}% ({secs:.0f}s)")

        # Add untracked time if significant
        unaccounted = total_duration_secs - total_accounted
        if unaccounted > 30:
            lines.append(f"  [Untracked]: {unaccounted:.0f}s")

        return lines if lines else ["Talk time unavailable"]

    def get_transcript(self, call_id: str) -> str:
        """
        Fetch full transcript for a specific call.

        Returns speaker-attributed text with each sentence on a new line.

        Args:
            call_id: Gong call ID

        Returns:
            Full transcript as "Speaker: text" format
        """
        response = requests.get(
            f'{self.base_url}/calls/{call_id}/transcript',
            headers=self.headers,
            timeout=30
        )

        if response.status_code == 404:
            return ''

        response.raise_for_status()

        # Gong returns transcript as array of sentences with speaker attribution
        sentences = response.json().get('callTranscripts', [])
        lines = []

        for sentence in sentences:
            speaker = sentence.get('speakerName', 'Unknown')
            text = sentence.get('sentence', '')
            if text.strip():
                lines.append(f'{speaker}: {text}')

        return '\n'.join(lines)

    def get_calls(self, limit: int = 100, skip: int = 0) -> List[Dict]:
        """
        Get recent calls with rich structured data.

        Uses /v2/calls to get call list, then /v2/calls/extensive to batch
        fetch rich data for all calls.

        Args:
            limit: Number of calls to return
            skip: Number of calls to skip (for pagination)

        Returns:
            List of enriched call dicts with full Gong intelligence data
        """
        # STEP 1: Get call list with basic metadata
        response = requests.get(
            f'{self.base_url}/calls',
            headers=self.headers,
            params={'limit': limit},
            timeout=30
        )
        response.raise_for_status()

        calls = response.json().get('calls', [])

        if not calls:
            return []

        # STEP 2: Batch fetch rich data using /v2/calls/extensive
        # Max 20 calls per request
        call_ids = [c['id'] for c in calls]
        enriched = []

        for i in range(0, len(call_ids), 20):
            batch_ids = call_ids[i:i+20]

            # Build request body with contentSelector
            request_body = {
                'filter': {'callIds': batch_ids},
                'contentSelector': {
                    'exposedFields': {
                        'parties': True,
                        'content': {
                            'brief': True,
                            'topics': True,
                            'keyPoints': True,
                            'trackers': True,
                            'outline': True
                        },
                        'interaction': {
                            'speakers': True,
                            'questions': True
                        }
                    }
                }
            }

            try:
                extensive_resp = requests.post(
                    f'{self.base_url}/calls/extensive',
                    headers=self.headers,
                    json=request_body,
                    timeout=30
                )

                if extensive_resp.status_code == 200:
                    batch_calls = extensive_resp.json().get('calls', [])
                    enriched.extend(batch_calls)
            except Exception as e:
                print(f'Warning: Failed to fetch extensive data for batch: {e}')
                continue

        # STEP 3: Merge basic metadata + rich data
        rich_by_id = {
            c.get('metaData', {}).get('id'): c
            for c in enriched
        }

        results = []
        for call in calls:
            call_id = call['id']

            if call_id in rich_by_id:
                rich = rich_by_id[call_id]
                metadata = rich.get('metaData', {})
                content = rich.get('content', {})
                interaction = rich.get('interaction', {})

                # Flatten into format expected by format_summary()
                merged = {
                    'id': call_id,
                    'title': metadata.get('title', call.get('title', '')),
                    'started': metadata.get('started', call.get('started', '')),
                    'duration': metadata.get('duration', call.get('duration', 0)),
                    'brief': content.get('brief', ''),
                    'topics': [t.get('name', '') for t in content.get('topics', [])],
                    'keyPoints': [kp.get('text', '') for kp in content.get('keyPoints', [])],
                    'parties': rich.get('parties', []),
                    'speakers': interaction.get('speakers', []),
                }
                results.append(merged)
            else:
                # Fallback to basic data if extensive fetch failed
                results.append({
                    'id': call_id,
                    'title': call.get('title', ''),
                    'started': call.get('started', ''),
                    'duration': call.get('duration', 0),
                    'brief': '',
                    'topics': [],
                    'keyPoints': [],
                    'parties': [],
                    'speakers': [],
                })

        return results
