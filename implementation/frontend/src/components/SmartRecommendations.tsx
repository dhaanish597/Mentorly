import { SmartRecommendation } from '../services/gamificationApi';
import { Icon } from './HorizonVisuals';

interface SmartRecommendationsProps {
  recommendations: SmartRecommendation[];
}

export function SmartRecommendations({ recommendations }: SmartRecommendationsProps) {
  if (!recommendations.length) return null;

  return (
    <section className="product-section">
      <div className="section-title">
        <h2>Smart Recommendations</h2>
        <span className="section-subtitle">
          Personalized next steps chosen by your AI teachers
        </span>
      </div>

      <div className="dashboard-row-grid-2">
        {recommendations.map(rec => (
          <article key={rec.id} className="gamified-card recommendation-card">
            <div className="recommendation-badge-row">
              <span className="quiz-pill recommendation-subject-pill">
                {rec.subject}
              </span>
              <span className="quiz-pill quiz-pill-xp">{rec.difficulty}</span>
            </div>
            <h3 className="recommendation-title">
              {rec.title}
            </h3>
            <p className="recommendation-reason">
              {rec.reason}
            </p>
            <div style={{ marginTop: '10px' }}>
              <a
                href={rec.url}
                className="collection-action"
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
              >
                Start Practice <Icon name="arrow" />
              </a>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
