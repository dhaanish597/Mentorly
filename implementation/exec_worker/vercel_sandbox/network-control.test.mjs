import {test} from 'node:test';
import assert from 'node:assert/strict';
import {networkControl} from './network-control.mjs';
const env = {VERCEL_TOKEN:'test', VERCEL_TEAM_ID:'team', VERCEL_PROJECT_ID:'project'};

test('uses fixed allow-all control, no guest credentials and cleans up', async () => {
  let config, command, deleted = false;
  const Sandbox = {create: async options => {config = options; return {
    runCommand: async value => {command = value; return {exitCode: 0, stdout: async () => 'NETWORK_CONTROL_OK\n'};},
    delete: async () => {deleted = true;},
  };}};
  assert.deepEqual(await networkControl(Sandbox, env), {status:'CONTROL_ONLY',tcpAndDnsSucceeded:true});
  assert.equal(config.networkPolicy, 'allow-all');
  assert.deepEqual(config.env, {});
  assert.deepEqual(config.ports, []);
  assert.equal(config.persistent, false);
  assert.equal(command.cmd, 'python3');
  assert.equal(deleted, true);
});

test('failure does not claim control success and still cleans up', async () => {
  let deleted = false;
  const Sandbox = {create: async () => ({
    runCommand: async () => ({exitCode: 1, stdout: async () => ''}),
    delete: async () => {deleted = true;},
  })};
  assert.equal((await networkControl(Sandbox, env)).tcpAndDnsSucceeded, false);
  assert.equal(deleted, true);
});

test('command and stdout errors trigger cleanup without reporting success', async () => {
  for (const stage of ['command', 'stdout']) {
    let deleted = false;
    const Sandbox = {create: async () => ({
      runCommand: async () => {
        if (stage === 'command') throw new Error('command error');
        return {exitCode: 0, stdout: async () => { throw new Error('stdout error'); }};
      },
      delete: async () => {deleted = true;},
    })};
    await assert.rejects(networkControl(Sandbox, env));
    assert.equal(deleted, true);
  }
});

test('cleanup error prevents a success result', async () => {
  const Sandbox = {create: async () => ({
    runCommand: async () => ({exitCode: 0, stdout: async () => 'NETWORK_CONTROL_OK\n'}),
    delete: async () => {throw new Error('cleanup error');},
  })};
  await assert.rejects(networkControl(Sandbox, env), /cleanup error/);
});
