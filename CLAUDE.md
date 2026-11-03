# Render farm

Distributed Mandelbrot renderer on a local kind cluster (`kind-render`):
controller (Python) → NATS JetStream → C++ workers → MinIO, autoscaled by KEDA,
observed with kube-prometheus-stack. See README.md for the architecture.

## Commands
- Deploy / redeploy everything (idempotent): `./scripts/deploy.sh`
- End-to-end check after any change: `JOB=test ./scripts/render.sh --width 512 --height 512`
  → must end with `saved out/test.png`. Look at the image.
- Watch scaling: `kubectl -n render get deploy render-worker -w`

## Image versions
Images are loaded into kind, never pulled. When worker/ or controller/ changes, bump the
tag everywhere or the cluster keeps running the old image:
`scripts/deploy.sh` (VERSION), `scripts/render.sh`, `k8s/worker.yaml`, `k8s/controller-setup.yaml`.

## Invariants
- Workers ack a tile only after the MinIO upload succeeds (no tile can be lost).
  Upload failure → NakWithDelay; malformed message → Term.
- `k8s/worker.yaml` must not set `replicas`: KEDA owns it (0–8).
- KEDA reads NATS `/jsz` on port 8222: keep `service.ports.monitor` enabled in helm/nats-values.yaml.
- Changing the TILES stream or `workers` consumer config: delete them first,
  `add_stream`/`add_consumer` fail on a config mismatch.

## Gotchas
- Jobs are immutable: delete `render-setup` before re-applying it (deploy.sh does).
- Host inotify limit is low (WSL): avoid `kubectl logs -f`, poll instead.
- `minio/minio` images no longer exist; MinIO uses Chainguard's image pinned by digest.
- Install order matters: monitoring first (PodMonitor CRDs), then NATS, KEDA, MinIO.

## Conventions
- Code, comments, commits in English; README and discussion in French.
- Pin chart/image/library versions, at least two weeks old.
- One commit per logical step; push to origin (HTTPS via gh, SSH key needs a passphrase).
