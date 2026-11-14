/**
 * Gamification API service for daily quizzes, leaderboards, goals, missions, and graphs.
 */

export interface DailyQuizAttempt {
  selected_option_index: number;
  is_correct: boolean;
  xp_awarded: number;
  correct_option_index?: number;
}

export interface DailyQuiz {
  id: string;
  date: string;
  category: string;
  difficulty: string;
  question: string;
  options: string[];
  xp_reward: number;
  completed: boolean;
  user_attempt?: DailyQuizAttempt;
  explanation?: string;
  correct_option_index?: number;
}

export interface UserStreak {
  current_streak: number;
  max_streak: number;
}

export interface DailyGoal {
  date: string;
  target_xp: number;
  current_xp: number;
  completed: boolean;
  percentage: number;
}

export interface WeeklyMission {
  id: string;
  title: string;
  description: string;
  target_count: number;
  current_count: number;
  reward_xp: number;
  completed: boolean;
}

export interface LeaderboardEntry {
  rank: number;
  user_id: string;
  display_name: string;
  avatar_initials: string;
  total_xp: number;
  streak: number;
  is_current_user: boolean;
}

export interface LeaderboardResponse {
  period: 'daily' | 'weekly' | 'all_time';
  rankings: LeaderboardEntry[];
  user_rank?: LeaderboardEntry;
}

export interface WeeklyXpPoint {
  day: string;
  date: string;
  xp: number;
}

export interface LearningActivityPoint {
  day: string;
  date: string;
  attempted: number;
  completed: number;
}

export interface QuizAccuracyStats {
  total: number;
  correct: number;
  accuracy_pct: number;
}

export interface CourseProgressStat {
  course: string;
  slug: string;
  progress_pct: number;
  completed_count: number;
  total_count: number;
  teacher: string;
}

export interface SkillPerformanceStat {
  skill: string;
  score: number;
}

export interface DashboardGraphs {
  weekly_xp: WeeklyXpPoint[];
  learning_activity: LearningActivityPoint[];
  quiz_accuracy: QuizAccuracyStats;
  course_progress: CourseProgressStat[];
  skill_performance: SkillPerformanceStat[];
}

export interface AchievementItem {
  slug: string;
  title: string;
  description: string;
  icon: string;
  category: string;
  xp_reward: number;
  unlocked: boolean;
  unlocked_at: string | null;
}

export interface SmartRecommendation {
  id: string;
  title: string;
  subject: string;
  reason: string;
  url: string;
  level: string;
  difficulty: string;
}

export interface DashboardGamificationData {
  daily_quiz: DailyQuiz | null;
  countdown_seconds: number;
  user_streak: UserStreak;
  daily_goal: DailyGoal;
  weekly_missions: WeeklyMission[];
  leaderboard: LeaderboardEntry[];
  user_rank?: LeaderboardEntry;
  graphs: DashboardGraphs;
  achievements: AchievementItem[];
  recommendations: SmartRecommendation[];
}

export interface QuizSubmissionResponse {
  already_completed: boolean;
  is_correct: boolean;
  correct_option_index: number;
  explanation: string;
  xp_awarded: number;
  message: string;
  streak: number;
  goal_completed: boolean;
  newly_unlocked_badges: string[];
}

export interface LearningPathChallenge {
  id: string;
  title: string;
  difficulty: string;
  xp: number;
}

export interface LearningPathItem {
  id: string;
  title: string;
  slug: string;
  teacher: string;
  teacher_id: string;
  description: string;
  levels_count: number;
  unlocked_level: number;
  xp_reward: number;
  challenges: LearningPathChallenge[];
}

const API_BASE = '/api/v1/gamification';

export const gamificationApi = {
  async getDashboard(userId?: string): Promise<DashboardGamificationData> {
    const url = userId ? `${API_BASE}/dashboard?user_id=${encodeURIComponent(userId)}` : `${API_BASE}/dashboard`;
    const res = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status} fetching gamification dashboard`);
    return res.json();
  },

  async submitQuiz(quizId: string, optionIndex: number, userId?: string): Promise<QuizSubmissionResponse> {
    const res = await fetch(`${API_BASE}/quiz/submit`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        quiz_id: quizId,
        selected_option_index: optionIndex,
        user_id: userId,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} submitting quiz`);
    return res.json();
  },

  async getLeaderboard(period: 'daily' | 'weekly' | 'all_time' = 'all_time', userId?: string): Promise<LeaderboardResponse> {
    const params = new URLSearchParams({ period });
    if (userId) params.set('user_id', userId);
    const res = await fetch(`${API_BASE}/leaderboard?${params.toString()}`, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status} fetching leaderboard`);
    return res.json();
  },

  async getLearningPaths(): Promise<LearningPathItem[]> {
    const res = await fetch(`${API_BASE}/learning-paths`, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status} fetching learning paths`);
    return res.json();
  },
};
