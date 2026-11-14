import { useState } from 'react';
import { DashboardGraphs as GraphData } from '../services/gamificationApi';
import { Icon } from './HorizonVisuals';

interface DashboardGraphsProps {
  data: GraphData;
}

export function DashboardGraphs({ data }: DashboardGraphsProps) {
  const [activeTab, setActiveTab] = useState<'xp' | 'activity' | 'courses' | 'skills'>('xp');

  const maxWeeklyXp = Math.max(100, ...data.weekly_xp.map(d => d.xp));
  const maxActivity = Math.max(5, ...data.learning_activity.map(d => Math.max(d.attempted, d.completed)));

  return (
    <article className="gamified-card graphs-container">
      <div className="gamified-card-header">
        <h3>
          <Icon name="award" /> Performance & Analytics
        </h3>
        <div className="graph-tab-bar" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'xp'}
            className={`graph-tab-btn ${activeTab === 'xp' ? 'active' : ''}`}
            onClick={() => setActiveTab('xp')}
          >
            Weekly XP
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'activity'}
            className={`graph-tab-btn ${activeTab === 'activity' ? 'active' : ''}`}
            onClick={() => setActiveTab('activity')}
          >
            Activity
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'courses'}
            className={`graph-tab-btn ${activeTab === 'courses' ? 'active' : ''}`}
            onClick={() => setActiveTab('courses')}
          >
            Course Mastery
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'skills'}
            className={`graph-tab-btn ${activeTab === 'skills' ? 'active' : ''}`}
            onClick={() => setActiveTab('skills')}
          >
            Skill Radar
          </button>
        </div>
      </div>

      <div className="chart-viewport">
        {activeTab === 'xp' && (
          <div className="bar-chart-container" role="img" aria-label="Weekly XP bar chart">
            {data.weekly_xp.map((item, i) => {
              const heightPct = Math.max(6, Math.round((item.xp / maxWeeklyXp) * 100));
              return (
                <div key={i} className="bar-chart-col">
                  <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#ff735c' }}>
                    {item.xp > 0 ? `${item.xp}` : ''}
                  </span>
                  <div
                    className="bar-pill"
                    style={{ height: `${heightPct}%` }}
                    data-tooltip={`${item.day} (${item.date}): ${item.xp} XP`}
                  />
                  <span className="bar-label">{item.day}</span>
                </div>
              );
            })}
          </div>
        )}

        {activeTab === 'activity' && (
          <div className="bar-chart-container" role="img" aria-label="Learning activity chart">
            {data.learning_activity.map((item, i) => {
              const compHeightPct = Math.max(8, Math.round((item.completed / maxActivity) * 100));
              return (
                <div key={i} className="bar-chart-col">
                  <div style={{ display: 'flex', gap: '3px', alignItems: 'flex-end', width: '100%', height: '100%' }}>
                    <div
                      className="bar-pill"
                      style={{ height: `${compHeightPct}%`, background: '#10b981' }}
                      data-tooltip={`${item.day}: ${item.completed} completed challenges`}
                    />
                  </div>
                  <span className="bar-label">{item.day}</span>
                </div>
              );
            })}
          </div>
        )}

        {activeTab === 'courses' && (
          <div className="course-progress-list">
            {data.course_progress.map(cp => {
              const accent =
                cp.slug === 'dsa'
                  ? '#ff735c'
                  : cp.slug === 'aptitude'
                  ? '#10b981'
                  : cp.slug === 'system_design'
                  ? '#8c78b8'
                  : cp.slug === 'cs_fundamentals'
                  ? '#f59e0b'
                  : '#ff735c';
              return (
                <div key={cp.slug} className="course-progress-row">
                  <div className="course-progress-header">
                    <span>{cp.course}</span>
                    <span className="course-progress-teacher">
                      {cp.teacher} • {cp.completed_count}/{cp.total_count} ({cp.progress_pct}%)
                    </span>
                  </div>
                  <div className="course-progress-track">
                    <div
                      className="course-progress-bar"
                      style={{ width: `${cp.progress_pct}%`, background: accent }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {activeTab === 'skills' && (
          <div className="skill-bars-list">
            {data.skill_performance.map(sp => (
              <div key={sp.skill} className="skill-bar-row">
                <div className="skill-bar-header">
                  <span>{sp.skill}</span>
                  <span style={{ fontWeight: 700, color: '#8c78b8' }}>{sp.score}%</span>
                </div>
                <div className="skill-track">
                  <div className="skill-fill" style={{ width: `${sp.score}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
