"""Structural validation and bounded arithmetic, with explicit unknowns."""
from math import isfinite


def evaluate(graph: dict) -> dict:
    nodes, edges = graph['nodes'], graph['edges']
    ids = [n['node_id'] for n in nodes]
    errors = []
    if len(ids) != len(set(ids)): errors.append('duplicate_node_id')
    edge_ids = [e['edge_id'] for e in edges]
    if len(edge_ids) != len(set(edge_ids)): errors.append('duplicate_edge_id')
    if any(e['source_node_id'] not in ids or e['target_node_id'] not in ids for e in edges): errors.append('edge_endpoint_missing')
    a = graph['assumptions']
    calculations = {}
    def calc(name, keys, func):
        values = [a.get(k) for k in keys]
        if all(type(v) in (int,float) and 0 <= v <= 10**18 and isfinite(v) for v in values):
            value = func(*values)
            if isfinite(value): calculations[name] = value
    calc('fanout_writes_per_second', ['event_rate_per_second','recipients_per_event'], lambda x,y:x*y)
    calc('origin_reads_per_second', ['read_rps','miss_fraction'], lambda x,y:x*y)
    calc('retry_storage_bytes', ['events_per_second','retry_window_seconds','bytes_per_event','replicas'], lambda w,x,y,z:w*x*y*z)
    return {'structural_errors': errors, 'calculations': calculations, 'mechanism_status': 'unknown', 'reason': 'Architecture guarantees require scenario-specific evidence.'}
