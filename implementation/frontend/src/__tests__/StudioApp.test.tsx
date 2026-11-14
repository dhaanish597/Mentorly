import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { StudioApp } from '../StudioApp';
import type { Graph } from '../studioApi';
import type { ScenarioView, Snapshot } from '../StudioViews';
const flowSpy = vi.hoisted(() => vi.fn());
const voiceSpy = vi.hoisted(() => vi.fn());
vi.mock('@xyflow/react', () => ({ ReactFlow: (props:{children:React.ReactNode}) => { flowSpy(props); return <div>{props.children}</div>; }, Background: () => null, Controls: () => null, applyNodeChanges: (_:unknown, n:unknown) => n }));
vi.mock('../StudioVoice', () => ({ StudioVoice: (props:unknown) => { voiceSpy(props); return <section aria-label="Voice input"><button>Answer by voice</button></section>; } }));
vi.mock('../StudioRepository', () => ({ RepositoryPanel: () => { const [draft,setDraft]=useState(''); return <section aria-label="Repository workspace"><label>Repository reasoning<textarea value={draft} onChange={event=>setDraft(event.target.value)}/></label></section>; } }));
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); window.history.replaceState({},'', '/'); });
function mockStudio(initial: Partial<Snapshot> = {}, detail: Partial<ScenarioView> = {}) {
  let current: Snapshot = {session_id:'session',epoch:4,diagram_revision:7,state:'active',posture:'teaching',graph:{nodes:[],edges:[],assumptions:{}},events:[],...initial};
  const scenario: ScenarioView = {id:'SD-CORE-01',version:'1',title:'Coordinator',problem_statement:'Design',prerequisites:[],learning_objectives:[],linked_exercise_ids:[],constraint_index:0,constraint:{id:'C0',title:'Base',description:'Define'},hint_level:0,...detail};
  const requests: {url:string;body:Record<string,unknown>}[]=[];
  const route = vi.fn<(url:string,body:Record<string,unknown>)=>unknown>(()=>({}));
  vi.stubGlobal('fetch',vi.fn(async (url:string,options:RequestInit={})=>{
    const body:Record<string,unknown>=typeof options.body==='string' ? JSON.parse(options.body) : {};
    requests.push({url,body});
    let data:unknown;
    if(url.endsWith('/scenarios')) data={scenarios:[{id:scenario.id,title:scenario.title,mode:'guided_system_design',version:'1'}]};
    else if(url.endsWith('/scenario')) data=scenario;
    else if(url.endsWith('/workspaces')) data={workspace_id:body.workspace_id};
    else if(url.endsWith('/sessions') && options.method==='POST') { current={...current,session_id:String(body.session_id)}; data={session_id:current.session_id,epoch:current.epoch,diagram_revision:current.diagram_revision}; }
    else if(/\/studio\/sessions\/[^/]+$/.test(url)) data=current;
    else data=route(url,body);
    return new Response(JSON.stringify(data),{status:200});
  }));
  return {requests,route,update:(patch:Partial<Snapshot>)=>{current={...current,...patch};}};
}
async function startStudio() {
  render(<StudioApp/>); await screen.findByRole('radio',{name:/Coordinator/});
  fireEvent.click(screen.getByRole('button',{name:'Start session'}));
  await screen.findByRole('button',{name:'Send explanation'});
}
const latestExplanation = {id:'latest',epoch:4,diagram_revision:7,kind:'explain',content:'Saved explanation',created_at:'2026-11-14T10:01:00Z',transcript_revision:1,superseded_by:null};
const componentGraph: Graph = {nodes:[{node_id:'gateway',label:'Gateway',kind:'service',replica_count:1,statefulness:'unknown',partition_key:'',consistency_mode:'unknown',notes:'',properties:{position:{x:10,y:20}}}],edges:[],assumptions:{}};

describe('studio review regressions',()=>{
  it('appends delayed speech to the latest typed explanation',async()=>{
    mockStudio(); await startStudio();
    const captured=voiceSpy.mock.calls[voiceSpy.mock.calls.length-1][0] as {onTranscript:(text:string)=>void};
    fireEvent.change(screen.getByLabelText('Your explanation'),{target:{value:'Typed while transcribing'}});
    act(()=>captured.onTranscript('Reviewed speech'));
    expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('Typed while transcribing\nReviewed speech');
  });
  it('keeps correction identity through a coach refresh',async()=>{
    const fixture=mockStudio({turns:[latestExplanation]});
    fixture.route.mockImplementation(url=>url.endsWith('/coach') ? {text:'A hint',epoch:4} : {turn_id:'new',epoch:5});
    await startStudio(); fireEvent.click(screen.getByText('Your decision timeline')); fireEvent.click(screen.getByRole('button',{name:'Edit latest explanation'}));
    fireEvent.click(screen.getByText('Help')); fireEvent.click(screen.getByRole('button',{name:'Hint'}));
    await waitFor(()=>expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button',{name:'Send correction'}));
    await waitFor(()=>expect(fixture.requests.some(request=>request.url.endsWith('/turns/latest/correction'))).toBe(true));
  });
  it('refreshes feedback events for voice without erasing a correction or graph history',async()=>{
    const fixture=mockStudio({turns:[latestExplanation]});
    fixture.route.mockImplementation(url=>{
      if(url.endsWith('/feedback')) {fixture.update({events:[{sequence:1,type:'feedback.ready',payload:{epoch:4,text:'A saved question'}}]});return {epoch:4,status:'ready',question:'A saved question'};}
      return {};
    });
    await startStudio(); fireEvent.click(screen.getByText('Your decision timeline')); fireEvent.click(screen.getByRole('button',{name:'Edit latest explanation'}));
    fireEvent.click(screen.getByRole('button',{name:'Add component'})); fireEvent.click(screen.getByRole('button',{name:'Undo'}));
    fireEvent.click(screen.getByText('Feedback on the last explanation')); fireEvent.click(screen.getByRole('button',{name:'Request feedback'}));
    await waitFor(()=>expect((voiceSpy.mock.calls[voiceSpy.mock.calls.length-1][0] as {events:Snapshot['events']}).events?.some(event=>event.type==='feedback.ready')).toBe(true));
    expect(screen.getByRole('button',{name:'Send correction'})).toBeTruthy();
    expect(within(screen.getByText('Feedback on the last explanation').closest('details')!).getByText('A saved question')).toBeTruthy();
    expect((screen.getByRole('button',{name:'Redo'}) as HTMLButtonElement).disabled).toBe(false);
  });
  it('retains repository reasoning when switching studio areas',async()=>{
    mockStudio(); await startStudio();
    fireEvent.click(screen.getByRole('tab',{name:'Codebase learning'}));
    fireEvent.change(screen.getByLabelText('Repository reasoning'),{target:{value:'Repository draft and citations'}});
    fireEvent.click(screen.getByRole('tab',{name:'System design'}));
    fireEvent.click(screen.getByRole('tab',{name:'Codebase learning'}));
    expect((screen.getByLabelText('Repository reasoning') as HTMLTextAreaElement).value).toBe('Repository draft and citations');
  });
  it('clears undo and redo when restoring a saved revision',async()=>{
    const fixture=mockStudio({graph:componentGraph});
    fixture.route.mockImplementation(url=>url.endsWith('/diagrams') ? {revisions:[{revision:6,parent_revision:5,created_at:'2026-11-14T10:00:00Z'}]} : url.endsWith('/restore') ? {revision:8,epoch:5,graph:componentGraph} : {revision:8,epoch:5,validation:{}});
    await startStudio(); fireEvent.click(screen.getByRole('button',{name:'Add component'})); fireEvent.click(screen.getByRole('button',{name:'Undo'}));
    fireEvent.click(screen.getByRole('button',{name:'Save diagram'})); await waitFor(()=>expect((screen.getByRole('button',{name:'Save diagram'}) as HTMLButtonElement).disabled).toBe(true));
    fireEvent.click(screen.getByText('Saved revisions and review')); fireEvent.click(screen.getByRole('button',{name:'Load revisions'}));
    fireEvent.click(await screen.findByRole('button',{name:'Restore as new revision'}));
    await waitFor(()=>expect(fixture.requests.some(request=>request.url.endsWith('/restore'))).toBe(true));
    await waitFor(()=>expect((screen.getByRole('button',{name:'Redo'}) as HTMLButtonElement).disabled).toBe(true));
    expect((screen.getByRole('button',{name:'Undo'}) as HTMLButtonElement).disabled).toBe(true);
  });
  it('opens node properties from ReactFlow keyboard selection without mutating graph',async()=>{
    mockStudio({graph:componentGraph}); await startStudio();
    const flow=flowSpy.mock.calls[flowSpy.mock.calls.length-1][0] as {onNodesChange:(changes:{type:'select';id:string;selected:boolean}[])=>void};
    act(()=>flow.onNodesChange([{type:'select',id:'gateway',selected:true}]));
    expect((screen.getByLabelText('Label') as HTMLInputElement).value).toBe('Gateway');
    expect((screen.getByRole('button',{name:'Save diagram'}) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button',{name:'Undo'}) as HTMLButtonElement).disabled).toBe(true);
  });
  it.each([
    ['edge-to-node','select-first'], ['edge-to-node','deselect-first'],
    ['node-to-edge','select-first'], ['node-to-edge','deselect-first'],
  ] as const)('keeps batched %s keyboard selection with %s callbacks',async(direction,order)=>{
    const graph:Graph={...componentGraph,nodes:[...componentGraph.nodes,{...componentGraph.nodes[0],node_id:'store',label:'Store'}],edges:[{edge_id:'wire',source_node_id:'gateway',target_node_id:'store',protocol:'HTTPS',directionality:'directed',rate_estimate_rps:null,failure_behavior:''}]};
    mockStudio({graph}); await startStudio();
    type SelectChange={type:'select';id:string;selected:boolean};
    type FlowCallbacks={onNodesChange:(changes:SelectChange[])=>void;onEdgesChange:(changes:SelectChange[])=>void};
    const initial=flowSpy.mock.calls[flowSpy.mock.calls.length-1][0] as FlowCallbacks;
    const fromEdge=direction==='edge-to-node';
    act(()=>fromEdge ? initial.onEdgesChange([{type:'select',id:'wire',selected:true}]) : initial.onNodesChange([{type:'select',id:'gateway',selected:true}]));
    const callbacks=flowSpy.mock.calls[flowSpy.mock.calls.length-1][0] as FlowCallbacks;
    const select=()=>fromEdge ? callbacks.onNodesChange([{type:'select',id:'gateway',selected:true}]) : callbacks.onEdgesChange([{type:'select',id:'wire',selected:true}]);
    const deselect=()=>fromEdge ? callbacks.onEdgesChange([{type:'select',id:'wire',selected:false}]) : callbacks.onNodesChange([{type:'select',id:'gateway',selected:false}]);
    act(()=>{ if(order==='select-first'){select();deselect();}else{deselect();select();} });
    expect((screen.getByLabelText(fromEdge ? 'Label' : 'Protocol') as HTMLInputElement).value).toBe(fromEdge ? 'Gateway' : 'HTTPS');
    expect((screen.getByRole('button',{name:'Save diagram'}) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button',{name:'Undo'}) as HTMLButtonElement).disabled).toBe(true);
  });
  it('does not treat a superseded witness without a current replacement as completion evidence',async()=>{
    mockStudio({turns:[{...latestExplanation,id:'teach',superseded_by:'missing'}],events:[{sequence:1,type:'coach.action',payload:{epoch:4,action:'teachback'}},{sequence:2,type:'turn.recorded',payload:{epoch:4,turn_id:'teach'}},{sequence:3,type:'coach.action',payload:{epoch:4,action:'transfer'}},{sequence:4,type:'turn.recorded',payload:{epoch:4,turn_id:'missing-transfer'}}]},{constraint_index:3});
    await startStudio(); expect(screen.queryByRole('button',{name:'Finish practice'})).toBeNull();
  });
  it('resolves corrected teach-back and transfer witnesses by their original timeline positions',async()=>{
    const fixture=mockStudio({turns:[{...latestExplanation,id:'teach',superseded_by:'teach-corrected'},{...latestExplanation,id:'transfer',superseded_by:'transfer-corrected'},{...latestExplanation,id:'teach-corrected',kind:'teachback',transcript_revision:2},{...latestExplanation,id:'transfer-corrected',kind:'transfer',transcript_revision:2}],events:[{sequence:1,type:'coach.action',payload:{epoch:4,action:'teachback'}},{sequence:2,type:'turn.recorded',payload:{epoch:4,turn_id:'teach'}},{sequence:3,type:'coach.action',payload:{epoch:4,action:'transfer'}},{sequence:4,type:'turn.recorded',payload:{epoch:4,turn_id:'transfer'}},{sequence:5,type:'turn.recorded',payload:{epoch:4,turn_id:'teach-corrected'}},{sequence:6,type:'turn.recorded',payload:{epoch:4,turn_id:'transfer-corrected'}}]},{constraint_index:3});
    fixture.route.mockImplementation(()=>({})); await startStudio();
    expect(screen.getByRole('button',{name:'Finish practice'})).toBeTruthy();
  });
});

describe('studio session', () => {
  it('opens Codebase learning from its repository deep link', async () => {
    window.history.replaceState({},'', '/studio?area=repository');
    vi.stubGlobal('fetch',vi.fn(async () => new Response(JSON.stringify({scenarios:[]}),{status:200})));
    await act(async () => { render(<StudioApp/>); });
    expect(screen.getByRole('tab',{name:'Codebase learning'}).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('region',{name:'Repository workspace'})).toBeTruthy();
  });
  it('shows all scenarios as readable cards and keeps assessment settings advanced', async () => {
    vi.stubGlobal('fetch',vi.fn(async () => new Response(JSON.stringify({scenarios:Array.from({length:12},(_,i)=>({id:`SD-${i}`,title:`Scenario ${i+1}`,mode:'guided_system_design',version:'1'}))}),{status:200})));
    render(<StudioApp/>);
    expect(await screen.findAllByRole('radio')).toHaveLength(12);
    expect((screen.getByRole('combobox',{name:'Posture'}).closest('details') as HTMLDetailsElement).open).toBe(false);
    fireEvent.click(screen.getByText('Interview settings'));
    expect(screen.getByRole('combobox',{name:'Posture'})).toBeTruthy();
  });

  it('puts visible voice and one explanation draft before workspace tools, with Help preserving coaching', async () => {
    vi.stubGlobal('fetch',vi.fn(async (url:string,options:RequestInit={}) => {
      const body=typeof options.body==='string' ? JSON.parse(options.body) : {};
      const data=url.endsWith('/scenarios') ? {scenarios:[{id:'SD-CORE-01',title:'Coordinator',mode:'guided_system_design',version:'1'}]} : url.endsWith('/scenario') ? {id:'SD-CORE-01',version:'1',title:'Coordinator',problem_statement:'Design',prerequisites:[],learning_objectives:[],linked_exercise_ids:[],constraint_index:0,constraint:{id:'C0',title:'Base',description:'Define'},hint_level:0} : url.endsWith('/sessions') && options.method==='POST' ? {session_id:body.session_id,epoch:1,diagram_revision:0} : {session_id:'s',epoch:1,diagram_revision:0,state:'active',posture:'teaching',graph:{nodes:[],edges:[],assumptions:{}},events:[]};
      return new Response(JSON.stringify(data),{status:200});
    }));
    render(<StudioApp/>); await screen.findByRole('radio',{name:/Coordinator/});
    fireEvent.click(screen.getByRole('button',{name:'Start session'}));
    expect(await screen.findByRole('button',{name:'Answer by voice'})).toBeTruthy();
    expect(screen.getAllByRole('textbox',{name:'Your explanation'})).toHaveLength(1);
    expect((screen.getByRole('button',{name:'Hint'}).closest('details') as HTMLDetailsElement).open).toBe(false);
    expect(screen.getAllByRole('button').filter(button => !button.closest('details:not([open])'))).toHaveLength(9);
    expect(screen.queryByLabelText('Label')).toBeNull();
    expect(screen.queryByLabelText('Assumptions (JSON object)')).toBeNull();
    expect(screen.getByRole('tab',{name:'Canvas'}).getAttribute('aria-selected')).toBe('true');
    const mentor=screen.getByRole('complementary',{name:'Mentor conversation'});
    expect(mentor.compareDocumentPosition(screen.getByRole('region',{name:'Architecture workspace'})) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(screen.getByText('Help'));
    for (const name of ['Hint','Options','Sketch','Explain','Teach back','Transfer','Rewind','Skip','Advance','Finish']) expect(screen.getByRole('button',{name})).toBeTruthy();
  });

  it('corrects the latest explanation in the shared draft using transcript revision fencing', async () => {
    const requests: {url:string;body:Record<string,unknown>}[]=[];
    let corrected=false;
    vi.stubGlobal('fetch',vi.fn(async (url:string,options:RequestInit={}) => {
      const body=typeof options.body==='string' ? JSON.parse(options.body) : {};
      requests.push({url,body});
      if(url.endsWith('/correction')) { corrected=true; return new Response(JSON.stringify({turn_id:'corrected',epoch:5,transcript_revision:2,supersedes_turn_id:'latest'}),{status:200}); }
      const data=url.endsWith('/scenarios') ? {scenarios:[{id:'SD-CORE-01',title:'Coordinator',mode:'guided_system_design',version:'1'}]} : url.endsWith('/scenario') ? {id:'SD-CORE-01',version:'1',title:'Coordinator',problem_statement:'Design',prerequisites:[],learning_objectives:[],linked_exercise_ids:[],constraint_index:0,constraint:{id:'C0',title:'Base',description:'Define'},hint_level:0} : url.endsWith('/sessions') && options.method==='POST' ? {session_id:body.session_id,epoch:4,diagram_revision:7} : {session_id:'s',epoch:corrected ? 5 : 4,diagram_revision:7,graph:{nodes:[],edges:[],assumptions:{}},events:[],turns:[{id:'old',epoch:3,diagram_revision:6,kind:'explain',content:'Original transcript',created_at:'2026-11-14T10:00:00Z',transcript_revision:1,superseded_by:'latest'},{id:'latest',epoch:4,diagram_revision:7,kind:'explain',content:'Latest transcript',created_at:'2026-11-14T10:01:00Z',transcript_revision:1,superseded_by:corrected ? 'corrected' : null}]};
      return new Response(JSON.stringify(data),{status:200});
    }));
    render(<StudioApp/>); await screen.findByRole('radio',{name:/Coordinator/}); fireEvent.click(screen.getByRole('button',{name:'Start session'}));
    await screen.findByRole('button',{name:'Send explanation'});
    fireEvent.click(screen.getByText('Your decision timeline'));
    fireEvent.click(screen.getByRole('button',{name:'Edit latest explanation'}));
    expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('Latest transcript');
    fireEvent.change(screen.getByLabelText('Your explanation'),{target:{value:'Corrected reasoning'}});
    fireEvent.click(screen.getByRole('button',{name:'Send correction'}));
    await waitFor(() => expect(requests.find(r=>r.url.endsWith('/turns/latest/correction'))?.body).toEqual({epoch:4,base_revision:1,text:'Corrected reasoning',kind:'explain'}));
    expect(await screen.findByRole('button',{name:'Send explanation'})).toBeTruthy();
  });

  it('creates a real session and saves a structured component with revision fencing', async () => {
    const requests: {url:string;method:string;body:any}[] = [];
    const fetcher = vi.fn(async (url: string, options: RequestInit = {}) => {
      const method = options.method ?? 'GET'; const body = typeof options.body === 'string' ? JSON.parse(options.body) : null;
      requests.push({url,method,body});
      const data = url.endsWith('/scenarios') ? {scenarios:[{id:'SD-CORE-01',title:'Coordinator',mode:'guided_system_design',version:'1'}]} : url.endsWith('/scenario') ? {id:'SD-CORE-01',version:'1',title:'Coordinator',problem_statement:'Design a coordinator',prerequisites:[],learning_objectives:[],linked_exercise_ids:[],constraint_index:0,constraint:{id:'C0',title:'Base',description:'Define a service'},hint_level:0} : url.endsWith('/workspaces') ? {workspace_id:body.workspace_id} : url.endsWith('/sessions') && method === 'POST' ? {session_id:body.session_id,epoch:1,diagram_revision:0} : url.endsWith('/diagram') ? {revision:1,epoch:2,validation:{mechanism_status:'unknown'}} : {session_id:'s',epoch:1,diagram_revision:0,scenario_id:'SD-CORE-01',graph:{nodes:[],edges:[],assumptions:{}},events:[]};
      return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
    });
    vi.stubGlobal('fetch',fetcher); render(<StudioApp/>);
    await screen.findByRole('radio',{name:/Coordinator/});
    fireEvent.click(screen.getByRole('button',{name:'Start session'}));
    await screen.findByRole('button',{name:'Add component'});
    fireEvent.click(screen.getByRole('button',{name:'Add component'}));
    const canvasTab = screen.getByRole('tab',{name:'Canvas'});
    canvasTab.focus(); fireEvent.keyDown(canvasTab,{key:'ArrowRight'});
    expect(screen.getByRole('tab',{name:'Table'}).getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('tab',{name:'Table'}));
    fireEvent.change(screen.getByLabelText('Label'),{target:{value:'Gateway'}});
    fireEvent.click(screen.getByRole('tab',{name:'Canvas'}));
    expect((screen.getByLabelText('Label') as HTMLInputElement).value).toBe('Gateway');
    fireEvent.click(screen.getByRole('button',{name:'Save diagram'}));
    await waitFor(() => expect(requests.some(r => r.url.endsWith('/diagram'))).toBe(true));
    const mutation = requests.find(r => r.url.endsWith('/diagram'))!;
    expect(mutation.body.base_revision).toBe(0);
    expect(mutation.body.nodes[0].label).toBe('Gateway');
    expect(await screen.findByText(/Revision 1/)).toBeTruthy();
    fireEvent.click(screen.getByRole('tab',{name:'Assumptions'}));
    fireEvent.click(screen.getByText('Advanced assumptions JSON'));
    const assumptions = screen.getByLabelText('Assumptions (JSON object)') as HTMLTextAreaElement;
    fireEvent.change(assumptions,{target:{value:'{"read_rps":100}'}});
    expect((screen.getByRole('button',{name:'Undo'}) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button',{name:'Apply assumptions'}));
    fireEvent.click(screen.getByRole('tab',{name:'Table'}));
    fireEvent.change(screen.getByLabelText('Label'),{target:{value:'Changed'}});
    fireEvent.click(screen.getByRole('button',{name:'Undo'}));
    expect((screen.getByLabelText('Label') as HTMLInputElement).value).toBe('Gateway');
    fireEvent.click(screen.getByRole('button',{name:'Redo'}));
    expect((screen.getByLabelText('Label') as HTMLInputElement).value).toBe('Changed');
    fireEvent.click(screen.getByRole('button',{name:'Undo'}));
    fireEvent.click(screen.getByRole('tab',{name:'Assumptions'}));
    expect((screen.getByLabelText('Assumptions (JSON object)') as HTMLTextAreaElement).value).toContain('100');
    fireEvent.click(screen.getByRole('button',{name:'Undo'}));
    expect((screen.getByLabelText('Assumptions (JSON object)') as HTMLTextAreaElement).value).not.toContain('100');
    fireEvent.click(screen.getByRole('tab',{name:'Canvas'}));
    fireEvent.click(screen.getByRole('button',{name:'Add component'}));
    const flow = flowSpy.mock.calls[flowSpy.mock.calls.length-1][0] as {nodes:{id:string}[];onConnect:(connection:{source:string;target:string})=>void};
    act(() => flow.onConnect({source:flow.nodes[0].id,target:flow.nodes[0].id}));
    expect(screen.queryByLabelText('Protocol')).toBeNull();
    act(() => flow.onConnect({source:flow.nodes[0].id,target:flow.nodes[1].id}));
    fireEvent.change(screen.getByLabelText('Protocol'),{target:{value:'HTTPS'}});
    fireEvent.click(screen.getByRole('button',{name:'Save diagram'}));
    await waitFor(() => expect(requests.filter(r=>r.url.endsWith('/diagram'))).toHaveLength(2));
    const connectionSave=requests.filter(r=>r.url.endsWith('/diagram'))[1];
    expect(connectionSave.body.base_revision).toBe(1);
    expect(connectionSave.body.edges[0]).toMatchObject({source_node_id:flow.nodes[0].id,target_node_id:flow.nodes[1].id,protocol:'HTTPS'});
  });
  it('locks graph editing until an in-flight save settles', async () => {
    let finish!: (response:Response) => void;
    const pending = new Promise<Response>(resolve => {finish=resolve;});
    vi.stubGlobal('fetch',vi.fn(async (url:string, options:RequestInit={}) => {
      if (url.endsWith('/diagram')) return pending;
      const body=typeof options.body==='string' ? JSON.parse(options.body) : {};
      const data=url.endsWith('/scenarios') ? {scenarios:[{id:'SD-CORE-01',title:'Coordinator',mode:'guided_system_design',version:'1'}]} : url.endsWith('/scenario') ? {id:'SD-CORE-01',version:'1',title:'Coordinator',problem_statement:'Design',prerequisites:[],learning_objectives:[],linked_exercise_ids:[],constraint_index:0,constraint:{id:'C0',title:'Base',description:'Define'},hint_level:0} : url.endsWith('/sessions') && options.method==='POST' ? {session_id:body.session_id,epoch:1,diagram_revision:0} : {session_id:'s',epoch:1,diagram_revision:0,graph:{nodes:[],edges:[],assumptions:{}},events:[]};
      return new Response(JSON.stringify(data),{status:200});
    }));
    render(<StudioApp/>); await screen.findByRole('radio',{name:/Coordinator/});
    fireEvent.click(screen.getByRole('button',{name:'Start session'})); await screen.findByRole('button',{name:'Add component'});
    fireEvent.click(screen.getByRole('button',{name:'Add component'})); fireEvent.click(screen.getByRole('button',{name:'Save diagram'}));
    await waitFor(() => expect(screen.getByLabelText('Label').matches(':disabled')).toBe(true));
    expect(screen.getByRole('button',{name:'Add component'}).matches(':disabled')).toBe(true);
    await act(async () => {finish(new Response(JSON.stringify({revision:1,epoch:2,validation:{}}),{status:200}));});
    await waitFor(() => expect(screen.getByLabelText('Label').matches(':disabled')).toBe(false));
  });

  it('ignores a stale session reload after an interruption', async () => {
    let finishReload!: (response:Response) => void; let snapshotCount=0; const sent:number[]=[];
    const pending=new Promise<Response>(resolve => {finishReload=resolve;});
    const snapshot={session_id:'s',epoch:1,diagram_revision:0,graph:{nodes:[],edges:[],assumptions:{}},events:[]};
    vi.stubGlobal('fetch',vi.fn(async (url:string,options:RequestInit={}) => {
      const body=typeof options.body==='string' ? JSON.parse(options.body) : {};
      if (url.endsWith('/sessions') && options.method === 'POST') snapshot.session_id=body.session_id;
      if (url.endsWith('/turns')) { sent.push(body.epoch); return new Response(JSON.stringify({turn_id:'t',epoch:body.epoch}),{status:200}); }
      if (url.endsWith('/interrupt')) return new Response(JSON.stringify({epoch:2}),{status:200});
      if (/\/studio\/sessions\/[^/]+$/.test(url) && !options.method?.includes('POST')) { snapshotCount++; if(snapshotCount===2) return pending; }
      const data=url.endsWith('/scenarios') ? {scenarios:[{id:'SD-CORE-01',title:'Coordinator',mode:'guided_system_design',version:'1'}]} : url.endsWith('/scenario') ? {id:'SD-CORE-01',version:'1',title:'Coordinator',problem_statement:'Design',prerequisites:[],learning_objectives:[],linked_exercise_ids:[],constraint_index:0,constraint:{id:'C0',title:'Base',description:'Define'},hint_level:0} : url.endsWith('/sessions') && options.method==='POST' ? {session_id:body.session_id,epoch:1,diagram_revision:0} : snapshot;
      return new Response(JSON.stringify(data),{status:200});
    }));
    render(<StudioApp/>); await screen.findByRole('radio',{name:/Coordinator/}); fireEvent.click(screen.getByRole('button',{name:'Start session'})); await screen.findByRole('button',{name:'Send explanation'});
    fireEvent.change(screen.getByLabelText('Your explanation'),{target:{value:'First'}}); fireEvent.click(screen.getByRole('button',{name:'Send explanation'}));
    await waitFor(() => expect(snapshotCount).toBe(2)); fireEvent.click(screen.getByRole('button',{name:'Interrupt current turn'}));
    await act(async () => { await Promise.resolve(); finishReload(new Response(JSON.stringify(snapshot),{status:200})); });
    await waitFor(() => expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText('Your explanation'),{target:{value:'Second'}}); fireEvent.click(screen.getByRole('button',{name:'Send explanation'}));
    await waitFor(() => expect(sent).toEqual([1,2]));
  });

  it('prevents accepting a preview after the graph has unsaved edits', async () => {
    const graph={nodes:[],edges:[],assumptions:{}};
    vi.stubGlobal('fetch',vi.fn(async (url:string,options:RequestInit={}) => {
      const body=typeof options.body==='string' ? JSON.parse(options.body) : {};
      const data=url.endsWith('/scenarios') ? {scenarios:[{id:'SD-CORE-01',title:'Coordinator',mode:'guided_system_design',version:'1'}]} : url.endsWith('/scenario') ? {id:'SD-CORE-01',version:'1',title:'Coordinator',problem_statement:'Design',prerequisites:[],learning_objectives:[],linked_exercise_ids:[],constraint_index:0,constraint:{id:'C0',title:'Base',description:'Define'},hint_level:0} : url.endsWith('/proposals') ? {proposal_id:'p',graph,validation:{}} : url.endsWith('/sessions') && options.method==='POST' ? {session_id:body.session_id,epoch:1,diagram_revision:0} : {session_id:'s',epoch:1,diagram_revision:0,graph,events:[]};
      return new Response(JSON.stringify(data),{status:200});
    }));
    render(<StudioApp/>); await screen.findByRole('radio',{name:/Coordinator/}); fireEvent.click(screen.getByRole('button',{name:'Start session'})); await screen.findByRole('button',{name:'Add component'});
    fireEvent.click(screen.getByText('Review a proposed graph')); fireEvent.change(screen.getByLabelText('Proposed graph'),{target:{value:JSON.stringify(graph)}}); fireEvent.click(screen.getByRole('button',{name:'Preview proposal'}));
    const accept=await screen.findByRole('button',{name:'Accept proposal'}); expect((accept as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole('button',{name:'Add component'})); expect((accept as HTMLButtonElement).disabled).toBe(true);
  });

});
