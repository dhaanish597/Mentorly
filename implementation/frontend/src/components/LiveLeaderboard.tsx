import { useEffect, useState } from 'react';
import { LeaderboardEntry, gamificationApi } from '../services/gamificationApi';
import { Icon } from './HorizonVisuals';

interface LiveLeaderboardProps {
  initialLeaderboard: LeaderboardEntry[];
  userRank?: LeaderboardEntry;
  userId?: string;
}

export function LiveLeaderboard({ initialLeaderboard, userRank, userId }: LiveLeaderboardProps) {
  const [period, setPeriod] = useState<'daily' | 'weekly' | 'all_time'>('all_time');
  const [rankings, setRankings] = useState<LeaderboardEntry[]>(initialLeaderboard);
  const [currentUserRank, setCurrentUserRank] = useState<LeaderboardEntry | undefined>(userRank);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    if (period !== 'all_time') {
      setLoading(true);
      gamificationApi
        .getLeaderboard(period, userId)
        .then(res => {
          if (active) {
            setRankings(res.rankings);
            if (res.user_rank) setCurrentUserRank(res.user_rank);
          }
        })
        .catch(err => console.error('Failed to load leaderboard', err))
        .finally(() => {
          if (active) setLoading(false);
        });
    } else {
      setRankings(initialLeaderboard);
      if (userRank) setCurrentUserRank(userRank);
    }
    return () => {
      active = false;
    };
  }, [period, initialLeaderboard, userRank, userId]);

  return (
    <article className="gamified-card">
      <div className="gamified-card-header">
        <h3>
          <Icon name="award" /> Live Leaderboard
        </h3>
        <div className="leaderboard-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={period === 'daily'}
            className={`leaderboard-tab-btn ${period === 'daily' ? 'active' : ''}`}
            onClick={() => setPeriod('daily')}
          >
            Daily
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={period === 'weekly'}
            className={`leaderboard-tab-btn ${period === 'weekly' ? 'active' : ''}`}
            onClick={() => setPeriod('weekly')}
          >
            Weekly
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={period === 'all_time'}
            className={`leaderboard-tab-btn ${period === 'all_time' ? 'active' : ''}`}
            onClick={() => setPeriod('all_time')}
          >
            All-Time
          </button>
        </div>
      </div>

      {loading ? (
        <p className="quiet-empty">Updating standings…</p>
      ) : (
        <div className="leaderboard-list">
          {rankings.map(row => {
            const isTop3 = row.rank <= 3;
            const rankClass = isTop3 ? `rank-${row.rank}` : '';
            return (
              <div
                key={row.user_id}
                className={`leaderboard-row ${row.is_current_user ? 'is-current' : ''}`}
              >
                <span className={`leaderboard-rank ${rankClass}`}>{row.rank}</span>
                <span className="leaderboard-avatar">{row.avatar_initials}</span>
                <span className="leaderboard-name">
                  {row.display_name} {row.is_current_user && '(You)'}
                </span>
                <span className="leaderboard-streak" title={`${row.streak} day streak`}>
                  <Icon name="flame" /> {row.streak}d
                </span>
                <span className="leaderboard-xp">{row.total_xp} XP</span>
              </div>
            );
          })}

          {currentUserRank && !rankings.some(r => r.is_current_user) && (
            <div
              className="leaderboard-row is-current"
              style={{ marginTop: '6px', borderTop: '2px dashed #ffc4ba' }}
            >
              <span className="leaderboard-rank">#{currentUserRank.rank}</span>
              <span className="leaderboard-avatar">{currentUserRank.avatar_initials}</span>
              <span className="leaderboard-name">{currentUserRank.display_name} (You)</span>
              <span className="leaderboard-streak">
                <Icon name="flame" /> {currentUserRank.streak}d
              </span>
              <span className="leaderboard-xp">{currentUserRank.total_xp} XP</span>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
