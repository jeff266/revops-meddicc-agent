"""
Shared utility functions for MEDDICC agent.

This module provides common functionality used across ETL and analysis scripts.
"""

import re


def slugify(name: str) -> str:
    """
    Convert a company name to a cache file slug.
    MUST be identical across etl_calls.py, etl_deals.py,
    and run_nightly.py. Uses hyphens to match existing cache.

    Examples:
        'Acme Corp' -> 'acme-corp'
        'Scale AI' -> 'scale-ai'
        'Notion Labs Inc' -> 'notion-labs-inc'
        'Skyscanner + YourCompany' -> 'skyscanner'
        'YourCompany <> ClickHouse' -> 'clickhouse'
    """
    if not name:
        return ''

    # Get vendor name from config
    vendor = 'yourcompany'  # Default
    try:
        import yaml
        from pathlib import Path
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        if config_path.exists():
            config = yaml.safe_load(open(config_path))
            org_name = config.get('organization', {}).get('name', '')
            if org_name and 'YOUR_' not in org_name:
                vendor = org_name.lower()
    except Exception:
        pass  # Use default if config fails

    # First: check if name contains vendor with connectors (vendor-first or vendor-last)
    # Split on connector symbols AND dashes to get all parts
    parts = re.split(r'\s*[-–—<>&+/]\s*|\s+and\s+', name, flags=re.IGNORECASE)

    # Remove the vendor/internal company name and empty parts
    company_parts = [
        p.strip() for p in parts
        if p.strip() and vendor not in p.lower()
    ]

    # Use first non-vendor part, or first part if all contain vendor
    if company_parts:
        name = company_parts[0]
    else:
        name = parts[0] if parts else name

    # Clean - remove filler words and session descriptors
    name = re.sub(
        r'\b(and|the|with|vs|versus|for|at|in|of|call|meeting|onsite|demo|kickoff|discovery|scoping)\b',
        '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name).strip().lower()
    name = re.sub(r'[^a-z0-9\s]', '', name)

    slug = name.replace(' ', '-').strip('-')
    return slug if len(slug) >= 3 else ''


METHODOLOGY_COMPONENTS = {
    'MEDDICC': ['Metrics', 'Economic Buyer', 'Decision Criteria',
                'Decision Process', 'Identified Pain',
                'Champion', 'Competition'],
    'MEDDPIC': ['Metrics', 'Economic Buyer', 'Decision Criteria',
                'Decision Process', 'Paper Process',
                'Identified Pain', 'Champion', 'Competition'],
    'SPICED':  ['Situation', 'Pain', 'Impact',
                'Critical Event', 'Decision'],
    'BANT':    ['Budget', 'Authority', 'Need', 'Timeline'],
}


def load_client_config() -> dict:
    import yaml
    from pathlib import Path
    p = Path(__file__).parent.parent / 'config' / 'client.yaml'
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def get_methodology(config: dict = None) -> str:
    if config is None:
        config = load_client_config()
    m = (config.get('methodology')
         or config.get('organization', {}).get('sales_methodology')
         or 'MEDDICC')
    return str(m).upper()


def get_components(config: dict = None) -> list:
    return METHODOLOGY_COMPONENTS.get(
        get_methodology(config), METHODOLOGY_COMPONENTS['MEDDICC'])


def component_key(name: str) -> str:
    """'Economic Buyer' -> 'economic_buyer';
       'Identified Pain' -> 'identified_pain'"""
    return name.lower().replace(' ', '_')


def get_pipeline_config(pipeline_id: str = None,
                        config: dict = None) -> dict:
    """Return the pipeline config block. Defaults to the
    pipeline marked is_primary if pipeline_id not given."""
    if config is None:
        config = load_client_config()
    pipelines = config.get('pipeline', {}).get('pipelines', [])
    if pipeline_id:
        for p in pipelines:
            if p['id'] == pipeline_id:
                return p
        raise ValueError(f"Unknown pipeline_id '{pipeline_id}'")
    for p in pipelines:
        if p.get('is_primary'):
            return p
    if pipelines:
        return pipelines[0]
    return {}


def get_stage_order(stage_id: str, pipeline_id: str = None,
                    config: dict = None) -> int:
    """Return the order value for a stage ID within a
    pipeline. Returns None if the stage ID is not found —
    caller must handle this (likely an archived/renamed
    stage — see Phase C)."""
    p = get_pipeline_config(pipeline_id, config)
    for s in p.get('stages', []):
        if s['id'] == stage_id:
            return s['order']
    return None


def get_value_field(config: dict = None) -> str:
    if config is None:
        config = load_client_config()
    return config.get('pipeline', {}).get('value_field', 'amount')


def is_won_stage(stage_id: str, pipeline_id: str = None,
                 config: dict = None) -> bool:
    p = get_pipeline_config(pipeline_id, config)
    for s in p.get('stages', []):
        if s['id'] == stage_id:
            return bool(s.get('is_won'))
    return False


def is_lost_stage(stage_id: str, pipeline_id: str = None,
                  config: dict = None) -> bool:
    p = get_pipeline_config(pipeline_id, config)
    for s in p.get('stages', []):
        if s['id'] == stage_id:
            return bool(s.get('is_lost'))
    return False


def is_excluded_from_progression(stage_id: str, pipeline_id: str = None,
                                  config: dict = None) -> bool:
    """
    Check if a stage should be excluded from highest_stage_order_reached ranking.

    Administrative or terminal-adjacent stages (like Disqualified, Review) should
    not participate in high-water-mark progression or they can outrank won deals
    and pollute the win-rate denominator.

    Returns True if the stage has exclude_from_progression: true in config.
    """
    p = get_pipeline_config(pipeline_id, config)
    for s in p.get('stages', []):
        if s['id'] == stage_id:
            return bool(s.get('exclude_from_progression'))
    return False


def get_progression_stage_order(stage_id: str, pipeline_id: str = 'default',
                                 config: dict = None) -> int:
    """
    Stage order for high-water-mark ranking. Returns None for stages
    flagged exclude_from_progression (administrative stages like
    Disqualified/Review must not outrank real progression), and None
    for unmapped stages.

    Use this instead of get_stage_order() when computing
    highest_stage_order_reached to prevent excluded stages from
    inflating the high-water mark.

    NOTE: If porting this to an existing deployment, ensure
    highest_stage_order_reached values are audited for stages flagged
    exclude_from_progression — historical values may need correction via
    a one-time SQL patch.
    """
    p = get_pipeline_config(pipeline_id, config)
    for s in p.get('stages', []):
        if s['id'] == stage_id:
            if s.get('exclude_from_progression'):
                return None
            return s['order']
    return None


def get_segment(employee_count: int or None, config: dict = None) -> tuple:
    """
    Return (segment_name, expected_cycle_days) for an employee count.

    Maps employee count to configured segmentation bands (e.g., SMB, Mid-Market,
    Enterprise). Returns 'Unknown' for None/missing employee counts.

    Args:
        employee_count: Number of employees (from Company.numberofemployees)
        config: Optional full config dict (loaded if not provided)

    Returns:
        tuple: (segment_name, expected_cycle_days)
            e.g. ('SMB', 33), ('Enterprise', 132), ('Unknown', None)

    Examples:
        get_segment(100) -> ('SMB', 33)
        get_segment(500) -> ('Mid-Market', 84)
        get_segment(5000) -> ('Enterprise', 132)
        get_segment(None) -> ('Unknown', None)
    """
    if config is None:
        config = load_client_config()

    bands = config.get('segmentation', {}).get('bands', [])

    # Handle None/missing employee count -> Unknown
    if employee_count is None:
        unknown = next((b for b in bands if b['name'] == 'Unknown'), None)
        return ('Unknown', unknown.get('expected_cycle_days') if unknown else None)

    # Find matching band
    for band in bands:
        lo = band.get('min', 0)
        hi = band.get('max', float('inf'))
        if lo <= employee_count <= hi:
            return (band['name'], band.get('expected_cycle_days'))

    # No match found -> Unknown
    return ('Unknown', None)


def get_fiscal_quarter(as_of=None, config: dict = None) -> tuple:
    """
    Return (q_start_date, q_end_date, label) for the fiscal quarter
    containing as_of, based on config fiscal.fy_start_month.

    For example, fy_start_month=2 creates quarters:
      Q1: Feb-Apr, Q2: May-Jul, Q3: Aug-Oct, Q4: Nov-Jan

    FY label is the year of the FY END. For example, if fy_start_month=2,
    then May 2026 sits in FY2027 Q2 (because the FY runs Feb 2026 - Jan 2027).

    Args:
        as_of: Date to find quarter for (default: today)
        config: Optional full config dict (loaded if not provided)

    Returns:
        tuple: (start_date, end_date, label)
            e.g. (date(2026,5,1), date(2026,7,31), "FY2027 Q2")
    """
    from datetime import date
    from dateutil.relativedelta import relativedelta

    if as_of is None:
        as_of = date.today()

    if config is None:
        config = load_client_config()

    fy_start_month = config.get('fiscal', {}).get('fy_start_month', 1)

    # Find which quarter this date falls in
    # Quarters are 3 months each starting from fy_start_month
    year = as_of.year
    month = as_of.month

    # Calculate months since FY start
    if month >= fy_start_month:
        # Same fiscal year
        fy_year = year + 1  # FY label is END year
        months_into_fy = month - fy_start_month
    else:
        # Previous fiscal year
        fy_year = year
        months_into_fy = (12 - fy_start_month) + month

    # Which quarter (0-3)?
    quarter_num = months_into_fy // 3 + 1  # 1-4

    # Calculate quarter start
    q_start_month = fy_start_month + ((quarter_num - 1) * 3)
    if q_start_month > 12:
        q_start_month -= 12
        q_start_year = fy_year
    else:
        q_start_year = fy_year - 1

    q_start = date(q_start_year, q_start_month, 1)

    # Quarter end is last day of 3rd month
    q_end = q_start + relativedelta(months=3) - relativedelta(days=1)

    label = f"FY{fy_year} Q{quarter_num}"

    return (q_start, q_end, label)
