CREATE TABLE IF NOT EXISTS compliance_rules (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'medium',
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS violations (
  id TEXT PRIMARY KEY,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  rule_id TEXT NOT NULL REFERENCES compliance_rules(id),
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','bot')),
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  actor_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'open',
  assignee_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  description TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (actor_kind='human' AND actor_user_id IS NOT NULL AND actor_bot_id IS NULL)
    OR (actor_kind='bot' AND actor_bot_id IS NOT NULL AND actor_user_id IS NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_violations_interaction_id ON violations(interaction_id);
CREATE INDEX IF NOT EXISTS idx_violations_customer_id ON violations(customer_id);

CREATE TABLE IF NOT EXISTS qa_rubrics (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qa_rubric_sections (
  id TEXT PRIMARY KEY,
  rubric_id TEXT NOT NULL REFERENCES qa_rubrics(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  weight numeric(7,4) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_rubric_sections_rubric_id ON qa_rubric_sections(rubric_id);

CREATE TABLE IF NOT EXISTS qa_rubric_criteria (
  id TEXT PRIMARY KEY,
  section_id TEXT NOT NULL REFERENCES qa_rubric_sections(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  weight numeric(7,4) NOT NULL,
  critical_fail boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_rubric_criteria_section_id ON qa_rubric_criteria(section_id);

CREATE TABLE IF NOT EXISTS qa_scorecards (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL UNIQUE REFERENCES interactions(id) ON DELETE CASCADE,
  rubric_id TEXT NOT NULL REFERENCES qa_rubrics(id),
  subject_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  subject_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  reviewer_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  total_score numeric(6,2),
  band TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_scorecards_interaction_id ON qa_scorecards(interaction_id);

CREATE TABLE IF NOT EXISTS qa_scorecard_entries (
  id TEXT PRIMARY KEY,
  scorecard_id TEXT NOT NULL REFERENCES qa_scorecards(id) ON DELETE CASCADE,
  criterion_id TEXT NOT NULL REFERENCES qa_rubric_criteria(id),
  ai_suggested_score numeric(6,2),
  final_score numeric(6,2),
  note TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_scorecard_entries_scorecard_id ON qa_scorecard_entries(scorecard_id);

CREATE TABLE IF NOT EXISTS coaching_actions (
  id TEXT PRIMARY KEY,
  subject_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  subject_bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
  scorecard_id TEXT REFERENCES qa_scorecards(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  due_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS calibration_sessions (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
  rubric_id TEXT NOT NULL REFERENCES qa_rubrics(id),
  status TEXT NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS calibration_reviewer_scores (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES calibration_sessions(id) ON DELETE CASCADE,
  reviewer_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  scores jsonb NOT NULL DEFAULT '{}'::jsonb,
  notes TEXT,
  variance_from_target numeric(6,2),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

