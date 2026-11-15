import { Icon, MentorPortrait } from './HorizonVisuals';
import { TEACHER_LIST, TeacherConfig } from '../config/teachers';

interface MeetYourTeachersProps {
  onSelectTeacher?: (teacher: TeacherConfig) => void;
}

export function MeetYourTeachers({ onSelectTeacher }: MeetYourTeachersProps) {
  return (
    <section className="product-section">
      <div className="section-title">
        <h2>Meet Your AI Teachers</h2>
        <span className="section-subtitle">
          Four specialized AI mentors dedicated to each core domain
        </span>
      </div>

      <div className="dashboard-row-grid-4">
        {TEACHER_LIST.map(teacher => (
          <article key={teacher.id} className="teacher-card">
            <div className="teacher-card-portrait-wrap">
              <span className="teacher-badge-pill" style={{ borderLeft: `3px solid ${teacher.accentColor}` }}>
                {teacher.name}
              </span>
              <MentorPortrait teacher={teacher} alt={`Meet ${teacher.name} · ${teacher.subject}`} eager />
            </div>

            <div className="teacher-info">
              <h3>{teacher.name}</h3>
              <div className="teacher-subject">{teacher.subject}</div>
              <p className="teacher-tagline">“{teacher.tagline}”</p>
              <div className="teacher-personality">
                {teacher.personality}
              </div>
            </div>

            <div className="teacher-specialties">
              {teacher.specialties.slice(0, 3).map(spec => (
                <span key={spec} className="specialty-tag">
                  {spec}
                </span>
              ))}
            </div>

            <a
              href={teacher.defaultPath}
              className="teacher-cta-btn"
              onClick={() => onSelectTeacher?.(teacher)}
            >
              Practice with {teacher.name} <Icon name="arrow" />
            </a>
          </article>
        ))}
      </div>
    </section>
  );
}
