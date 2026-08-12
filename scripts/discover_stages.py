#!/usr/bin/env python3
"""
HubSpot Stage Discovery Tool

Connects to HubSpot and prints all pipeline stages with their IDs.
Output is formatted for easy copying into config/client.yaml.

Usage:
    export HUBSPOT_API_KEY="pat-na1-..."
    python scripts/discover_stages.py

Output:
    Prints all pipelines and stages in YAML format
    Copy relevant sections into config/client.yaml
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    # Stage discovery uses hubspot._get() directly (raw pipeline stage
    # data), which isn't part of the generic CRMAdapter interface — this
    # imports the concrete HubSpot client rather than going through
    # get_crm_adapter().
    from adapters.crm.hubspot import HubSpotDealsClient
except ImportError:
    print("❌ Error: scripts/adapters/crm/hubspot.py not found")
    print("   Make sure you're running from the repo root")
    sys.exit(1)


def main():
    # Check for API key
    api_key = os.getenv("HUBSPOT_API_KEY")
    if not api_key:
        print("❌ Error: HUBSPOT_API_KEY environment variable not set")
        print("\nUsage:")
        print("    export HUBSPOT_API_KEY=\"pat-na1-your-key-here\"")
        print("    python scripts/discover_stages.py")
        sys.exit(1)

    print("🔍 Discovering HubSpot Pipeline Stages...\n")

    # Initialize HubSpot client
    try:
        hubspot = HubSpotDealsClient(api_key)
    except Exception as e:
        print(f"❌ Error initializing HubSpot client: {e}")
        sys.exit(1)

    # Fetch all pipelines
    try:
        endpoint = "/crm/v3/pipelines/deals"
        response = hubspot._get(endpoint)
        pipelines = response.get('results', [])

        if not pipelines:
            print("⚠️  No pipelines found")
            sys.exit(1)

        print(f"✅ Found {len(pipelines)} pipeline(s)\n")
        print("=" * 80)
        print("COPY THIS INTO config/client.yaml")
        print("=" * 80)
        print()

        # Print each pipeline with its stages
        for pipeline in pipelines:
            pipeline_label = pipeline.get('label', 'Unknown')
            pipeline_id = pipeline.get('id', 'unknown')
            stages = pipeline.get('stages', [])

            # Print pipeline header
            print(f"# {pipeline_label} (ID: {pipeline_id})")
            print(f"# {len(stages)} stages")
            print()

            # Print stages
            for idx, stage in enumerate(stages, 1):
                stage_label = stage.get('label', 'Unknown')
                stage_id = stage.get('id', 'unknown')
                metadata = stage.get('metadata', {})
                is_closed_won = metadata.get('isClosed') == 'true' and metadata.get('probability') == '1.0'
                is_closed_lost = metadata.get('isClosed') == 'true' and metadata.get('probability') == '0.0'

                # Add annotations for special stages
                annotation = ""
                if is_closed_won:
                    annotation = "  # ← Closed Won stage"
                elif is_closed_lost:
                    annotation = "  # ← Closed Lost stage"
                elif 'meeting set' in stage_label.lower():
                    annotation = "  # ← Consider excluding (pre-discovery)"
                elif 'disqualified' in stage_label.lower():
                    annotation = "  # ← Consider excluding (disqualified)"

                print(f"  {idx}. {stage_label:<30} (ID: {stage_id}){annotation}")

            print()
            print("-" * 80)
            print()

        # Print suggested configuration — the pipeline.pipelines[]
        # stage-order model (config/client.yaml). HubSpot's isClosed/
        # probability metadata and stage labels can only HINT at
        # won/lost/meeting-set/disqualified/renewal — a human must
        # confirm every hint below before it goes live.
        print()
        print("=" * 80)
        print("SUGGESTED CONFIGURATION — copy into config/client.yaml under 'pipeline:'")
        print("=" * 80)
        print()
        print("# Every flag below marked HINT was guessed from HubSpot's own")
        print("# metadata or the stage/pipeline label — review and correct")
        print("# each one. order values, qualified_stage_order, is_primary,")
        print("# and analyze: are business decisions this tool cannot make.")
        print()
        print("pipeline:")
        print("  value_field: amount")
        print("  # ← If one property holds deal value, name it here.")
        print("  # If value is a SUM of properties (e.g. New ARR + Expansion ARR),")
        print("  # use the computed form instead:")
        print("  # value_field:")
        print("  #   type: computed")
        print('  #   components: ["new_revenue", "expansion_revenue"]')
        print("  # IMPORTANT: use HubSpot INTERNAL names, not labels.")
        print("  # 'New ARR' in the UI may be 'new_revenue' internally.")
        print("  # List internal names: GET /crm/v3/properties/deals")
        print("  lost_reason_field: closed_lost_reason  # ← verify this is your org's real property")
        print("  # win_rate_qualified_field: sao  # ← optional: boolean field like SAO")
        print("  # (Sales Accepted Opportunity). If set, win rate uses this as the")
        print("  # denominator instead of stage-order-based qualification. Omit if")
        print("  # you use stage progression to define qualified opportunities.")
        print("  pipelines:")

        for p_idx, pipeline in enumerate(pipelines):
            label = pipeline.get('label', 'Unknown')
            pid = pipeline.get('id', 'unknown')
            stages = pipeline.get('stages', [])
            is_renewal_like = any(kw in label.lower() for kw in ('renewal', 'partner'))

            print(f'    - id: "{pid}"')
            print(f'      name: "{label}"')
            if p_idx == 0 and not is_renewal_like:
                print('      is_primary: true  # ← review: exactly one pipeline should have this')
            if is_renewal_like:
                print('      analyze: false')
                print('      # HINT: label suggests renewal/partner — confirm with the client.')
                print('      # analyze: false = excluded from deal analysis (MEDDICC/SPICED),')
                print('      # INCLUDED in analytics (won totals, retention, snapshots).')
            print('      stages:')

            for idx, stage in enumerate(stages, 1):
                stage_label = stage.get('label', 'Unknown')
                stage_id = stage.get('id', 'unknown')
                metadata = stage.get('metadata', {})
                is_closed_won = metadata.get('isClosed') == 'true' and metadata.get('probability') == '1.0'
                is_closed_lost = metadata.get('isClosed') == 'true' and metadata.get('probability') == '0.0'
                is_meeting_set_like = 'meeting set' in stage_label.lower()
                is_disqualified_like = 'disqualified' in stage_label.lower()

                print(f'        - id: "{stage_id}"')
                print(f'          name: "{stage_label}"')
                print(f'          order: {idx}  # ← review: must reflect true sales-cycle sequence')
                if is_closed_won:
                    print('          is_won: true  # HINT: HubSpot isClosed + probability 1.0')
                if is_closed_lost:
                    print('          is_lost: true  # HINT: HubSpot isClosed + probability 0.0')
                if is_disqualified_like:
                    print('          is_lost: true               # HINT: label contains "disqualified"')
                    print('          exclude_from_analysis: true  # REQUIRED together — see RULE below')
                    print('          exclude_from_progression: true  # HINT: administrative stage —')
                    print('          # excluded from highest-stage-reached ranking so it can\'t')
                    print('          # inflate the win-rate denominator.')
                elif is_meeting_set_like:
                    print('          exclude_from_analysis: true  # HINT: label contains "meeting set"')

                # Emit stage_probability for non-terminal stages
                if not (is_closed_won or is_closed_lost):
                    prob_str = metadata.get('probability')
                    if prob_str:
                        try:
                            prob_val = float(prob_str)
                            print(f'          stage_probability: {prob_val:.2f}  # HINT: HubSpot\'s own stage')
                            print('          # probability. Used by the stage-weighted forecast.')
                            print('          # Replace with your team\'s real historical conversion')
                            print('          # rates if you have them — HubSpot defaults are often')
                            print('          # never calibrated.')
                        except (ValueError, TypeError):
                            print('          stage_probability: null  # HINT: metadata missing —')
                            print('          # stage-weighted forecast needs a value here.')
                    else:
                        print('          stage_probability: null  # HINT: metadata missing —')
                        print('          # stage-weighted forecast needs a value here.')

            print('      qualified_stage_order: 0  # ← FILL IN: first order value that counts as "qualified"')
            print()

        print("# RULE: any Disqualified-type stage must carry BOTH is_lost: true")
        print("# AND exclude_from_analysis: true. is_lost makes it terminal for")
        print("# analytics (deal_status flips to 'lost', exits the funnel, counts")
        print("# against qualification rate — it stays out of the win-rate")
        print("# denominator automatically via qualified_stage_order, no separate")
        print("# handling needed). exclude_from_analysis keeps it out of the")
        print("# nightly MEDDICC agent's active-deal population. A stage with")
        print("# ONLY exclude_from_analysis (no is_lost) looks \"active forever\"")
        print("# in pipeline analytics — it never resolves to won or lost.")
        print("# Meeting Set is the one legitimate exception: pre-discovery and")
        print("# still open, so it gets exclude_from_analysis WITHOUT is_lost.")
        print()
        print("# Optional capability surface (commented by default — unset means")
        print("# 'not tracked', matching today's behavior exactly. Full reference")
        print("# and explanations live in config/client.yaml itself):")
        print("#   win_rate_qualified_field: <your SAO-style boolean property>")
        print("#   forecast_category_field: <your forecast category property>")
        print("#   prior_arr_field: <your prior-ARR property, for GRR/NRR>")
        print("#   fiscal:")
        print("#     fy_start_month: <1-12, 1 = calendar year, the default>")
        print()
        print("=" * 80)
        print()
        print("✅ Stage discovery complete!")
        print()
        print("Next steps:")
        print("  1. Copy the pipeline: block above into config/client.yaml,")
        print("     resolving every HINT and FILL IN marker")
        print("  2. Decide is_primary, analyze:, order, and qualified_stage_order")
        print("     for every pipeline — these are business decisions, not")
        print("     something HubSpot's metadata can answer")
        print("  3. Fill in the optional capability surface only for fields you")
        print("     actually have (leave the rest commented/unset)")
        print("  4. Adjust stage progression requirements if needed")
        print()

    except Exception as e:
        print(f"❌ Error fetching pipelines: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
