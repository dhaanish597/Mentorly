import { DailyGoal, UserStreak, WeeklyMission } from '../services/gamificationApi';
import { Icon } from './HorizonVisuals';

interface DailyGoalsAndMissionsProps {
  goal: DailyGoal;
  streak: UserStreak;
  missions: WeeklyMission[];
}

export function DailyGoalsAndMissions({ goal, streak, missions }: DailyGoalsAndMissionsProps) {
  // SVG Ring calculation: circumference = 2 * PI * r = 2 * 3.14159 * 36 = 226.2
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const clampedPct = Math.min(100, Math.max(0, goal.percentage));
  const strokeDashoffset = circumference - (clampedPct / 100) * circumference;

  return (
    <article className="gamified-card">
      <div className="gamified-card-header">
        <h3>
          <Icon name="target" /> Daily Goal & Missions
        </h3>
        <span className="streak-counter-pill">
          <Icon name="flame" /> {streak.current_streak} Day Streak
        </span>
      </div>

      <div className="daily-goal-content">
        <div className="goal-ring-container">
          <svg className="goal-ring-svg" viewBox="0 0 88 88" aria-hidden="true">
            <circle
              className="goal-ring-bg"
              cx="44"
              cy="44"
              r={radius}
              fill="transparent"
              strokeWidth="7"
            />
            <circle
              className="goal-ring-progress"
              cx="44"
              cy="44"
              r={radius}
              fill="transparent"
              strokeWidth="7"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
            />
          </svg>
          <div className="goal-ring-label">
            <span>{clampedPct}%</span>
            <span className="goal-ring-sublabel">Goal</span>
          </div>
        </div>

        <div className="goal-details">
          <h4>{goal.completed ? 'Daily Goal Achieved! 🎯' : `${goal.current_xp} / ${goal.target_xp} XP Today`}</h4>
          <p>
            {goal.completed
              ? 'Awesome work! You earned your 100 daily XP. Keep the momentum going.'
              : `Earn ${goal.target_xp - goal.current_xp} more XP by completing quizzes or coding challenges.`}
          </p>
          <div style={{ marginTop: '10px' }}>
            <a
              href="/library"
              className="daily-mini-challenge-btn"
            >
              <Icon name="zap" /> Start 2-Min Mini Challenge
            </a>
          </div>
        </div>
      </div>

      <div className="weekly-missions-list">
        <div className="missions-section-title">
          Weekly Missions
        </div>
        {missions.map(mission => {
          const pct = Math.min(100, Math.round((mission.current_count / mission.target_count) * 100));
          return (
            <div key={mission.id} className="mission-item">
              <div className="mission-header">
                <span className="mission-title">{mission.title}</span>
                <span className="mission-reward">+{mission.reward_xp} XP</span>
              </div>
              <div className="mission-desc">{mission.description}</div>
              <div className="mission-progress-bar">
                <div
                  className={`mission-progress-fill ${mission.completed ? 'done' : ''}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}
