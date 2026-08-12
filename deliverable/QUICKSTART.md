# Quick Start: First MEDDICC Analysis in 10 Minutes

Get your first automated MEDDICC analysis running without reading the full docs.

---

## Prerequisites (Have These Ready)

- [ ] Anthropic API key ([get one](https://console.anthropic.com/settings/keys))
- [ ] CRM API key (HubSpot, Salesforce, etc.)
- [ ] Call transcript source (Gong, Fireflies, Apollo)
- [ ] One deal with at least 2 recorded calls

---

## Step 1: Copy Files (2 minutes)

```bash
# Clone or download this deliverable package
cd /path/to/your/project

# Copy the prompt files
mkdir -p prompts
cp deliverable/prompts/*.md prompts/

# Copy the rubric
mkdir -p rubrics
cp deliverable/rubrics/*.md rubrics/

# Create memory structure
mkdir -p memory/{deals,calls,learnings,versions}
```

---

## Step 2: Set API Keys (1 minute)

```bash
# Set environment variables
export ANTHROPIC_API_KEY="your-key-here"
export HUBSPOT_API_KEY="your-key-here"
export GONG_API_KEY="your-key-here"  # Or Fireflies/Apollo

# Or create .env file:
cat > .env << EOF
ANTHROPIC_API_KEY=your-key-here
HUBSPOT_API_KEY=your-key-here
GONG_API_KEY=your-key-here
EOF
```

---

## Step 3: Create Simple Test Script (3 minutes)

```python
#!/usr/bin/env python3
"""test_meddicc.py - Quick test of MEDDICC analysis"""

import os
from anthropic import Anthropic

# Initialize Claude
client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Read prompts
with open('prompts/01_context_builder.md') as f:
    context_builder_prompt = f.read()

with open('prompts/02_generator.md') as f:
    generator_prompt = f.read()

with open('prompts/03_evaluator.md') as f:
    evaluator_prompt = f.read()

# Mock data for testing (replace with real data)
previous_calls = """
Call #1 (July 15, 2026):
- Met with Jamie (Director of Product)
- Discussed pain: Manual reporting takes 40 hrs/week
- Identified need for automated analytics

Call #2 (July 22, 2026):
- Demo call with Jamie + Sarah (VP Finance)
- Sarah mentioned budget concerns
- Jamie seemed supportive of solution
"""

current_call = """
Call #3 (August 1, 2026):
Participants: Sarah Johnson (VP Finance), Jamie Lee (Director of Product)
Duration: 28 minutes

Transcript:
[14:32] Sarah: "We're currently spending 40 hours per week on manual report aggregation.
Our target is to reduce that to under 10 hours within 6 months."

[15:10] Sarah: "That 40 hours is costing us about $85K annually in fully-loaded engineering time."

[15:45] Sarah: "If you can get us to 10 hours like you showed in the demo, that's a $63K annual saving."

[18:15] Sarah: "I have signing authority up to $250K. Your proposal is $180K, so this is fully
within my budget."

[9:03] Sarah: "We allocated $200K for this initiative in our Q3 planning."
"""

# Step 1: Context Builder
print("🔨 Building context from previous calls...")
context_response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4000,
    messages=[{
        "role": "user",
        "content": f"{context_builder_prompt}\n\nPrevious Calls:\n{previous_calls}"
    }]
)
context_state = context_response.content[0].text
print("✅ Context built\n")

# Step 2: Generator
print("📝 Generating MEDDICC analysis...")
generator_response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=8000,
    messages=[{
        "role": "user",
        "content": f"{generator_prompt}\n\nRunning MEDDICC State:\n{context_state}\n\nNewest Call:\n{current_call}"
    }]
)
analysis = generator_response.content[0].text
print("✅ Analysis generated\n")

# Step 3: Evaluator
print("🔍 Evaluating quality...")
evaluator_response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4000,
    messages=[{
        "role": "user",
        "content": f"{evaluator_prompt}\n\nGenerator Output:\n{analysis}\n\nSource Material:\n{context_state}\n{current_call}"
    }]
)
evaluation = evaluator_response.content[0].text
print("✅ Evaluation complete\n")

# Print results
print("=" * 80)
print("MEDDICC ANALYSIS")
print("=" * 80)
print(analysis)
print("\n" + "=" * 80)
print("QUALITY EVALUATION")
print("=" * 80)
print(evaluation)

# Check if approved
if "APPROVED" in evaluation or "✅ APPROVED" in evaluation:
    print("\n🎉 Analysis APPROVED - Ready for CRM update")
else:
    print("\n❌ Analysis REJECTED - See evaluation feedback above")
```

---

## Step 4: Run Test (2 minutes)

```bash
python test_meddicc.py
```

**Expected output:**
```
🔨 Building context from previous calls...
✅ Context built

📝 Generating MEDDICC analysis...
✅ Analysis generated

🔍 Evaluating quality...
✅ Evaluation complete

================================================================================
MEDDICC ANALYSIS
================================================================================
[Full analysis with scores, evidence, gaps...]

================================================================================
QUALITY EVALUATION
================================================================================
Verdict: ✅ APPROVED
[Evaluation details...]

🎉 Analysis APPROVED - Ready for CRM update
```

---

## Step 5: Review Output (2 minutes)

Check the analysis for:
- ✅ All 7 MEDDICC components present
- ✅ Scores (0-10) for each component
- ✅ Direct quotes with evidence
- ✅ Specific recommended actions
- ✅ Evaluator verdict (APPROVED/REJECTED)

---

## What Just Happened?

1. **Context Builder** read your previous calls and built running MEDDICC state
2. **Generator** analyzed the newest call and updated scores with evidence
3. **Evaluator** checked quality (evidence traceability, score justification, etc.)
4. Result: Either APPROVED (write to CRM) or REJECTED (fix and retry)

---

## Next Steps

### If Analysis Was Approved ✅
1. Review the recommended actions - are they specific enough?
2. Check the scores - do they match your intuition about the deal?
3. Look at the evidence - are quotes accurate and relevant?
4. **You're ready to integrate with your CRM**

### If Analysis Was Rejected ❌
1. Read the "Required Fixes" section in the evaluation
2. This usually means:
   - Weak evidence (too many "seems" without quotes)
   - Inflated scores (8/10 with vague evidence)
   - Vague actions ("follow up on metrics")
3. The rejection is PROTECTING your CRM from bad data - this is good
4. Check `examples/rejected-analysis-example.md` to see common failure patterns

---

## Customize for Your Business (Optional)

### Using MEDDPICC Instead?

Edit `prompts/01_context_builder.md` and add:

```markdown
### 8. Paper Process
**Status:** [✅/⚠️/❌]
**Evidence:**
- Contract review steps
- Legal requirements
**Gaps:**
- [ ] Contract timeline unknown

### 9. Implies Pain
**Status:** [✅/⚠️/❌]
**Evidence:**
- Is pain implied by desired solution?
```

Update scorecard from `/70` to `/90` (9 components × 10 points)

### Using Different Stages?

Edit `prompts/03_evaluator.md` and replace:

```markdown
**Discovery** → **Scoping:**
- Identify Pain: ≥5
- Champion: ≥4
```

With your actual CRM stages and requirements.

---

## Troubleshooting

### "ImportError: No module named 'anthropic'"
```bash
pip install anthropic
```

### "API key not found"
Check environment variables:
```bash
echo $ANTHROPIC_API_KEY
```

### "Analysis is too generic"
Your test data might be too simple. Try with a real call transcript that has:
- Specific numbers (budgets, timelines, metrics)
- Direct quotes from buyers
- Named stakeholders with titles

### "Evaluator always rejects"
This is normal during initial testing. Common issues:
- Weak evidence in source material
- Scores don't match evidence quality
- Actions are too vague

Check `examples/approved-analysis-example.md` to see what good looks like.

---

## Cost of This Test

**Tokens used:**
- Context Builder: ~5,000 tokens = $0.001
- Generator: ~10,000 tokens = $0.03
- Evaluator: ~8,000 tokens = $0.024
- **Total: ~$0.055**

For 100 deals with daily calls: ~$33/month

---

## Production Deployment

Once your test works:

1. **Read the full README.md** for production setup
2. **Set up GitHub Actions** using `workflows/nightly-meddicc-analysis.yml`
3. **Integrate with your CRM** to write approved analyses automatically
4. **Add rep rollup queries** from `queries/rep-rollup-analysis.sql`

---

## Support

**Stuck?**
1. Check `examples/` folder for approved/rejected analysis samples
2. Read `README.md` for full documentation
3. Review `rubrics/evaluator-pass-fail-criteria.md` for quality standards

**Remember:** The system is designed to reject bad analyses. If you're getting rejections, that's the quality gate working correctly. Fix the evidence and try again.

---

**Time to first analysis:** 10 minutes ✅
**Cost per test:** $0.055 ✅
**Ready for production?** Read README.md for full deployment guide.
