import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { StudioMentor } from '../StudioMentor';
vi.mock('../StudioVoice',()=>({StudioVoice:({onPlaybackStateChange}:{onPlaybackStateChange?:(playing:boolean)=>void})=><><button onClick={()=>onPlaybackStateChange?.(true)}>Start actual audio</button><button onClick={()=>onPlaybackStateChange?.(false)}>End actual audio</button></>}));
afterEach(cleanup);
it('drives Nexus speaking portrait only from actual audio state',()=>{
  const view=render(<StudioMentor session={{id:'s',token:'t',workspace:{id:'w',token:'wk'}}} snapshot={null} scenario={null} reply="" draft="" onDraft={vi.fn()} kind="explain" onKind={vi.fn()} locked={false} actionDisabled={false} dirty={false} assumptionsPending={false} busy={false} turnInFlight={false} onSend={vi.fn()} onCoach={vi.fn()} onInterrupt={vi.fn()} onTeaching={vi.fn()} correcting={false} onCancelCorrection={vi.fn()} />);
  fireEvent.click(screen.getByRole('button',{name:'Start actual audio'}));
  expect(view.container.querySelector('.mentor-speaking')).not.toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'End actual audio'}));
  expect(view.container.querySelector('.mentor-speaking')).toBeNull();
});
