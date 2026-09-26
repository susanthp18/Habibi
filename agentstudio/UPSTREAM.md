# PayInt Voice Studio engine: upstream record

`engine/` is a vendored copy of Dograh, stored in this repo as plain files. Nothing is fetched from Dograh at build or run time, so upstream releases never reach us on their own.

| Part | Upstream | Pinned at |
|---|---|---|
| `engine/` | https://github.com/dograh-hq/dograh | tag `dograh-v1.47.0` (commit `d91e4f5`) |
| `engine/pipecat/` | https://github.com/dograh-hq/pipecat (Dograh's fork) | commit `70385ad`, unmodified |

## What we changed
`patches/engine.diff` is our full delta against the tag. It covers internal auth, the removed cloud (MPS) calls, local parsing, voices, transcription and generation, the white-label text and the tests. `patches/engine-new-files.txt` lists the files we added. When you change engine code, regenerate both (see step 5 below).

## Reproducible build
- `engine/api/constraints.txt` holds the exact versions of every Python package in the tested image. The Dockerfile applies it with `-c` to all installs.
- The base images in `engine/api/Dockerfile` are pinned by digest. ffmpeg was already pinned by sha256.

## Upgrading to a newer Dograh
1. `git clone --depth 1 --branch <new-tag> --recurse-submodules https://github.com/dograh-hq/dograh /tmp/dograh-new`
2. `cd /tmp/dograh-new && git apply --3way <repo>/agentstudio/patches/engine.diff`, then resolve the conflicts. Copy in the files listed in `engine-new-files.txt`.
3. Replace `engine/` with the result, without the `.git` directories.
4. Rebuild without `-c` constraints, run the engine tests and the Voice Studio checks, then refresh the pins:
   - `constraints.txt`: from the new image, one `name==version` per installed distribution, excluding `pipecat-ai`.
   - the digests: `docker buildx imagetools inspect <image>`.
5. Regenerate `patches/engine.diff`, by diffing the pristine tag against `engine/`, and update the table above.
