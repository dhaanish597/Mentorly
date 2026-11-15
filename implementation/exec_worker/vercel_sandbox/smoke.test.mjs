import { test } from 'node:test';
import assert from 'node:assert/strict';
import { credentials, smoke, NETWORK_PROBE, SECRET_PROBE, LOOP_PROBE, LOOP_GONE, MARKER_WRITE, MARKER_ABSENT, MARKER_PRESENT } from './smoke.mjs';
const auth = { VERCEL_TOKEN: 'test-token', VERCEL_TEAM_ID: 'test-team', VERCEL_PROJECT_ID: 'test-project' };
const markers = new Map([
  ['print("VIVA_SANDBOX_OK")', 'VIVA_SANDBOX_OK'], [NETWORK_PROBE, 'VIVA_NETWORK_BLOCKED'],
  [SECRET_PROBE, 'VIVA_SELECTED_SECRETS_ABSENT'], [LOOP_PROBE, 'VIVA_LOOP_STARTED'],
  [LOOP_GONE, 'VIVA_LOOP_GONE'], [MARKER_WRITE, 'VIVA_MARKER_WRITTEN'],
  [MARKER_ABSENT, 'VIVA_MARKER_ABSENT'], [MARKER_PRESENT, 'VIVA_MARKER_PRESENT'],
]);
function fake({ failSource, failCreate = 0, failDelete = 0, loopExit = 137 } = {}) {
  const state = { created: 0, deleted: [], sources: [] };
  const sdk = { create: async options => {
    const id = ++state.created;
    if (id === failCreate) throw new Error('create failed');
    assert.equal(options.networkPolicy, 'deny-all');
    assert.equal(options.persistent, false);
    assert.equal(options.timeout, 30000);
    assert.deepEqual(options.env, {});
    assert.deepEqual(options.ports, []);
    assert.deepEqual(options.resources, { vcpus: 1 });
    assert.equal(options.source, undefined);
    return {
      runCommand: async command => {
        assert.equal(command.cmd, 'python3');
        assert.deepEqual(command.args.slice(0, 2), ['-I', '-c']);
        const source = command.args[2];
        state.sources.push([id, source]);
        assert.ok(markers.has(source));
        assert.equal(command.timeoutMs, source === LOOP_PROBE ? 1000 : source === NETWORK_PROBE ? 6000 : 2000);
        if (source === failSource) throw new Error('command failed');
        return { exitCode: source === LOOP_PROBE ? loopExit : 0,
          stdout: async () => markers.get(source) + '\n' };
      },
      delete: async () => { state.deleted.push(id); if (id === failDelete) throw new Error('delete failed'); },
    };
  } };
  return { sdk, state };
}
test('missing and partial auth fails before creating a sandbox', async () => {
  const { sdk, state } = fake();
  await assert.rejects(smoke(sdk, {}), /unavailable/);
  await assert.rejects(smoke(sdk, { VERCEL_TOKEN: 'partial' }), /Incomplete/);
  assert.equal(state.created, 0);
});
test('OIDC is explicit and unrelated host secrets are excluded', () => {
  const oidc = 'header.' + Buffer.from(JSON.stringify({ owner_id: 'team', project_id: 'project' })).toString('base64url') + '.signature';
  assert.deepEqual(credentials({ VERCEL_OIDC_TOKEN: oidc, DATABASE_URL: 'secret' }),
    { token: oidc, teamId: 'team', projectId: 'project' });
  assert.throws(() => credentials({ VERCEL_OIDC_TOKEN: 'invalid' }), /Invalid/);
});
test('all fixed probes pass with positive marker control and both VMs deleted', async () => {
  const { sdk, state } = fake();
  const result = await smoke(sdk, auth);
  assert.equal(result.timeoutCauseVerified, false);
  assert.equal(result.boundedLoopTerminationObserved, true);
  assert.equal(result.learnerExecutionAccepted, false);
  assert.deepEqual(state.deleted, [1, 2]);
  assert.deepEqual(state.sources.slice(-2), [[2, MARKER_ABSENT], [1, MARKER_PRESENT]]);
});
for (const source of [NETWORK_PROBE, SECRET_PROBE, LOOP_PROBE, LOOP_GONE, MARKER_ABSENT, MARKER_PRESENT]) {
  test('command failure fails closed and deletes each created VM: ' + markers.get(source), async () => {
    const { sdk, state } = fake({ failSource: source });
    await assert.rejects(smoke(sdk, auth), /command failed/);
    assert.equal(state.deleted.length, state.created);
  });
}
test('second creation failure cleans first VM', async () => {
  const { sdk, state } = fake({ failCreate: 2 });
  await assert.rejects(smoke(sdk, auth), /create failed/);
  assert.deepEqual(state.deleted, [1]);
});
test('cleanup attempts second VM even if first deletion fails', async () => {
  const { sdk, state } = fake({ failDelete: 1 });
  await assert.rejects(smoke(sdk, auth), /cleanup failed/);
  assert.deepEqual(state.deleted, [1, 2]);
});
for (const exit of [0, null, "unknown"]) {
  test('loop requires explicit nonzero terminal result: ' + exit, async () => {
    const { sdk, state } = fake({ loopExit: exit });
    await assert.rejects(smoke(sdk, auth), /termination not observed/);
    assert.deepEqual(state.deleted, [1]);
  });
}
// Exercise the fixed Python's decisions without making any real network requests.
for (const [tcpBlocked, dnsBlocked] of [[true, true], [true, false], [false, true], [false, false]]) {
  test(`fixed Python requires both denials: tcp=${tcpBlocked}, dns=${dnsBlocked}`, async () => {
    const { spawnSync } = await import('node:child_process');
    const setup = `import socket\nfrom unittest.mock import patch\n`;
    const script = setup + `\nclass FakeSocket:\n` +
      `    def __enter__(self): return self\n` +
      `    def __exit__(self, *args): pass\n` +
      `    def settimeout(self, timeout): pass\n` +
      `    def connect(self, address):\n` +
      (tcpBlocked ? `        raise OSError("blocked")\n` : `        pass\n`) +
      `\nwith patch('socket.socket', return_value=FakeSocket()), patch('socket.getaddrinfo', ` +
      (dnsBlocked ? `side_effect=OSError('blocked')` : `return_value=[]`) + `):\n` +
      `    exec(${JSON.stringify(NETWORK_PROBE)})\n`;
    const result = spawnSync('python3', ['-I', '-c', script], { encoding: 'utf8', timeout: 5000 });
    assert.equal(result.status, tcpBlocked && dnsBlocked ? 0 : 1, result.stderr);
    assert.equal(result.stdout, tcpBlocked && dnsBlocked ? 'VIVA_NETWORK_BLOCKED\n' : '');
  });
}

for (const key of ['VCC_GNANI_API_KEY', 'VCC_GROQ_API_KEY', 'VCC_INTERNAL_WORKER_SECRET', 'VERCEL_OIDC_TOKEN', 'VERCEL_TOKEN', 'GNANI_API_KEY', 'GNANI_STT_API_KEY',
  'GNANI_TTS_API_KEY', 'SUPABASE_SERVICE_ROLE_KEY', 'DATABASE_URL']) {
  for (const value of ['local-test-secret', '']) {
    test(`selected-secret Python rejects presence including empty values: ${key}, empty=${value === ''}`, async () => {
      const { spawnSync } = await import('node:child_process');
      const result = spawnSync('python3', ['-I', '-c', SECRET_PROBE], {
        encoding: 'utf8', timeout: 5000, env: { PATH: process.env.PATH, [key]: value },
      });
      assert.equal(result.status, 1, result.stderr);
      assert.equal(result.stdout, '');
      assert.equal(result.stderr, '');
    });
  }
}
test('selected-secret Python passes when selected names absent without exposing unrelated values', async () => {
  const { spawnSync } = await import('node:child_process');
  const result = spawnSync('python3', ['-I', '-c', SECRET_PROBE], {
    encoding: 'utf8', timeout: 5000,
    env: { PATH: process.env.PATH, UNRELATED_TEST_VALUE: 'must-not-be-printed' },
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, 'VIVA_SELECTED_SECRETS_ABSENT\n');
  assert.equal(result.stderr, '');
});
