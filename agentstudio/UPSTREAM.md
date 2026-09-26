# PayInt Voice Studio engine: upstream record

`engine/` is a vendored copy of Dograh, stored in this repo as plain files. Nothing is fetched from Dograh at build or run time, so upstream releases never reach us on their own.

| Part | Upstream | Pinned at |
|---|---|---|
| `engine/` | https://github.com/dograh-hq/dograh | tag `dograh-v1.47.0` (commit `d91e4f5`) |
| `engine/pipecat/` | https://github.com/dograh-hq/pipecat (Dograh's fork) | commit `70385ad8a5204458a241e60287289932e3eb3ae2` |

## What we changed
- `patches/engine.diff` and `patches/pipecat.diff` are our full delta against the pins, new files included.
- Regenerate them with `bash patches/refresh.sh` after any change under `engine/`. The script needs network access to GitHub.
- The diffs ignore line endings, because Windows checkouts convert them.

The delta covers:
- **Engine API:** internal auth, the removed cloud (MPS) calls, local knowledge-base parsing, transcription, workflow generation and the voice catalog, Azure voice delivery and preview, version restore for rollback, tool provenance on run events, approved tool revisions, and the white-label text.
- **Engine UI source:** the PayInt host slots (`@/host/<Slot>`, see below) and the regenerated API client.

## The ported UI
`Habibi/src/agentstudio/` is generated from `engine/ui/src` by `Habibi/scripts/port-agentstudio.mjs`. Never edit it by hand; change the engine UI source and re-run the port.

PayInt screens that live inside engine pages are host slots:
- The engine UI source imports `@/host/<Slot>`.
- The port maps that to `Habibi/src/agentstudio-host/<Slot>`.
- Current slots: RunProvenance, PublishDialog, VersionRelease, PromptLint, AiSimulator and ToolReview.

## Reproducible build
- `engine/api/constraints.txt` holds the exact versions of every Python package in the tested image. The Dockerfile applies it with `-c` to all installs.
- The base images in `engine/api/Dockerfile` are pinned by digest. ffmpeg was already pinned by sha256.

## Upgrading to a newer Dograh
1. Clone the new tag with submodules into a scratch directory.
2. `git apply --3way` both patch files from this directory, and resolve the conflicts.
3. Replace `engine/` with the result, without the `.git` directories. Update the pins in the table above and in `patches/refresh.sh`.
4. **API client:** if the API changed, regenerate the UI client from the engine's OpenAPI spec. Use `@hey-api/openapi-ts` at the version in `ui/package-lock.json`, run the port, then typecheck Habibi.
5. **Rebuild and test:** rebuild without `-c` constraints, run the engine tests and the Voice Studio checks, then refresh the pins:
   - `constraints.txt`: one `name==version` per installed distribution in the new image, excluding `pipecat-ai`;
   - the base-image digests: `docker buildx imagetools inspect <image>`.
6. Run `bash patches/refresh.sh`.
