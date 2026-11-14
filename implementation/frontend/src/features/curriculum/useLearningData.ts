import { useEffect, useState } from 'react';
import { learningApi, type LearningCatalog, type LearningProgress } from '../../services/learningApi';
import { ensureWorkspaceSession } from '../../state/workspaceSession';
import type { Workspace } from '../../studioApi';

export interface LearningData {
  catalog: LearningCatalog | null; progress: LearningProgress | null; workspace: Workspace | null;
  loading: boolean; error: string | null;
}
export function useLearningData(): LearningData & { reload: () => void } {
  const [data, setData] = useState<LearningData>({ catalog: null, progress: null, workspace: null, loading: true, error: null });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(current => ({ ...current, loading: true, error: null }));
    const load = async () => {
      const catalogPromise = learningApi.getCatalog(controller.signal);
      const progressPromise = ensureWorkspaceSession().then(async workspace => ({ workspace, progress: await learningApi.getProgress(workspace, controller.signal) }));
      const [catalog, { workspace, progress }] = await Promise.all([catalogPromise, progressPromise]);
      if (!controller.signal.aborted) setData({ catalog, progress, workspace, loading: false, error: null });
    };
    load().catch(error => {
      if (!controller.signal.aborted) setData(current => ({ ...current, loading: false, error: error instanceof Error ? error.message : 'Learning is unavailable. Please retry.' }));
    });
    return () => controller.abort();
  }, [revision]);
  return { ...data, reload: () => setRevision(value => value + 1) };
}
