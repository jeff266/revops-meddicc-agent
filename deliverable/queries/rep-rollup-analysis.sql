-- Rep Rollup Analysis: Aggregate MEDDICC Performance Across Book of Business
--
-- Purpose: Identify coaching opportunities by analyzing a rep's MEDDICC patterns
-- across all their active deals, not just individual calls.
--
-- This enables "Level 3" coaching:
-- - Level 1: Fix this one call
-- - Level 2: Fix this one deal
-- - Level 3: Fix this rep's systematic gaps
--
-- Assumptions:
-- - MEDDICC analyses are stored in a table with deal_id and component scores
-- - Deal ownership tracked in CRM
-- - Component scores range 0-10
-- - You adapt column names to match your schema

-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE STRUCTURE (Customize to Your Schema)
-- ─────────────────────────────────────────────────────────────────────────────

-- CREATE TABLE meddicc_analyses (
--   analysis_id TEXT PRIMARY KEY,
--   deal_id TEXT NOT NULL,
--   analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
--
--   -- Component Scores (0-10)
--   metrics_score INT,
--   economic_buyer_score INT,
--   decision_criteria_score INT,
--   decision_process_score INT,
--   identify_pain_score INT,
--   champion_score INT,
--   competition_score INT,
--
--   -- Overall Assessment
--   total_score INT,          -- Sum of all component scores (/70)
--   deal_health TEXT,         -- 'Strong' | 'At Risk' | 'Stalled'
--
--   -- Deal Context
--   deal_stage TEXT,
--   arr DECIMAL,
--   close_date DATE,
--   owner_email TEXT
-- );

-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 1: Rep Summary Card
-- ─────────────────────────────────────────────────────────────────────────────
-- Shows each rep's overall MEDDICC performance

SELECT
  owner_email AS rep,
  COUNT(DISTINCT deal_id) AS active_deals,

  -- Overall Health Distribution
  SUM(CASE WHEN deal_health = 'Strong' THEN 1 ELSE 0 END) AS strong_deals,
  SUM(CASE WHEN deal_health = 'At Risk' THEN 1 ELSE 0 END) AS at_risk_deals,
  SUM(CASE WHEN deal_health = 'Stalled' THEN 1 ELSE 0 END) AS stalled_deals,

  -- Average Component Scores
  ROUND(AVG(metrics_score), 1) AS avg_metrics,
  ROUND(AVG(economic_buyer_score), 1) AS avg_economic_buyer,
  ROUND(AVG(decision_criteria_score), 1) AS avg_decision_criteria,
  ROUND(AVG(decision_process_score), 1) AS avg_decision_process,
  ROUND(AVG(identify_pain_score), 1) AS avg_identify_pain,
  ROUND(AVG(champion_score), 1) AS avg_champion,
  ROUND(AVG(competition_score), 1) AS avg_competition,

  -- Overall Average
  ROUND(AVG(total_score), 1) AS avg_total_score,

  -- Weighted Pipeline (only Strong deals)
  SUM(CASE WHEN deal_health = 'Strong' THEN arr ELSE 0 END) AS qualified_pipeline

FROM meddicc_analyses
WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)  -- Last 30 days
GROUP BY owner_email
ORDER BY avg_total_score DESC;

-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 2: Rep Weakness Detection
-- ─────────────────────────────────────────────────────────────────────────────
-- Identifies which MEDDICC components a rep consistently struggles with

WITH rep_component_scores AS (
  SELECT
    owner_email,
    'Metrics' AS component,
    AVG(metrics_score) AS avg_score
  FROM meddicc_analyses
  WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  GROUP BY owner_email

  UNION ALL

  SELECT
    owner_email,
    'Economic Buyer' AS component,
    AVG(economic_buyer_score) AS avg_score
  FROM meddicc_analyses
  WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  GROUP BY owner_email

  UNION ALL

  SELECT
    owner_email,
    'Decision Criteria' AS component,
    AVG(decision_criteria_score) AS avg_score
  FROM meddicc_analyses
  WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  GROUP BY owner_email

  UNION ALL

  SELECT
    owner_email,
    'Decision Process' AS component,
    AVG(decision_process_score) AS avg_score
  FROM meddicc_analyses
  WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  GROUP BY owner_email

  UNION ALL

  SELECT
    owner_email,
    'Identify Pain' AS component,
    AVG(identify_pain_score) AS avg_score
  FROM meddicc_analyses
  WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  GROUP BY owner_email

  UNION ALL

  SELECT
    owner_email,
    'Champion' AS component,
    AVG(champion_score) AS avg_score
  FROM meddicc_analyses
  WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  GROUP BY owner_email

  UNION ALL

  SELECT
    owner_email,
    'Competition' AS component,
    AVG(competition_score) AS avg_score
  FROM meddicc_analyses
  WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  GROUP BY owner_email
),

team_averages AS (
  SELECT
    component,
    AVG(avg_score) AS team_avg
  FROM rep_component_scores
  GROUP BY component
)

SELECT
  r.owner_email AS rep,
  r.component,
  ROUND(r.avg_score, 1) AS rep_avg,
  ROUND(t.team_avg, 1) AS team_avg,
  ROUND(r.avg_score - t.team_avg, 1) AS gap_from_team,
  CASE
    WHEN r.avg_score < 5 THEN '🔴 Critical'
    WHEN r.avg_score < 6 THEN '🟡 Below Bar'
    WHEN r.avg_score < t.team_avg THEN '⚠️ Below Team'
    ELSE '✅ Strong'
  END AS performance
FROM rep_component_scores r
JOIN team_averages t ON r.component = t.component
WHERE r.avg_score < t.team_avg  -- Only show below-team components
ORDER BY r.owner_email, r.avg_score ASC;

-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 3: Coaching Focus for Specific Rep
-- ─────────────────────────────────────────────────────────────────────────────
-- Deep dive into one rep's patterns with specific deal examples

WITH rep_deals AS (
  SELECT *
  FROM meddicc_analyses
  WHERE owner_email = 'sarah.johnson@company.com'  -- Replace with target rep
    AND analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
),

component_analysis AS (
  SELECT
    'Metrics' AS component,
    AVG(metrics_score) AS avg_score,
    COUNT(CASE WHEN metrics_score < 5 THEN 1 END) AS weak_deals,
    COUNT(*) AS total_deals
  FROM rep_deals

  UNION ALL

  SELECT
    'Economic Buyer',
    AVG(economic_buyer_score),
    COUNT(CASE WHEN economic_buyer_score < 5 THEN 1 END),
    COUNT(*)
  FROM rep_deals

  UNION ALL

  SELECT
    'Decision Criteria',
    AVG(decision_criteria_score),
    COUNT(CASE WHEN decision_criteria_score < 5 THEN 1 END),
    COUNT(*)
  FROM rep_deals

  UNION ALL

  SELECT
    'Decision Process',
    AVG(decision_process_score),
    COUNT(CASE WHEN decision_process_score < 5 THEN 1 END),
    COUNT(*)
  FROM rep_deals

  UNION ALL

  SELECT
    'Identify Pain',
    AVG(identify_pain_score),
    COUNT(CASE WHEN identify_pain_score < 5 THEN 1 END),
    COUNT(*)
  FROM rep_deals

  UNION ALL

  SELECT
    'Champion',
    AVG(champion_score),
    COUNT(CASE WHEN champion_score < 5 THEN 1 END),
    COUNT(*)
  FROM rep_deals

  UNION ALL

  SELECT
    'Competition',
    AVG(competition_score),
    COUNT(CASE WHEN competition_score < 5 THEN 1 END),
    COUNT(*)
  FROM rep_deals
)

SELECT
  component,
  ROUND(avg_score, 1) AS avg_score,
  weak_deals,
  total_deals,
  ROUND(100.0 * weak_deals / total_deals, 0) AS pct_weak,
  CASE
    WHEN avg_score < 5 THEN '🔴 Primary Coaching Focus'
    WHEN weak_deals > total_deals / 2 THEN '🟡 Secondary Focus'
    ELSE '✅ Strength'
  END AS coaching_priority
FROM component_analysis
ORDER BY avg_score ASC;

-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 4: Specific Deal Examples for Coaching
-- ─────────────────────────────────────────────────────────────────────────────
-- Shows actual deals where rep is weak on a specific component

SELECT
  deal_id,
  deal_stage,
  arr,
  close_date,
  champion_score,  -- Replace with target component
  deal_health,
  analyzed_at
FROM meddicc_analyses
WHERE owner_email = 'sarah.johnson@company.com'  -- Replace with target rep
  AND champion_score < 5  -- Replace 'champion_score' with weak component
  AND analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
ORDER BY arr DESC  -- Prioritize high-value deals
LIMIT 10;

-- Use these deal_ids to pull full MEDDICC analyses for coaching sessions

-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 5: Rep Performance Trends Over Time
-- ─────────────────────────────────────────────────────────────────────────────
-- Track if coaching is working by showing component score trends

WITH weekly_scores AS (
  SELECT
    owner_email,
    DATE_TRUNC('week', analyzed_at) AS week,
    AVG(metrics_score) AS metrics,
    AVG(economic_buyer_score) AS economic_buyer,
    AVG(decision_criteria_score) AS decision_criteria,
    AVG(decision_process_score) AS decision_process,
    AVG(identify_pain_score) AS identify_pain,
    AVG(champion_score) AS champion,
    AVG(competition_score) AS competition,
    AVG(total_score) AS total
  FROM meddicc_analyses
  WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 90 DAY)
  GROUP BY owner_email, DATE_TRUNC('week', analyzed_at)
)

SELECT
  owner_email AS rep,
  week,
  ROUND(metrics, 1) AS metrics,
  ROUND(economic_buyer, 1) AS economic_buyer,
  ROUND(decision_criteria, 1) AS decision_criteria,
  ROUND(decision_process, 1) AS decision_process,
  ROUND(identify_pain, 1) AS identify_pain,
  ROUND(champion, 1) AS champion,
  ROUND(competition, 1) AS competition,
  ROUND(total, 1) AS total_score
FROM weekly_scores
WHERE owner_email = 'sarah.johnson@company.com'  -- Replace with target rep
ORDER BY week DESC;

-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 6: Team Leaderboard (for Manager View)
-- ─────────────────────────────────────────────────────────────────────────────
-- Rank reps by MEDDICC execution quality

SELECT
  owner_email AS rep,
  COUNT(DISTINCT deal_id) AS active_deals,
  ROUND(AVG(total_score), 1) AS avg_total_score,

  -- Quality metrics
  ROUND(100.0 * SUM(CASE WHEN deal_health = 'Strong' THEN 1 ELSE 0 END) / COUNT(*), 0) AS pct_strong,
  ROUND(100.0 * SUM(CASE WHEN total_score >= 42 THEN 1 ELSE 0 END) / COUNT(*), 0) AS pct_qualified,  -- 42/70 = 60%

  -- Qualified pipeline
  SUM(CASE WHEN deal_health = 'Strong' THEN arr ELSE 0 END) AS qualified_arr,

  -- Most common weakness
  CASE
    WHEN AVG(metrics_score) = LEAST(AVG(metrics_score), AVG(economic_buyer_score), AVG(decision_criteria_score),
                                     AVG(decision_process_score), AVG(identify_pain_score), AVG(champion_score), AVG(competition_score))
      THEN 'Metrics'
    WHEN AVG(economic_buyer_score) = LEAST(AVG(metrics_score), AVG(economic_buyer_score), AVG(decision_criteria_score),
                                             AVG(decision_process_score), AVG(identify_pain_score), AVG(champion_score), AVG(competition_score))
      THEN 'Economic Buyer'
    WHEN AVG(decision_criteria_score) = LEAST(AVG(metrics_score), AVG(economic_buyer_score), AVG(decision_criteria_score),
                                                AVG(decision_process_score), AVG(identify_pain_score), AVG(champion_score), AVG(competition_score))
      THEN 'Decision Criteria'
    WHEN AVG(decision_process_score) = LEAST(AVG(metrics_score), AVG(economic_buyer_score), AVG(decision_criteria_score),
                                               AVG(decision_process_score), AVG(identify_pain_score), AVG(champion_score), AVG(competition_score))
      THEN 'Decision Process'
    WHEN AVG(identify_pain_score) = LEAST(AVG(metrics_score), AVG(economic_buyer_score), AVG(decision_criteria_score),
                                            AVG(decision_process_score), AVG(identify_pain_score), AVG(champion_score), AVG(competition_score))
      THEN 'Identify Pain'
    WHEN AVG(champion_score) = LEAST(AVG(metrics_score), AVG(economic_buyer_score), AVG(decision_criteria_score),
                                       AVG(decision_process_score), AVG(identify_pain_score), AVG(champion_score), AVG(competition_score))
      THEN 'Champion'
    ELSE 'Competition'
  END AS weakest_component

FROM meddicc_analyses
WHERE analyzed_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
GROUP BY owner_email
HAVING COUNT(DISTINCT deal_id) >= 5  -- Only reps with 5+ active deals
ORDER BY avg_total_score DESC;

-- ─────────────────────────────────────────────────────────────────────────────
-- CUSTOMIZATION GUIDE
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. TABLE NAMES
--    Replace 'meddicc_analyses' with your actual table name
--    If you store analyses in CRM custom fields, adapt JOIN logic

-- 2. COLUMN NAMES
--    Update component score column names to match your schema:
--    - metrics_score → your_metrics_field
--    - economic_buyer_score → your_eb_field
--    etc.

-- 3. DATE RANGE
--    Change 'DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)' to match your review cadence:
--    - Weekly 1:1s: 7 days
--    - Monthly reviews: 30 days
--    - Quarterly reviews: 90 days

-- 4. THRESHOLDS
--    Adjust score thresholds based on your standards:
--    - < 5 = weak (default)
--    - >= 42/70 = 60% qualified (default)
--    - Change to match your qualification bar

-- 5. REP IDENTIFIER
--    Replace 'owner_email' with your rep identifier:
--    - owner_id (if using IDs)
--    - rep_name (if using names)

-- 6. FOR MEDDPICC
--    Add paper_process_score to all queries:
--    - Add to SELECT avg calculations
--    - Add to UNION ALL in component_analysis
--    - Update total_score denominator to /90 instead of /70

-- ─────────────────────────────────────────────────────────────────────────────
-- USAGE EXAMPLES
-- ─────────────────────────────────────────────────────────────────────────────

-- Weekly 1:1 Prep:
-- 1. Run Query 3 (Coaching Focus) for the rep
-- 2. Run Query 4 (Deal Examples) for their weakest component
-- 3. Pull 2-3 call transcripts from those deals
-- 4. Review evidence quality for that component

-- Monthly Team Review:
-- 1. Run Query 6 (Team Leaderboard)
-- 2. Run Query 2 (Weakness Detection) to find team patterns
-- 3. Design training on most common weak component

-- Quarterly Rep Assessment:
-- 1. Run Query 5 (Trends) to see 90-day progression
-- 2. Compare to Query 1 (Summary Card) from previous quarter
-- 3. Assess if coaching is working

-- ─────────────────────────────────────────────────────────────────────────────
-- PYTHON ALTERNATIVE (if not using SQL database)
-- ─────────────────────────────────────────────────────────────────────────────

-- If you're storing analyses in files (memory/deals/), use this Python pattern:

"""
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

def load_all_analyses():
    analyses = []
    deals_dir = Path('memory/deals')

    for deal_dir in deals_dir.iterdir():
        if deal_dir.is_dir():
            for analysis_file in deal_dir.glob('analysis_*.json'):
                with open(analysis_file) as f:
                    analyses.append(json.load(f))

    return analyses

def rep_summary(owner_email, days=30):
    analyses = load_all_analyses()
    cutoff = datetime.now() - timedelta(days=days)

    rep_analyses = [
        a for a in analyses
        if a.get('owner_email') == owner_email
        and datetime.fromisoformat(a.get('analyzed_at')) >= cutoff
    ]

    component_scores = defaultdict(list)
    for analysis in rep_analyses:
        for component in ['metrics', 'economic_buyer', 'decision_criteria',
                         'decision_process', 'identify_pain', 'champion', 'competition']:
            score = analysis.get(f'{component}_score')
            if score is not None:
                component_scores[component].append(score)

    summary = {
        'rep': owner_email,
        'active_deals': len(rep_analyses),
        'component_averages': {
            component: round(sum(scores) / len(scores), 1)
            for component, scores in component_scores.items()
        }
    }

    return summary

# Usage:
# rep_summary('sarah.johnson@company.com', days=30)
"""
