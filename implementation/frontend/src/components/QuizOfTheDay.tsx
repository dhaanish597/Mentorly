import { useEffect, useState } from 'react';
import { Icon } from './HorizonVisuals';
import { DailyQuiz, QuizSubmissionResponse, gamificationApi } from '../services/gamificationApi';

interface QuizOfTheDayProps {
  initialQuiz: DailyQuiz | null;
  countdownSeconds?: number;
  userId?: string;
  onAnswerSubmitted?: (result: QuizSubmissionResponse) => void;
}

export function QuizOfTheDay({
  initialQuiz,
  countdownSeconds = 28800,
  userId,
  onAnswerSubmitted,
}: QuizOfTheDayProps) {
  const [quiz, setQuiz] = useState<DailyQuiz | null>(initialQuiz);
  const [selectedOption, setSelectedOption] = useState<number | null>(
    initialQuiz?.user_attempt?.selected_option_index ?? null
  );
  const [submitting, setSubmitting] = useState(false);
  const [submissionResult, setSubmissionResult] = useState<QuizSubmissionResponse | null>(null);
  const [timeLeft, setTimeLeft] = useState(countdownSeconds);
  const [celebrate, setCelebrate] = useState(false);

  useEffect(() => {
    if (initialQuiz) {
      setQuiz(initialQuiz);
      if (initialQuiz.user_attempt) {
        setSelectedOption(initialQuiz.user_attempt.selected_option_index);
      }
    }
  }, [initialQuiz]);

  // Live countdown timer until midnight
  useEffect(() => {
    const timer = setInterval(() => {
      setTimeLeft(prev => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const formatTimer = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const isCompleted = quiz?.completed || submissionResult !== null;
  const isCorrect = submissionResult ? submissionResult.is_correct : (quiz?.user_attempt?.is_correct ?? false);
  const correctOptionIndex = submissionResult?.correct_option_index ?? quiz?.correct_option_index;
  const explanation = submissionResult?.explanation ?? quiz?.explanation;

  const handleSubmit = async () => {
    if (selectedOption === null || !quiz || isCompleted || submitting) return;
    setSubmitting(true);
    try {
      const res = await gamificationApi.submitQuiz(quiz.id, selectedOption, userId);
      setSubmissionResult(res);
      if (res.is_correct) {
        setCelebrate(true);
      }
      onAnswerSubmitted?.(res);
    } catch (err) {
      console.error('Failed to submit quiz answer', err);
    } finally {
      setSubmitting(false);
    }
  };

  if (!quiz) {
    return (
      <div className="gamified-card quiz-card">
        <p className="quiet-empty">Daily quiz loading…</p>
      </div>
    );
  }

  const optionLetters = ['A', 'B', 'C', 'D'];

  return (
    <article className={`gamified-card quiz-card ${celebrate ? 'confetti-celebration' : ''}`}>
      <div className="gamified-card-header">
        <h3>
          <Icon name="star" /> Quiz of the Day
        </h3>
        <span className="header-badge">{quiz.category.toUpperCase()}</span>
      </div>

      <div className="quiz-meta-row">
        <span className="quiz-pill">{quiz.difficulty.toUpperCase()}</span>
        <span className="quiz-pill quiz-pill-xp">+{quiz.xp_reward} XP</span>
        <span className="quiz-pill quiz-pill-timer" title="Time remaining until next quiz">
          <Icon name="clock" /> {formatTimer(timeLeft)}
        </span>
      </div>

      <p className="quiz-question-text">{quiz.question}</p>

      <div className="quiz-options-list" role="radiogroup" aria-label="Quiz options">
        {quiz.options.map((option, idx) => {
          const isSelected = selectedOption === idx;
          let optionClass = 'quiz-option-btn';
          if (isSelected) optionClass += ' selected';
          if (isCompleted) {
            if (correctOptionIndex !== undefined && idx === correctOptionIndex) {
              optionClass += ' correct';
            } else if (isSelected && !isCorrect) {
              optionClass += ' incorrect';
            }
          }

          return (
            <button
              key={idx}
              type="button"
              className={optionClass}
              disabled={isCompleted || submitting}
              onClick={() => setSelectedOption(idx)}
              aria-checked={isSelected}
              role="radio"
            >
              <span className="quiz-option-letter">{optionLetters[idx]}</span>
              <span>{option}</span>
            </button>
          );
        })}
      </div>

      {!isCompleted ? (
        <div className="quiz-actions">
          <span className="quiz-pill">{selectedOption === null ? 'Select an answer' : 'Ready to submit'}</span>
          <button
            type="button"
            className="quiz-submit-btn"
            disabled={selectedOption === null || submitting}
            onClick={handleSubmit}
          >
            {submitting ? 'Verifying…' : 'Submit Answer'} <Icon name="arrow" />
          </button>
        </div>
      ) : (
        <div className={`quiz-explanation-box ${isCorrect ? 'success' : 'failed'}`}>
          <strong>{isCorrect ? '🎉 Correct! +50 XP Earned!' : '💡 Good effort! Review the mechanism:'}</strong>
          <p style={{ margin: '6px 0 0 0' }}>{explanation}</p>
        </div>
      )}
    </article>
  );
}
