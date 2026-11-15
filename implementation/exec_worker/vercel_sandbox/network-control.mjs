/** Fixed benign allow-all connectivity control; never executes learner code. */
import { pathToFileURL } from 'node:url';
import { credentials } from './smoke.mjs';

const source = `import socket
socket.setdefaulttimeout(3)
socket.getaddrinfo("example.com", 443)
with socket.create_connection(("1.1.1.1", 443), timeout=3):
    pass
print("NETWORK_CONTROL_OK")`;

export async function networkControl(Sandbox, env = process.env) {
  const sandbox = await Sandbox.create({
    ...credentials(env), image: 'vercel/sandbox/universal', persistent: false,
    timeout: 30_000, resources: { vcpus: 1 }, networkPolicy: 'allow-all',
    ports: [], env: {}, signal: AbortSignal.timeout(45_000),
  });
  try {
    const result = await sandbox.runCommand({cmd: 'python3', args: ['-I', '-c', source],
      timeoutMs: 8_000, signal: AbortSignal.timeout(12_000)});
    return {status: 'CONTROL_ONLY', tcpAndDnsSucceeded:
      result.exitCode === 0 && await result.stdout() === 'NETWORK_CONTROL_OK\n'};
  } finally {
    await sandbox.delete({signal: AbortSignal.timeout(10_000)});
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    credentials(process.env);
    const {Sandbox} = await import('@vercel/sandbox');
    console.log(JSON.stringify(await networkControl(Sandbox)));
  } catch {
    console.error('Sandbox control failed; creation, execution or cleanup was not verified.');
    process.exitCode = 1;
  }
}
