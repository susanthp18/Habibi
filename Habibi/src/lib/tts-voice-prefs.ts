/** Local favorites / recently-used Azure TTS ShortNames for the voice picker. */

const FAVORITES_KEY = "habibi.ttsVoiceFavorites";
const RECENT_KEY = "habibi.ttsVoiceRecent";
const MAX_RECENT = 8;
const MAX_FAVORITES = 24;

function readStringArray(key: string): string[] {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === "string" && x.trim().length > 0);
  } catch {
    return [];
  }
}

function writeStringArray(key: string, values: string[]) {
  try {
    localStorage.setItem(key, JSON.stringify(values));
  } catch {
    /* ignore quota / private mode */
  }
}

export function loadTtsFavorites(): string[] {
  return readStringArray(FAVORITES_KEY).slice(0, MAX_FAVORITES);
}

export function loadTtsRecent(): string[] {
  return readStringArray(RECENT_KEY).slice(0, MAX_RECENT);
}

export function toggleTtsFavorite(shortName: string): string[] {
  const sn = shortName.trim();
  if (!sn) return loadTtsFavorites();
  const cur = loadTtsFavorites();
  const next = cur.includes(sn) ? cur.filter((x) => x !== sn) : [sn, ...cur].slice(0, MAX_FAVORITES);
  writeStringArray(FAVORITES_KEY, next);
  return next;
}

export function pushTtsRecent(shortName: string): string[] {
  const sn = shortName.trim();
  if (!sn) return loadTtsRecent();
  const next = [sn, ...loadTtsRecent().filter((x) => x !== sn)].slice(0, MAX_RECENT);
  writeStringArray(RECENT_KEY, next);
  return next;
}
