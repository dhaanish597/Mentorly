-- Curated quizzes, missions and achievement definitions.

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

INSERT INTO weekly_missions (id, title, description, target_count, reward_xp, mission_type, week_key) VALUES
  ('wm-challenges', 'Master the Arena', 'Complete 3 coding challenges with verified tests', 3, 200, 'challenges', 'current'),
  ('wm-quizzes', 'Curious Mind', 'Solve 3 Daily Quizzes of the Day', 3, 150, 'quizzes', 'current'),
  ('wm-xp', 'XP Champion', 'Accumulate 250 total XP across activities', 250, 250, 'xp', 'current');

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
