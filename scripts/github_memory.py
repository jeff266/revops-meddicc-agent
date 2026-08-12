"""
GitHub Memory Layer for MEDDICC Agent

Manages learnings, versions, diffs, and counter files via GitHub API.
Supports both local file operations and GitHub API for Actions environment.
"""
import os
import json
import secrets
import threading
import secrets
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import base64


# Detect if running in GitHub Actions
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # Format: "owner/repo"


class GitHubMemory:
    """Manages memory layer files (learnings, versions, diffs, counter)."""

    def __init__(self, repo_root: Path = None):
        """Initialize memory manager."""
        if repo_root is None:
            repo_root = Path(__file__).parent.parent

        self.repo_root = Path(repo_root)
        self.memory_dir = self.repo_root / "memory"
        self.learnings_dir = self.memory_dir / "learnings"
        self.versions_dir = self.memory_dir / "versions"
        self.diffs_dir = self.memory_dir / "diffs"
        self.issues_dir = self.memory_dir / "issues"
        self.rubric_obs_dir = self.memory_dir / "rubric_observations"
        self.meta_dir = self.memory_dir / "meta"
        self.runs_dir = self.meta_dir / "runs"
        self.calls_dir = self.memory_dir / "calls"
        self.deals_dir = self.memory_dir / "deals"

        # Ensure directories exist (both local and GitHub Actions)
        self.learnings_dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.diffs_dir.mkdir(parents=True, exist_ok=True)
        self.issues_dir.mkdir(parents=True, exist_ok=True)
        self.rubric_obs_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.calls_dir.mkdir(parents=True, exist_ok=True)
        self.deals_dir.mkdir(parents=True, exist_ok=True)

        # Thread safety locks for parallel processing
        self._save_lock = threading.Lock()
        self._counter_lock = threading.Lock()

    # ─────────────────────────────────────────────────────────────────
    # Counter Management (Per-Run Files + Rollup)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _rollup_counter(runs_dir: Path) -> dict:
        """
        Compute counter state by rolling up per-run marker files.
        Returns derived state, not incremented.
        """
        run_file_paths = list(runs_dir.glob('*.json'))

        if not run_file_paths:
            # No runs yet
            next_rewrite = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            return {
                "total_runs": 0,
                "runs_since_rewrite": 0,
                "last_full_rewrite": None,
                "next_full_rewrite_due": next_rewrite
            }

        # Load and sort by timestamp field (not filename)
        runs_with_timestamp = []
        for run_file in run_file_paths:
            try:
                with open(run_file, 'r') as f:
                    data = json.load(f)
                    runs_with_timestamp.append((data.get('timestamp', ''), run_file, data))
            except:
                continue

        # Sort by timestamp field
        runs_with_timestamp.sort(key=lambda x: x[0])
        run_files = [(path, data) for _, path, data in runs_with_timestamp]

        # Find last full rewrite
        last_full_rewrite_date = None
        last_full_rewrite_idx = -1

        for idx, (run_file, data) in enumerate(run_files):
            if data.get('is_full_rewrite'):
                last_full_rewrite_date = data.get('timestamp', '')[:10]
                last_full_rewrite_idx = idx

        # Count runs since last rewrite
        if last_full_rewrite_idx >= 0:
            runs_since_rewrite = len(run_files) - last_full_rewrite_idx - 1
        else:
            runs_since_rewrite = len(run_files)

        # Calculate next rewrite due date
        if last_full_rewrite_date:
            try:
                last_rewrite_dt = datetime.strptime(last_full_rewrite_date, '%Y-%m-%d')
                next_rewrite = (last_rewrite_dt + timedelta(days=30)).strftime('%Y-%m-%d')
            except:
                next_rewrite = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        else:
            next_rewrite = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')

        return {
            "total_runs": len(run_files),
            "runs_since_rewrite": runs_since_rewrite,
            "last_full_rewrite": last_full_rewrite_date,
            "next_full_rewrite_due": next_rewrite
        }

    def get_counter(self) -> dict:
        """
        Get current counter state via rollup (thread-safe).
        No longer reads counter.json file.
        """
        with self._counter_lock:
            return self._rollup_counter(self.runs_dir)

    def update_counter(self, is_full_rewrite: bool = False) -> dict:
        """
        Write collision-proof per-run marker file.
        Returns updated counter state via rollup.
        """
        with self._counter_lock:
            now_utc = datetime.now(timezone.utc)
            timestamp = now_utc.strftime('%Y-%m-%dT%H%M%SZ')
            run_id = os.getenv('GITHUB_RUN_ID', secrets.token_hex(4))
            filename = f'{timestamp}_nightly_{run_id}.json'

            # Write per-run marker
            run_file = self.runs_dir / filename
            with open(run_file, 'w') as f:
                json.dump({
                    'timestamp': now_utc.isoformat(),
                    'job': 'nightly',
                    'run_id': run_id,
                    'is_full_rewrite': is_full_rewrite
                }, f, indent=2)

            # Return rollup state
            return self._rollup_counter(self.runs_dir)

    def should_full_rewrite(self) -> bool:
        """Check if it's time for a full rewrite (30 days)."""
        counter = self.get_counter()
        return counter["runs_since_rewrite"] >= 30

    # ─────────────────────────────────────────────────────────────────
    # Learning Entries
    # ─────────────────────────────────────────────────────────────────

    def save_learning(self, learning: dict) -> Path:
        """Save a learning entry. Thread-safe."""
        with self._save_lock:
            # Generate ID with run_id and sequence to prevent collisions
            today = datetime.now().strftime('%Y-%m-%d')
            run_id = os.getenv('GITHUB_RUN_ID', secrets.token_hex(4))

            # Count existing learnings for this run to get sequence number
            existing = list(self.learnings_dir.glob(f'{today}_{run_id}_*.json'))
            seq = len(existing) + 1
            learning_id = f"{today}_{run_id}_{seq:03d}"

            learning["id"] = learning_id
            learning["timestamp"] = datetime.now().isoformat()

            # Write file
            learning_path = self.learnings_dir / f"{learning_id}.json"
            with open(learning_path, 'w') as f:
                json.dump(learning, f, indent=2)

            return learning_path

    def save_issue(self, issue: dict) -> Path:
        """Save an issue entry (bugs, prompt_issue outcomes). Thread-safe."""
        with self._save_lock:
            # Generate ID with run_id and sequence to prevent collisions
            today = datetime.now().strftime('%Y-%m-%d')
            run_id = os.getenv('GITHUB_RUN_ID', secrets.token_hex(4))

            # Count existing issues for this run to get sequence number
            existing = list(self.issues_dir.glob(f'{today}_{run_id}_*.json'))
            seq = len(existing) + 1
            issue_id = f"{today}_{run_id}_{seq:03d}"

            issue["id"] = issue_id
            issue["timestamp"] = datetime.now().isoformat()

            # Write file to issues directory
            issue_path = self.issues_dir / f"{issue_id}.json"
            with open(issue_path, 'w') as f:
                json.dump(issue, f, indent=2)

            return issue_path

    def save_rubric_observation(self, observation: dict,
                                company: str) -> Optional[Path]:
        """
        Save a rubric observation only when criterion_fired is not null
        and suggested_change is not null. Thread-safe.
        Observations with no criterion fired are not worth storing.
        """
        if not observation.get('criterion_fired'):
            return None
        if not observation.get('suggested_change'):
            return None

        with self._save_lock:
            today = datetime.now().strftime('%Y-%m-%d')
            run_id = os.getenv('GITHUB_RUN_ID', secrets.token_hex(4))

            # Count existing observations for this run to get sequence number
            existing = list(self.rubric_obs_dir.glob(f'{today}_{run_id}_*.json'))
            seq = len(existing) + 1
            obs_id = f'{today}_{run_id}_{seq:03d}'
            path = self.rubric_obs_dir / f'{obs_id}.json'

            data = {
                'id': obs_id,
                'timestamp': datetime.now().isoformat(),
                'company': company,
                **observation
            }
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            return path

    def get_todays_learnings(self) -> List[dict]:
        """Get all learning entries from today."""
        today = datetime.now().strftime('%Y-%m-%d')
        learnings = []

        for path in self.learnings_dir.glob(f"{today}_*.json"):
            with open(path, 'r') as f:
                learnings.append(json.load(f))

        return sorted(learnings, key=lambda x: x.get('id', ''))

    def get_recent_learnings(self, days: int = 30) -> List[dict]:
        """Get learning entries from last N days."""
        cutoff = datetime.now() - timedelta(days=days)
        learnings = []

        for path in self.learnings_dir.glob("*.json"):
            with open(path, 'r') as f:
                learning = json.load(f)
                timestamp = learning.get('timestamp', '')

                try:
                    learning_date = datetime.fromisoformat(timestamp)
                    if learning_date >= cutoff:
                        learnings.append(learning)
                except:
                    pass

        return sorted(learnings, key=lambda x: x.get('timestamp', ''))

    # ─────────────────────────────────────────────────────────────────
    # Versions & Diffs
    # ─────────────────────────────────────────────────────────────────

    def save_version(self, claude_md_content: str) -> Path:
        """Save a versioned snapshot of CLAUDE.md."""
        today = datetime.now().strftime('%Y-%m-%d')
        version_path = self.versions_dir / f"CLAUDE_{today}.md"

        with open(version_path, 'w') as f:
            f.write(claude_md_content)

        return version_path

    def save_diff(self, diff_content: str) -> Path:
        """Save daily diff explanation with run_id to prevent collisions."""
        today = datetime.now().strftime('%Y-%m-%d')
        run_id = os.getenv('GITHUB_RUN_ID', secrets.token_hex(4))
        diff_path = self.diffs_dir / f"{today}_{run_id}.md"

        with open(diff_path, 'w') as f:
            f.write(diff_content)

        return diff_path

    def get_current_claude_md(self) -> str:
        """Get current CLAUDE.md content."""
        claude_md_path = self.repo_root / "prompts" / "CLAUDE.md"

        with open(claude_md_path, 'r') as f:
            return f.read()

    def update_claude_md(self, new_content: str) -> None:
        """Update CLAUDE.md file."""
        claude_md_path = self.repo_root / "prompts" / "CLAUDE.md"

        with open(claude_md_path, 'w') as f:
            f.write(new_content)

    # ─────────────────────────────────────────────────────────────────
    # GitHub PR Creation (for Actions environment)
    # ─────────────────────────────────────────────────────────────────

    def create_pr(
        self,
        branch_name: str,
        title: str,
        body: str,
        files_to_commit: Dict[str, str]
    ) -> Optional[str]:
        """
        Create a GitHub PR with file changes.

        Args:
            branch_name: Name of the branch
            title: PR title
            body: PR description
            files_to_commit: Dict of {file_path: content}

        Returns:
            PR URL if successful, None otherwise
        """
        if not IS_GITHUB_ACTIONS:
            print("⚠️  PR creation only works in GitHub Actions environment")
            return None

        if not GITHUB_TOKEN or not GITHUB_REPO:
            print("⚠️  Missing GITHUB_TOKEN or GITHUB_REPO")
            return None

        # Defensive checks for None values
        if not branch_name or not title or body is None:
            print(f"⚠️  Invalid PR parameters: branch_name={bool(branch_name)}, title={bool(title)}, body={body is not None}")
            return None

        if not files_to_commit:
            print("⚠️  No files to commit")
            return None

        # Check for None values in file content
        for file_path, content in files_to_commit.items():
            if content is None:
                print(f"⚠️  File '{file_path}' has None content")
                return None

        try:
            import requests

            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            api_base = f"https://api.github.com/repos/{GITHUB_REPO}"

            # 1. Get default branch SHA
            repo_resp = requests.get(f"{api_base}", headers=headers)
            repo_resp.raise_for_status()
            default_branch = repo_resp.json()["default_branch"]

            # 2. Get default branch ref
            ref_resp = requests.get(f"{api_base}/git/ref/heads/{default_branch}", headers=headers)
            ref_resp.raise_for_status()
            base_sha = ref_resp.json()["object"]["sha"]

            # 3. Create new branch
            create_ref_resp = requests.post(
                f"{api_base}/git/refs",
                headers=headers,
                json={
                    "ref": f"refs/heads/{branch_name}",
                    "sha": base_sha
                }
            )
            create_ref_resp.raise_for_status()

            # 4. Create/update files on new branch
            for file_path, content in files_to_commit.items():
                # Get current file SHA if it exists
                try:
                    file_resp = requests.get(f"{api_base}/contents/{file_path}", headers=headers)
                    file_sha = file_resp.json()["sha"] if file_resp.status_code == 200 else None
                except:
                    file_sha = None

                # Update file
                content_b64 = base64.b64encode(content.encode()).decode()
                update_data = {
                    "message": f"Update {file_path}",
                    "content": content_b64,
                    "branch": branch_name
                }
                if file_sha:
                    update_data["sha"] = file_sha

                update_resp = requests.put(
                    f"{api_base}/contents/{file_path}",
                    headers=headers,
                    json=update_data
                )
                update_resp.raise_for_status()

            # 5. Create PR
            pr_resp = requests.post(
                f"{api_base}/pulls",
                headers=headers,
                json={
                    "title": title,
                    "body": body,
                    "head": branch_name,
                    "base": default_branch
                }
            )
            pr_resp.raise_for_status()

            pr_url = pr_resp.json()["html_url"]
            return pr_url

        except Exception as e:
            print(f"Error creating PR: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────
    # Call Cache Management
    # ─────────────────────────────────────────────────────────────────

    def load_call_cache(self, slug: str) -> Optional[dict]:
        """Load call cache for a company slug with fuzzy prefix matching."""
        # Try exact match first
        cache_path = self.calls_dir / f"{slug}.json"
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"   ⚠️  Error loading cache {slug}.json: {e}")
                return None

        # Fuzzy match: prefix matching with vendor-first reversal
        from utils import load_client_config
        config = load_client_config()
        vendor = (config.get('organization', {}).get('name', 'yourcompany') or 'yourcompany').lower()

        matching_files = [
            f for f in self.calls_dir.glob("*.json")
            if f.stem == slug
            or f.stem.startswith(slug + '-')
            or f.stem == f'{vendor}-{slug}'
            or f.stem.startswith(f'{vendor}-{slug}-')
        ]

        if len(matching_files) == 1:
            best_match = matching_files[0]
            print(f"   🔍 Fuzzy match: {slug} → {best_match.name}")
            try:
                with open(best_match, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"   ⚠️  Error loading cache {best_match.name}: {e}")
                return None
        elif len(matching_files) > 1:
            # Ambiguous — don't guess, return None
            print(f"   ⚠️  Ambiguous slug match for {slug}: "
                  f"{[f.name for f in matching_files]}")
            return None

        return None

    def save_call_cache(self, slug: str, cache_data: dict):
        """Save call cache for a company slug with fuzzy prefix matching."""
        # Check for existing file with prefix match (vendor-first reversal)
        from utils import load_client_config
        config = load_client_config()
        vendor = (config.get('organization', {}).get('name', 'yourcompany') or 'yourcompany').lower()

        matching_files = [
            f for f in self.calls_dir.glob("*.json")
            if f.stem == slug
            or f.stem.startswith(slug + '-')
            or f.stem == f'{vendor}-{slug}'
            or f.stem.startswith(f'{vendor}-{slug}-')
        ]

        if len(matching_files) == 1:
            # Use existing file
            cache_path = matching_files[0]
            if cache_path.stem != slug:
                print(f"   🔍 Saving to existing: {slug} → {cache_path.name}")
        elif len(matching_files) > 1:
            # Ambiguous - use exact slug to avoid corruption
            print(f"   ⚠️  Ambiguous slug for save, using exact: {slug}.json")
            cache_path = self.calls_dir / f"{slug}.json"
        else:
            # No match - create new file
            cache_path = self.calls_dir / f"{slug}.json"

        cache_data['last_etl_date'] = datetime.now().isoformat()

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️  Error saving cache {cache_path.name}: {e}")

    def load_deal_index(self) -> dict:
        """Load deal index mapping deal_id -> company_slug."""
        index_path = self.calls_dir / "_deal_index.json"
        if not index_path.exists():
            return {}

        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"   ⚠️  Error loading deal index: {e}")
            return {}

    def save_deal_index(self, index: dict):
        """Save deal index mapping deal_id -> company_slug."""
        index_path = self.calls_dir / "_deal_index.json"

        try:
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(index, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️  Error saving deal index: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Deals Index (CSV-built deal cache)
    # ─────────────────────────────────────────────────────────────────

    def load_deals_index(self) -> dict:
        """Load deals index built from HubSpot CSV export."""
        index_path = self.deals_dir / "index.json"

        if not index_path.exists():
            return {'deals': {}}

        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"   ⚠️  Error loading deals index: {e}")
            return {'deals': {}}

    def get_active_deals_from_index(self) -> list:
        """Returns list of deal dicts from the CSV-built index."""
        index = self.load_deals_index()
        return list(index.get('deals', {}).values())


def get_memory_manager(repo_root: Path = None) -> GitHubMemory:
    """Get configured memory manager."""
    return GitHubMemory(repo_root)


if __name__ == "__main__":
    # Test memory operations
    memory = get_memory_manager()

    print("=" * 80)
    print("TESTING MEMORY LAYER")
    print("=" * 80)

    # Test counter
    counter = memory.get_counter()
    print(f"\nCounter state:")
    print(json.dumps(counter, indent=2))

    # Test learning save
    test_learning = {
        "company": "Test Corp",
        "deal_id": "123456",
        "loop_performance": {
            "iterations_to_pass": 2,
            "passed": True,
            "budget_exhausted": False
        },
        "cumulative_calls_context": 3,
        "iteration_1_failures": ["Evidence quality"],
        "components_weak": ["Champion"],
        "components_strong": ["Metrics", "Economic Buyer"],
        "required_changes_injected": "Added specific evidence for Economic Buyer",
        "resolution": "Passed on iteration 2",
        "proposed_instruction": "Always quote specific evidence from calls, not generic statements"
    }

    learning_path = memory.save_learning(test_learning)
    print(f"\n✓ Saved learning to: {learning_path}")

    # Test version save
    test_claude_md = "# Test CLAUDE.md\n\nThis is a test version."
    version_path = memory.save_version(test_claude_md)
    print(f"✓ Saved version to: {version_path}")

    # Test diff save
    test_diff = "# Daily Diff - 2026-07-29\n\nAdded 3 new learnings about evidence quality."
    diff_path = memory.save_diff(test_diff)
    print(f"✓ Saved diff to: {diff_path}")

    # Check if should do full rewrite
    should_rewrite = memory.should_full_rewrite()
    print(f"\nShould do full rewrite: {should_rewrite}")

    print("\n" + "=" * 80)
    print("✓ Memory layer test complete")
    print("=" * 80)
