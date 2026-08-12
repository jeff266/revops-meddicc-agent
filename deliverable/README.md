# MEDDICC Deal Intelligence Agent - Ready-to-Deploy Package

**Status:** Production-ready template | Drop into repo and customize

**What This Is:**
A complete implementation of a nightly MEDDICC analysis agent that reads your sales calls, updates deal state, and gives reps coaching feedback—automatically.

**Time to First Run:** 15-30 minutes (API keys + minor customization)

---

## What's Included

### 1. Three AI Role Prompts (`prompts/`)
The core intelligence layer that makes this work:

- **`01_context_builder.md`** - Builds cumulative deal state from all previous calls
- **`02_generator.md`** - Analyzes newest call and updates MEDDICC assessment
- **`03_evaluator.md`** - Quality control gate that blocks bad analyses from touching your CRM

**Key Feature:** These are **editable templates**, not black boxes. Customize the framework (MEDDICC → MEDDPICC), adjust scoring thresholds, change stage definitions—everything is exposed.

### 2. GitHub Actions Workflow (`workflows/`)
- **`nightly-meddicc-analysis.yml`** - Drop-in workflow that runs daily
  - Fetches active deals from CRM
  - Pulls call transcripts from Gong/Fireflies/Apollo
  - Runs three-role analysis pipeline
  - Updates CRM with approved analyses
  - Commits learnings to memory layer

**Runs at:** 2 AM UTC (customizable)
**Manual trigger:** Yes, with test mode option

### 3. Evaluator Rubric (`rubrics/`)
- **`evaluator-pass-fail-criteria.md`** - Objective quality gates with actual pass/fail tests
  - 7 evaluation criteria with specific thresholds
  - Test procedures for each criterion
  - Pass/fail examples
  - Quality score calculation

**This is not vague guidance.** It's "reject if Economic Buyer scores 8/10 without a direct quote."

### 4. Rep Rollup Queries (`queries/`)
- **`rep-rollup-analysis.sql`** - Aggregate MEDDICC scores across a rep's entire book
  - Rep summary cards
  - Weakness detection (vs team averages)
  - Coaching focus areas with deal examples
  - Performance trends over time
  - Team leaderboard

**Enables:** Level 3 coaching (fix this rep's systematic gaps, not just this one deal)

### 5. Examples (Coming Soon)
- Sample MEDDICC analyses (approved)
- Sample MEDDICC analyses (rejected with feedback)
- Sample CRM update payloads

---

## Quick Start (15-30 minutes)

### Prerequisites
- GitHub repository for your project
- CRM with API access (HubSpot, Salesforce, etc.)
- Call intelligence tool (Gong, Fireflies, Apollo)
- Anthropic API key (for Claude)

### Step 1: Copy Files to Your Repo

```bash
# From this deliverable folder, copy to your repo:
cp -r prompts/ /path/to/your/repo/
cp -r workflows/ /path/to/your/repo/.github/
cp -r rubrics/ /path/to/your/repo/
cp -r queries/ /path/to/your/repo/

# Create memory structure
mkdir -p /path/to/your/repo/memory/{deals,calls,learnings,versions}
```

### Step 2: Configure GitHub Secrets

Go to: **Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Secret Name | Description | Where to Get It |
|-------------|-------------|-----------------|
| `ANTHROPIC_API_KEY` | Claude API key | https://console.anthropic.com/settings/keys |
| `HUBSPOT_API_KEY` | HubSpot private app token | Settings → Integrations → Private Apps |
| `GONG_API_KEY` | Gong API key (or Fireflies/Apollo) | Gong settings → API |

**Optional:**
- `SLACK_WEBHOOK_URL` - For failure notifications

### Step 3: Customize Prompts (5-10 minutes)

**If using MEDDPICC instead of MEDDICC:**

Edit `prompts/01_context_builder.md`, `prompts/02_generator.md`, `prompts/03_evaluator.md`:
- Add sections for **Paper Process** and **Implies Pain**
- Update scorecard table from `/70` to `/90`

**If using your own framework:**
- Replace the 7 component sections with your components
- Keep the same evidence structure (Status, Evidence, Confidence, Gaps)

**Customize stage definitions:**

In `prompts/03_evaluator.md` and `rubrics/evaluator-pass-fail-criteria.md`, find the "Stage Progression Standards" section and replace with your CRM stages.

Example:
```markdown
**Discovery** → **Demo:**
- Identify Pain: ≥5
- Champion: ≥4

**Demo** → **Proposal:**
- Metrics: ≥6
- Economic Buyer: ≥6
- Champion: ≥6
```

### Step 4: Update Workflow Script Paths

Edit `.github/workflows/nightly-meddicc-analysis.yml`:

1. Update the script path in "Run MEDDICC Analysis" step:
   ```yaml
   run: |
     python scripts/run_nightly.py  # Replace with your script path
   ```

2. Adjust the cron schedule if needed:
   ```yaml
   schedule:
     - cron: '0 2 * * *'  # 2 AM UTC - change to your preferred time
   ```

### Step 5: Test It

**Manual test run:**

1. Go to **Actions** tab in GitHub
2. Select "Nightly MEDDICC Analysis" workflow
3. Click **Run workflow**
4. Check "Run in test mode" (limits to 5 deals)
5. Click **Run workflow**

**Check results:**
- View workflow logs
- Check `memory/` folder for updated deal states
- Verify CRM was updated (if not in test mode)

### Step 6: Enable Nightly Runs

Once testing passes:
- Workflow will run automatically at scheduled time
- Check logs next morning
- Review `memory/learnings/` for deal insights

---

## How It Works

### Architecture: Three AI Roles

```
┌─────────────────────┐
│  Context Builder    │  Reads ALL previous calls for deal
│  (Role 1)           │  Builds running MEDDICC state
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Generator          │  Analyzes NEWEST call
│  (Role 2)           │  Updates MEDDICC assessment
└──────────┬──────────┘  Scores each component (0-10)
           │              Flags gaps and risks
           ▼
┌─────────────────────┐
│  Evaluator          │  Quality control gate
│  (Role 3)           │  Checks 7 criteria
└──────────┬──────────┘  Pass = write to CRM
           │              Fail = reject and require fixes
           ▼
     CRM Update
```

### Why Three Roles?

**Problem:** One big prompt tries to do too much. It either:
- Misses context from previous calls (amnesia)
- Invents evidence that doesn't exist (hallucination)
- Lets bad data into CRM (garbage in = garbage out)

**Solution:** Separation of concerns
1. **Context Builder** - Just reads history, no analysis
2. **Generator** - Analyzes current call against history
3. **Evaluator** - Validates before writing to CRM

**Result:** Better quality, traceable evidence, no CRM corruption

### Memory Layer

```
memory/
├── deals/
│   ├── deal_12345/
│   │   ├── context_state.json      # Running MEDDICC state
│   │   ├── analysis_2026-08-01.json # Per-call analyses
│   │   └── analysis_2026-08-02.json
│   └── index.json                   # Active deals cache
├── calls/
│   ├── fireflies_cache.json         # Call transcripts
│   └── apollo_cache.json
├── learnings/
│   └── 2026-08-02_insights.md       # Daily learnings
└── versions/
    └── context_v1.json              # Schema versions
```

**Key concept:** Each analysis builds on previous state. The system learns over time.

---

## Customization Guide

### Change MEDDICC Components

**File:** `prompts/01_context_builder.md`, `prompts/02_generator.md`

Replace sections 1-7 with your components. Example for BANT:
```markdown
### 1. Budget
**Status:** [✅/⚠️/❌]
**Evidence:**
- Call #X: "[Quote about budget]"
**Confidence:** [High/Medium/Low]
**Gaps:**
- [ ] Budget amount not confirmed
```

### Change Scoring Scale

**File:** `prompts/02_generator.md`

Current: 0-10 per component, /70 total

To change to 0-5 scale:
```markdown
**Score:** [0-5]
- 0-1: Not identified
- 2-3: Partial
- 4-5: Fully qualified
```

Update scorecard table total from `/70` to `/35` (7 components × 5 points)

### Change Quality Thresholds

**File:** `rubrics/evaluator-pass-fail-criteria.md`

Adjust score thresholds in Criterion 4:
```markdown
**PASS if:**
- ✅ Scores 0-2: No evidence (was 0-3)
- ✅ Scores 3-4: Some evidence (was 4-6)
- ✅ Scores 5: Strong evidence (was 7-8)
```

### Add More Criteria

**File:** `prompts/03_evaluator.md`

Add sections after Criterion 7:
```markdown
### ✅ CRITERION 8: Temporal Consistency
**Requirement:** Timeline references must be realistic
**Pass Conditions:**
- ✅ Close dates align with decision process timeline
- ✅ No contradictory date references
```

### Use Different CRM

**File:** `.github/workflows/nightly-meddicc-analysis.yml`

Update environment variables:
```yaml
env:
  SALESFORCE_API_KEY: ${{ secrets.SALESFORCE_API_KEY }}  # Instead of HUBSPOT_API_KEY
```

Update script to use Salesforce client instead of HubSpot.

### Use Different Call Source

**File:** Your `run_nightly.py` script

Replace Gong client with your source:
```python
# Instead of:
from gong_client import get_gong_calls

# Use:
from chorus_client import get_chorus_calls
# or
from custom_source import get_call_transcripts
```

---

## Rep Rollup Queries

**Purpose:** Coaching at scale (see patterns across all of a rep's deals)

**File:** `queries/rep-rollup-analysis.sql`

### Query 1: Rep Summary Card
Shows each rep's overall MEDDICC performance
```sql
-- Average scores across all components
-- Deal health distribution
-- Qualified pipeline value
```

### Query 2: Rep Weakness Detection
Identifies which components a rep consistently struggles with
```sql
-- Compares rep to team averages
-- Flags components below team average
-- Prioritizes critical gaps (< 5)
```

### Query 3: Coaching Focus
Deep dive into one rep's patterns
```sql
-- Shows % of deals weak on each component
-- Prioritizes coaching focus areas
-- Lists specific deal examples
```

### Query 6: Team Leaderboard
Ranks reps by MEDDICC execution quality
```sql
-- Ordered by average total score
-- Shows qualification percentage
-- Identifies each rep's weakest component
```

**Usage Example:**

Weekly 1:1 prep:
1. Run Query 3 for the rep → see weakest component
2. Run Query 4 with that component → get specific deal examples
3. Pull call transcripts for 2-3 of those deals
4. Review evidence quality in the 1:1

---

## Common Issues

### Issue: Workflow times out
**Fix:** Increase `timeout-minutes` in workflow file or reduce deal batch size

```yaml
timeout-minutes: 120  # Increase from 60
```

### Issue: API rate limits
**Fix:** Add backoff/retry logic in your API client

```python
import time
from requests.exceptions import HTTPError

def fetch_with_retry(url, max_retries=3):
    for i in range(max_retries):
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except HTTPError as e:
            if e.response.status_code == 429:  # Rate limit
                time.sleep(2 ** i)  # Exponential backoff
            else:
                raise
```

### Issue: Secrets not working
**Fix:** Verify secret names match exactly (case-sensitive)
- ❌ `anthropic_api_key`
- ✅ `ANTHROPIC_API_KEY`

### Issue: Memory not committing
**Fix:** Check workflow has write permissions

```yaml
permissions:
  contents: write  # Must be present
```

### Issue: Bad quality analyses getting through
**Fix:** Switch to Strict Mode in evaluator

Edit `prompts/03_evaluator.md`:
```markdown
**Default: Strict Mode**
- Reject if ANY criterion fails
```

---

## Cost Estimates

**Per-deal analysis cost (Anthropic API):**
- Context Builder: ~5,000 tokens (Haiku) = $0.001
- Generator: ~10,000 tokens (Sonnet) = $0.03
- Evaluator: ~8,000 tokens (Sonnet) = $0.024
- **Total per deal:** ~$0.055

**Monthly cost (100 active deals, 20 new calls/day):**
- 20 analyses/day × $0.055 = $1.10/day
- **Monthly: ~$33**

**Ways to reduce cost:**
- Use Haiku for Context Builder (already recommended)
- Use Haiku for Evaluator if quality is consistently good
- Only analyze deals with new calls (delta updates)
- Cache call transcripts to avoid re-fetching

---

## What's Next

### After Initial Deployment

1. **Week 1-2: Strict Mode**
   - Review every rejected analysis
   - Tune prompts if Generator consistently fails on same criteria
   - Build confidence in quality

2. **Week 3-4: Collect Feedback**
   - Ask reps: "Is this analysis accurate?"
   - Track which components have weakest evidence
   - Identify patterns in false positives/negatives

3. **Month 2: Optimize**
   - Switch to Standard Mode if rejection rate < 10%
   - Add custom criteria for your business (e.g., "Legal Process" for enterprise deals)
   - Build rep rollup dashboard

4. **Month 3+: Scale**
   - Expand to all deals (not just active)
   - Add automated coaching emails
   - Integrate with forecast reviews

### Advanced Features to Add

- **Slack notifications** when deal health drops
- **Email digests** with weekly MEDDICC updates
- **Dashboard** showing team MEDDICC heatmap
- **Forecasting** using MEDDICC completeness scores
- **Win/loss analysis** by component strength

---

## Support and Contributions

**Questions?**
- Check workflow logs in GitHub Actions
- Review `memory/issues/` folder (auto-created for errors)
- Read prompt files—they're heavily documented

**Want to contribute?**
- Share your customizations (different frameworks, CRM integrations)
- Submit improved evaluation criteria
- Add examples of great/terrible analyses

---

## License

This is a paid deliverable template. Customize freely for your business.

**Not included:** Implementation of `run_nightly.py`, CRM API clients, or call transcript fetching. Those are specific to your tech stack.

**Included:** The intelligence layer (prompts), quality gates (rubric), automation structure (workflow), and coaching queries.

---

## Key Principles

1. **Evidence > Inference:** Every claim must trace to a direct quote
2. **Strict > Lenient:** Better to reject a borderline analysis than corrupt your CRM
3. **Context is King:** Each call builds on previous state, not analyzed in isolation
4. **Quality Gates Work:** Evaluator blocks 30-40% of initial analyses (this is good)
5. **Coaching at Scale:** Rep rollups show patterns you can't see in individual deals

---

**Ready to deploy?** Start with Step 1 above. Should take 15-30 minutes to get first analysis running.

**Questions on customization?** Read the prompt files. They're templates, not black boxes.

**Want to see it in action?** Check `examples/` folder (coming soon) for sample analyses.
