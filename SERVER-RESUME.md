# Resume a saved conversion on a server

This fork includes native CUDA dtype selection, UTF-8 subprocess logs, an optional live progress banner, portable checkpoint validation, and bounded length-aware audio batches. The book, generated audio, voice assignments, credentials, local checkpoints and model weights are **not in Git**. Transfer saved job data separately.

## Preserve the current job

Do not rerun script annotation or regroup an existing script to resume audio. Preserve these files together:

- `annotated_script.json`, `chunks.json`, `voice_config.json`, `recovery-manifest.json`;
- every completed file referenced by `chunks.json` under `voicelines/`;
- `app/config.json` and any voice references/adapters used by this job.

The supplied trial uses built-in CustomVoice speakers; its portable snapshot includes its patched app/settings and completed audio. The checkpoint helper does not package arbitrary user-created voice libraries outside `app/`; copy any custom reference/adaptor directories separately if your project uses them.

`chunks.json` is authoritative. Missing or corrupt chunk state can cause the upstream app to rebuild pending segments. Never replace it with a newly grouped script. Completed audio paths are relative to the project root.

## Make and verify an idle checkpoint

Stop the active worker at a batch boundary, verify its process has exited and the app's `/api/status/audio` says `running: false`, then run from the project root:

```sh
python Checkpoint-Conversion.py
python Checkpoint-Conversion.py --snapshot checkpoints/server-transfer
python Checkpoint-Conversion.py --root checkpoints/server-transfer --verify
```

Use an unused destination name. Snapshotting refuses generating segments and active trial locks. The audit rejects a completed record with missing/empty audio. The snapshot copies state, completed audio, app code/settings, root helpers, and trial history, then verifies SHA-256 hashes. Windows Python environments and model weights are excluded. An interrupted snapshot without `checkpoint-manifest.json` is incomplete.

Stop all writers yourself before snapshotting: the helper's lock checks are not a global process lock. Do not clear a live lock. If a worker crashed, verify the actual PID is gone and back up metadata before repairing stale `generating` entries or lock files. Only genuinely unfinished entries may return to `pending`.

## Restore with Docker

1. Transfer the **entire fresh checkpoint**, preserving directory layout. A Git clone alone does not contain saved progress. Never upload the checkpoint to Git.
2. Before editing or running anything in that copied directory, run `python Checkpoint-Conversion.py --verify`. It validates file hashes, the segment inventory and all saved audio.
3. Keep that verified copy untouched as an archive. Make a writable working copy for the server. Apply newer committed helper/code changes only to the working copy, preserving the script, chunk state, voice assignments and saved audio.
4. From the working directory, build and start the prepared single-GPU configuration:

```sh
docker compose -f docker-compose.saved-job.yml up -d --build
docker compose -f docker-compose.saved-job.yml exec alexandria python Checkpoint-Conversion.py
```

Docker and NVIDIA Container Toolkit with a compatible driver are prerequisites. The included image is based on PyTorch/CUDA. The configuration mounts the entire working project at `/alexandria` so JSON files and audio persist. Individual JSON-file bind mounts are unsuitable because state saves use atomic replacement. The upstream compose file alone does not persist all of this saved job's root-level metadata.

The Hugging Face cache is a separate Docker volume. Use the same model/tokenizer as the saved job. For the provided CustomVoice trial these are `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` and `Qwen/Qwen3-TTS-Tokenizer-12Hz`. Transfer the existing complete model cache or explicitly authorize any downloads. Continuing audio from a completed script does not need an LLM/Ollama service.

The web UI is on port 4200. The live banner is optional: helpers write `app/static/conversion-status.json`; a clean clone without that runtime file leaves the banner hidden. The static file can lag an active render; inspect actual worker activity before declaring a stall.

## Run a bounded optimized group

With the app running in the same container and no other audio job active:

```sh
docker compose -f docker-compose.saved-job.yml exec \
  -e ALEXANDRIA_TRIAL_DIR=/alexandria/server-trial-01 \
  alexandria python -u Run-40-Batches.py --plan-only

docker compose -f docker-compose.saved-job.yml exec \
  -e ALEXANDRIA_TRIAL_DIR=/alexandria/server-trial-01 \
  alexandria python -u Run-40-Batches.py
```

This specialized trial requires sufficient pending work in each length bucket. It plans **40 logical batches / 206 segments**: 16 batches of eight short passages, 16 of four medium passages, six of two long passages, two of one very long passage. It samples across passage lengths, saves production audio at original segment positions, loads one resident model, and stops after the bounded plan. The limits were tested on an 8GB GPU; benchmark before changing them for another card.

`--plan-only` audits saved output and persists a pending-only plan without rendering. The runner verifies the saved script against `recovery-manifest.json`, audits done audio, and refuses to submit done segments for regeneration. Preserve the job directory, plan and measurements when resuming an interrupted group: it skips completed rows and done segments from partially saved batches. Each job has `active.lock` and `status.json`. Inspect worker PIDs and the API before any restart; independent direct workers cannot see each other through the app API.

Create `<trial-directory>/stop-requested` for a graceful stop at the next batch boundary. Remove that file only when deliberately resuming. Do not render the same saved job simultaneously on two machines.

## Optional two-group queue

`Queue-Next-40.py` is the coordinator used for a local two-group trial. It waits for `forty-batch-trial/` to complete, checkpoints, starts one further group in `forty-batch-trial-02/`, checkpoints, then stops. It expects the app at `http://127.0.0.1:4200`, and both names are fixed. It refuses an existing second-group directory to prevent accidental duplication. Queue state is `next-40-queue.json`; logs are in the project parent's `logs/` directory.

Create `next-40-stop-requested` plus the active group's `stop-requested` to stop both rendering and continuation. Do not start this coordinator just to resume a completed project; create a separately authorized bounded trial instead.

## Two GPUs and verification limits

The supplied Docker configuration exposes **GPU 0 only**, and the current runner is single GPU. Merely adding a second GPU to Docker will not distribute generation. Do not launch two independent `ProjectManager` instances against the same `chunks.json`; their in-process locks cannot protect shared metadata across processes.

Dual-GPU operation still requires disjoint pending assignments, worker-isolated metadata/output, and one coordinator to validate and merge results by original segment ID. Benchmark representative short/long passages on the actual server before relying on a runtime estimate. Docker restoration and dual-Blackwell throughput have not been tested on the target server.

Local bounded trials verified batch generation, saved-audio preservation, resident-model reuse and portable checkpoint hashes. Tests cover checkpoint integrity/rejection and real UTF-8 subprocess output. Hash preservation proves files did not change; it does not establish perceptual audio quality. Merge only after all segments are complete and validated.

Run the focused checks without a GPU:

```sh
python -m unittest discover -s tests -v
```
