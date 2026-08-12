"""
HubSpot Deals Client for MEDDICC Agent

Manages active deals and deal notes for MEDDICC analysis.
"""
import os
import sys
import requests
from typing import List, Dict, Optional
from datetime import datetime

from utils import get_components, component_key, get_methodology, load_client_config
from .base import CRMAdapter


class HubSpotDealsClient(CRMAdapter):
    """Client for HubSpot Deals API."""

    BASE_URL = "https://api.hubapi.com"

    # Pipeline IDs
    SALES_PIPELINE = "default"
    RENEWAL_PIPELINE = "866608541"

    # Cache for closed stage IDs (fetched once per session)
    _closed_stage_ids = None

    def __init__(self, api_key: str = None):
        """Initialize with API key."""
        self.api_key = api_key or os.getenv("HUBSPOT_API_KEY")
        if not self.api_key:
            raise ValueError("HUBSPOT_API_KEY environment variable not set")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Execute GET request."""
        response = self.session.get(f"{self.BASE_URL}{endpoint}", params=params)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: dict = None) -> dict:
        """Execute POST request."""
        response = self.session.post(f"{self.BASE_URL}{endpoint}", json=data)
        response.raise_for_status()
        return response.json()

    def _patch(self, endpoint: str, data: dict = None) -> dict:
        """Execute PATCH request."""
        response = self.session.patch(f"{self.BASE_URL}{endpoint}", json=data)
        response.raise_for_status()
        return response.json()

    def _get_closed_stage_ids(self) -> List[str]:
        """
        Fetch closed stage IDs from all pipelines.
        Caches result in class variable.
        Returns list of stage IDs where label contains 'Closed Won' or 'Closed Lost'.
        """
        if HubSpotDealsClient._closed_stage_ids is not None:
            return HubSpotDealsClient._closed_stage_ids

        endpoint = "/crm/v3/pipelines/deals"
        response = self._get(endpoint)
        pipelines = response.get('results', [])

        closed_ids = []
        for pipeline in pipelines:
            pipeline_label = pipeline.get('label', '')
            stages = pipeline.get('stages', [])

            for stage in stages:
                stage_label = stage.get('label', '').lower()
                stage_id = stage.get('id', '')

                if 'closed won' in stage_label or 'closed lost' in stage_label:
                    closed_ids.append(stage_id)

        # Cache for session
        HubSpotDealsClient._closed_stage_ids = closed_ids
        print(f"   Closed stage IDs excluded: {closed_ids}")

        return closed_ids

    def get_active_deals(self) -> List[dict]:
        """
        Get all active deals (not Closed Won/Lost).

        Returns deals with company associations and key properties.
        """
        endpoint = "/crm/v3/objects/deals/search"

        # Get closed stage IDs dynamically from all pipelines
        closed_stage_ids = self._get_closed_stage_ids()

        # Build filter: exclude Closed Won and Closed Lost stages
        filters = []
        if closed_stage_ids:
            filters.append({
                'propertyName': 'dealstage',
                'operator': 'NOT_IN',
                'values': closed_stage_ids
            })

        body = {
            'filterGroups': [{'filters': filters}] if filters else [],
            'properties': [
                'dealname',
                'dealstage',
                'pipeline',
                'closedate',
                'incremental_arr',
                'amount',
                'hubspot_owner_id',
                'dealtype',
                'createdate',
                'last_meddicc_analysis_date'
            ],
            'sorts': [
                {'propertyName': 'closedate', 'direction': 'ASCENDING'}  # Earliest close date first
            ],
            'limit': 100
        }

        all_deals = []
        after = None

        while True:
            if after:
                body['after'] = after

            response = self._post(endpoint, body)
            results = response.get('results', [])
            all_deals.extend(results)

            paging = response.get('paging', {})
            after = paging.get('next', {}).get('after')

            if not after:
                break

        return all_deals

    def get_all_deals_including_closed(self, properties: List[str] = None) -> List[dict]:
        """
        Get ALL deals regardless of stage or pipeline (active + closed,
        every pipeline). No stage/pipeline exclusion filters — used by
        history and analytics ETL modes, which apply their own
        filtering (or intentionally apply none) after the fetch.

        Args:
            properties: HubSpot property names to fetch. Defaults to
                the same base set as get_active_deals() if not given.
        """
        endpoint = "/crm/v3/objects/deals/search"

        if properties is None:
            properties = [
                'dealname',
                'dealstage',
                'pipeline',
                'closedate',
                'incremental_arr',
                'amount',
                'hubspot_owner_id',
                'dealtype',
                'createdate',
                'last_meddicc_analysis_date'
            ]

        body = {
            'filterGroups': [],
            'properties': properties,
            'sorts': [
                {'propertyName': 'closedate', 'direction': 'ASCENDING'}
            ],
            'limit': 100
        }

        all_deals = []
        after = None

        while True:
            if after:
                body['after'] = after

            response = self._post(endpoint, body)
            results = response.get('results', [])
            all_deals.extend(results)

            paging = response.get('paging', {})
            after = paging.get('next', {}).get('after')

            if not after:
                break

        return all_deals

    def get_deals_modified_since(self, since_date: str) -> List[dict]:
        """
        Fetch only deals modified after since_date.
        Used for delta updates between CSV exports.

        Args:
            since_date: ISO format string e.g. '2026-08-01T02:00:00'

        Returns:
            List of deal objects with basic properties
        """
        endpoint = "/crm/v3/objects/deals/search"

        body = {
            'filterGroups': [{
                'filters': [{
                    'propertyName': 'hs_lastmodifieddate',
                    'operator': 'GT',
                    'value': since_date
                }]
            }],
            'properties': [
                'dealname',
                'dealstage',
                'pipeline',
                'closedate',
                'amount',
                'incremental_arr',
                'hubspot_owner_id',
                'hs_lastmodifieddate'
            ],
            'limit': 100
        }

        all_deals = []
        after = None

        while True:
            if after:
                body['after'] = after

            response = self._post(endpoint, body)
            results = response.get('results', [])
            all_deals.extend(results)

            paging = response.get('paging', {})
            after = paging.get('next', {}).get('after')

            if not after:
                break

        return all_deals

    def get_deal_company(self, deal_id: str) -> Optional[dict]:
        """Get associated company for a deal."""
        endpoint = f"/crm/v3/objects/deals/{deal_id}/associations/companies"

        try:
            response = self._get(endpoint)
            associations = response.get('results', [])

            if not associations:
                return None

            company_id = associations[0].get('id')

            # Get company details
            company_endpoint = f"/crm/v3/objects/companies/{company_id}"
            company_response = self._get(
                company_endpoint,
                params={'properties': ['name', 'domain', 'numberofemployees', 'industry']}
            )

            return company_response

        except Exception as e:
            print(f"Error getting company for deal {deal_id}: {e}")
            return None

    def get_deal_contacts(self, deal_id: str) -> List[dict]:
        """Get associated contacts for a deal."""
        endpoint = f"/crm/v3/objects/deals/{deal_id}/associations/contacts"

        try:
            response = self._get(endpoint)
            contact_associations = response.get('results', [])

            contacts = []
            for assoc in contact_associations[:10]:  # Limit to 10 contacts
                contact_id = assoc.get('id')
                contact_endpoint = f"/crm/v3/objects/contacts/{contact_id}"
                contact_response = self._get(
                    contact_endpoint,
                    params={'properties': ['firstname', 'lastname', 'email', 'jobtitle']}
                )
                contacts.append(contact_response)

            return contacts

        except Exception as e:
            print(f"Error getting contacts for deal {deal_id}: {e}")
            return []

    def update_deal_property(self, deal_id: str, property_name: str, value: str) -> dict:
        """Update a single deal property."""
        endpoint = f"/crm/v3/objects/deals/{deal_id}"

        data = {
            'properties': {
                property_name: value
            }
        }

        return self._patch(endpoint, data)

    def _extract_scores_from_analysis(self, analysis_content: str) -> dict:
        """
        Extract structured scores from a qualification analysis markdown.

        Returns dict with:
        - overall_score: sum of all component scores
        - status: red/yellow/green (derived from numeric scores)
        - one <component_key>_score per methodology component
        - summary: 2-sentence summary from "Summary & Recommended Actions"

        The component map is built dynamically from the configured
        methodology so the same extractor works for MEDDICC, SPICED,
        BANT, and MEDDPIC. 'Identified Pain' is mapped to 'pain_score'
        to preserve existing Supabase/HubSpot column naming.
        """
        import re

        # Component name -> score key, built from the configured methodology
        COMPONENT_MAP = {c: f"{component_key(c)}_score" for c in get_components()}
        OVERRIDES = {'Identified Pain': 'pain_score'}
        for comp, key in OVERRIDES.items():
            if comp in COMPONENT_MAP:
                COMPONENT_MAP[comp] = key

        scores = {
            'overall_score': '0',
            'status': 'yellow',
            'summary': 'Analysis pending',
        }
        for score_key in COMPONENT_MAP.values():
            scores[score_key] = '0'

        # Extract all component scores using "Score: N/10" pattern
        component_scores = []

        for component, score_key in COMPONENT_MAP.items():
            # Match "Component:\nScore: N/10" or "Component:\n**Score**: N/10" pattern (multiline)
            pattern = rf'{re.escape(component)}.*?\*{{0,2}}Score\*{{0,2}}:\s*(\d+)/10'
            match = re.search(pattern, analysis_content, re.DOTALL | re.IGNORECASE)
            if match:
                score = int(match.group(1))
                component_scores.append(score)
                scores[score_key] = str(score)

        # Calculate overall score as sum of all components (0-70)
        if component_scores:
            scores['overall_score'] = str(sum(component_scores))

        # Determine status from numeric scores
        if component_scores:
            avg = sum(component_scores) / len(component_scores)
            low_count = sum(1 for s in component_scores if s < 4)
            high_count = sum(1 for s in component_scores if s >= 7)

            if low_count >= 4:
                scores['status'] = 'red'
            elif high_count >= 5:
                scores['status'] = 'green'
            else:
                scores['status'] = 'yellow'

        # Extract summary from "Summary & Recommended Actions" section
        summary_match = re.search(
            r'#+\s*Summary\s*&?\s*Recommended Actions[:\s]*(.*?)(?:\n#+|\Z)',
            analysis_content,
            re.DOTALL | re.IGNORECASE
        )

        if summary_match:
            summary_text = summary_match.group(1).strip()
            # Get first two sentences
            sentences = re.split(r'(?<=[.!?])\s+', summary_text)
            if len(sentences) >= 2:
                scores['summary'] = ' '.join(sentences[:2]).strip()
            elif sentences:
                scores['summary'] = sentences[0].strip()

        return scores

    def _prop_names(self) -> dict:
        """
        Resolve the four core HubSpot property names for the configured
        methodology. Defaults are meddicc_* for MEDDICC and
        <methodology>_* otherwise. Any of them can be overridden via
        config/client.yaml under hubspot.properties.
        """
        cfg = load_client_config()
        props = (cfg.get('hubspot', {}) or {}).get('properties', {})
        m = get_methodology().lower()
        defaults = {
            'score':          f'{m}_score' if m != 'meddicc' else 'meddicc_score',
            'status':         f'{m}_status' if m != 'meddicc' else 'meddicc_status',
            'last_analyzed':  f'{m}_last_analyzed' if m != 'meddicc' else 'meddicc_last_analyzed',
            'summary':        f'{m}_analysis_summary' if m != 'meddicc' else 'meddicc_analysis_summary',
        }
        defaults.update({k: v for k, v in props.items()
                         if isinstance(v, str)})
        return defaults

    def write_analysis(self, deal_id: str, scores: dict, analysis_content: str,
                       calls_count: int = 0) -> dict:
        """
        Write the qualification analysis to a deal by PATCHing deal
        properties.

        Uses the config-driven core properties (score, status,
        last_analyzed, summary) plus champion / economic buyer
        per-component scores when those components exist in the
        configured methodology. `scores` must include 'overall_score',
        'status', and one <component_key>_score per configured component
        (see HubSpotDealsClient._extract_scores_from_analysis).
        """
        today = datetime.now().strftime('%Y-%m-%d')

        props = self._prop_names()
        components = get_components()
        m = get_methodology().lower()

        properties = {
            props['score']:         scores['overall_score'],
            props['status']:        scores['status'],
            props['last_analyzed']: today,
            props['summary']:       scores['summary'],
        }

        # Per-component advocacy/authority scores, only for methodologies
        # that actually have those components.
        if 'Champion' in components:
            properties[f'{m}_champion_score'] = scores.get('champion_score', '0')
        if 'Economic Buyer' in components:
            properties[f'{m}_economic_buyer_score'] = scores.get('economic_buyer_score', '0')

        # PATCH deal properties with structured scores
        endpoint = f"/crm/v3/objects/deals/{deal_id}"
        result = self._patch(endpoint, {'properties': properties})
        print(f"  ✓ Updated deal properties (score: {scores['overall_score']}, status: {scores['status']})")
        return result

    def upsert_meddicc_note(self, deal_id: str, analysis_content: str, calls_count: int = 0) -> dict:
        """
        Deprecated alias — legacy 3-arg signature. Extracts scores from
        analysis_content itself (as it always has), then delegates to
        write_analysis(). Preserves current behavior exactly for any
        caller still using this name.
        """
        scores = self._extract_scores_from_analysis(analysis_content)
        return self.write_analysis(deal_id, scores, analysis_content, calls_count)

    # Alias for future methodology-agnostic naming
    upsert_analysis_note = upsert_meddicc_note

    def get_deal_context(self, deal_id: str) -> dict:
        """
        Get full deal context for MEDDICC analysis.

        Returns company info, contacts, deal properties.
        """
        # Get deal properties
        endpoint = f"/crm/v3/objects/deals/{deal_id}"
        deal = self._get(
            endpoint,
            params={'properties': ['dealname', 'dealstage', 'incremental_arr', 'closedate', 'pipeline']}
        )

        # Get company
        company = self.get_deal_company(deal_id)

        # Get contacts
        contacts = self.get_deal_contacts(deal_id)

        return {
            'deal': deal,
            'company': company,
            'contacts': contacts
        }

    def setup_properties(self) -> bool:
        """
        Create the custom qualification properties in HubSpot if they
        don't exist. Property names and the component list are driven by
        the configured methodology, so MEDDICC keeps its existing
        meddicc_* names while SPICED/BANT/MEDDPIC get their own.

        Creates the four core properties (score, status, last_analyzed,
        summary) plus one number property per methodology component.
        Idempotent — safe to run repeatedly (existing properties are
        skipped via the 409 branch below).
        """
        endpoint = "/crm/v3/properties/deals"

        props = self._prop_names()
        methodology = get_methodology()
        m = methodology.lower()
        components = get_components()

        properties_to_create = [
            {
                "name": props['score'],
                "label": f"{methodology} Score",
                "type": "number",
                "fieldType": "number",
                "groupName": "dealinformation",
                "description": f"Overall {methodology} qualification score"
            },
            {
                "name": props['status'],
                "label": f"{methodology} Status",
                "type": "string",
                "fieldType": "text",
                "groupName": "dealinformation",
                "description": f"{methodology} health status: red/yellow/green"
            },
            {
                "name": props['last_analyzed'],
                "label": f"{methodology} Last Analyzed",
                "type": "date",
                "fieldType": "date",
                "groupName": "dealinformation",
                "description": f"Date of most recent {methodology} analysis"
            },
            {
                "name": props['summary'],
                "label": f"{methodology} Analysis Summary",
                "type": "string",
                "fieldType": "textarea",
                "groupName": "dealinformation",
                "description": f"2-sentence summary of {methodology} analysis"
            },
        ]

        # One number property per methodology component
        for c in components:
            properties_to_create.append({
                "name": f"{m}_{component_key(c)}_score",
                "label": f"{methodology} {c} Score",
                "type": "number",
                "fieldType": "number",
                "groupName": "dealinformation",
                "description": f"{c} component score (0-10)"
            })

        # Show what will be created before creating
        print(f"Properties to create for {methodology}:")
        for prop in properties_to_create:
            print(f"  - {prop['name']}")

        created_count = 0
        for prop in properties_to_create:
            try:
                self._post(endpoint, prop)
                created_count += 1
                print(f"  ✓ Created property: {prop['name']}")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 409:
                    # Property already exists
                    print(f"  → Property exists: {prop['name']}")
                else:
                    print(f"  ⚠️  Error creating {prop['name']}: {e}")

        return True

    # Deprecation alias — old callers keep working.
    setup_hubspot_properties = setup_properties

    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            endpoint = "/crm/v3/objects/deals"
            response = self._get(endpoint, params={'limit': 1})
            return 'results' in response
        except Exception as e:
            print(f"Connection failed: {e}")
            return False


def get_hubspot_deals_client(api_key: str = None) -> HubSpotDealsClient:
    """Get configured HubSpot Deals client."""
    return HubSpotDealsClient(api_key)


if __name__ == "__main__":
    # Test HubSpot connection
    client = get_hubspot_deals_client()

    print("Testing HubSpot connection...")
    if not client.test_connection():
        print("❌ Failed to connect")
        sys.exit(1)

    print("✓ Connected to HubSpot")

    # Setup custom properties (run once, idempotent)
    print("\nSetting up custom qualification properties...")
    client.setup_properties()

    # Get active deals
    print("\nFetching active deals...")
    deals = client.get_active_deals()
    print(f"Found {len(deals)} active deals")

    if deals:
        # Test with first deal
        test_deal = deals[0]
        deal_id = test_deal.get('id')
        deal_name = test_deal.get('properties', {}).get('dealname', 'Unknown')

        print(f"\nTesting with deal: {deal_name}")

        # Get deal context
        context = client.get_deal_context(deal_id)
        company = context.get('company')
        if company:
            company_name = company.get('properties', {}).get('name', 'Unknown')
            print(f"  Company: {company_name}")

        contacts = context.get('contacts', [])
        print(f"  Contacts: {len(contacts)}")
