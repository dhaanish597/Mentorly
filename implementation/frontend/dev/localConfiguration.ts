import defaults from '../../config/local-development.json';

export function localConfiguration(env: Readonly<Record<string, string | undefined>>) {
  const port = (value: string | undefined, fallback: number): number => {
    if (value === undefined) return fallback;
    if (!/^\d+$/.test(value) || Number(value) < 1024 || Number(value) > 65535) throw new Error('Local development ports must be unprivileged integers.');
    return Number(value);
  };
  const host = env.VCC_BACKEND_HOST ?? defaults.backend_host;
  if (!['localhost', '127.0.0.1'].includes(host)) throw new Error('Local development hosts must use explicit loopback origins.');
  return {
    apiTarget: env.VCC_PREVIEW_API_TARGET ?? `http://${host}:${port(env.VCC_BACKEND_PORT, defaults.backend_port)}`,
    frontendPort: port(env.VCC_FRONTEND_PORT, defaults.frontend_port),
  };
}
