#!/usr/bin/env python3
"""
Supabase Writer Client for MEDDICC Agent

Handles parallel writes to Supabase alongside GitHub for:
- Deal metadata
- Call transcripts with signal detection (feature gaps, objections)
- MEDDICC analyses with full scoring breakdown
"""
from supabase import create_client, Client
import os
import re
from datetime import datetime, date
from typing import List, Optional

from utils import get_methodology
from .base import StorageAdapter

FEATURE_GAP_KEYWORDS = [
    'feature gap', 'missing feature', "doesn't support", "can't do",
    'limitation', 'not able to', 'workaround', 'not supported',
    'lack of', 'unable to', 'no support for'
]

OBJECTION_KEYWORDS = [
    'concern', 'worried', 'not sure', 'pushback', 'hesitant',
    'risk', 'what about', 'but what', 'challenge', 'obstacle',
    "can't commit", 'too expensive', 'timeline', 'vendor risk'
]

def _has_keyword(text: str, keywords: list) -> bool:
    """Check if text contains any of the keywords."""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)

def _safe_int(val) -> Optional[int]:
    """Safely convert value to int."""
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None

def _safe_numeric(val) -> Optional[float]:
    """Safely convert value to float, handling formatted numbers."""
    try:
        v = str(val).replace('$', '').replace(',', '').strip()
        return float(v) if v else None
    except (ValueError, TypeError):
        return None

def _safe_date(val) -> Optional[str]:
    """Safely convert value to ISO date string."""
    if not val:
        return None
    try:
        if isinstance(val, (date, datetime)):
            return val.isoformat()[:10]
        s = str(val).strip()
        return s[:10] if len(s) >= 10 else None
    except Exception:
        return None


class SupabaseWriter(StorageAdapter):
    """Client for writing MEDDICC agent data to Supabase."""

    def __init__(self):
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_KEY')
        if not url or not key:
            raise ValueError(
                'SUPABASE_URL and SUPABASE_SERVICE_KEY must be set')
        self.client: Client = create_client(url, key)

    def upsert_deal(self, deal: dict) -> None:
        """
        Upsert a deal from the deal index, history mode, or analytics
        mode. Base fields are always written. Mode-specific fields
        (history: deal_status/create_date/days_to_close; analytics:
        pipeline_id/deal_value/highest_stage_order_reached/
        qualified_date/lost_reason/stage_source/new_arr/expansion_arr/
        prior_arr/sao/forecast_category) are only included when present
        in the deal dict, so callers that don't populate them leave
        those columns untouched on conflict (Postgres partial-upsert
        semantics) — active mode's behavior is unaffected.

        NOTE: the stage column is 'stage', not 'stage_id' — a prior
        production bug (c6490e9) wrote to a 'stage_id' key that doesn't
        exist on this table. Do not reintroduce it; 'stage' below is
        the only stage column and is always written unconditionally.
        """
        row = {
            'deal_id':       str(deal['deal_id']),
            'company_name':  deal.get('company_name', ''),
            'company_slug':  deal.get('company_slug', ''),
            'stage':         deal.get('stage'),
            'pipeline':      deal.get('pipeline'),
            'arr_usd':       _safe_numeric(deal.get('arr')),
            'close_date':    _safe_date(deal.get('close_date')),
            'owner_email':   deal.get('owner'),
            'last_analyzed': deal.get('last_analyzed'),
            'updated_at':    datetime.now().isoformat(),
        }

        # History-mode fields
        if 'deal_status' in deal:
            row['deal_status'] = deal['deal_status']
        if 'create_date' in deal:
            row['create_date'] = _safe_date(deal['create_date'])
        if 'days_to_close' in deal:
            row['days_to_close'] = _safe_int(deal['days_to_close'])

        # Analytics-mode fields (Phase A qualification tracking)
        if 'pipeline_id' in deal:
            row['pipeline_id'] = deal['pipeline_id']
        if 'deal_value' in deal:
            row['deal_value'] = _safe_numeric(deal['deal_value'])
        if 'highest_stage_order_reached' in deal:
            row['highest_stage_order_reached'] = deal['highest_stage_order_reached']
        if 'qualified_date' in deal:
            row['qualified_date'] = _safe_date(deal['qualified_date'])
        if 'lost_reason' in deal:
            row['lost_reason'] = deal.get('lost_reason')
        if 'stage_source' in deal:
            row['stage_source'] = deal['stage_source']

        # Analytics-mode optional reporting fields (migration 007)
        if 'new_arr' in deal:
            row['new_arr'] = _safe_numeric(deal['new_arr'])
        if 'expansion_arr' in deal:
            row['expansion_arr'] = _safe_numeric(deal['expansion_arr'])
        if 'prior_arr' in deal:
            row['prior_arr'] = _safe_numeric(deal['prior_arr'])
        if 'sao' in deal:
            row['sao'] = deal.get('sao')  # Boolean, no conversion needed
        if 'forecast_category' in deal:
            row['forecast_category'] = deal.get('forecast_category')

        self.client.table('deals').upsert(
            row, on_conflict='deal_id').execute()

    def upsert_call(self, call: dict, company_name: str) -> None:
        """Upsert a call from the call cache."""
        summary = (call.get('formatted_summary')
                   or call.get('summary') or '')
        self.client.table('calls').upsert({
            'call_id':              str(call['id']),
            'company_slug':         call.get('company_slug', ''),
            'company_name':         company_name,
            'source':               call.get('source', ''),
            'call_date':            _safe_date(call.get('date')),
            'duration_minutes':     _safe_numeric(
                                        call.get('duration_minutes')),
            'title':                call.get('title', ''),
            'formatted_summary':    summary,
            'competitors_mentioned': call.get('competitors_mentioned'),
            'has_feature_gap':      _has_keyword(summary,
                                        FEATURE_GAP_KEYWORDS),
            'has_objection':        _has_keyword(summary,
                                        OBJECTION_KEYWORDS),
            'updated_at':           datetime.now().isoformat(),
        }, on_conflict='call_id').execute()

    def insert_analysis(self, deal_id: str, company_name: str,
                        result: dict, scores: dict,
                        output_file: str) -> None:
        """
        Insert a new analysis row.

        The seven legacy MEDDICC score columns are populated only when
        the configured methodology is MEDDICC (else None). The
        methodology-agnostic component_scores JSONB is always written and
        holds every per-component score.
        """
        is_meddicc = get_methodology() == 'MEDDICC'

        def legacy(key):
            """Legacy MEDDICC column — only populated for MEDDICC."""
            return _safe_int(scores.get(key)) if is_meddicc else None

        component_scores = scores.get('component_scores') or {
            k: v for k, v in scores.items()
            if k.endswith('_score') and k != 'overall_score'
        }

        row = {
            'deal_id':                 str(deal_id),
            'company_name':            company_name,
            'overall_score':           _safe_int(
                                           scores.get('overall_score')),
            'status':                  scores.get('status', 'red'),
            'metrics_score':           legacy('metrics_score'),
            'economic_buyer_score':    legacy('economic_buyer_score'),
            'decision_criteria_score': legacy('decision_criteria_score'),
            'decision_process_score':  legacy('decision_process_score'),
            'pain_score':              legacy('pain_score'),
            'champion_score':          legacy('champion_score'),
            'competition_score':       legacy('competition_score'),
            'iterations':              result.get('iterations', 1),
            'passed':                  result.get('passed', False),
            'full_analysis_text':      result.get('draft', ''),
            'summary':                 scores.get('summary', ''),
            'output_file':             output_file,
            'component_scores':        component_scores,
        }

        try:
            self.client.table('analyses').insert(row).execute()
        except Exception as e:
            # Retry without component_scores if the column doesn't exist yet
            if 'component_scores' in str(e):
                row.pop('component_scores', None)
                self.client.table('analyses').insert(row).execute()
                print("⚠️  component_scores column missing — run migration 003")
            else:
                raise

    def bulk_upsert_calls(self, calls: list,
                          company_name: str) -> int:
        """Upsert multiple calls at once. Returns count upserted."""
        if not calls:
            return 0
        rows = []
        for call in calls:
            call['company_slug'] = call.get('company_slug', '')
            summary = (call.get('formatted_summary')
                       or call.get('summary') or '')
            rows.append({
                'call_id':            str(call['id']),
                'company_slug':       call.get('company_slug', ''),
                'company_name':       company_name,
                'source':             call.get('source', ''),
                'call_date':          _safe_date(call.get('date')),
                'duration_minutes':   _safe_numeric(
                                          call.get('duration_minutes')),
                'title':              call.get('title', ''),
                'formatted_summary':  summary,
                'competitors_mentioned': call.get(
                    'competitors_mentioned'),
                'has_feature_gap':    _has_keyword(
                    summary, FEATURE_GAP_KEYWORDS),
                'has_objection':      _has_keyword(
                    summary, OBJECTION_KEYWORDS),
                'updated_at':         datetime.now().isoformat(),
            })
        self.client.table('calls').upsert(
            rows, on_conflict='call_id').execute()
        return len(rows)

    def query(self, sql: str, params: Optional[dict] = None) -> List[dict]:
        """
        Execute a read query.

        supabase-py's REST/PostgREST client has no generic raw-SQL
        endpoint, and no 'exec_sql' Postgres function is defined in
        scripts/migrations/ — setup_supabase.py's best-effort call to it
        is wrapped in a silent try/except, so it cannot be relied on here.
        Raising explicitly means callers (e.g. the CRO agent) discover
        this immediately rather than by trial and error.
        """
        raise NotImplementedError(
            'Use table-specific methods; raw SQL not supported by this '
            'client version'
        )


def select_all(sb, table, columns='*', filters=None, page_size=1000):
    """Paginated select — PostgREST caps unpaginated responses
    at 1,000 rows silently."""
    rows, page = [], 0
    while True:
        q = sb.table(table).select(columns)
        for f in (filters or []):
            q = getattr(q, f[0])(*f[1:])
        batch = (q.range(page*page_size,
                 (page+1)*page_size - 1).execute().data
                 or [])
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        page += 1
