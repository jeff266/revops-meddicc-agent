from pathlib import Path
from datetime import datetime, timezone
import json
import threading
import os
import secrets

class TokenTracker:

    def __init__(self, memory_dir: Path, job: str = 'unknown'):
        self.usage_dir = memory_dir / 'token_usage'
        self.usage_dir.mkdir(parents=True, exist_ok=True)

        # Use absolute path from script location (scripts/ -> repo root -> config/)
        costs_path = Path(__file__).parent.parent / 'config' / 'model_costs.json'
        with open(costs_path) as f:
            self.model_costs = json.load(f)

        self.job = job
        self.run_id = os.getenv('GITHUB_RUN_ID', secrets.token_hex(4))
        self.session_records = []
        self._lock = threading.Lock()  # Thread safety for concurrent record() calls

    def record(self, response, model: str, role: str,
               company: str = '') -> float:
        """
        Pass the raw Anthropic response object.
        Extracts usage, calculates cost, appends to session records.
        Returns cost in USD.
        Thread-safe for concurrent calls.
        """
        input_tokens  = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = self._cost(model, input_tokens, output_tokens)

        with self._lock:
            self.session_records.append({
                'timestamp': datetime.now().isoformat(),
                'model':         model,
                'role':          role,
                'company':       company,
                'input_tokens':  input_tokens,
                'output_tokens': output_tokens,
                'cost_usd':      cost,
            })
        return cost

    def _cost(self, model: str, inp: int, out: int) -> float:
        rates = self.model_costs.get(model, {'input': 0, 'output': 0})
        return round((inp * rates['input'] + out * rates['output']) / 1_000_000, 8)

    def save(self) -> dict:
        """
        Write session records to a collision-proof per-run file.
        Return the run's summary dict.
        """
        if not self.session_records:
            return {'total_cost_usd': 0, 'total_input_tokens': 0,
                    'total_output_tokens': 0, 'total_calls': 0,
                    'by_model': {}, 'by_role': {}}

        summary = self._summarize(self.session_records)

        # Collision-proof filename: {date}T{time}Z_{job}_{run_id}.json
        now_utc = datetime.now(timezone.utc)
        timestamp = now_utc.strftime('%Y-%m-%dT%H%M%SZ')
        filename = f'{timestamp}_{self.job}_{self.run_id}.json'
        run_path = self.usage_dir / filename

        with open(run_path, 'w') as f:
            json.dump({
                'timestamp': now_utc.isoformat(),
                'job':       self.job,
                'run_id':    self.run_id,
                'summary':   summary,
                'records':   self.session_records,
            }, f, indent=2)

        return summary

    def _summarize(self, records: list) -> dict:
        by_model, by_role = {}, {}
        total_cost = 0

        for r in records:
            m = r['model']
            if m not in by_model:
                by_model[m] = {'input_tokens': 0, 'output_tokens': 0,
                                'cost_usd': 0.0, 'calls': 0}
            by_model[m]['input_tokens']  += r['input_tokens']
            by_model[m]['output_tokens'] += r['output_tokens']
            by_model[m]['cost_usd']      += r['cost_usd']
            by_model[m]['calls']         += 1

            role = r['role']
            if role not in by_role:
                by_role[role] = {'input_tokens': 0, 'output_tokens': 0,
                                  'cost_usd': 0.0}
            by_role[role]['input_tokens']  += r['input_tokens']
            by_role[role]['output_tokens'] += r['output_tokens']
            by_role[role]['cost_usd']      += r['cost_usd']
            total_cost += r['cost_usd']

        # Round model costs
        for m in by_model:
            by_model[m]['cost_usd'] = round(by_model[m]['cost_usd'], 6)
        for role in by_role:
            by_role[role]['cost_usd'] = round(by_role[role]['cost_usd'], 6)

        return {
            'total_cost_usd':     round(total_cost, 6),
            'total_input_tokens': sum(r['input_tokens'] for r in records),
            'total_output_tokens':sum(r['output_tokens'] for r in records),
            'total_calls':        len(records),
            'by_model':           by_model,
            'by_role':            by_role,
        }

    @staticmethod
    def rollup_monthly(usage_dir: Path, year_month: str) -> dict:
        """
        Compute monthly totals by summing all per-run files for the given month.
        year_month format: 'YYYY-MM'
        Returns: {'total_cost_usd': float, 'total_input_tokens': int,
                  'total_output_tokens': int, 'total_calls': int, 'runs': int}
        """
        total_cost = 0.0
        total_input = 0
        total_output = 0
        total_calls = 0
        run_count = 0

        # Match both old daily files and new per-run files
        for run_file in usage_dir.glob(f'{year_month}-*.json'):
            if 'monthly' in run_file.name:
                continue  # Skip old monthly aggregates
            try:
                with open(run_file) as f:
                    data = json.load(f)
                    summary = data.get('summary', {})
                    total_cost += summary.get('total_cost_usd', 0)
                    total_input += summary.get('total_input_tokens', 0)
                    total_output += summary.get('total_output_tokens', 0)
                    total_calls += summary.get('total_calls', 0)
                    run_count += 1
            except (json.JSONDecodeError, KeyError):
                continue

        return {
            'total_cost_usd': round(total_cost, 6),
            'total_input_tokens': total_input,
            'total_output_tokens': total_output,
            'total_calls': total_calls,
            'runs': run_count,
        }

    def print_summary(self, summary: dict, deals_processed: int = 0,
                      show_monthly: bool = True):
        print("\n=== TOKEN USAGE ===")
        for model, s in summary['by_model'].items():
            label = model.replace('claude-', '').replace('-20250929','').replace('-20251001','')
            print(f"  {label:<35}  "
                  f"{s['input_tokens']:>8,} in  "
                  f"{s['output_tokens']:>7,} out  "
                  f"${s['cost_usd']:.5f}  "
                  f"({s['calls']} calls)")
        print(f"  {'─'*70}")
        print(f"  {'TOTAL (this run)':<35}  "
              f"{summary['total_input_tokens']:>8,} in  "
              f"{summary['total_output_tokens']:>7,} out  "
              f"${summary['total_cost_usd']:.5f}")
        if deals_processed > 0:
            cph = round(summary['total_cost_usd'] / deals_processed, 5)
            print(f"  Cost per deal: ${cph}")

        if show_monthly:
            year_month = datetime.now(timezone.utc).strftime('%Y-%m')
            monthly = self.rollup_monthly(self.usage_dir, year_month)
            print(f"  {'TOTAL (month-to-date)':<35}  "
                  f"{monthly['total_input_tokens']:>8,} in  "
                  f"{monthly['total_output_tokens']:>7,} out  "
                  f"${monthly['total_cost_usd']:.5f}  "
                  f"({monthly['runs']} runs)")
        print()
