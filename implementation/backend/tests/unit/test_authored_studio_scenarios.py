"""Independent architecture examples and adversarial missing-evidence cases."""
from copy import deepcopy

import pytest

from backend.app.models.enums import ExerciseId
from backend.app.studio.scenario_content import CONTENT, get_content
from backend.app.studio.scenario_rules import evaluate_scenario, rule_input_fields


CASES = {
    'SD-BR-01': ({'quota_coordination':'atomic_shared','outage_policy':'fail_closed','regional_quota_policy':'single_authority'},
                 {'quota_coordination':'sticky_local','outage_policy':'bounded_local_fallback','regional_quota_policy':'bounded_overrun'},
                 {'quota_overrun_bound':2,'admission_p99_ms':6,'origin_capacity_rps':10000,'origin_forwarded_rps':5000}, ['api_gateway','kv_cache']),
    'SD-BR-02': ({'stampede_policy':'singleflight','cache_write_policy':'versioned_write'},
                 {'stampede_policy':'stale_while_revalidate','cache_write_policy':'lease_token'},
                 {'read_rps':25000,'miss_fraction':.01,'origin_capacity_rps':1000,'origin_refreshes_per_hot_key':1,'staleness_seconds':2}, ['kv_cache','relational_db']),
    'SD-BR-03': ({'durable_pending':True,'idempotent_effects':True,'lease_recovery':True,'retry_terminal_policy':'dead_letter','fairness_policy':'per_tenant_limit'},
                 {'outbox':True,'idempotent_effects':True,'lease_recovery':True,'retry_terminal_policy':'bounded_manual_review','fairness_policy':'weighted_fair_queue'},
                 {'arrival_rps':1000,'service_rate_per_worker':125,'workers':12}, ['message_queue','relational_db','worker_pool']),
    'SD-BR-04': ({'tie_policy':'stable_user_id','score_update_policy':'monotonic_max','ranking_merge':'global_sorted_set'},
                 {'tie_policy':'shared_rank','score_update_policy':'deduplicated_delta','ranking_merge':'shard_topk_merge'},
                 {'users':1000000,'bytes_per_entry':64,'replicas':2,'storage_budget_bytes':256000000,'staleness_seconds':1}, ['kv_cache']),
    'SD-CORE-01': ({'execution_isolation':'gvisor','durable_idempotency':True,'epoch_fencing':True,'stream_replay':True,'event_backplane':'pubsub_with_replay_store','cross_node_mutation':'single_owner_partition'},
                   {'execution_isolation':'equivalent_reviewed_isolation','durable_idempotency':True,'epoch_fencing':True,'stream_replay':True,'event_backplane':'durable_stream','cross_node_mutation':'database_cas'}, {}, ['worker_pool','relational_db']),
    'SD-CORE-02': ({'durable_pending':True,'fairness_policy':'partitioned_lanes','idempotent_effects':True,'replay_log':True},
                   {'outbox':True,'fairness_policy':'weighted_fair_queue','idempotent_effects':True,'replay_log':True},
                   {'events_per_second':1200,'retry_window_seconds':604800,'bytes_per_event':500,'replicas':2,'storage_budget_bytes':1000000000000,'rpo_seconds':.8}, ['message_queue','relational_db','worker_pool']),
    'SD-CORE-03': ({'collision_policy':'unique_retry','link_revocation':'versioned_tombstone'},
                   {'collision_policy':'allocated_range','link_revocation':'authorization_on_read'},
                   {'alphabet_size':62,'key_length':7,'issued_links':1000000000,'read_rps':100000,'miss_fraction':.01,'origin_capacity_rps':5000,'revocation_bound_seconds':2}, ['relational_db']),
    'SD-CORE-04': ({'durable_pending':True,'retry_terminal_policy':'dead_letter','idempotent_effects':True,'preference_check':'at_dispatch','fairness_policy':'per_tenant_limit'},
                   {'outbox':True,'retry_terminal_policy':'bounded_manual_review','idempotent_effects':True,'preference_check':'versioned_snapshot_with_consent','fairness_policy':'weighted_fair_queue'},
                   {'event_rate_per_second':100,'recipients_per_event':10000,'dispatch_capacity_rps':2000000}, ['message_queue','relational_db','worker_pool']),
    'SD-CORE-05': ({'prefix_index':'trie','query_epoch_fencing':True,'cache_scope':'public_only','search_failure_policy':'last_good_bounded'},
                   {'prefix_index':'search_index','query_epoch_fencing':True,'cache_scope':'per_user','search_failure_policy':'replica_failover'},
                   {'query_rps':10000,'query_capacity_per_replica':5000,'available_replicas':4,'index_lag_seconds':3}, ['search_index']),
}


def example(scenario_id, alternative=False):
    original, other, assumptions, kinds = CASES[scenario_id]
    kinds = list(kinds)
    if alternative and scenario_id in ('SD-BR-03','SD-CORE-02','SD-CORE-04'):
        kinds.remove('message_queue')  # SQL outbox alternative has no broker.
    nodes = [{'node_id':'client','kind':'client','properties':{}},
             {'node_id':'service','kind':'stateless_service','properties':deepcopy(other if alternative else original)}]
    nodes += [{'node_id':f'n{i}','kind':kind,'properties':{}} for i,kind in enumerate(kinds)]
    edges = [{'edge_id':f'e{i}','source_node_id':'client' if i == 0 else 'service','target_node_id':node['node_id']} for i,node in enumerate(nodes[1:])]
    return {'nodes':nodes,'edges':edges,'assumptions':deepcopy(assumptions)}


@pytest.mark.parametrize('scenario_id', CASES)
@pytest.mark.parametrize('alternative', [False, True])
def test_authored_architecture_families_satisfy_only_conditional_model(scenario_id, alternative):
    result = evaluate_scenario(example(scenario_id, alternative), scenario_id, 3)
    assert result['status'] == 'satisfied_under_declared_assumptions'
    assert result['semantic_reasoning_status'] == 'unassessed'
    assert all(check['status'] == result['status'] for check in result['checks'])


def test_launch_identity_content_and_linked_exercises_are_real():
    assert len(CONTENT) == 12
    assert sum(s['learning_mode']=='dsa_to_system_bridge' for s in CONTENT.values()) == 4
    assert sum(s['learning_mode']=='guided_system_design' for s in CONTENT.values()) == 5
    valid = {e.value for e in ExerciseId}
    for spec in CONTENT.values():
        assert set(spec['linked_exercise_ids']) <= valid
        assert len(spec['content_sha256']) == 64
        assert len(spec['valid_architecture_families']) >= 2
        assert [c['id'] for c in spec['progressive_constraints']] == ['C0','C1','C2','C3']
    copied = get_content('SD-BR-01')
    copied['title'] = 'changed by caller'
    assert CONTENT['SD-BR-01']['title'] != copied['title']


def test_unknown_and_disconnected_declarations_do_not_pass():
    graph = example('SD-BR-03')
    graph['assumptions'] = {}
    assert evaluate_scenario(graph,'SD-BR-03',1)['status'] == 'unknown'
    graph['edges'] = []
    assert evaluate_scenario(graph,'SD-BR-03',0)['status'] == 'unknown'
    graph['nodes'][1]['properties']['durable_pending'] = 'True'
    assert evaluate_scenario(graph,'SD-BR-03',0)['status'] != 'satisfied_under_declared_assumptions'


def test_capacity_violation_and_constraint_changes_change_result():
    graph = example('SD-BR-03')
    assert evaluate_scenario(graph,'SD-BR-03',0)['status'] == 'satisfied_under_declared_assumptions'
    graph['assumptions']['workers'] = 1
    result = evaluate_scenario(graph,'SD-BR-03',1)
    assert result['status'] == 'contradicts_constraint'
    assert result['checks'][-1]['calculation'] == {'estimated_load':1000.0,'modeled_capacity':100.0,'units':'rate_or_identifier_count'}
    graph = example('SD-BR-01')
    graph['assumptions']['origin_forwarded_rps'] = 50000
    assert evaluate_scenario(graph,'SD-BR-01',2)['status'] == 'contradicts_constraint'


@pytest.mark.parametrize('value', [True, '5000', float('nan'), float('inf'), 10**500, -1])
def test_invalid_numeric_assumptions_never_prove_capacity(value):
    graph = example('SD-BR-03')
    graph['assumptions']['arrival_rps'] = value
    assert evaluate_scenario(graph,'SD-BR-03',1)['status'] == 'unknown'


def test_repository_claim_requires_server_verified_evidence():
    for sid in ('REPO-EXP-01','REPO-EXP-02','REPO-DEF-02'):
        graph = {'nodes':[],'edges':[],'assumptions':{}}
        assert evaluate_scenario(graph,sid,3)['status'] == 'unknown'
        assert evaluate_scenario(graph,sid,3,evidence_verified=True)['status'] == 'satisfied_under_declared_assumptions'


def test_pinned_spec_is_independent_of_new_catalog_version():
    pinned = get_content('SD-BR-03')
    graph = example('SD-BR-03')
    pinned['progressive_constraints'][0]['checks'] = [{'op':'number','key':'unmet_new_fact','minimum':1,'maximum':2}]
    assert evaluate_scenario(graph,'SD-BR-03',0,spec=pinned)['status'] == 'unknown'
    assert evaluate_scenario(graph,'SD-BR-03',0)['status'] == 'satisfied_under_declared_assumptions'


def test_fresh_transfer_uses_changed_constraint_and_unknowns():
    graph = example('SD-CORE-05')
    assert evaluate_scenario(graph,'SD-CORE-05',3)['status'] == 'satisfied_under_declared_assumptions'
    result = evaluate_scenario(graph,'SD-CORE-05',3,transfer=True)
    assert result['status'] == 'contradicts_constraint'
    assert result['checks'][-1]['constraint_id'] == 'TRANSFER'
    graph['assumptions']['index_lag_seconds'] = 1
    assert evaluate_scenario(graph,'SD-CORE-05',3,transfer=True)['status'] == 'satisfied_under_declared_assumptions'
    assert evaluate_scenario(example('SD-BR-03'),'SD-BR-03',3,transfer=True)['status'] == 'unknown'


def test_input_fields_expose_active_formulas_and_transfer_but_not_future_policy():
    spec = get_content('SD-BR-03')
    fields = {f['key']:f for f in rule_input_fields(spec,1)}
    assert {'arrival_rps','workers','service_rate_per_worker'} <= fields.keys()
    assert fields['arrival_rps']['type'] == 'number'
    assert 'idempotent_effects' not in fields  # C2 is not active.
    assert 'max_tenant_workers' not in fields
    transfer_fields = {f['key']:f for f in rule_input_fields(spec,3,transfer=True)}
    assert transfer_fields['max_tenant_workers']['maximum'] == 2
