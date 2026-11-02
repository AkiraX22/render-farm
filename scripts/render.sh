#!/usr/bin/env bash
# Submits a render job to the farm, waits for it, and downloads the final PNG to out/.
# Extra arguments are passed to the controller, e.g. --width 3840 --height 2160 --max-iter 5000.
set -euo pipefail
cd "$(dirname "$0")/.."

JOB="${JOB:-job-$(date +%H%M%S)}"
CONTROLLER_IMAGE="${CONTROLLER_IMAGE:-render-controller:0.3.0}"
ARGS=$(printf '"%s", ' render --job "$JOB" "$@")

kubectl apply -f - <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: render-$JOB
  namespace: render
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: controller
          image: $CONTROLLER_IMAGE
          imagePullPolicy: IfNotPresent
          args: [${ARGS%, }]
          envFrom:
            - secretRef:
                name: minio-credentials
YAML

kubectl -n render wait --for=condition=ready pod -l job-name="render-$JOB" --timeout=60s >/dev/null
kubectl -n render logs -f "job/render-$JOB"
kubectl -n render wait --for=condition=complete "job/render-$JOB" --timeout=30s >/dev/null

# Download the result through a temporary port-forward, signing the request with SigV4.
USER=$(kubectl -n minio get secret minio-credentials -o jsonpath='{.data.MINIO_ROOT_USER}' | base64 -d)
PASS=$(kubectl -n minio get secret minio-credentials -o jsonpath='{.data.MINIO_ROOT_PASSWORD}' | base64 -d)
kubectl -n minio port-forward svc/minio 19000:9000 >/dev/null &
PF=$!
trap 'kill $PF 2>/dev/null' EXIT
sleep 2
mkdir -p out
curl -fsS --user "$USER:$PASS" --aws-sigv4 "aws:amz:us-east-1:s3" \
    -o "out/$JOB.png" "http://127.0.0.1:19000/renders/jobs/$JOB/final.png"
echo "saved out/$JOB.png"
