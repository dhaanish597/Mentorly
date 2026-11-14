-- Gamification, Daily Quizzes, Leaderboards, Goals, Missions, and Badges

CREATE TABLE daily_quizzes (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  category TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  question TEXT NOT NULL,
  options_json TEXT NOT NULL,
  correct_option_index INTEGER NOT NULL,
  explanation TEXT NOT NULL,
  xp_reward INTEGER NOT NULL DEFAULT 50,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_daily_quizzes_date ON daily_quizzes(date);

CREATE TABLE daily_quiz_attempts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  quiz_id TEXT NOT NULL REFERENCES daily_quizzes(id) ON DELETE CASCADE,
  selected_option_index INTEGER NOT NULL,
  is_correct INTEGER NOT NULL,
  xp_awarded INTEGER NOT NULL DEFAULT 0,
  attempted_at TEXT NOT NULL,
  UNIQUE(user_id, quiz_id)
);
CREATE INDEX idx_daily_quiz_attempts_user ON daily_quiz_attempts(user_id);

CREATE TABLE user_xp_ledger (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  amount INTEGER NOT NULL,
  reason TEXT NOT NULL,
  reference_id TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_user_xp_ledger_user ON user_xp_ledger(user_id);

CREATE TABLE user_streaks (
  user_id TEXT PRIMARY KEY,
  current_streak INTEGER NOT NULL DEFAULT 1,
  max_streak INTEGER NOT NULL DEFAULT 1,
  last_activity_date TEXT NOT NULL
);

CREATE TABLE user_goals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  date TEXT NOT NULL,
  target_xp INTEGER NOT NULL DEFAULT 100,
  current_xp INTEGER NOT NULL DEFAULT 0,
  completed INTEGER NOT NULL DEFAULT 0,
  UNIQUE(user_id, date)
);

CREATE TABLE weekly_missions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  target_count INTEGER NOT NULL,
  reward_xp INTEGER NOT NULL DEFAULT 150,
  mission_type TEXT NOT NULL,
  week_key TEXT NOT NULL
);

CREATE TABLE user_mission_progress (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  mission_id TEXT NOT NULL REFERENCES weekly_missions(id) ON DELETE CASCADE,
  current_count INTEGER NOT NULL DEFAULT 0,
  completed INTEGER NOT NULL DEFAULT 0,
  completed_at TEXT,
  UNIQUE(user_id, mission_id)
);

CREATE TABLE achievements (
  slug TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  icon TEXT NOT NULL,
  category TEXT NOT NULL,
  xp_reward INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE user_achievements (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  achievement_slug TEXT NOT NULL REFERENCES achievements(slug) ON DELETE CASCADE,
  unlocked_at TEXT NOT NULL,
  UNIQUE(user_id, achievement_slug)
);

CREATE TABLE user_profiles (
  user_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  avatar_initials TEXT NOT NULL,
  total_xp INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

-- Seed achievements definitions
INSERT INTO achievements (slug, title, description, icon, category, xp_reward) VALUES
  ('first_challenge', 'First Challenge', 'Completed your very first coding challenge', 'rocket', 'DSA', 100),
  ('logic_explorer', 'Logic Explorer', 'Successfully predicted the outcome of a complex algorithm', 'compass', 'Reasoning', 100),
  ('bug_hunter', 'Bug Hunter', 'Identified and repaired a failing edge case in Python', 'shield', 'Debugging', 100),
  ('voice_champion', 'Voice Champion', 'Explained your code rationale using voice input', 'mic', 'Communication', 150),
  ('consistency_master', 'Consistency Master', 'Maintained a 3-day learning streak', 'flame', 'Consistency', 200),
  ('daily_quiz_master', 'Daily Quiz Master', 'Answered 3 daily quizzes correctly', 'award', 'Quizzes', 150),
  ('weekly_warrior', 'Weekly Warrior', 'Completed all weekly missions for the week', 'zap', 'Missions', 250),
  ('problem_solver', 'Problem Solver', 'Completed 5 challenges across multiple topics', 'star', 'Mastery', 200),
  ('edge_case_expert', 'Edge Case Expert', 'Handled negative numbers and boundary invariants', 'target', 'Testing', 150),
  ('complexity_analyst', 'Complexity Analyst', 'Defended time and space complexity with your mentor', 'clock', 'Analysis', 150);

-- Seed active weekly missions
INSERT INTO weekly_missions (id, title, description, target_count, reward_xp, mission_type, week_key) VALUES
  ('wm-challenges', 'Master the Arena', 'Complete 3 coding challenges with verified tests', 3, 200, 'challenges', 'current'),
  ('wm-quizzes', 'Curious Mind', 'Solve 3 Daily Quizzes of the Day', 3, 150, 'quizzes', 'current'),
  ('wm-xp', 'XP Champion', 'Accumulate 250 total XP across activities', 250, 250, 'xp', 'current');

-- Seed peer learners for live leaderboard competition
INSERT INTO user_profiles (user_id, display_name, avatar_initials, total_xp, created_at) VALUES
  ('usr-peer-1', 'Aarav Sharma', 'AS', 1450, '2026-11-01T00:00:00Z'),
  ('usr-peer-2', 'Priya Patel', 'PP', 1280, '2026-11-01T00:00:00Z'),
  ('usr-peer-3', 'Vikram Rao', 'VR', 1150, '2026-11-01T00:00:00Z'),
  ('usr-peer-4', 'Ananya Iyer', 'AI', 980, '2026-11-01T00:00:00Z'),
  ('usr-peer-5', 'Rohan Gupta', 'RG', 850, '2026-11-01T00:00:00Z'),
  ('usr-peer-6', 'Sneha Reddy', 'SR', 720, '2026-11-01T00:00:00Z'),
  ('usr-peer-7', 'Karthik Nair', 'KN', 640, '2026-11-01T00:00:00Z'),
  ('usr-peer-8', 'Meera Joshi', 'MJ', 550, '2026-11-01T00:00:00Z'),
  ('usr-peer-9', 'Devendra Sen', 'DS', 480, '2026-11-01T00:00:00Z');

-- Initial XP transactions for peer learners (for daily and weekly leaderboard filters)
INSERT INTO user_xp_ledger (id, user_id, amount, reason, reference_id, created_at) VALUES
  ('xpl-1', 'usr-peer-1', 150, 'challenge', 'ex1', '2026-11-14T10:00:00Z'),
  ('xpl-2', 'usr-peer-2', 100, 'challenge', 'ex2', '2026-11-14T11:00:00Z'),
  ('xpl-3', 'usr-peer-3', 120, 'quiz', 'q1', '2026-11-14T12:00:00Z'),
  ('xpl-4', 'usr-peer-4', 90, 'challenge', 'ex3', '2026-11-14T09:00:00Z'),
  ('xpl-5', 'usr-peer-5', 80, 'quiz', 'q1', '2026-11-14T08:00:00Z'),
  ('xpl-6', 'usr-peer-1', 400, 'weekly_missions', 'wm-all', '2026-11-12T10:00:00Z'),
  ('xpl-7', 'usr-peer-2', 350, 'challenges', 'ex-batch', '2026-11-11T12:00:00Z'),
  ('xpl-8', 'usr-peer-3', 300, 'challenges', 'ex-batch', '2026-11-13T14:00:00Z');

-- Curated rotating Daily Quizzes
INSERT INTO daily_quizzes (id, date, category, difficulty, question, options_json, correct_option_index, explanation, xp_reward, created_at) VALUES
  ('quiz-2026-11-14', '2026-11-14', 'dsa', 'medium',
   'In a sliding window algorithm finding the minimum subarray length with sum >= target, what ensures the left pointer can only move forward without backtracking?',
   '["All array elements are strictly positive, ensuring monotonic prefix sums", "The array is pre-sorted in ascending order", "The window size is fixed at compile-time", "A hash map records previously visited indices"]',
   0,
   'When all array elements are strictly positive, expanding the right pointer monotonically increases the window sum, and contracting the left pointer monotonically decreases it. This monotonic property guarantees the left pointer never needs to backtrack, preserving an O(N) linear time bound.',
   50, '2026-11-14T00:00:00Z'),

  ('quiz-2026-11-15', '2026-11-15', 'system_design', 'medium',
   'When designing an API rate limiter for a distributed cluster, which Redis data structure or algorithm best prevents burst traffic at window boundaries with minimal memory?',
   '["Fixed Window Counter", "Sliding Window Log", "Token Bucket or Sliding Window Counter", "Least Recently Used (LRU) Cache"]',
   2,
   'The Sliding Window Counter or Token Bucket balances boundary smoothness with O(1) memory overhead. Fixed window suffers from 2x boundary spikes, while sliding window log consumes unbounded memory per request timestamp.',
   50, '2026-11-14T00:00:00Z'),

  ('quiz-2026-11-16', '2026-11-16', 'cs_fundamentals', 'easy',
   'Which condition is NOT one of Coffman''s four necessary conditions for a deadlock to occur in an operating system?',
   '["Mutual Exclusion", "Hold and Wait", "Preemption Allowed", "Circular Wait"]',
   2,
   'The four Coffman conditions are Mutual Exclusion, Hold and Wait, No Preemption, and Circular Wait. If preemption IS allowed (resources can be forcibly confiscated), deadlocks cannot persist.',
   50, '2026-11-14T00:00:00Z'),

  ('quiz-2026-11-17', '2026-11-17', 'aptitude', 'medium',
   'A train traveling at 72 km/h crosses a 200m long platform in 22 seconds. What is the length of the train?',
   '["240 meters", "220 meters", "200 meters", "260 meters"]',
   0,
   '72 km/h = 72 * (5/18) = 20 m/s. In 22 seconds, total distance covered = 20 * 22 = 440m. Total distance = Length of train + Length of platform = L + 200m = 440m. Therefore, Length of train L = 240m.',
   50, '2026-11-14T00:00:00Z'),

  ('quiz-2026-11-18', '2026-11-18', 'dsa', 'hard',
   'What is the worst-case space complexity of QuickSort when implemented with tail-call optimization on the smaller partition?',
   '["O(N)", "O(log N)", "O(1)", "O(N log N)"]',
   1,
   'By always recurring on the smaller partition first and using a loop for the larger partition, the maximum call stack depth is strictly bounded by O(log N), preventing worst-case O(N) recursion depth.',
   50, '2026-11-14T00:00:00Z'),

  ('quiz-2026-11-19', '2026-11-19', 'cs_fundamentals', 'medium',
   'In relational databases, which ACID property is directly guaranteed by write-ahead logging (WAL) even in the event of an abrupt power failure?',
   '["Atomicity and Durability", "Isolation and Consistency", "Only Consistency", "Only Isolation"]',
   0,
   'Write-Ahead Logging (WAL) ensures all changes are logged sequentially to non-volatile disk before modifying data pages. On crash recovery, uncommitted transactions are rolled back (Atomicity) and committed transactions are redone (Durability).',
   50, '2026-11-14T00:00:00Z'),

  ('quiz-2026-11-20', '2026-11-20', 'system_design', 'hard',
   'Under the CAP theorem, which database trade-off is chosen during a network partition if a distributed system chooses Availability over Consistency (AP)?',
   '["Nodes reject writes to ensure all reads return the latest data", "Every non-failing node returns a response, but data may be stale or conflicting", "Transactions block until all nodes acknowledge replication", "The database automatically switches to single-leader synchronous replication"]',
   1,
   'In an AP system under network partition, nodes continue serving read and write requests independently to maintain availability, sacrificing linearizable consistency and resolving conflicts asynchronously (e.g. DynamoDB, Cassandra).',
   50, '2026-11-14T00:00:00Z');
