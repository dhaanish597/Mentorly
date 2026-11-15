/** Fixed-code connectivity probe only. Never accepts learner source or network input. */
import { pathToFileURL } from 'node:url';

export function credentials(env) {
  const supplied = ['VERCEL_TOKEN', 'VERCEL_TEAM_ID', 'VERCEL_PROJECT_ID']
    .map(key => typeof env[key] === 'string' ? env[key].trim() : '');
  if (supplied.some(Boolean)) {
    if (!supplied.every(Boolean)) throw new Error('Incomplete Vercel access-token credentials');
    return { token: supplied[0], teamId: supplied[1], projectId: supplied[2] };
  }
  if (typeof env.VERCEL_OIDC_TOKEN === 'string' && env.VERCEL_OIDC_TOKEN.trim()) {
    // Match SDK credential extraction; the API verifies the token signature.
    let claims;
    try { claims = JSON.parse(Buffer.from(env.VERCEL_OIDC_TOKEN.split('.')[1], 'base64url')); }
    catch { throw new Error('Invalid Vercel OIDC credentials'); }
    if (typeof claims.owner_id !== 'string' || !claims.owner_id ||
        typeof claims.project_id !== 'string' || !claims.project_id) {
      throw new Error('Invalid Vercel OIDC credentials');
    }
    return { token: env.VERCEL_OIDC_TOKEN.trim(), teamId: claims.owner_id, projectId: claims.project_id };
  }
  throw new Error('Vercel credentials unavailable; no sandbox created');
}

// This code is constant: no user-provided destinations, source, or arguments.
export const NETWORK_PROBE = `import signal
import socket

def expired(signum, frame):
    raise TimeoutError("probe deadline")

signal.signal(signal.SIGALRM, expired)
blocked = []
for check in ("tcp", "dns"):
    signal.alarm(2)
    try:
        if check == "tcp":
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conn:
                conn.settimeout(1)
                conn.connect(("1.1.1.1", 443))
        else:
            socket.getaddrinfo("example.com", 443)
    except (OSError, TimeoutError):
        blocked.append(check)
    finally:
        signal.alarm(0)
if blocked != ["tcp", "dns"]:
    raise SystemExit(1)
print("VIVA_NETWORK_BLOCKED")
`;

export const SECRET_PROBE = `import os
keys = ("VCC_GNANI_API_KEY", "VCC_GROQ_API_KEY", "VCC_INTERNAL_WORKER_SECRET", "VERCEL_OIDC_TOKEN", "VERCEL_TOKEN", "GNANI_API_KEY", "GNANI_STT_API_KEY", "GNANI_TTS_API_KEY", "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL")
if any(key in os.environ for key in keys):
    raise SystemExit(1)
print("VIVA_SELECTED_SECRETS_ABSENT")`;
export const MARKER_WRITE = 'from pathlib import Path; Path("/tmp/viva-fixed-probe-marker").write_text("VIVA_FIXED_MARKER"); print("VIVA_MARKER_WRITTEN")';
export const MARKER_ABSENT = 'from pathlib import Path; assert not Path("/tmp/viva-fixed-probe-marker").exists(); print("VIVA_MARKER_ABSENT")';
export const MARKER_PRESENT = 'from pathlib import Path; assert Path("/tmp/viva-fixed-probe-marker").read_text() == "VIVA_FIXED_MARKER"; print("VIVA_MARKER_PRESENT")';
export const LOOP_PROBE = `import os
from pathlib import Path
Path("/tmp/viva-fixed-probe-pid").write_text(str(os.getpid()))
print("VIVA_LOOP_STARTED", flush=True)
while True:
    pass`;
export const LOOP_GONE = 'from pathlib import Path; pid = int(Path("/tmp/viva-fixed-probe-pid").read_text()); assert not Path("/proc").joinpath(str(pid)).exists(); print("VIVA_LOOP_GONE")';

export async function smoke(Sandbox, env = process.env) {
  const auth = credentials(env);
  const create = () => Sandbox.create({
    ...auth, image: 'vercel/sandbox/universal', persistent: false,
    timeout: 30_000, resources: { vcpus: 1 }, networkPolicy: 'deny-all',
    ports: [], env: {}, signal: AbortSignal.timeout(45_000),
  });
  const sandboxes = [];
  const run = (sandbox, source, timeoutMs = 2_000) => sandbox.runCommand({
    cmd: 'python3', args: ['-I', '-c', source], timeoutMs,
    signal: AbortSignal.timeout(10_000),
  });
  const expect = async (sandbox, source, marker, timeoutMs) => {
    const result = await run(sandbox, source, timeoutMs);
    if (result.exitCode !== 0 || await result.stdout() !== marker + '\n') {
      throw new Error('Sandbox fixed probe failed');
    }
  };
  try {
    const first = await create();
    sandboxes.push(first);
    await expect(first, 'print("VIVA_SANDBOX_OK")', 'VIVA_SANDBOX_OK');
    await expect(first, NETWORK_PROBE, 'VIVA_NETWORK_BLOCKED', 6_000);
    await expect(first, SECRET_PROBE, 'VIVA_SELECTED_SECRETS_ABSENT');
    const loop = await run(first, LOOP_PROBE, 1_000);
    if (!Number.isInteger(loop.exitCode) || loop.exitCode === 0 ||
        await loop.stdout() !== 'VIVA_LOOP_STARTED\n') {
      throw new Error('Sandbox loop termination not observed');
    }
    await expect(first, LOOP_GONE, 'VIVA_LOOP_GONE');
    await expect(first, MARKER_WRITE, 'VIVA_MARKER_WRITTEN');
    const second = await create();
    sandboxes.push(second);
    await expect(second, MARKER_ABSENT, 'VIVA_MARKER_ABSENT');
    // Positive control: marker must still exist in the first live VM.
    await expect(first, MARKER_PRESENT, 'VIVA_MARKER_PRESENT');
    return {
      status: 'SMOKE_ONLY', networkDenied: true, selectedSecretNamesAbsent: true,
      separateFilesystemObserved: true, boundedLoopTerminationObserved: true,
      loopExitCode: loop.exitCode, timeoutCauseVerified: false,
      timeoutVerificationBlocker: 'SDK result has no termination-cause field',
      learnerExecutionAccepted: false,
    };
  } finally {
    // Attempt every deletion even if one fails; never claim success on cleanup failure.
    const cleanup = await Promise.allSettled(sandboxes.map(sandbox =>
      sandbox.delete({ signal: AbortSignal.timeout(10_000) })));
    if (cleanup.some(result => result.status === 'rejected')) {
      throw new Error('Sandbox cleanup failed');
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    credentials(process.env); // Check before importing SDK or making any API request.
    const { Sandbox } = await import('@vercel/sandbox');
    console.log(JSON.stringify(await smoke(Sandbox)));
  } catch {
    // SDK errors can contain request metadata: never print raw exceptions or credentials.
    console.error('Vercel smoke failed: check credentials, SDK installation, access, and cleanup.');
    process.exitCode = 1;
  }
}
