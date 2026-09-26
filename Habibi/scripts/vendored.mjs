/**
 * Source trees that are generated from vendored code and therefore exempt from
 * the house-style gates (file size, layering, type and spacing scales, ...).
 *
 * src/agentstudio is produced by scripts/port-agentstudio.mjs from the
 * AgentStudio engine's UI; it is kept byte-for-byte reproducible so engine
 * upgrades can be re-ported. Host code that wires it in (src/agentstudio-host,
 * src/routes/_app.studio*) is ours and is gated like everything else.
 */
import { sep } from "node:path";

const VENDORED = [`${sep}src${sep}agentstudio${sep}`];

export function isVendored(fullPath) {
  const p = `${fullPath}${sep}`;
  return VENDORED.some((v) => p.includes(v));
}
