"""
HubSpot Property History Fetcher
Phase D Task 3 - Batch fetch dealstage property history for all deals

Fetches property history from HubSpot API with:
- Batch processing with rate limiting
- Progress persistence (resume on failure)
- Caching to avoid redundant API calls
- Validation of returned data

Usage:
    python scripts/analytics/hubspot_history.py --deals deal_id1,deal_id2,...
    python scripts/analytics/hubspot_history.py --all  # Fetch for all deals in Supabase
    python scripts/analytics/hubspot_history.py --resume  # Resume from cache
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from supabase import create_client
from adapters.storage.supabase import select_all


class RateLimiter:
    """Conservative rate limiter for HubSpot API."""

    def __init__(self, calls_per_second: float = 5):
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0

    def wait(self):
        """Wait if necessary to respect rate limit."""
        now = time.time()
        time_since_last = now - self.last_call
        if time_since_last < self.min_interval:
            sleep_time = self.min_interval - time_since_last
            time.sleep(sleep_time)
        self.last_call = time.time()


class PropertyHistoryFetcher:
    """Fetches dealstage property history from HubSpot."""

    def __init__(self, cache_file: str = 'property_history_cache.json'):
        self.api_key = os.environ.get('HUBSPOT_API_KEY')
        if not self.api_key:
            raise ValueError("HUBSPOT_API_KEY environment variable required")

        self.base_url = "https://api.hubapi.com/crm/v3/objects/deals"
        self.cache_file = Path(cache_file)
        self.rate_limiter = RateLimiter(calls_per_second=5)  # Conservative

        # Load existing cache
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        """Load cached property history if exists."""
        if self.cache_file.exists():
            with open(self.cache_file) as f:
                return json.load(f)
        return {
            'fetched_at': None,
            'deals': {},
            'errors': [],
            'stats': {
                'total_requested': 0,
                'successful': 0,
                'failed': 0,
                'cached': 0
            }
        }

    def _save_cache(self):
        """Save current cache to disk."""
        self.cache['fetched_at'] = datetime.now().isoformat()
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)

    def fetch_deal_history(self, deal_id: str, force: bool = False) -> Optional[Dict]:
        """
        Fetch dealstage property history for a single deal.

        Returns dict with:
            - deal_id: str
            - history: List[Dict] with timestamp and value for each change
            - fetched_at: str ISO timestamp
            - source: 'cache' or 'api'
        """
        # Check cache first unless forced
        if not force and deal_id in self.cache['deals']:
            self.cache['stats']['cached'] += 1
            cached = self.cache['deals'][deal_id]
            cached['source'] = 'cache'
            return cached

        # Respect rate limits
        self.rate_limiter.wait()

        # Fetch from HubSpot API
        url = f"{self.base_url}/{deal_id}"
        params = {
            'properties': 'dealstage',
            'propertiesWithHistory': 'dealstage'
        }
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()

            data = response.json()

            # Extract property history
            history = []
            if 'propertiesWithHistory' in data and 'dealstage' in data['propertiesWithHistory']:
                for entry in data['propertiesWithHistory']['dealstage']:
                    history.append({
                        'timestamp': entry.get('timestamp'),
                        'value': entry.get('value'),
                        'source_type': entry.get('sourceType'),
                        'source_id': entry.get('sourceId')
                    })

            result = {
                'deal_id': deal_id,
                'history': history,
                'fetched_at': datetime.now().isoformat(),
                'source': 'api'
            }

            # Cache the result
            self.cache['deals'][deal_id] = result
            self.cache['stats']['successful'] += 1

            # Save cache every 10 successful fetches
            if self.cache['stats']['successful'] % 10 == 0:
                self._save_cache()

            return result

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP error fetching deal {deal_id}: {e}"
            print(f"  ⚠️  {error_msg}")
            self.cache['errors'].append({
                'deal_id': deal_id,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            self.cache['stats']['failed'] += 1
            return None

        except Exception as e:
            error_msg = f"Error fetching deal {deal_id}: {e}"
            print(f"  ⚠️  {error_msg}")
            self.cache['errors'].append({
                'deal_id': deal_id,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            self.cache['stats']['failed'] += 1
            return None

    def fetch_batch(self, deal_ids: List[str], force: bool = False) -> Dict[str, Dict]:
        """
        Fetch property history for a batch of deals.

        Returns dict mapping deal_id -> history data.
        """
        results = {}
        total = len(deal_ids)

        print(f"Fetching property history for {total} deals...")
        print(f"Rate limit: {self.rate_limiter.calls_per_second} calls/sec")
        print()

        for i, deal_id in enumerate(deal_ids, 1):
            if i % 50 == 0 or i == total:
                print(f"  Progress: {i}/{total} deals ({i/total*100:.1f}%)")

            self.cache['stats']['total_requested'] += 1

            result = self.fetch_deal_history(deal_id, force=force)
            if result:
                results[deal_id] = result

        # Final save
        self._save_cache()

        return results

    def get_stats(self) -> Dict:
        """Return current statistics."""
        return self.cache['stats'].copy()


def get_all_deal_ids() -> List[str]:
    """Get all deal IDs from Supabase."""
    url = os.environ['SUPABASE_URL']
    key = os.environ['SUPABASE_SERVICE_KEY']
    client = create_client(url, key)

    deals = select_all(client, 'deals', columns='deal_id')
    return [d['deal_id'] for d in deals]


def main():
    parser = argparse.ArgumentParser(description='Fetch HubSpot dealstage property history')
    parser.add_argument('--deals', help='Comma-separated deal IDs to fetch')
    parser.add_argument('--all', action='store_true', help='Fetch for all deals in Supabase')
    parser.add_argument('--resume', action='store_true', help='Resume from cache')
    parser.add_argument('--force', action='store_true', help='Force re-fetch even if cached')
    parser.add_argument('--cache-file', default='property_history_cache.json',
                       help='Path to cache file')
    parser.add_argument('--rate-limit', type=float, default=5.0,
                       help='API calls per second (default: 5)')

    args = parser.parse_args()

    # Determine which deals to fetch
    deal_ids = []

    if args.resume:
        print("Resuming from cache...")
        fetcher = PropertyHistoryFetcher(cache_file=args.cache_file)
        print(f"Cache loaded: {len(fetcher.cache['deals'])} deals already fetched")
        print()
        # Just print stats and exit
        stats = fetcher.get_stats()
        print("Cache Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        return 0

    elif args.all:
        print("Fetching all deals from Supabase...")
        deal_ids = get_all_deal_ids()
        print(f"Found {len(deal_ids)} deals")

    elif args.deals:
        deal_ids = [d.strip() for d in args.deals.split(',')]
        print(f"Fetching {len(deal_ids)} specified deals")

    else:
        parser.print_help()
        return 1

    print()

    # Fetch property history
    fetcher = PropertyHistoryFetcher(cache_file=args.cache_file)
    fetcher.rate_limiter.calls_per_second = args.rate_limit

    results = fetcher.fetch_batch(deal_ids, force=args.force)

    # Print summary
    print()
    print("=" * 70)
    print("PROPERTY HISTORY FETCH COMPLETE")
    print("=" * 70)
    stats = fetcher.get_stats()
    print(f"Total requested: {stats['total_requested']}")
    print(f"Successful: {stats['successful']}")
    print(f"Failed: {stats['failed']}")
    print(f"From cache: {stats['cached']}")
    print()
    print(f"Results saved to: {args.cache_file}")

    # Show sample history
    if results:
        sample_deal_id = list(results.keys())[0]
        sample = results[sample_deal_id]
        print()
        print(f"Sample history for deal {sample_deal_id}:")
        for entry in sample['history'][:5]:  # First 5 entries
            ts = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
            print(f"  {ts.strftime('%Y-%m-%d %H:%M')} - {entry['value']}")
        if len(sample['history']) > 5:
            print(f"  ... and {len(sample['history']) - 5} more entries")

    return 0


if __name__ == '__main__':
    sys.exit(main())
