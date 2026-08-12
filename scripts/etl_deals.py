#!/usr/bin/env python3
"""
ETL: HubSpot Deals API → Deal Index

Modes:
  --mode active (default): Fetches active deals only, writes to memory/deals/index.json and Supabase
  --mode history: Fetches ALL deals including closed, writes to Supabase only for CRO history queries
  --mode analytics: Fetches ALL deals in ALL configured pipelines regardless of stage (including
    pipelines marked analyze: false — excluded from MEDDICC only, not from analytics), writes to
    Supabase only. Powers snapshot_deals.py / compute_waterfall.py / generate_win_loss.py.

Auto-detects pipeline stages to exclude (closed won/lost, meeting set) in active mode.
"""
import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime
import re

# Add parent directory to path for imports
REPO_ROOT = Path(__file__).parent.parent
DEALS_DIR = REPO_ROOT / 'memory' / 'deals'
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from utils import (slugify, get_value_properties, compute_deal_value,
                   get_pipeline_config, get_stage_order, is_won_stage,
                   is_lost_stage, load_client_config)
from adapters import get_crm_adapter, get_storage_adapter
from adapters.storage.supabase import select_all

DEALS_DIR.mkdir(parents=True, exist_ok=True)

# Default exclusions — these are HubSpot universal defaults only.
# For your specific stage IDs, run: python scripts/discover_stages.py
# and update config/client.yaml with your actual stage IDs.
# Do NOT hardcode appointmentscheduled — it means different things
# in different HubSpot pipelines.

EXCLUDED_PIPELINES_DEFAULT = []
CLOSED_WON_STAGES_DEFAULT = ['closedwon']
CLOSED_LOST_STAGES_DEFAULT = ['closedlost']


def _excluded_stages_from_pipeline_config(pipelines: list) -> dict:
    """
    Derive the legacy excluded_stages return shape from the new
    pipeline.pipelines[] stage-order model (config/client.yaml).

    The new schema unifies what used to be two separate concepts
    (Meeting Set / Disqualified) under per-stage flags:
      - exclude_from_analysis alone  → 'meeting_set' (pre-discovery,
        still open — e.g. Meeting Set)
      - exclude_from_analysis + is_lost together → 'disqualified'
        (terminal — the config's RULE requires Disqualified-type
        stages to carry both flags, so deal_status still flips to
        'lost' via closed_lost below)
    The two output lists are mutually exclusive; a stage can't land in
    both. closed_won/closed_lost are independent of exclude_from_analysis
    — any is_won/is_lost stage always resolves deal_status, regardless
    of whether it's also excluded from active analysis. A pipeline
    flagged analyze: false contributes its ID to excluded_pipelines;
    its individual stages don't need to be enumerated since the
    pipeline-level exclusion already covers them.
    """
    meeting_set = []
    disqualified = []
    closed_won = []
    closed_lost = []
    excluded_pipelines = []

    for p in pipelines:
        if p.get('analyze') is False:
            pid = p.get('id')
            if pid:
                excluded_pipelines.append(pid)
            continue

        for stage in p.get('stages', []):
            sid = stage.get('id')
            if not sid:
                continue
            excludes = bool(stage.get('exclude_from_analysis'))
            lost = bool(stage.get('is_lost'))
            won = bool(stage.get('is_won'))

            if excludes and lost:
                disqualified.append(sid)
            elif excludes:
                meeting_set.append(sid)

            if won:
                closed_won.append(sid)
            if lost:
                closed_lost.append(sid)

    return {
        'meeting_set': meeting_set,
        'disqualified': disqualified,
        'closed_won': closed_won or CLOSED_WON_STAGES_DEFAULT,
        'closed_lost': closed_lost or CLOSED_LOST_STAGES_DEFAULT,
        'excluded_pipelines': excluded_pipelines,
    }


def get_excluded_stages() -> dict:
    """
    Load stage exclusions from config/client.yaml.

    Prefers the new pipeline.pipelines[] stage-order model — see
    _excluded_stages_from_pipeline_config(). Falls back to the legacy
    flat excluded_stages block for older forks that haven't migrated.
    If both shapes are present in the same file, the new shape wins —
    they describe the same underlying stages and must not drift apart.

    Returns the same 5-key shape either way so downstream callers
    (get_deal_status, get_meeting_set_stages, the active/history mode
    filters in main()) don't need to know which config shape is in use.
    """
    default_result = {
        'meeting_set': [],
        'disqualified': [],
        'closed_won': CLOSED_WON_STAGES_DEFAULT,
        'closed_lost': CLOSED_LOST_STAGES_DEFAULT,
        'excluded_pipelines': EXCLUDED_PIPELINES_DEFAULT,
    }

    try:
        import yaml
        config_path = REPO_ROOT / 'config' / 'client.yaml'
        if not config_path.exists():
            print("  ⚠️  config/client.yaml not found")
            print("     Run: python scripts/discover_stages.py")
            print("     Then configure your stage IDs in client.yaml")
            return default_result

        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

        # New shape: pipeline.pipelines[] with per-stage order/flags.
        new_pipelines = config.get('pipeline', {}).get('pipelines', [])
        if new_pipelines:
            return _excluded_stages_from_pipeline_config(new_pipelines)

        # Legacy shape: flat excluded_stages block (older forks).
        excluded = config.get('excluded_stages', {})
        if excluded:
            def get_ids(section):
                stages = excluded.get(section, [])
                if isinstance(stages, list):
                    return [s.get('id') for s in stages if s.get('id')
                            and 'YOUR_' not in str(s.get('id', ''))]
                return []

            excluded_pipelines = []
            for pipeline in config.get('pipelines', {}).get('excluded', []):
                pipeline_id = pipeline.get('id', '')
                if pipeline_id and 'YOUR_' not in str(pipeline_id):
                    excluded_pipelines.append(pipeline_id)

            return {
                'meeting_set': get_ids('meeting_set'),
                'disqualified': get_ids('disqualified'),
                'closed_won': get_ids('closed_won') or CLOSED_WON_STAGES_DEFAULT,
                'closed_lost': get_ids('closed_lost') or CLOSED_LOST_STAGES_DEFAULT,
                'excluded_pipelines': excluded_pipelines,
            }

        return default_result
    except Exception as e:
        print(f"  ⚠️  Could not load client.yaml: {e}")
        return default_result


def get_deal_status(stage: str, excluded_stages: dict) -> str:
    """Determine deal status for history mode."""
    if stage in excluded_stages['closed_won']:
        return 'won'
    if stage in excluded_stages['closed_lost']:
        return 'lost'
    return 'active'


def calculate_days_to_close(create_date_str: str, close_date_str: str) -> int:
    """Calculate days from create to close for closed deals."""
    try:
        if not create_date_str or not close_date_str:
            return None
        create_date = datetime.fromisoformat(create_date_str.split('T')[0])
        close_date = datetime.fromisoformat(close_date_str.split('T')[0])
        return (close_date - create_date).days
    except Exception:
        return None


def get_meeting_set_stages(hubspot, excluded_stages: dict):
    """
    Fetch pipeline stages and auto-detect Meeting Set stages.
    Returns list of stage IDs from config + auto-detected.
    """
    # Start with config-defined Meeting Set stages
    meeting_set_stages = list(excluded_stages['meeting_set'])

    try:
        endpoint = "/crm/v3/pipelines/deals"
        response = hubspot._get(endpoint)
        pipelines = response.get('results', [])

        for pipeline in pipelines:
            stages = pipeline.get('stages', [])
            for stage in stages:
                stage_label = stage.get('label', '').lower()
                stage_id = stage.get('id', '')

                # Auto-detect additional meeting set stages by label
                if 'meeting set' in stage_label and stage_id not in meeting_set_stages:
                    meeting_set_stages.append(stage_id)

        return meeting_set_stages

    except Exception as e:
        print(f"⚠️  Could not fetch stages: {e}")
        return excluded_stages['meeting_set']


# Base HubSpot properties analytics mode always needs, independent of
# the client's value_field/reporting-field configuration.
ANALYTICS_BASE_PROPERTIES = [
    'dealname',
    'dealstage',
    'pipeline',
    'closedate',
    'incremental_arr',
    'amount',
    'hubspot_owner_id',
    'dealtype',
    'createdate',
    'last_meddicc_analysis_date',
]


def _analytics_properties(config: dict) -> list:
    """
    Build the HubSpot property list for --mode analytics: the base
    deal properties, plus get_value_properties() (whatever feeds
    deal_value — one field or the computed components), plus any
    optional reporting fields the client has actually configured
    (win_rate_qualified_field, lost_reason_field,
    forecast_category_field, prior_arr_field). Fields nobody configured
    are simply omitted — this is the opt-in capability surface, not a
    fixed superset.
    """
    props = list(ANALYTICS_BASE_PROPERTIES)
    props.extend(get_value_properties(config))

    pipeline_cfg = config.get('pipeline', {})
    for key in ('win_rate_qualified_field', 'lost_reason_field',
                'forecast_category_field', 'prior_arr_field'):
        field = pipeline_cfg.get(key)
        if field:
            props.append(field)

    # De-dupe while preserving order (e.g. a computed value_field
    # component can coincide with a base property).
    seen = set()
    deduped = []
    for p in props:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def main():
    parser = argparse.ArgumentParser(description="ETL HubSpot deals to memory/Supabase")
    parser.add_argument(
        '--mode',
        type=str,
        choices=['active', 'history', 'analytics'],
        default='active',
        help=('active (default): active deals for MEDDICC agent | '
              'history: all deals including closed (Supabase only) | '
              'analytics: ALL deals, all stages, all configured '
              'pipelines including analyze:false ones (Supabase only, '
              'for snapshot/waterfall/qualification-rate)')
    )
    parser.add_argument(
        '--file',
        type=str,
        help='CSV file path (for history mode bulk import from HubSpot export)'
    )
    args = parser.parse_args()

    # Validate: --file requires --mode history
    if args.file and args.mode != 'history':
        print("ERROR: --file can only be used with --mode history")
        return

    print("=" * 80)
    print(f"HUBSPOT DEALS ETL - MODE: {args.mode.upper()}")
    print("=" * 80)

    # Load full config once — analytics mode needs it for value_field,
    # reporting-field names, and per-pipeline qualified_stage_order.
    full_config = load_client_config()

    # Load stage exclusions from config
    excluded_stages = get_excluded_stages()

    # Initialize HubSpot client
    print("\n1. Connecting to HubSpot API...")
    try:
        hubspot = get_crm_adapter()
    except Exception as e:
        print(f"❌ Failed to initialize HubSpot client: {e}")
        print("\nMake sure HUBSPOT_API_KEY environment variable is set.")
        return

    # Analytics mode writes to Supabase only — fail fast if it isn't
    # configured, rather than silently producing nothing later.
    sb_writer = None
    existing_qual_map = {}
    if args.mode == 'analytics':
        if not os.getenv('SUPABASE_URL'):
            print("❌ --mode analytics writes to Supabase only, but "
                  "SUPABASE_URL is not set.")
            return
        try:
            sb_writer = get_storage_adapter()
        except Exception as e:
            print(f"❌ Failed to initialize storage adapter: {e}")
            return

        # Batch-read existing high-water-mark state ONCE, before
        # processing any deals — never per-deal. A deal missing from
        # this map is genuinely new (no prior row); a deal present
        # with a None value is a known row that hasn't crossed a
        # stage/qualified threshold yet. Either way we never guess.
        print("\n2. Batch-reading existing qualification state from Supabase...")
        try:
            existing_rows = select_all(
                sb_writer.client, 'deals',
                'deal_id, highest_stage_order_reached, qualified_date')
            existing_qual_map = {
                str(r['deal_id']): (r.get('highest_stage_order_reached'),
                                    r.get('qualified_date'))
                for r in existing_rows
            }
            print(f"   {len(existing_qual_map)} existing deal rows loaded")
        except Exception as e:
            # A partial/failed read must NOT silently degrade to "no
            # existing data" — that risks lowering high-water marks
            # for deals we simply failed to read back. Abort instead.
            print(f"❌ Batch read of existing deals failed: {e}")
            print("   Aborting — will not risk overwriting "
                  "highest_stage_order_reached with incomplete data.")
            return

    # Determine which deals to fetch based on mode
    if args.mode == 'active':
        # Auto-detect Meeting Set stages
        print("\n2. Auto-detecting Meeting Set stages...")
        meeting_set_stages = get_meeting_set_stages(hubspot, excluded_stages)
        print(f"   Meeting Set stages: {meeting_set_stages}")

        # Fetch active deals only (excludes closed stages via dynamic filtering)
        print("\n3. Fetching active deals from HubSpot API...")
        try:
            all_deals_api = hubspot.get_active_deals()
            closed_stages = hubspot._get_closed_stage_ids()
            print(f"   Fetched {len(all_deals_api)} deals")
            print(f"   Auto-excluded closed stages: {closed_stages}")
        except Exception as e:
            print(f"❌ Failed to fetch deals: {e}")
            return
    elif args.mode == 'history':
        meeting_set_stages = []
        closed_stages = []

        if args.file:
            # Load from CSV export
            print(f"\n2. Loading deals from CSV: {args.file}...")
            try:
                import csv
                all_deals_api = []
                with open(args.file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Convert CSV row to deal object format
                        deal_obj = {
                            'id': row.get('Record ID') or row.get('deal_id'),
                            'properties': {
                                'dealname': row.get('Deal Name') or row.get('dealname', ''),
                                'pipeline': row.get('Pipeline') or row.get('pipeline', ''),
                                'dealstage': row.get('Deal Stage') or row.get('dealstage', ''),
                                'incremental_arr': row.get('Incremental ARR') or row.get('amount', '0'),
                                'closedate': row.get('Close Date') or row.get('closedate', ''),
                                'createdate': row.get('Create Date') or row.get('createdate', ''),
                                'hubspot_owner_id': row.get('Deal owner') or row.get('hubspot_owner_id', ''),
                                'hs_object_id': row.get('Record ID') or row.get('deal_id'),
                            }
                        }
                        all_deals_api.append(deal_obj)
                print(f"   Loaded {len(all_deals_api)} deals from CSV")
            except Exception as e:
                print(f"❌ Failed to load CSV: {e}")
                print("   Make sure CSV has columns: Record ID, Deal Name, Pipeline, Deal Stage, Close Date, Create Date")
                return
        else:
            # Fetch ALL deals including closed from API
            print("\n2. Fetching ALL deals (including closed) from HubSpot API...")
            print("   Note: For large datasets, use --file with a CSV export instead")
            try:
                # Use search API without stage filters
                all_deals_api = hubspot.get_all_deals_including_closed()
                print(f"   Fetched {len(all_deals_api)} deals (active + closed)")
            except Exception as e:
                print(f"❌ Failed to fetch deals: {e}")
                print("   Try exporting from HubSpot and using --file instead")
                return

    else:  # analytics mode
        meeting_set_stages = []
        closed_stages = []

        # No stage/pipeline filtering at the API level — analytics
        # deliberately includes pipelines marked analyze: false (they're
        # excluded from MEDDICC only, not from analytics: renewal won
        # totals, GRR/NRR, etc. still need those deals).
        analytics_properties = _analytics_properties(full_config)
        print("\n3. Fetching ALL deals from HubSpot API (analytics mode)...")
        print(f"   Properties requested: {analytics_properties}")
        try:
            all_deals_api = hubspot.get_all_deals_including_closed(
                properties=analytics_properties)
            print(f"   Fetched {len(all_deals_api)} deals (all stages, all pipelines)")
        except Exception as e:
            print(f"❌ Failed to fetch deals: {e}")
            return

    # Process deals
    print("\n4. Processing deals and fetching company info...")
    deals = {}
    skipped = {
        'renewal_pipeline': 0,
        'meeting_set': 0,
        'disqualified': 0,
        'no_company': 0,
        'no_slug': 0
    }

    # Analytics-mode-only summary state
    analytics_status_counts = {'active': 0, 'won': 0, 'lost': 0}
    analytics_qualified_count = 0
    unmapped_pipelines = set()

    # Config read once, outside the loop — reused per-deal below.
    pipeline_top_config = full_config.get('pipeline', {})
    lost_reason_field = pipeline_top_config.get('lost_reason_field')
    forecast_category_field = pipeline_top_config.get('forecast_category_field')
    prior_arr_field = pipeline_top_config.get('prior_arr_field')
    win_rate_qualified_field = pipeline_top_config.get('win_rate_qualified_field')
    value_field_cfg = pipeline_top_config.get('value_field', 'amount')

    for i, deal_obj in enumerate(all_deals_api, 1):
        if i % 50 == 0:
            print(f"   Processed {i}/{len(all_deals_api)} deals...")

        deal_id = deal_obj.get('id')
        props = deal_obj.get('properties', {})

        deal_name = props.get('dealname', '')
        pipeline = props.get('pipeline') or ''
        stage = props.get('dealstage') or ''
        arr = props.get('incremental_arr') or props.get('amount', '0')
        close_date = props.get('closedate', '')
        create_date = props.get('createdate', '')
        owner_id = props.get('hubspot_owner_id', '')

        if not deal_id:
            continue

        # In active mode, apply stage filters. In history mode, include everything.
        if args.mode == 'active':
            # Filter: exclude Renewal pipeline (by ID or name)
            excluded_pipelines = excluded_stages['excluded_pipelines']
            if pipeline in excluded_pipelines or any(excl in pipeline.lower() for excl in excluded_pipelines if excl.isalpha()):
                skipped['renewal_pipeline'] += 1
                continue

            # Filter: exclude Disqualified stage
            if stage in excluded_stages['disqualified']:
                skipped['disqualified'] += 1
                continue

            # Filter: exclude Meeting Set stages
            if stage in meeting_set_stages:
                skipped['meeting_set'] += 1
                continue

        # Get company (with error handling)
        try:
            company_obj = hubspot.get_deal_company(deal_id)
            if not company_obj:
                skipped['no_company'] += 1
                continue

            company_name = company_obj.get('properties', {}).get('name', '')
            if not company_name.strip():
                skipped['no_company'] += 1
                continue

        except Exception as e:
            skipped['no_company'] += 1
            continue

        # Generate slug
        slug = slugify(company_name)
        if not slug:
            skipped['no_slug'] += 1
            continue

        # Build deal object with mode-specific fields
        deal_dict = {
            'deal_id': deal_id,
            'deal_name': deal_name,
            'company_name': company_name,
            'company_slug': slug,
            'pipeline': pipeline,
            'stage': stage,
            'arr': arr,
            'close_date': close_date,
            'owner_id': owner_id,
            'last_modified': datetime.now().isoformat(),
        }

        # Add history-specific fields
        if args.mode == 'history':
            deal_status = get_deal_status(stage, excluded_stages)
            deal_dict['deal_status'] = deal_status
            deal_dict['create_date'] = create_date

            # Calculate days_to_close for closed deals
            if deal_status in ('won', 'lost'):
                days = calculate_days_to_close(create_date, close_date)
                deal_dict['days_to_close'] = days

        # Add analytics-specific fields
        if args.mode == 'analytics':
            pipeline_id_norm = pipeline if pipeline else 'default'

            try:
                pipeline_cfg_for_deal = get_pipeline_config(
                    pipeline_id_norm, full_config)
            except ValueError:
                # Deal belongs to a pipeline not in client.yaml at all.
                # Don't guess won/lost/order for it — fall back to
                # 'active' and leave stage-order fields untouched.
                pipeline_cfg_for_deal = {}
                unmapped_pipelines.add(pipeline_id_norm)

            current_order = None
            if pipeline_cfg_for_deal:
                if is_won_stage(stage, pipeline_id_norm, full_config):
                    deal_status = 'won'
                elif is_lost_stage(stage, pipeline_id_norm, full_config):
                    deal_status = 'lost'
                else:
                    deal_status = 'active'
                current_order = get_stage_order(
                    stage, pipeline_id_norm, full_config)
            else:
                deal_status = 'active'

            deal_value = compute_deal_value(props, full_config)

            # highest_stage_order_reached: GREATEST(existing, current).
            # Never lower the mark. Use get_progression_stage_order()
            # instead of get_stage_order() — it returns None for stages
            # flagged exclude_from_progression, preventing administrative
            # stages (Disqualified, Review) from inflating the high-water
            # mark and polluting the win-rate denominator.
            from utils import get_progression_stage_order
            progression_order = get_progression_stage_order(
                stage, pipeline_id_norm, full_config)

            existing_highest, existing_qdate = existing_qual_map.get(
                str(deal_id), (None, None))
            if progression_order is not None:
                highest = (max(progression_order, existing_highest)
                          if existing_highest is not None else progression_order)
            else:
                highest = existing_highest

            # qualified_date: never overwrite an existing value. Only
            # set it the first time highest crosses this pipeline's
            # qualified_stage_order threshold. Omitting the key (rather
            # than re-writing the existing value) is what makes "never
            # overwrite" hold — upsert() only updates columns present
            # in the row, so an omitted key leaves the DB value as-is.
            qualified_order = (pipeline_cfg_for_deal.get('qualified_stage_order')
                               if pipeline_cfg_for_deal else None)
            new_qualified_date = None
            if not existing_qdate:
                if (highest is not None and qualified_order is not None
                        and highest >= qualified_order):
                    new_qualified_date = datetime.now().strftime('%Y-%m-%d')

            def _safe_numeric_or_none(val):
                if val in (None, '', 'null'):
                    return None
                try:
                    return float(str(val).replace('$', '').replace(',', '').strip())
                except (ValueError, TypeError):
                    return None

            # new_arr / expansion_arr: only populated when value_field is
            # the computed (ARR-components) shape — positional mapping,
            # first component = new, second = expansion, matching the
            # documented config example (components: [new, expansion]).
            new_arr = expansion_arr = None
            if isinstance(value_field_cfg, dict):
                components = value_field_cfg.get('components', [])
                if len(components) > 0:
                    new_arr = _safe_numeric_or_none(props.get(components[0]))
                if len(components) > 1:
                    expansion_arr = _safe_numeric_or_none(props.get(components[1]))

            prior_arr = (_safe_numeric_or_none(props.get(prior_arr_field))
                        if prior_arr_field else None)

            sao = None
            if win_rate_qualified_field:
                sao_raw = props.get(win_rate_qualified_field)
                if isinstance(sao_raw, bool):
                    sao = sao_raw
                elif isinstance(sao_raw, str):
                    sao = sao_raw.lower() in ('true', '1', 'yes')

            forecast_category = (props.get(forecast_category_field)
                                 if forecast_category_field else None)

            deal_dict['deal_status'] = deal_status
            deal_dict['create_date'] = create_date
            deal_dict['pipeline_id'] = pipeline_id_norm
            deal_dict['deal_value'] = deal_value
            deal_dict['highest_stage_order_reached'] = highest
            if new_qualified_date:
                deal_dict['qualified_date'] = new_qualified_date
            deal_dict['stage_source'] = 'prospective'
            deal_dict['new_arr'] = new_arr
            deal_dict['expansion_arr'] = expansion_arr
            deal_dict['prior_arr'] = prior_arr
            deal_dict['sao'] = sao
            deal_dict['forecast_category'] = forecast_category

            if deal_status == 'lost' and lost_reason_field:
                deal_dict['lost_reason'] = props.get(lost_reason_field, '')

            analytics_status_counts[deal_status] = (
                analytics_status_counts.get(deal_status, 0) + 1)
            if new_qualified_date or existing_qdate:
                analytics_qualified_count += 1

        deals[deal_id] = deal_dict

    # In active mode, write memory/deals/index.json. In history/analytics
    # mode, skip — Supabase only, never touches the MEDDICC deal index.
    if args.mode == 'active':
        # Build index
        print(f"\n5. Building index...")
        index = {
            'last_etl_date': datetime.now().isoformat(),
            'total_deals': len(deals),
            'excluded_closed_stages': closed_stages,
            'excluded_meeting_set_stages': meeting_set_stages,
            'excluded_disqualified_stages': excluded_stages['disqualified'],
            'excluded_renewal_pipeline': excluded_stages['excluded_pipelines'],
            'deals': deals,
        }

        out = DEALS_DIR / 'index.json'
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

        print(f'\n✓ Deal index built: {len(deals)} active deals')
        print(f'  Skipped breakdown:')
        print(f'    {skipped["renewal_pipeline"]} Renewal pipeline')
        print(f'    {skipped["disqualified"]} Disqualified')
        print(f'    {skipped["meeting_set"]} Meeting Set stage')
        print(f'    {skipped["no_company"]} No company')
        print(f'    {skipped["no_slug"]} Invalid slug')
        print(f'  Output: {out}')
    elif args.mode == 'history':
        print(f"\n5. Processed {len(deals)} deals (active + closed)")
        # Count by status
        status_counts = {}
        for d in deals.values():
            status = d.get('deal_status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        print(f'  Status breakdown:')
        for status, count in sorted(status_counts.items()):
            print(f'    {status}: {count} deals')
    else:  # analytics mode
        print(f"\n5. Processed {len(deals)} deals (all stages, all pipelines)")
        # skipped['no_company'] + skipped['no_slug'] are almost always
        # spam/test company records, not real pipeline — e.g. a portal
        # with 1,807 raw deal records may only have 1,672 with a real,
        # slug-able company name. Don't treat this gap as a bug.
        print(f'  Filtered (spam/test records, no usable company): '
              f'{skipped["no_company"] + skipped["no_slug"]} '
              f'({skipped["no_company"]} no company, '
              f'{skipped["no_slug"]} invalid slug)')
        if unmapped_pipelines:
            print(f'  ⚠️  {len(unmapped_pipelines)} unmapped pipeline(s) '
                  f'not in config/client.yaml: {sorted(unmapped_pipelines)}')
            print('     Deals in these pipelines were kept as \'active\' '
                  'with stage-order fields left untouched.')

    # Write to Supabase if configured
    if os.getenv('SUPABASE_URL'):
        print(f'\n6. Writing to Supabase...')
        try:
            # Analytics mode already initialized sb_writer for the
            # batch-read above — reuse it instead of opening a second
            # connection.
            sb = sb_writer if sb_writer is not None else get_storage_adapter()
            count = 0
            for deal_id, deal in deals.items():
                try:
                    sb.upsert_deal(deal)
                    count += 1
                except Exception as e:
                    print(f'  ⚠️  Supabase upsert failed for '
                          f'{deal.get("company_name")}: {e}')
            print(f'  ✓ Supabase: {count} deals upserted')
        except Exception as e:
            print(f'  ⚠️  Supabase write failed: {e}')
            count = 0
    else:
        print(f'\n  ⏭️  SUPABASE_URL not set — skipping Supabase write')
        count = 0

    # Analytics-mode final summary: fetched / written / active / won /
    # lost / qualified / qualification rate.
    if args.mode == 'analytics':
        print("\n" + "=" * 80)
        print("ANALYTICS ETL SUMMARY")
        print("=" * 80)
        print(f'  Fetched:     {len(all_deals_api)}')
        print(f'  Written:     {count}')
        print(f'  Active:      {analytics_status_counts.get("active", 0)}')
        print(f'  Won:         {analytics_status_counts.get("won", 0)}')
        print(f'  Lost:        {analytics_status_counts.get("lost", 0)}')
        print(f'  Qualified:   {analytics_qualified_count}')
        created_count = len(deals)
        qual_rate = (analytics_qualified_count / created_count * 100
                    if created_count else 0)
        print(f'  Qualification rate: {qual_rate:.1f}% '
              f'({analytics_qualified_count}/{created_count})')

    # Print first 10 for verification
    print('\nFirst 10 active deals:')
    for i, (did, d) in enumerate(list(deals.items())[:10], 1):
        print(f'  [{i}] {d["company_name"]} | {d["stage"]} | '
              f'{d["pipeline"]} | ${d["arr"]}')

    # Print unique stages
    stages = sorted(set(d['stage'] for d in deals.values()))
    print(f'\nStages in index ({len(stages)} total):')
    for s in stages:
        count = sum(1 for d in deals.values() if d['stage'] == s)
        print(f'  {s}: {count} deals')

    print("\n" + "=" * 80)
    print("✓ ETL Complete")
    print("=" * 80)


if __name__ == '__main__':
    main()
