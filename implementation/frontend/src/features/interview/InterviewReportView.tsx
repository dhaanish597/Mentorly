import type { InterviewReport, Recommendation } from './types';

type ReportProps = { report: InterviewReport; onRecommendation?: (recommendation: Recommendation) => void };
export function InterviewReportView({ report, onRecommendation }: ReportProps): JSX.Element {
  return <section className="interview-report" aria-labelledby="interview-report-title">
    <header><p>Interview ended · {report.completion_reason.replace(/_/g, ' ')}</p><h2 id="interview-report-title" tabIndex={-1}>Interview report</h2><p>{report.answered_count} answers recorded. Completion is not proof of correctness or mastery.</p></header>
    <section aria-label="Assessment limits" className="interview-limits">
      <h3>What was—and was not—assessed</h3>
      <dl>{[['Semantic validity', report.semantic_validity], ['Technical code correctness', report.technical_correctness], ['Psychology', report.psychology]].map(([label, assessment]) => {
        const a = assessment as { status: string; reason: string };
        return <div key={label as string}><dt>{label as string}</dt><dd><strong>{a.status}</strong><p>{a.reason}</p></dd></div>;
      })}</dl>
    </section>
    <h3>Answer evidence</h3>
    {!report.answers.length && <p>No answers were submitted before the interview ended.</p>}
    {report.answers.map(answer => <article key={answer.question_id} className="interview-answer-evidence">
      <h4>{answer.question}</h4><blockquote>{answer.answer}</blockquote>
      {answer.code && <details><summary>Submitted code (not executed)</summary><pre>{answer.code}</pre></details>}
      {answer.semantic_review && <aside aria-label="Semantic explanation review"><h5>Explanation quality</h5><p>{answer.semantic_review.status.replace(/_/g, ' ')} · {answer.semantic_review.model_provenance.status.replace(/_/g, ' ')}</p><p>{answer.semantic_review.explanation}</p><p>{answer.semantic_review.uncertainty}</p><p>Follow-up: {answer.semantic_review.followup}</p><ul>{(answer.semantic_review.criteria ?? []).map(criterion => <li key={criterion.id}>{criterion.id.replace(/_/g, ' ')}: {criterion.status.replace(/_/g, ' ')} — {criterion.explanation}</li>)}</ul><small>Answer revision {answer.semantic_review.reviewed_answer_revision}. Reasoning quality is a model interpretation, not execution proof.</small></aside>}
      <ul>{answer.indicators.map(indicator => <li key={indicator.id}><strong>{indicator.label}</strong> — {indicator.value ? 'mentioned' : 'not observed'}; semantic validity unassessed.
        {indicator.excerpts.map(excerpt => <blockquote key={`${excerpt.start}:${excerpt.end}`}><q>{excerpt.text}</q><small>Exact answer excerpt, characters {excerpt.start}–{excerpt.end}</small></blockquote>)}
      </li>)}</ul>
    </article>)}
    <section aria-labelledby="interview-practice-title"><h3 id="interview-practice-title">Practice next</h3>
      {report.practice_topics?.map(item => <article key={`${item.type}:${item.topic}`}><h4>{item.topic.replace(/-/g, ' ')}</h4><p>{item.reason}</p></article>)}
      {report.recommendations.length ? report.recommendations.map(item => <article key={`${item.exercise_id}:${item.spec_version}`} className="interview-recommendation"><p>{item.reason}</p><p>Exercise: <code>{item.exercise_id}</code> · {item.lesson_id ? `Lesson: ${item.lesson_id}` : 'Lesson mapping not available'}</p>
        {onRecommendation ? <button type="button" onClick={() => onRecommendation(item)}>Open recommended practice</button> : <a href={`/practice/${encodeURIComponent(item.exercise_id)}?spec=${encodeURIComponent(item.spec_version)}`}>Open recommended practice</a>}
      </article>) : <p>No catalog-backed lesson mapping is available for this interview type. Revisit your assumptions and add concrete examples.</p>}
    </section>
    <details open><summary>Evidence limitations</summary><ul>{report.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>
  </section>;
}
