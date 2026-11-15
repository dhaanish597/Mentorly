const STORAGE_KEY = 'viva.microphone-input.v1';
const MAX_DEVICE_ID_LENGTH = 1024;
const MAX_SERIALIZED_LENGTH = MAX_DEVICE_ID_LENGTH * 6 + 2;

function isDeviceId(value: unknown): value is string {
  return typeof value === 'string' && value.length <= MAX_DEVICE_ID_LENGTH
    && value.trim().length > 0 && !/[\u0000-\u001f\u007f]/.test(value);
}
function parseDeviceId(raw: string | null | undefined): string | null {
  if (!raw || raw.length > MAX_SERIALIZED_LENGTH) return null;
  try {
    const value: unknown = JSON.parse(raw);
    return isDeviceId(value) ? value : null;
  } catch { return null; /* Malformed preferences must not select a microphone. */ }
}

/** Device preference only: no labels, audio, credentials, or permission/consent. */
export function loadInputDeviceId(storage?: Pick<Storage, 'getItem'>): string | null {
  try {
    const target = storage ?? (typeof window === 'undefined' ? undefined : window.localStorage);
    return parseDeviceId(target?.getItem(STORAGE_KEY));
  } catch { return null; /* Storage denial uses the system default, without requesting capture. */ }
}
export function saveInputDeviceId(id: string | null, storage?: Pick<Storage, 'setItem' | 'removeItem'>): boolean {
  if (id !== null && !isDeviceId(id)) return false;
  try {
    const target = storage ?? (typeof window === 'undefined' ? undefined : window.localStorage);
    if (!target) return false;
    if (id === null) target.removeItem(STORAGE_KEY);
    else target.setItem(STORAGE_KEY, JSON.stringify(id));
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(STORAGE_KEY, { detail: id }));
    return true;
  } catch { return false; /* Caller must report that persistence failed. */ }
}
export function subscribeInputDeviceId(receive: (id: string | null) => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const local = (event: Event) => {
    const id: unknown = (event as CustomEvent<unknown>).detail;
    receive(isDeviceId(id) ? id : null);
  };
  const crossTab = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY && event.key !== null) return;
    try { if (event.storageArea && event.storageArea !== window.localStorage) return; }
    catch { return; /* An inaccessible storage area cannot be trusted as this preference store. */ }
    receive(parseDeviceId(event.newValue));
  };
  window.addEventListener(STORAGE_KEY, local);
  window.addEventListener('storage', crossTab);
  return () => {
    window.removeEventListener(STORAGE_KEY, local);
    window.removeEventListener('storage', crossTab);
  };
}
