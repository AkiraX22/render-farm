#!/usr/bin/env bash
# Builds the images and deploys the whole render farm on the kind cluster. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER="${CLUSTER:-render}"
VERSION=0.4.0

kind get clusters | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER" --config kind-config.yaml
kubectl config use-context "kind-$CLUSTER"

docker build -t "render-worker:$VERSION" worker
docker build -t "render-controller:$VERSION" controller
kind load docker-image "render-worker:$VERSION" "render-controller:$VERSION" --name "$CLUSTER"

helm repo add nats https://nats-io.github.io/k8s/helm/charts/ --force-update
helm repo add kedacore https://kedacore.github.io/charts --force-update
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm repo update nats kedacore prometheus-community

# Monitoring first: it installs the PodMonitor/ServiceMonitor CRDs used by everything else.
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 92.10.1 \
    -n monitoring --create-namespace -f helm/monitoring-values.yaml --wait --timeout 10m
kubectl -n monitoring create configmap render-farm-dashboard --from-file=dashboards/render-farm.json \
    --dry-run=client -o yaml | kubectl label --local -f - grafana_dashboard=1 -o yaml | kubectl apply -f -

helm upgrade --install nats nats/nats --version 2.15.1 \
    -n nats --create-namespace -f helm/nats-values.yaml --wait --timeout 5m
helm upgrade --install keda kedacore/keda --version 2.21.0 \
    -n keda --create-namespace -f helm/keda-values.yaml --wait --timeout 5m

kubectl apply -f k8s/namespaces.yaml
kubectl apply -f k8s/minio-credentials.yaml -f k8s/minio.yaml
kubectl -n minio rollout status deploy/minio --timeout=5m

# Jobs are immutable: recreate the setup job (bucket, stream, consumer) on every deploy.
kubectl -n render delete job render-setup --ignore-not-found
kubectl apply -f k8s/controller-setup.yaml
kubectl -n render wait --for=condition=complete job/render-setup --timeout=5m

kubectl apply -f k8s/worker.yaml -f k8s/worker-scaledobject.yaml -f k8s/monitoring.yaml
echo "render farm deployed; run ./scripts/render.sh to render an image"
