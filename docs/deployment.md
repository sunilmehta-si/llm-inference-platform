# Kubernetes deployment blueprint

The chart supports a gateway-only deployment or a gateway with one NVIDIA vLLM engine.
It is a blueprint for a Linux cluster; the Mac demo executes model inference natively.
Rendering a chart validates its structure, not GPU availability or runtime correctness.

## Prerequisites

- A Linux Kubernetes cluster with NVIDIA drivers and a working device plugin/GPU Operator.
- A node with enough GPU memory for the selected checkpoint plus KV cache and runtime overhead.
- A default storage class for the model-cache PVC.
- A built gateway image accessible to the cluster.
- Engine image and model license reviewed for your intended use; pinned example versions
  are configuration examples, not a claim of the newest release.

Build/push the gateway image using the README instructions. Create a local Kubernetes Secret
from the private configuration without putting its value in shell history or Helm values:

```bash
set -a
source .env
set +a
.venv/bin/python -c 'import json,os; print(json.dumps({"apiVersion":"v1","kind":"Secret","metadata":{"name":"inference-gateway-key"},"stringData":{"GATEWAY_API_KEY":os.environ["GATEWAY_API_KEY"]}}))' \
  | kubectl apply -f -

helm upgrade --install inference deploy/helm/inference \
  -f deploy/helm/inference/values-nvidia.yaml \
  --set gateway.existingSecret=inference-gateway-key
```

Only run these commands in your intended cluster/namespace. No cluster provisioning or GPU
workload deployment is performed automatically by project setup.

Check rollout, logs, GPU assignment, readiness, and a smoke request before recording results.
The example uses an unquantized NVIDIA checkpoint distinct from the quantized MLX checkpoint;
benchmark comparisons must document that difference. The engine can take many minutes to
download/load weights, so the startup probe allows a long initialization window.

For an existing backend, omit `values-nvidia.yaml` and set `gateway.backendUrl` and
`gateway.model` to match it. The chart derives its default engine service URL from the release name.

## Scope

- Gateway runs as a non-root user with a read-only root filesystem and one replica.
- Model cache uses a PVC. GPU allocation requests `nvidia.com/gpu: 1`.
- The engine is an internal ClusterIP service; add cluster-appropriate network isolation.
- Metrics, TLS ingress, secrets management, autoscaling, and NVIDIA monitoring need integration
  with your cluster's platform. None are implicitly provisioned by this chart.
