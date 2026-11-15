/** Explicit local development recovery only. Never changes production API URLs. */
export function developmentApiTarget(target: string, replacements: Readonly<Record<string, string>>): string {
  const replacement = replacements[target.replace(/\/$/, '')];
  if (!replacement) return target;
  const isSafeLoopback = (value: string): boolean => {
    try {
      const url = new URL(value);
      return url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
        && !url.username && !url.password && !url.search && !url.hash && url.pathname === '/';
    } catch { return false; }
  };
  if (!isSafeLoopback(target) || !isSafeLoopback(replacement)) throw new Error('Development backend recovery must use credential-free loopback origins.');
  return replacement;
}
