import type { ExerciseMetadata } from '../types/api';

export interface PublicExample {
  readonly input_args: Record<string, unknown>;
  readonly output: unknown;
  readonly explanation: string;
}
export type CatalogExercise = ExerciseMetadata & {
  readonly examples?: PublicExample[];
  readonly tags?: string[];
  readonly collection?: string;
  readonly catalog_status?: string;
};
export function catalogTopics(exercises: ExerciseMetadata[]): string[] {
  return [...new Set(exercises.flatMap(exercise => exercise.core_concepts))].sort((a, b) => a.localeCompare(b));
}
export function publicExamples(exercise: ExerciseMetadata | undefined): PublicExample[] {
  return (exercise as CatalogExercise | undefined)?.examples ?? [];
}
