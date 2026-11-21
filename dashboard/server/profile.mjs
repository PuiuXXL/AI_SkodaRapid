import {mkdir, readFile, rename, writeFile} from "node:fs/promises";
import {dirname} from "node:path";
import {randomUUID} from "node:crypto";

export const genres = ["pop", "rock", "electronic", "jazz", "classical", "lofi", "acoustic", "dance", "hiphop", "kids"];
export const defaultProfile = {
  id: "andrei", name: "Andrei", role: "adult", revision: 0,
  music_genres: ["rock", "pop"], preferences: {talkativeness: "normal", volume: 0.4},
  safe_contact: {name: ""}, emergency_contact: {name: ""},
  consent: {safe_contact_notify: false}, announce: true, youtube_tracks: []
};

export class InputError extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}
function label(value, max, required = false) {
  if (typeof value !== "string" || value.length > max || (required && !value.trim())) {
    throw new InputError("Verifică numele și lungimea câmpurilor.");
  }
  return value.trim();
}
export function validateProfile(input) {
  const name = label(input?.name, 60, true);
  const safeName = label(input.safe_contact?.name, 60);
  const emergencyName = label(input.emergency_contact?.name, 60);
  const {talkativeness, volume} = input.preferences ?? {};
  const consent = input.consent?.safe_contact_notify;
  if (!["low", "normal", "high"].includes(talkativeness) || !Number.isFinite(volume) || volume < 0 || volume > 1) throw new InputError("Preferințe audio invalide.");
  if (typeof consent !== "boolean" || typeof input.announce !== "boolean" || (consent && !safeName)) throw new InputError("Completează numele contactului înainte de acord.");
  if (!Array.isArray(input.music_genres) || input.music_genres.some(g => !genres.includes(g))) throw new InputError("Gen muzical necunoscut.");
  if (!Array.isArray(input.youtube_tracks) || input.youtube_tracks.length > 40) throw new InputError("Poți salva cel mult 40 de piese.");
  const tracks = input.youtube_tracks.map(t => {
    if (!/^[\w-]{11}$/.test(t?.id ?? "") || !genres.includes(t.genre)) throw new InputError("Piesă YouTube invalidă.");
    return {id: t.id, title: label(t.title, 120, true), genre: t.genre};
  });
  if (new Set(tracks.map(t => t.id)).size !== tracks.length) throw new InputError("Piesa este deja în bibliotecă.");
  return {name, music_genres: [...new Set(input.music_genres)], preferences: {talkativeness, volume},
    safe_contact: {name: safeName}, emergency_contact: {name: emergencyName}, consent: {safe_contact_notify: consent},
    announce: input.announce, youtube_tracks: tracks};
}
export function profileStore(file) {
  let tail = Promise.resolve();
  async function load() {
    try {
      const stored = JSON.parse(await readFile(file, "utf8"));
      return {...structuredClone(defaultProfile), ...stored, id: defaultProfile.id,
        preferences: {...defaultProfile.preferences, ...stored.preferences}, revision: stored.revision ?? 1};
    } catch (err) { if (err.code === "ENOENT") return structuredClone(defaultProfile); throw err; }
  }
  function save(input) {
    const work = tail.then(async () => {
      const current = await load();
      if (input.revision !== current.revision) throw new InputError("Profilul a fost modificat în altă fereastră. Reîncarcă profilul înainte să salvezi.", 409);
      const clean = validateProfile(input);
      const next = {...current, ...clean, preferences: {...current.preferences, ...clean.preferences}, revision: current.revision + 1};
      await mkdir(dirname(file), {recursive: true});
      const temp = file + "." + randomUUID() + ".tmp";
      await writeFile(temp, JSON.stringify(next, null, 2) + "\n", {mode: 0o600});
      await rename(temp, file);
      return next;
    });
    tail = work.catch(() => {});
    return work;
  }
  return {load, save};
}
