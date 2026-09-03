# 21 — Dependency & Software Supply Chain

**Role:** Software supply-chain and dependency architect
**Scope:** Direct and transitive dependencies across both stacks — manifests, lockfiles, resolution, provenance, licensing, and the gates (or absence of gates) between a package and production.
**Method:** Five parallel analysts — JavaScript dependencies, Python dependencies, vulnerabilities, licences, dependency hygiene. Ground truth for the manifest inventory was established first-hand before briefing, and every load-bearing claim in this report was re-verified against the file or the installed metadata by me afterwards. Read-only throughout: no install, no update, no lockfile write, no `audit fix`, no edit to any file but this one.

**What actually ran.** `npm audit --json` (read-only), an **OSV.dev batch query over all 135 installed Python distributions**, `pip check`, `npm ls`, and direct reads of `*.dist-info/METADATA` from the live `backend/.venv`. **OSV-Scanner, Trivy, Grype, Syft, pip-audit and Safety are all absent from this machine**, and none is installed by either CI workflow — the Python scan was possible only because the OSV HTTP API was reachable from this session, not because the repo or the machine can do it. That absence is itself finding **S1**. No container image was built or scanned; the OS layers remain unexamined (§9).

---

## Verdict

The frontend's dependency graph is genuinely well-managed: one lockfile that is in exact sync with its manifest, 587 packages all resolved from `registry.npmjs.org`, every one carrying an integrity hash, and exactly one install script in the entire tree. Someone did this carefully.

The backend's dependency graph — the one that holds borrower PII, moves payments and places the calls — **has no lockfile at all.** 114 of its 134 installed packages, including the whole TLS and deserialization surface, re-resolve against PyPI on every image build.

And the single supply-chain control anybody in this repository wrote — a 24-hour publish-age guard, correctly aimed at exactly the right threat — is configured for a package manager that neither CI nor this machine uses. It protects nothing.

---

## 1. The inventory

Complete, after correcting two omissions in my own first pass (§15).

| Manifest | Tracked | Notes |
|---|---|---|
| `Habibi/package.json` | yes | 58 deps + 19 devDeps = 77 declared |
| `Habibi/package-lock.json` | yes | lockfileVersion 3; 587 install locations, 536 distinct names |
| `Habibi/bun.lock` | yes | **a second lockfile** — 589 entries, last touched 2026-07-22 |
| `Habibi/bunfig.toml` | yes | **the repo's only supply-chain control** |
| `backend/requirements.txt` | yes | 17 direct deps |
| `backend/requirements-voice.txt` | yes | 3 direct deps |
| `backend/requirements-mcp.txt` | yes | 1 direct dep, unbounded; installed by a runbook, not a build (S22) |
| `backend/pyproject.toml` | yes | `[tool.vulture]` only — no `[project]` table |
| `backend/Dockerfile` | yes | two stages, `base` and `voice` |
| `backend/docker-compose.yml` / `.dev.yml` | yes | five app services |
| `PRAXIST-main/**` | yes | **4,518 tracked files** — a whole vendored third-party project |
| `.vite/deps/{package.json,_metadata.json}` | yes | committed empty build cache (S23) |

**No Python lockfile exists anywhere** — no `uv.lock`, `poetry.lock`, `Pipfile.lock` or `constraints.txt`, and no hash pinning. **No `.npmrc`, no `packageManager`, no `engines`, no `.nvmrc`, no `overrides`, no `resolutions`.**

---

## 2. The map: how a package reaches production

```
       JAVASCRIPT                              PYTHON
  package.json (77 caret ranges)          requirements.txt (17)
        |                                 requirements-voice.txt (3)
        +-- package-lock.json  [live]           |
        +-- bun.lock           [stale]          |  (no lockfile, no hashes)
        |                                       |
  CI: npm ci  -> tsc, vitest, lint        CI: pip install -r ...
      (NO npm audit)                          (NO pip-audit)
      (NO npm run build)                       |
        |                                 backend/Dockerfile:20  (base)
  no frontend Dockerfile                  backend/Dockerfile:41  (voice)
  no frontend compose service                  |
        |                                 api / worker / bot_worker  [base]
  nitro bundle -> Cloudflare (default)     voice / voice_insurance   [voice]
```

Two facts about this diagram carry most of the report. **Nothing on either path runs a vulnerability scanner.** And the Python path has no lockfile between the manifest and the image, so the right-hand column is re-resolved from scratch every time anyone builds.

---

## 3. S1 (P0) — No dependency-vulnerability gate exists on any path

Neither workflow runs `npm audit`, `pip-audit`, `safety`, or any SCA scanner. There is no `.github/dependabot.yml`, no `renovate.json`, no root `CONTRIBUTING.md`, and no ADR touching dependencies (`docs/adr/` holds only `0001-one-owner-for-the-tool-grant.md` and `0002-cardless-agents-are-denied-every-tool.md`). No scanner is installed on this machine either.

The consequence is exact and worth stating plainly: **a CVE disclosed tomorrow against any of the 587 npm packages or the 134 Python distributions would be noticed by no mechanism in this repository, ever.** Not late — never. Every other finding in this report was found by a person looking; nothing here finds them on its own.

The cheapest possible fix is one step in each workflow. `npm audit --audit-level=high` and `pip-audit` would today report everything in §9 — five npm advisories with non-breaking fixes, 21 unpatched advisories in `nltk`, and a one-patch-version `aiohttp` gap. None of it is exotic; nobody was told.

---

## 4. S2 (P0) — No Python lockfile: 85% of the backend runtime is unpinned

`backend/requirements.txt:1-3` opens with a clear statement of intent:

> `# Known-good pins from the local venv (optimization Tier 0).`
> `# Bump deliberately after testing — do not leave floating majors in prod.`

And `backend/requirements-voice.txt:11-13` names the exact failure mode:

> `# Pinned, not floating: an unpinned >= means a Pipecat release can change the`
> `# voice runtime inside an image rebuild with no code change and no review.`

Both are right. Neither is enforced by anything.

The backend manifests declare **21 direct dependencies**. `backend/.venv` contains **134 distributions**. The other **114 — 85% of the tree — are constrained nowhere in the repository.** `backend/Dockerfile:20` and `:41` run plain `pip install -r`, with no lock, no constraints file, and no `--require-hashes`, so all 114 resolve fresh against PyPI at image-build time.

That set is not incidental. It includes `cryptography`, `pyopenssl`, `urllib3`, `requests`, `aiohttp`, `certifi`, `pydantic-core`, `protobuf` and `onnxruntime` — the entire TLS and deserialization surface of a system that handles collections calls. Two images built from the same git commit a month apart are not the same image, and nothing in the repo can tell you how they differ.

This is what makes S5, S11 and S12 unrecoverable rather than merely untidy: there is no artifact that records what was actually shipped. It is also why the two real Python vulnerabilities in §9 (S7, S8) sit in versions that **no manifest in this repository names**.

---

## 5. S3 (P1) — The only supply-chain control that exists is inert

This is the sharpest finding in the audit, and it is not a missing control. It is a control that was designed, reasoned about, written down, and then orphaned.

`Habibi/bunfig.toml` in full:

```toml
[install]
saveTextLockfile = true
# 24h supply-chain guard: skip package versions published less than a day ago.
minimumReleaseAge = 86400
# Each entry bypasses the 24h guard for one package — confirm with the user
# before adding any.
minimumReleaseAgeExcludes = ["@lovable.dev/vite-tanstack-config", ...]
```

`minimumReleaseAge = 86400` is a genuine defence against the compromised-publish window — the interval during which a hijacked maintainer account's malicious release is live but not yet reported. It is aimed at precisely the right threat, and the allowlist even carries a review discipline ("confirm with the user before adding any").

**It is bun-only configuration.** CI installs with `npm ci` (`.github/workflows/frontend-typecheck.yml:30`); npm does not read `bunfig.toml`. **`bun` is not installed on this machine.** Every path that actually installs a package ignores this file.

Two details sharpen it further. The allowlist that waives the guard contains six packages, all from the same vendor — and first on the list is `@lovable.dev/vite-tanstack-config`, which `Habibi/vite.config.ts:7` shows is *the only import in the entire Vite config*, composing the whole build. It is declared as a caret range (`package.json:80` `^2.7.6`) against a package publishing several releases a day. So the guard is disabled for the highest-blast-radius dependency in the tree — a defensible trade if the config and platform ship together, but one that should be a documented risk acceptance rather than a line in a TOML file.

---

## 6. S4 (P1) — Two tracked lockfiles, diverging on 206 packages

Both `Habibi/package-lock.json` and `Habibi/bun.lock` are tracked. There is no `packageManager` field to say which is correct, and npm, pnpm and yarn are all installed on this machine.

Git settles which is live:

| file | last commit | date |
|---|---|---|
| `Habibi/bun.lock` | `ccc8070` initial commit | **2026-07-22** |
| `Habibi/package.json` | `e6da33b` | 2026-08-30 |
| `Habibi/package-lock.json` | `e6da33b` | 2026-08-30 |

The manifest and the npm lock last moved **in the same commit** — npm's lock is live and exactly in sync. `bun.lock` has not been touched in 39 days across five later manifest commits.

The drift is not cosmetic. **206 shared packages resolve to different versions**, and 8 declared dependencies are missing from `bun.lock` entirely: `@pipecat-ai/client-js`, `@pipecat-ai/client-react`, `@pipecat-ai/small-webrtc-transport`, `@tanstack/react-virtual`, `@xyflow/react`, `liveline`, `sharp`, `vitest`. That is the **entire Pipecat voice-client stack** — the browser half of the regulated channel — plus the flow canvas and the test runner. React differs (19.2.7 vs 19.2.5), vite differs (8.1.5 vs 8.0.16), all 28 Radix packages differ, and `chalk` differs by a major.

Anyone running `bun install` gets a tree that cannot build the app. The failure would be loud, which caps this below P0.

**One consequence is sharper than staleness, though.** `bun.lock` resolves *older* versions of precisely the five packages `npm audit` flags in §9 — `brace-expansion` 1.1.14, `browserslist` 4.28.2, `js-yaml` 4.1.1, `nanoid` 3.3.12, `postcss` 8.5.15 — and every one of them is **still inside the vulnerable range**. `npm audit` reads `package-lock.json` only, so that second tree is invisible to the scanner today and would stay invisible to the CI gate recommended in S1. Two lockfiles is also two integrity surfaces: a poisoned resolution in `bun.lock` would never surface in an audit result. But the standing invitation to resolve 587 packages off an unreviewed graph is real, and `bun.lock` is itself the proof that someone has already installed with a second package manager once.

`packageManager: "npm@10.9.2"` is the one line that would have prevented it.

---

## 7. S5 (P1) — The "known-good pins from the local venv" come from a different interpreter

`backend/.venv/pyvenv.cfg:4` reads `version = 3.14.3`. `backend/Dockerfile:5` is `FROM python:3.12-slim`. `.github/workflows/backend-pytest.yml:74` is `python-version: "3.12"`.

So the venv that `requirements.txt:2` calls the source of its known-good pins runs an interpreter **two minor versions ahead of both the image and CI**, and the product never runs it.

This is not merely untidy, because environment markers resolve differently per Python version, so the container's transitive closure genuinely differs from the one developed against. Confirmed from installed metadata: `fastembed 0.8.0` requires `numpy>=2.3.0` on Python ≥3.14 but only `numpy>=1.26` on 3.12, and `onnxruntime>=1.24.2` on ≥3.14 against a floor seven minor versions lower on 3.12. `audioop-lts` is installed at all only because pipecat requires it under `python_version >= "3.13"`.

`backend/pyproject.toml` has no `[project]` table, so **`requires-python` is declared nowhere in the repository** — which is exactly why nothing caught this. A single `requires-python = ">=3.12,<3.13"` would have made venv creation fail on 3.14. It is the cheapest available mitigation for the largest finding.

---

## 8. S6 (P1) — PRAXIST-main: 4,518 files under a revenue-gated licence, redistributed by the submission script

`PRAXIST-main/` is a complete third-party project vendored in-tree: **4,518 tracked files**, its own `pyproject.toml` (`name = "praxist"`, `version = "0.5.0"`), and `PRAXIST-main/LICENSE.md` — a **Fair Source License Agreement v1.0** from Sapient Intelligence Pte Ltd. Source-available, not open source. The operative clauses:

- **§1.2.1** grants use only "for internal business purposes" and deployment "within its own organization."
- **§1.2.3** forbids distributing, sublicensing, selling or transferring the Software to any third party without prior written consent — with a carve-out for providing its *functionality* as part of your own service.
- **§1.3.1-1.3.3** make the free licence conditional on the Licensee's and its Affiliates' worldwide gross revenue being **under USD $1,000,000**; on crossing it the licence "shall automatically lapse," with 30 days to notify and 90 to terminate.
- **§1.9.2** makes failure to notify an **incurable material breach**.

**What I could prove reduces this considerably, and the accurate version matters more than the alarming one.** PRAXIST cannot reach any container image. Every service in `backend/docker-compose.yml` builds with `context: .` rooted at `backend/` (`:73-76`, `:134-137`, `:163-166`, `:187-190`, `:221-224`), and `PRAXIST-main/` is a sibling of `backend/` at the repo root — outside every build context. `Habibi/` has no Dockerfile at all. Nothing in `backend/*.py` imports it, and `praxist` is not installed in `backend/.venv`. So: stored in the repo, yes; executed locally, yes (`__pycache__` exists throughout its tree); **shipped in any artifact this repo builds, no.**

**The exception is real, though, and it is one line to fix.** `_make_submission_zip.py:100` walks `ROOT.rglob("*")` over all of `D:\Hackathon`, and `SKIP_DIR_NAMES` (`:11-31`) does **not** contain `PRAXIST-main`. Running it produces a zip containing all 4,518 PRAXIST files and hands them to a third party. That is redistribution of the Software under §1.2.3. Adding `"PRAXIST-main"` to that set closes it.

Credit where due: the same script is careful about secrets — `SKIP_ENV_NAMES` at `:63` under the comment `# Never ship secrets`, with `.env.example` explicitly re-allowed at `:88`.

---

## 9. Vulnerabilities

Two independent scans ran, both read-only: `npm audit --json` against the frontend lockfile, and an **OSV.dev batch query covering all 135 installed Python distributions** (`api.osv.dev/v1/querybatch`, HTTP 200). Four Python packages returned advisories — `nltk`, `aiohttp`, `cryptography` and `pip` (S7, S8, S10, S29). The other 131 returned none.

One caveat governs the Python results: OSV was queried against `backend/.venv`, which is a **Windows dev venv on Python 3.14** — not the Linux 3.12 image the product ships (S5). The versions below are what a developer runs. The image resolves separately and has never been scanned at all.

### S7 (P1) — `nltk 3.10.0` carries 21 advisories, is a core pipecat dependency, and downloads at import on the voice path

The most serious vulnerability finding in the audit, and the team did not choose the dependency.

`nltk 3.10.0` is installed. `pipecat_ai-1.6.0`'s metadata declares `Requires-Dist: nltk<4,>=3.10.0` — a **core** requirement, not an extra — so `backend/requirements-voice.txt:25` pulls it into the voice image unavoidably. OSV returns **21 advisories** against 3.10.0, essentially all fixed in **3.10.3**. Among them:

| ID | Nature |
|---|---|
| [GHSA-m4rf-3fr8-xwx3](https://osv.dev/vulnerability/GHSA-m4rf-3fr8-xwx3) / CVE-2026-79675 | **CRITICAL** — JVM argument injection in the Stanford wrappers |
| PYSEC-2026-3733 / CVE-2026-78682 | **SSRF in `nltk.pathsec.urlopen`** — callers include `nltk.data.load` and `Downloader.download` |
| [GHSA-f794-5jv7-7672](https://osv.dev/vulnerability/GHSA-f794-5jv7-7672) / CVE-2026-81727 | `Downloader.download` follows hardlinks, overwriting files outside the install root |
| PYSEC-2026-3735 / CVE-2026-79657 | RCE in allowlisted pickle loaders trusting whole module namespaces |
| [GHSA-6hwm-xvph-95vm](https://osv.dev/vulnerability/GHSA-6hwm-xvph-95vm) | Uncontrolled search path invoking Graphviz `dot` |
| + 16 more | XXE, path traversal, and ReDoS/quadratic-CPU in corpus readers and stemmers |

**Reachability was measured, not argued.** `backend/.venv/Lib/site-packages/pipecat/utils/string.py` does this at **module scope** — verified first-hand:

```python
import nltk
from nltk.tokenize import sent_tokenize

# Ensure punkt_tab tokenizer data is available
try:
    nltk.data.find("tokenizers/punkt_tab")
except LookupError:
    try:
        nltk.download("punkt_tab", quiet=True)
```

That module is the sentence-boundary detector for bot speech, imported by pipecat's core voice path (`simple_text_aggregator.py`, `processors/aggregators/sentence.py`, the RTVI observer). It is neither optional nor lazy. **On any voice container that does not pre-bake `nltk_data`, process start performs a network download through `Downloader.download`** — the exact function named by the SSRF and hardlink-overwrite advisories. For an on-prem bank behind an egress proxy that is also an undeclared startup dependency on an external host, which is its own problem.

**What is honestly *not* reachable:** the CRITICAL JVM-injection advisory needs the Stanford wrappers, which nothing here touches; the ReDoS family sits in corpus readers and stemmers that pipecat never calls, since it uses only `sent_tokenize`. The pickle-loader RCE is ambiguous — nltk 3.10.0 ships a `RestrictedUnpickler` and pipecat requests the non-pickle `punkt_tab` format, so I am **declining to claim that path is exploitable here.**

The rank is P1 not because a borrower can exploit it today, but because the most regulated surface in the product carries 21 unpatched advisories on a code path that runs at process start — and the fix is one line. `nltk>=3.10.3` sits comfortably inside pipecat's `<4` bound.

### S8 (P2) — `aiohttp 3.14.2`: out-of-bounds heap read in the C response parser

[GHSA-cq5v-8q36-5273](https://osv.dev/vulnerability/GHSA-cq5v-8q36-5273) / CVE-2026-69244, GHSA severity **HIGH**, fixed in **3.14.3** — one patch version away. An OOB heap read while building an error message for a malformed chunked response.

It is a hard requirement of two things on the request path: `pipecat-ai` (`aiohttp<4,>=3.11.12`) and `twilio` (`aiohttp>=3.8.4`, pinned at `backend/requirements.txt:13`). This is a **client-side** bug — it fires on responses, not requests — so the threat model is one of the upstreams this platform calls (Twilio, Deepgram, Azure Speech, the LLM endpoint) returning a malformed chunked body, whether hostile, compromised, or merely mangled by a TLS-terminating corporate proxy. That last case is realistic on-prem. Impact is a crash of the voice worker mid-call, not disclosure. A documented workaround exists (`AIOHTTP_NO_EXTENSIONS=1` forces the unaffected pure-Python parser).

### S9 (P3) — Five npm advisories, all transitive, and none reaches the shipped bundle

`npm audit --json`, 2026-09-02: **587 packages (295 prod / 235 dev / 120 optional). 5 vulnerabilities — 4 high, 1 moderate, 0 critical.** All `isDirect: false`; all `fixAvailable: true`.

| Package | Sev | Advisory | Nature |
|---|---|---|---|
| `brace-expansion` | high | [GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg), [GHSA-rgw5-rvv9-x895](https://github.com/advisories/GHSA-rgw5-rvv9-x895) | DoS via unbounded expansion; the second bypasses the CVE-2026-14257 mitigation |
| `browserslist` | high | [GHSA-c83g-rgw3-j3cx](https://github.com/advisories/GHSA-c83g-rgw3-j3cx), [GHSA-73wf-gq98-2v4g](https://github.com/advisories/GHSA-73wf-gq98-2v4g) | Unbounded memory growth; prototype write via untrusted `browserslist-stats.json` |
| `js-yaml` | high | [GHSA-5p4m-2wfm-xmqj](https://github.com/advisories/GHSA-5p4m-2wfm-xmqj) | Quadratic CPU in `!!omap` (CVE-2026-59870 fix not backported) |
| `nanoid` | high | [GHSA-2v37-7h3g-55p8](https://github.com/advisories/GHSA-2v37-7h3g-55p8) | Custom generators loop indefinitely when size is zero |
| `postcss` | moderate | [GHSA-fxqj-rqcc-2cmp](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp) | Attacker-controlled `sourceMappingURL` reads arbitrary `.map` files |

npm flags four as production-tree, but that is an accounting artefact of build plugins sitting in `dependencies` (§12, S20; and "Checked and cleared") rather than a runtime fact — every chain terminates in build or lint tooling (`browserslist ← @babel/core ← @vitejs/plugin-react`; `postcss`/`nanoid ← vite`; `brace-expansion ← minimatch ← eslint`).

Because this app is SSR rather than a static SPA, that distinction had to be proven rather than assumed. It was: grepping the built server bundle at `Habibi/.output/server` for all five package names returns **zero hits** (the one apparent `nanoid` match is zod's `/^[a-z0-9_-]{21}$/i` format validator). Nothing in `Habibi/src/` imports any of them directly.

So these are CI-runner and developer-workstation DoS vectors, not borrower-data exposure — **P3, downgraded from my initial P2 on that evidence.** What matters is not the five advisories but that nothing in this repository would have mentioned them (S1). One non-breaking `npm audit fix` clears the set.

### S10 (P3) — `cryptography 49.0.0`: confirmed vulnerable, confirmed unreachable

[GHSA-g6cj-pr64-35w5](https://osv.dev/vulnerability/GHSA-g6cj-pr64-35w5) / CVE-2026-69247, GHSA **HIGH** — a Bleichenbacher oracle in PKCS#7 `EnvelopedData` decryption, affecting `>=44.0.0,<50.0.0`.

**No backend code uses PKCS#7** — a grep across all backend Python for `pkcs7`/`PKCS7` returns nothing, and nothing imports `cryptography` directly. It arrives via `aiortc` (DTLS/SRTP) and `pyopenssl`. Recorded precisely *because* a naive scanner report would rank it HIGH and burn a day. Worth noting for whoever does upgrade: `pyopenssl 26.3.0` pins `cryptography<50`, below the fix, so moving to 50.0.0 requires moving pyopenssl too.

### S29 (P3) — `pip 26.1.2` in the dev venv: arbitrary write from a malicious index

[GHSA-qwm4-qh6w-59xr](https://osv.dev/vulnerability/GHSA-qwm4-qh6w-59xr) / CVE-2026-13346, MODERATE, fixed in **26.2.0**. Doubly-encoded package URLs served by an index allow writes to arbitrary disk locations, wheels included.

The fourth of the four Python packages OSV flagged, and the least alarming: it requires a malicious *index*, not a malicious package. CI is unaffected — `.github/workflows/backend-pytest.yml:80` runs `pip install --upgrade pip` before anything else. The exposure is the developer workstation, and any build pointed at a private mirror. Worth one line in the deployment guide if the bank runs its own PyPI mirror, because that mirror then becomes a single point that can write anywhere in the build container.

### What is still unscanned

- **Every image's OS layer.** No inventory exists for `python:3.12-slim`, `redis:7-alpine`, or `pgvector/pgvector:pg16`. This is the single largest unexamined surface in the audit. `trivy image collections-voice:local` after a build would close it.
- **The actual deployed Python tree.** The OSV results above describe a Windows 3.14 venv. Run `pip freeze` *inside the built image* and scan that.
- **The bun tree** — see S4; `npm audit` cannot read `bun.lock`.
- **`mcp`** — declared `>=1.2.0`, installed nowhere, so there was no version to query.
- **Packages with thin advisory coverage** — `liveline@0.0.7`, `@lovable.dev/vite-tanstack-config`, `nitro@3.0.260603-beta` all returned clean, which for a beta and a 0.0.x means "nobody has looked," not "safe."

---

## 10. Licences

**No AGPL and no GPL in anything this repo ships.** That is the finding that would have mattered most, and it is genuinely absent — checked across all 587 npm entries and all 134 Python distributions.

**JavaScript (587 entries).** 461 MIT, 33 Apache-2.0, 32 ISC, 24 MPL-2.0, 10 BSD-2-Clause, 10 LGPL-3.0-or-later, 6 BSD-3-Clause, and a small tail of dual and unusual expressions. **Zero packages with a missing licence field. Zero `SEE LICENSE IN` or `UNLICENSED` entries.** The LGPL block is all `sharp`/libvips, dev-flagged; the MPL block is `lightningcss`, a build-time CSS transformer whose output is not a derivative work. Neither creates an obligation on a shipped artifact — and there is no frontend image anyway.

**Python — three items that do ship.**

- **S15 (P2) — LGPL in every image.** `psycopg 3.3.4` declares `License-Expression: LGPL-3.0-only` (verified in installed metadata) and is pinned at `backend/requirements.txt:6`, so it is in all five service images. `soxr` (LGPL-2.1-or-later) and `num2words` (LGPL) ride along in the voice image via pipecat. LGPL permits proprietary use by import, but **on distribution** it requires notice that LGPL components are included and an offer of their source. Neither exists (S16).
- **S16 (P2) — no third-party NOTICE artifact is produced for anything.** A targeted search returns five `NOTICE`/`THIRD-PARTY` files and every one belongs to the vendored PRAXIST tree. MIT, BSD and ISC each require reproducing the copyright notice in copies; Apache-2.0 §4 requires carrying the NOTICE file. Shipping an image to a bank is a copy. This is the most common gap in commercial software and is fixed mechanically (`license-checker`, `pip-licenses`) — it is P2 chiefly because bank procurement routinely *asks* for this artifact, so its absence stalls deals well before it creates legal exposure.
- **S17 (P2) — a proprietary SDK in the shipped voice image.** `azure-cognitiveservices-speech 1.51.0` carries `Classifier: License :: Other/Proprietary License`. Notably its metadata also ships `licensefiles/speech/REDIST.txt` — Microsoft documents redistribution terms explicitly, so this is a condition to be met rather than an outright bar. Counsel should confirm the terms are satisfied before an image goes to a customer.
- **S18 (P2) — GPL binaries in the voice image.** `backend/Dockerfile:36-37` apt-installs `ffmpeg`, whose Debian build is GPL. Mere aggregation means it does not infect the Python application — they are separate programs — but the GPL's own obligations attach to ffmpeg: written offer of source, licence text reproduced. Same NOTICE gap as S16.
- **S25 (P3) — a GPLv3+ orphan on developer machines only.** `pyyaml-include 1.4.1` declares `License: GPLv3+` (verified) and is installed in `backend/.venv`, but **nothing requires it** — a reverse-dependency scan across all installed metadata returns zero hits, and neither requirements file pulls it. It reaches no image. Worth removing anyway: GPL code sitting in the same environment as proprietary code is how a copyleft package quietly becomes a runtime import later.

**S26 (P3) — the product has no licence of its own.** No root `LICENSE`; `Habibi/package.json` is `"private": true` with no `license` field. For a proprietary vendor that is the conservative default rather than a defect, and `private: true` correctly blocks accidental publication. But a bank receiving source or an image gets code with no accompanying terms. Add `"license": "UNLICENSED"` and a proprietary notice before first delivery.

---

## 11. Python resolution: what the two-file install actually does

I briefed the Python analyst on a hypothesis — that the second `pip install` silently overrides pins set by the first. **The analyst disproved the strong form of it, and the correction is worth recording because the true shape is more useful.**

In a clean `docker build`, pip's default `--upgrade-strategy only-if-needed` means `backend/Dockerfile:41` will *not* upgrade a package that `:20` already installed at a satisfying version. Checking every overlap, **no pin is actually violated in the container today**. `openai==2.46.0` satisfies pipecat's `<3,>=1.74.0`; `httpx==0.28.1` satisfies its consumers; `websockets>=12.0,<16` satisfies pipecat's `>=13.1`.

The real defect is that **the `<16` cap holds by accident, not by enforcement.** Nothing validates it. The second `pip install` never reads the first file and exits 0 regardless. Two pieces of evidence show the gap is live rather than theoretical:

- **The developer venv has already drifted out of its own declared ranges.** `websockets 16.1.1` is installed against `requirements.txt:15`'s `<16`, and `redis 8.0.1` against `:14`'s `<6`. `pip check` reports "No broken requirements found" and exits 0 — because it validates installed packages against each other, and never consults `requirements.txt` at all. **The declared constraint is checked by nothing, anywhere.**
- **There is a loaded instance waiting.** `requirements.txt:31` pins `ruff==0.6.9`. pipecat's `cli` extra declares `ruff<1,>=0.12.1`, and its `evals` extra pulls in `cli`. `requirements-voice.txt:13` explicitly tells the reader to re-run the voice evals after a bump. The day anyone adds `evals` to the extras list on `:25`, the second pip invocation will upgrade ruff past an `==` pin with no error — defeating the comment at `:28-30` that explains why ruff is pinned at all.

One flag makes the whole class loud instead of silent: `pip install -r requirements-voice.txt -c requirements.txt` at `Dockerfile:41`.

### S12 (P2) — redis: developed against 8.x, shipped 5.x, tested 5.x

`backend/requirements.txt:14` declares `redis>=5.0,<6`. The venv has **8.0.1** — two majors past the cap, hand-installed (it carries a pip `REQUESTED` marker; nothing in the tree requires it, since pipecat needs redis only under an extra that is not selected).

This one has teeth because redis is a real runtime dependency: `backend/voice/mesh_bus.py:39` and `backend/voice/workers/insurance.py:193` both `from redis.asyncio import Redis`, and compose runs a `redis:7-alpine` service wired into `api`, `voice` and `voice_insurance`. So **every line of mesh-bus code was written and exercised against redis-py 8.0.1, while the image and CI both install the newest 5.x.** I did not prove a runtime break — the `redis.asyncio.Redis` surface is broadly stable across those majors — and the finding is the untested two-major gap, not a demonstrated failure.

**The `websockets` divergence is symmetric with it, and has a named first-party consumer too.** `backend/voice/ws_proxy.py:41-42` does `import websockets` and `from websockets.exceptions import ConnectionClosed` inside `proxy_voice_websocket()` — the bidirectional bridge between Twilio Media Streams and Pipecat. So both ranged pins in `requirements.txt` behave the same way:

| Package | Dev venv | Container installs | First-party consumer |
|---|---|---|---|
| `redis` (`:14` `>=5.0,<6`) | 8.0.1 | newest 5.x | `voice/mesh_bus.py:39`, `voice/workers/insurance.py:193` |
| `websockets` (`:15` `>=12.0,<16`) | 16.1.1 | newest 15.x | `voice/ws_proxy.py:41-42` |

Both bridges were written and exercised against a major the container will never install, both sit on the voice path, and CI tests only the container's side. `ConnectionClosed` and the top-level client API are precisely the surfaces that moved across those websockets releases — I am not asserting a specific break, but the gap is untested in both directions.

Worth noting *why* this import was easy to miss: it is lazy and indented inside a function, as several imports in this codebase deliberately are (`kb_rerank.py:124`, `mcp_server.py:43`). Any dependency-usage sweep here has to grep unanchored and read each hit in context — an anchored `^import x` pattern will under-report.

### S11 (P2) — an unversioned `fastapi[all]` puts a cloud deploy CLI in the on-prem voice image

Verified end-to-end in installed metadata:

```
requirements-voice.txt:25   pipecat-ai[...,runner,...]==1.6.0
  -> pipecat-ai-prebuilt>=1.0.5          ; extra == "runner"
     -> Requires-Dist: fastapi[all]      <-- no version bound at all
        -> fastapi-cli[standard]
           -> fastapi-cloud-cli>=0.1.1   ; extra == "standard"
              => fastapi_cloud_cli 0.22.2  INSTALLED
```

The `voice` and `voice_insurance` containers ship an authenticating deploy client for a third-party hosting service, reached three levels below anything declared, through a transitive dependency that re-specifies the application's own web framework **with no ceiling**. `requirements-voice.txt:4-5` says the file exists "so CRM API upgrades are not coupled to Pipecat's transitive graph" — the coupling runs the other way, and is unbounded.

A telling detail: `fastapi-cli` publishes a `standard-no-fastapi-cloud-cli` extra for exactly this concern. Nothing on this path can reach it, because the choice is made by `fastapi[all]` two levels up.

For an on-prem bank target, "why does the voice runtime contain a cloud deployment CLI?" has no good answer in the repo.

---

## 12. Hygiene and process

**S13 (P2) — dev tooling and 190 test files ship in all five images.** `backend/Dockerfile:20` installs `requirements.txt`, which carries `pytest==9.1.1` (`:25`) and `ruff==0.6.9` (`:31`). All five compose services build from that base. Quantified honestly rather than inflated: `ruff` has **zero** `Requires-Dist` entries — one Rust binary; `pytest` resolves to four transitives on the target platform and its `dev` extra is not selected, so it brings **no network-facing package**. Roughly 35 MB and no notable CVE exposure. The larger half is adjacent: `backend/.dockerignore` excludes `.pytest_cache/` (`:7`) but **not `tests/`**, and `Dockerfile:23` is `COPY . .` — so **190 test files ship in every image regardless of the packages.** The root cause is that one file serves as both the CI dependency list and the production image manifest; the repo already has the splitting pattern (`requirements-voice.txt`, `requirements-mcp.txt`) and simply did not apply it here.

**S14 (P2) — digest pinning is a practice this team knows, applied once of four.** `backend/docker-compose.yml:53` pins MinIO by digest with a comment explaining why. Three lines away, `:20` `redis:7-alpine`, `:33` `pgvector/pgvector:pg16` and `backend/Dockerfile:5` `python:3.12-slim` all float. `pgvector/pgvector:pg16` is the one that matters — it floats across both Postgres patch releases and pgvector minors, and pgvector's index behaviour is load-bearing for the RAG path. The vendored `PRAXIST-main/services/product_usage/Dockerfile:1` pins its base by digest, so the repo literally contains a working example of what its own image is missing. The framing is not "you should pin images" — it is "the decision was made and reasoned once, and never generalised."

Two hardening defects sit in the same lines. **`build-essential` survives into the final voice image** — `backend/Dockerfile:32-38` builds the `voice` stage `FROM base` and installs it alongside `ffmpeg` with no later stage discarding it. `ffmpeg` is genuinely needed at runtime; a C toolchain is needed only to compile wheels, and shipping it turns a limited file-write into a comfortable place to compile a payload — in the one container that terminates borrower calls. The standard fix is a builder stage plus `COPY --from=`. And **neither backend image sets a `USER`**, so both run as root; the vendored `PRAXIST-main/services/product_usage/Dockerfile:9,14` adds a non-root user, so again the better pattern already exists in-tree.

**S19 (P2) — CI never builds the frontend.** `frontend-typecheck.yml` runs `npm ci`, `tsc --noEmit`, `vitest run` and `npm run lint` — and **no `npm run build`**. The app does produce a server bundle via `nitro`, pinned at `package.json:91` to `3.0.260603-beta` — the only exact pin in the manifest, on a **beta**, which drags an alpha `unstorage`, an rc `unenv` and an rc `h3` into the build. A beta-pinned build tool whose build is gated by nothing is a standing outage waiting for the next person to run it. (The exact pin is the *correct* mitigation for a prerelease; the finding is that its necessity should be a tracked item, not a silent line.)

**S20 (P2) — dead scaffold keeps a deprecated chain alive.** `recharts@2.15.4` is marked deprecated in the lock ("1.x and 2.x branches are no longer active"). Its only import site is `src/components/ui/chart.tsx`, which **nothing imports** — every real chart goes through a hand-written `@/components/charts` barrel. It is the sole reason the tree contains `lodash`, `prop-types`, two versions of `react-is`, `react-smooth`, `react-transition-group` and `victory-vendor`. Five more unused shadcn scaffold files (`form`, `calendar`, `carousel`, `drawer`, `input-otp`) similarly keep `react-hook-form`, `@hookform/resolvers`, `react-day-picker`, `embla-carousel-react`, `vaul` and `input-otp` alive. `sideEffects: false` means none of this reaches the bundle — it is attack surface and audit noise, not shipped bytes, and the fix is deleting files rather than editing the manifest.

**S21 (P3) — four genuinely unused dependencies**, verified against all 488 files under `Habibi/src/`: `liveline`, `date-fns`, `@pipecat-ai/client-react` (the code deliberately hand-rolls its job, with a comment saying so at `useSandboxLiveCall.ts:147`), and `@tanstack/router-plugin` (redundant top-level; reachable transitively). On `liveline` specifically — a 0.0.x single-maintainer package that looked like a provenance concern — the checks came back clean: lock integrity matches the live registry byte-for-byte with a valid npm signature, and it has ~218k weekly downloads. It is unnecessary, not suspicious. Worth noting the files named after it (`liveline-trend.tsx`, `liveline-spark.tsx`) are hand-written SVG components; the team wrote their own and kept the name.

**S22 (P2) — a documented runbook step performs an unconstrained install into a live environment.** `docs/ops/mcp.md:10` instructs an operator to run `pip install -r requirements-mcp.txt` — with **no `-c requirements.txt`** — into an environment that already holds `httpx==0.28.1`, `starlette==1.3.1`, `pydantic==2.13.4` and `uvicorn==0.51.0`. `requirements-mcp.txt:6` is `mcp>=1.2.0`, the only **fully unbounded** direct requirement in the backend, and the MCP SDK carries its own `starlette`/`httpx`/`pydantic`/`uvicorn` constraints. This is §11's "the second pip invocation cannot see the first file" mechanism promoted out of a Dockerfile and into a step a human executes by hand, against a running system, with no lockfile to catch the drift. The same one-line fix applies: `-c requirements.txt`. It matters more than it looks because `docs/ops/mcp.md:6-8` describes this as "a **read-only** slice of the collections tool catalog to an external agent... a product surface, not a debug sidecar."

**Credit where it is due, on the same file.** The optional-dependency handling here is exemplary and worth copying elsewhere: `backend/mcp_server.py:42-49` wraps the three SDK imports in `try/except ImportError` and raises `SystemExit` with the exact remediation — *"The `mcp` package is not installed. Install it with: pip install -r requirements-mcp.txt"*. The HTTP MCP surface under `backend/agent_core/mcp_http/` is first-party and needs no SDK at all, which is why the `api` and `worker` images are correct without `mcp` and CI is green without it. The split manifest degrades exactly as a split manifest should.

**S23 (P3) — committed empty build cache.** `.vite/deps/package.json` (`{"type":"module"}`) and `.vite/deps/_metadata.json` are tracked at the repo root. The metadata records `"optimized": {}`, `"chunks": {}` and `lockfileHash: "e3b0c442"` — the SHA-256 prefix of the **empty string**, meaning Vite hashed no lockfile because it was invoked from the repo root where there is none. A stray root-level `vite` run. `.vite` is ignored in neither `.gitignore`. No secrets, no source: untidy, not a problem.

**S24 (P3) — CI pip cache key omits the voice manifest.** `backend-pytest.yml:76` keys on `requirements.txt` while `:95` installs `requirements-voice.txt`. I flagged this as a possible stale-install correctness bug; **it is not.** `actions/setup-python` caches pip's content-addressed download cache, not site-packages, so a stale key can only cause a re-download, never a wrong version. The real cost is that the heavyweight voice wheels (`onnxruntime`, `scipy`, `av`, `opencv-python-headless`, the Azure SDK) miss on most runs and are never re-saved. One-line fix; minutes of CI time, no risk.

**S27 (P3) — manifest comments have drifted from the metadata.** Three cases, all verifiable: `requirements-voice.txt:25` selects a `silero` extra that declares no requirements at all (a no-op); `:31-32` attributes onnxruntime to the silero extra when it is an unconditional pipecat base requirement; and `:20-24` excludes `speechmatics` to avoid "transformers + huggingface_hub + tokenizers + safetensors", but `fastembed` on `:36` already pulls `huggingface_hub` and `tokenizers` — half the stated cost is already paid. The reasoning in these files is unusually good, which is why keeping it accurate is worth the small effort.

**S28 (P3) — the frontend's deployment target is an unexamined default.** `vite.config.ts:4` documents that the vendor config includes "nitro (build-only using **cloudflare as a default target**)". No wrangler config is tracked and `.output/` is gitignored, so the Cloudflare Workers preset is inherited from a third-party build config rather than chosen. For a product whose backend is deliberately on-prem, the frontend's build target defaulting to someone else's edge platform is worth an explicit decision either way.

---

## 13. Reproducibility

**If this repo were checked out clean today and every image rebuilt, the result would not match what is running — and the divergence is the whole Python runtime.** In order of blast radius:

1. **The Python transitive closure (unbounded).** No lock, no constraints, no hashes — 114 packages re-resolve at build time. This alone guarantees a different image.
4. **Three direct Python ranges** — `twilio`, `redis`, `websockets` (`requirements.txt:13-15`) float within their majors.
5. **Three of four base images float** — `python:3.12-slim`, `pgvector/pgvector:pg16`, `redis:7-alpine`. Only `minio` is reproducible.
6. **apt is unversioned** — `curl`, `ca-certificates`, `build-essential`, `ffmpeg` against live Debian archives. `build-essential` also means the compiler that builds any sdist floats, and it is never removed from the final voice image.
7. **Which frontend lockfile you used** (S4).
8. **npm caret ranges — the least dangerous item here.** All 77 declared ranges are satisfied by pinned lock versions, so `npm ci` is deterministic. The carets only bite on `npm install`/`npm update`, which no gate prevents.

The asymmetry is the spine of this report: **the frontend is reproducible via `npm ci` and gated by a CI job that enforces its lock. The backend — the regulated voice and payments runtime — has neither.**

---

## 14. What to do

In the order I would actually do it.

1. **Bump `nltk` to `>=3.10.3` (S7).** One line in `backend/requirements-voice.txt`, comfortably inside pipecat's `<4` bound, and it closes 21 advisories on the voice runtime's import path. Bump `aiohttp` to `3.14.3` in the same change (S8). This is first not because it is the deepest problem but because it is a few minutes of work on the most regulated surface in the product.
2. **Add a vulnerability gate to both workflows (S1).** `npm audit --audit-level=high` and `pip-audit`. Two steps. Nothing else on this list matters as much, because without it the next finding is also discovered by hand — and note that a gate reading `package-lock.json` still will not see the `bun.lock` tree (S4), so step 4 is part of making this one honest.
3. **Pre-bake `nltk_data` into the voice image, or set `NLTK_DATA`.** Independently of the version bump, no production container should be performing a network download at process start — least of all one behind a bank's egress proxy.
4. **Delete `Habibi/bun.lock` and add `packageManager: "npm@10.9.2"` (S4).** One deletion and one line closes the dual-lockfile hole permanently — and then decide, deliberately, whether the `bunfig.toml` guard should be reimplemented for npm or removed as misleading (S3). A control that does nothing is worse than no control, because it reads like coverage.
5. **Generate a Python lockfile from a 3.12 resolve, with hashes (S2, S5).** `uv` is already installed on this machine. Adding `requires-python = ">=3.12,<3.13"` to `backend/pyproject.toml` in the same change makes the interpreter mismatch impossible to recreate.
6. **Constrain the second pip install: `pip install -r requirements-voice.txt -c requirements.txt` (§11).** One flag turns a whole class of silent pin-defeat into a loud build failure.
7. **Add `"PRAXIST-main"` to `_make_submission_zip.py:11-31` (S6).** One line, removes an active redistribution of source-available licensed code. Then decide the tree's fate separately.
8. **Scan an actual image once (`trivy image collections-voice:local`).** The OS layers of every container have never been looked at. The first run is the only way to find out whether that matters.
9. **Split `requirements-dev.txt` and add `tests/` to `.dockerignore` (S13); drop `build-essential` to a builder stage and set a non-root `USER` (S14).** All three patterns already exist elsewhere in this repo.
10. **Generate `THIRD_PARTY_NOTICES.txt` for the images and the bundle (S16).** Mechanical, and bank procurement will ask for it.

---

## Findings index

| ID | Sev | Finding |
|---|---|---|
| S1 | **P0** | No vulnerability/SCA gate on any path; no scanner installed, none in CI, no dependabot/renovate |
| S2 | **P0** | No Python lockfile: 114 of 134 packages unpinned, including the TLS/deserialization surface |
| S3 | **P1** | The only supply-chain control (`bunfig.toml` 24h publish-age guard) is inert — bun-only, bun not used |
| S4 | **P1** | Two tracked lockfiles diverging on 206 packages; `bun.lock` missing the entire voice stack, 39 days stale, and unauditable by any tool here |
| S5 | **P1** | Dev venv is Python 3.14.3; image and CI are 3.12; `requires-python` declared nowhere |
| S6 | **P1** | PRAXIST-main: 4,518 files under a revenue-gated Fair Source licence, redistributed by the submission zip |
| S7 | **P1** | `nltk 3.10.0` — 21 advisories, a *core* pipecat dependency, with `nltk.download()` on the voice import path |
| S8 | P2 | `aiohttp 3.14.2` — CVE-2026-69244 OOB heap read in the response parser; reachable via pipecat and twilio |
| S9 | P3 | Five npm advisories (4 high, 1 moderate), all transitive, all build-time, none in the shipped bundle |
| S10 | P3 | `cryptography 49.0.0` PKCS#7 oracle — confirmed present, confirmed unreachable |
| S11 | P2 | `pipecat-ai[runner]` → unversioned `fastapi[all]` → a cloud deploy CLI in the on-prem voice image |
| S12 | P2 | `redis` declared `<6`, developed against 8.0.1, shipped and tested on 5.x |
| S13 | P2 | `pytest`/`ruff` and 190 test files ship in all five service images |
| S14 | P2 | Digest pinning applied to one of four base images; `build-essential` and root both survive into the voice image |
| S15 | P2 | LGPL (`psycopg`, `soxr`, `num2words`) and MPL (`certifi`, `tqdm`) in shipped images with no notice or source offer |
| S16 | P2 | No third-party NOTICE/attribution artifact produced for any shipped artifact |
| S17 | P2 | Proprietary Azure Speech SDK in the shipped voice image (has documented REDIST terms to satisfy) |
| S18 | P2 | GPL `ffmpeg` binaries apt-installed into the shipped voice image |
| S19 | P2 | CI never runs `npm run build`; beta-pinned `nitro` and its alpha/rc chain are ungated |
| S20 | P2 | Dead shadcn scaffold keeps deprecated `recharts` (+9 transitives) and five more deps alive |
| S21 | P3 | Four genuinely unused dependencies: `liveline`, `date-fns`, `@pipecat-ai/client-react`, `@tanstack/router-plugin` |
| S22 | P2 | `docs/ops/mcp.md:10` documents an unconstrained `pip install` into a live env; `mcp>=1.2.0` unbounded |
| S23 | P3 | Empty Vite build cache committed at the repo root; `.vite` ignored nowhere |
| S24 | P3 | CI pip cache key omits `requirements-voice.txt` — efficiency cost, not correctness |
| S25 | P3 | GPLv3+ `pyyaml-include` orphan in the dev venv (reaches no image) |
| S26 | P3 | No root LICENSE and no `license` field for the product itself |
| S27 | P3 | Three manifest comments have drifted from the installed metadata |
| S28 | P3 | Frontend build target (Cloudflare Workers) is an unexamined vendor default for an on-prem product |
| S29 | P3 | `pip 26.1.2` in the dev venv — CVE-2026-13346, needs a malicious index; CI upgrades pip first |
| — | — | **Unscanned, not cleared:** every image's OS layer; the real Linux dependency resolution; the `bun.lock` tree; `mcp` |

---

## Checked and cleared

Negative results, several of which were the hypotheses I most expected to confirm.

- **`package-lock.json` is in exact sync with `package.json`.** 58/58 dependencies and 19/19 devDependencies present in the lock's root entry with byte-identical range strings; zero extras, zero missing, zero range-satisfaction violations across all 77.
- **The npm lock is clean by every provenance measure.** All 587 entries carry both `integrity` and `resolved`; **zero resolve to anything outside `registry.npmjs.org`** — no git URLs, no tarballs, no alternate registries, no `link:` entries. Exactly **one** package in the tree declares an install script (`fsevents@2.3.3`, optional, darwin-only). That is a notably clean postinstall surface.
- **No peer dependency conflicts.** `npm ls --all` exits 0 with zero `invalid` markers across 587 packages; every `UNMET` is an optional platform binary. No evidence the lock was produced with `--legacy-peer-deps` or `--force`.
- **My `recharts` vs React 19 hypothesis was wrong.** Its lock entry declares `react: "^16 || ^17 || ^18 || ^19"`. No conflict.
- **My `zod` v3 vs `@hookform/resolvers` v5 hypothesis was wrong.** Resolvers v5 declares no `zod` peer at all — it moved to Standard Schema. The only zod straddle is three nested v4 copies under build-time TanStack plugins, correctly isolated by npm and never reaching the bundle.
- **My "build tools in `dependencies` bloat production" hypothesis was wrong.** The app deploys as a self-contained bundle; `dependencies` is never installed in production, and three of the four flagged packages are there to satisfy the build config's declared `peerDependencies`. Moving them would change zero shipped bytes.
- **My "second pip install silently overrides pins" hypothesis was wrong in its strong form.** pip's `only-if-needed` default prevents it, and no pin is currently violated in the container. The true defect is that the caps hold by accident and are validated by nothing — see §11.
- **My `numpy` conflict hypothesis was wrong.** fastembed, pipecat, onnxruntime, scipy and opencv all agree comfortably on `numpy 2.4.6`. The binding ceiling is `numba<2.5`, which nothing in my brief mentioned.
- **The CI `paths:` filters are correct.** Report 11 found a contract gate defeated by path filtering; **that pattern does not recur here.** `Habibi/**` and `backend/**` each correctly trigger their job, and `npm ci` genuinely gates lock/manifest sync. The hole is not in the filters — it is that nothing covers `backend/docker-compose.yml`, the root `.vite/`, or `PRAXIST-main/`.
- **`backend/.dockerignore` is good.** `.env` and `.env.*` excluded while `.env.example` is kept, plus `.venv/`, `.git/`, caches. Secrets do not enter the build context, and compose supplies credentials at runtime via `env_file` rather than baking them.
- **`pip check` passes** — the venv is internally consistent. It just disagrees with the manifests, which `pip check` never reads.
- **`Habibi/.output/` is properly ignored** — zero tracked files.
- **Voice dependencies are gated in CI**, with a comment explaining why (26 test files import pipecat at module scope). The highest-risk code is not the ungated code.
- **No AGPL anywhere**, in 587 npm packages or 134 Python distributions. No GPL in any shipped artifact.
- **PRAXIST cannot reach any image** — proven by build context, not assumed.
- **`liveline`'s provenance is clean** — lock integrity matches the live registry exactly, valid npm signature, ~218k weekly downloads. Unnecessary, not suspicious.
- **`@lovable.dev/vite-tanstack-config` is MIT**, from `registry.npmjs.org`, with valid integrity. The finding against it (S3) is about the waived release-age guard on a caret range, not about the publisher.
- **`PRAXIST-main/services/product_usage/Dockerfile` is well built and unreachable** — digest-pinned base, non-root user, `--no-cache-dir`, and referenced by no compose file this repo can build.

---

## 15. Corrections to my own framing

Recorded because the report should show where it was wrong, not only where the code is.

1. **My manifest inventory was incomplete, and I briefed all five analysts on it.** I searched for `bun.lockb` — bun's old binary lockfile — and so missed `Habibi/bun.lock`, the current text format, which is tracked and turned out to be a P1 finding (S4). I also missed `Habibi/bunfig.toml`, which turned out to hold the only supply-chain control in the repository (S3). Two analysts found both independently before my correction reached them. The lesson is that an inventory built from a filename list is only as good as the list.
2. **I miscounted the frontend dependencies** as 59 + 18. It is **58 + 19** = 77, confirmed programmatically against both `package.json` and the lock's root entry.
3. **Four of the technical hypotheses I handed to analysts were wrong** — recharts/React 19, zod/resolvers, build-tools-in-`dependencies`, and numpy conflicts. All four are recorded above under "Checked and cleared" rather than quietly dropped, because a brief that seeds a wrong hypothesis is a way to manufacture a false finding, and the record should show they were tested and rejected.
4. **My framing of the two-file pip install was too strong.** I described it as silently overriding pins; pip's default resolution strategy prevents that in a clean build. The corrected finding is narrower and, I think, more useful: the caps are unenforced rather than defeated, with one loaded instance (`ruff` vs pipecat's `cli` extra) waiting for a one-word change to a line of `requirements-voice.txt`.
5. **I initially treated the CI pip cache key as a possible correctness bug.** It is not — pip's cache is content-addressed, so a stale key costs a download, never a wrong version. Downgraded to P3 (S22).
6. **I wrote that the Python side could not be scanned. That was wrong, and I corrected it before publishing.** My reasoning was that no SCA binary is installed and the read-only remit forbade installing one — both true. What I missed is that OSV.dev has an HTTP API, so 135 installed distributions could be queried directly without installing anything. That path produced S7 and S8, the two most serious Python findings in the report. The lesson is that "no tool is installed" is not the same as "no scan is possible," and I nearly shipped a report whose largest section said "unknown."

7. **I ranked the npm advisories P2 on reachability reasoning, then downgraded them to P3 on evidence.** My argument was that they sit in build tooling. That argument was *not sufficient*, because this app is SSR rather than a static SPA, so build-time and runtime are not cleanly separated by inspection. The analyst settled it empirically instead — grepping the actual built server bundle at `Habibi/.output/server` for all five names, zero hits. Right conclusion, but it needed measuring rather than arguing, and the distinction matters for whoever re-runs this.

8. **What remains genuinely unscanned, stated so it is not mistaken for a clean bill:** every container image's OS layer, the real Linux dependency resolution (as opposed to the Windows 3.14 dev venv), the `bun.lock` tree, and `mcp`. Section 9 lists the specific commands. An absence of findings in those four places is an absence of looking.

9. **I published a false finding and then corrected it.** An earlier version of S22 asserted that `requirements-mcp.txt` was orphaned because "`backend/mcp_server` does not exist." It does exist — as `backend/mcp_server.py`, a module *file*. My verification command was `ls -d backend/mcp_server`, which asks whether a *directory* exists; a missing directory is not a missing module, and I read the negative result as confirmation because it agreed with the hypothesis I was testing. The replacement finding is narrower in scope but higher in severity, and the module I wrongly called dead turned out to contain the best optional-dependency handling in the repository — now credited in §12.

10. **The same class of error cost a second finding.** I initially cleared `websockets` as having no first-party consumer, on an anchored `^import websockets` grep. `backend/voice/ws_proxy.py:41-42` imports it lazily *inside a function*, indented, so the anchor excluded it. That moved the websockets half of S12 from a transitive-only concern to a named consumer on the voice path. Both mistakes share a root: a search pattern precise enough to look authoritative and narrow enough to be wrong. Where this report says "no usage found," read it as "none found by the sweep described," and note that this codebase uses deliberate lazy imports (`kb_rerank.py:124`, `mcp_server.py:43`) that defeat anchored patterns.
