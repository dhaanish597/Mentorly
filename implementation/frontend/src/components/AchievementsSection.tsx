import { AchievementItem } from '../services/gamificationApi';
import { Icon } from './HorizonVisuals';

interface AchievementsSectionProps {
  achievements: AchievementItem[];
}

export function AchievementsSection({ achievements }: AchievementsSectionProps) {
  const unlockedCount = achievements.filter(a => a.unlocked).length;

  return (
    <article className="gamified-card">
      <div className="gamified-card-header">
        <h3>
          <Icon name="award" /> Achievements & Badges
        </h3>
        <span className="header-badge">
          {unlockedCount} / {achievements.length} Unlocked
        </span>
      </div>

      <div className="achievements-grid">
        {achievements.map(badge => {
          return (
            <div
              key={badge.slug}
              className={`badge-item ${badge.unlocked ? 'unlocked' : 'locked'}`}
              title={`${badge.title}: ${badge.description} (${badge.xp_reward} XP)`}
            >
              <div className="badge-icon-box">
                <Icon name={badge.icon as any} />
              </div>
              <h4 className="badge-title">{badge.title}</h4>
              <span className="badge-category">
                {badge.unlocked ? `+${badge.xp_reward} XP` : 'Locked'}
              </span>
            </div>
          );
        })}
      </div>
    </article>
  );
}
