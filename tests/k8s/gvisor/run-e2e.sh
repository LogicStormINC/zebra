#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
EVIDENCE_DIR="${ZEBRA_K8S_EVIDENCE_DIR:-$ROOT_DIR/k8s-gvisor-evidence}"
CONTEXT="${ZEBRA_K8S_CONTEXT:-$(kubectl config current-context)}"
NAMESPACE="${ZEBRA_K8S_NAMESPACE:-zebra-k8s-gvisor-$(date +%s)}"
IMAGE="${ZEBRA_K8S_TEST_IMAGE:-python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b}"
K=(kubectl --context "$CONTEXT")
STATUS=0
REASON=""
CLEANUP=0
STARTED_AT=$(date +%s)

mkdir -p "$EVIDENCE_DIR"

write_result() {
  local finished_at
  finished_at=$(date +%s)
  python - "$EVIDENCE_DIR/result.json" "$STATUS" "$REASON" "$CLEANUP" \
    "$CONTEXT" "$NAMESPACE" "$STARTED_AT" "$finished_at" <<'PY'
import json
import sys
from pathlib import Path

path, status, reason, cleanup, context, namespace, started, finished = sys.argv[1:]
Path(path).write_text(
    json.dumps(
        {
            "schema_version": "zebra.k8s.gvisor.evidence.v1",
            "context": context,
            "namespace": namespace,
            "passed": status == "0" and cleanup == "1",
            "status": int(status),
            "reason": reason,
            "cleanup": cleanup == "1",
            "started_at_epoch": int(started),
            "finished_at_epoch": int(finished),
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY
}

cleanup() {
  local exit_status=$?
  set +e
  if [[ "$exit_status" -ne 0 && -z "$REASON" ]]; then
    STATUS="$exit_status"
    REASON="runner command failed"
  fi
  "${K[@]}" get runtimeclass gvisor -o yaml > "$EVIDENCE_DIR/runtimeclass.yaml" 2>&1 || true
  "${K[@]}" get pods -n "$NAMESPACE" -o json > "$EVIDENCE_DIR/pods.json" 2>&1 || true
  "${K[@]}" get quota,networkpolicy,pvc -n "$NAMESPACE" -o yaml > "$EVIDENCE_DIR/policy.yaml" 2>&1 || true
  "${K[@]}" logs -n "$NAMESPACE" job/worker > "$EVIDENCE_DIR/worker.log" 2>&1 || true
  "${K[@]}" logs -n "$NAMESPACE" pod/blocked-probe > "$EVIDENCE_DIR/blocked-probe.log" 2>&1 || true
  "${K[@]}" delete namespace "$NAMESPACE" --ignore-not-found --wait=true --timeout=120s \
    > "$EVIDENCE_DIR/cleanup.log" 2>&1
  if [[ "$?" -eq 0 ]]; then
    CLEANUP=1
  else
    STATUS=1
    REASON="namespace cleanup failed"
  fi
  write_result
  exit "$STATUS"
}
trap cleanup EXIT

if [[ ! "$IMAGE" =~ @sha256:[0-9a-f]{64}$ ]]; then
  STATUS=1
  REASON="test image must be digest pinned"
  exit 1
fi

if ! "${K[@]}" get nodes -o json > "$EVIDENCE_DIR/nodes.json"; then
  STATUS=1
  REASON="Kubernetes API is unavailable"
  exit 1
fi
if ! "${K[@]}" wait --for=condition=Ready nodes --all --timeout=30s; then
  STATUS=1
  REASON="no Ready Kubernetes node"
  exit 1
fi
RUNTIME_HANDLER=$("${K[@]}" get runtimeclass gvisor -o jsonpath='{.handler}' 2>/dev/null || true)
if [[ "$RUNTIME_HANDLER" != "runsc" ]]; then
  STATUS=1
  REASON="gvisor RuntimeClass is missing or handler is not runsc"
  exit 1
fi
if ! "${K[@]}" api-resources --api-group=networking.k8s.io | grep -q NetworkPolicy; then
  STATUS=1
  REASON="NetworkPolicy API is unavailable"
  exit 1
fi
NODE_ARGS=$("${K[@]}" get nodes -o jsonpath='{.items[*].metadata.annotations.k3s\.io/node-args}' 2>/dev/null || true)
if [[ "$NODE_ARGS" == *disable-network-policy* ]]; then
  STATUS=1
  REASON="cluster explicitly disables NetworkPolicy enforcement"
  exit 1
fi

"${K[@]}" create namespace "$NAMESPACE" >/dev/null
cat <<EOF | "${K[@]}" apply -f -
apiVersion: v1
kind: ResourceQuota
metadata:
  name: workspace-quota
  namespace: $NAMESPACE
spec:
  hard:
    pods: "5"
    requests.cpu: "1"
    limits.cpu: "2"
    requests.memory: 512Mi
    limits.memory: 1Gi
    requests.storage: 64Mi
    persistentvolumeclaims: "2"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: drill-scripts
  namespace: $NAMESPACE
data:
  api.py: |
$(sed 's/^/    /' "$ROOT_DIR/tests/k8s/gvisor/api.py")
  worker.py: |
$(sed 's/^/    /' "$ROOT_DIR/tests/k8s/gvisor/worker.py")
  blocked_probe.py: |
$(sed 's/^/    /' "$ROOT_DIR/tests/k8s/gvisor/blocked_probe.py")
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: worker-state
  namespace: $NAMESPACE
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Mi
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: $NAMESPACE
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: $NAMESPACE
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-worker-api
  namespace: $NAMESPACE
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: worker
      ports:
        - protocol: TCP
          port: 8080
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: $NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels: {app: api}
  template:
    metadata:
      labels: {app: api}
    spec:
      runtimeClassName: gvisor
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
        runAsGroup: 65532
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: api
          image: $IMAGE
          imagePullPolicy: IfNotPresent
          command: [python, /scripts/api.py]
          ports: [{name: http, containerPort: 8080}]
          readinessProbe: {httpGet: {path: /healthz, port: http}}
          resources:
            requests: {cpu: 10m, memory: 32Mi}
            limits: {cpu: 200m, memory: 128Mi}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: [ALL]}
          volumeMounts: [{name: scripts, mountPath: /scripts, readOnly: true}]
      volumes: [{name: scripts, configMap: {name: drill-scripts}}]
---
apiVersion: v1
kind: Service
metadata:
  name: api
  namespace: $NAMESPACE
spec:
  selector: {app: api}
  ports: [{port: 8080, targetPort: http}]
---
apiVersion: batch/v1
kind: Job
metadata:
  name: worker
  namespace: $NAMESPACE
spec:
  backoffLimit: 2
  template:
    metadata:
      labels: {app: worker}
    spec:
      restartPolicy: Never
      runtimeClassName: gvisor
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
        runAsGroup: 65532
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: worker
          image: $IMAGE
          imagePullPolicy: IfNotPresent
          command: [python, /scripts/worker.py]
          env:
            - {name: ZEBRA_API_URL, value: http://api:8080/healthz}
            - {name: ZEBRA_STATE_PATH, value: /state/checkpoint}
          resources:
            requests: {cpu: 10m, memory: 32Mi}
            limits: {cpu: 200m, memory: 128Mi}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: [ALL]}
          volumeMounts:
            - {name: scripts, mountPath: /scripts, readOnly: true}
            - {name: state, mountPath: /state}
      volumes:
        - {name: scripts, configMap: {name: drill-scripts}}
        - {name: state, persistentVolumeClaim: {claimName: worker-state}}
EOF

"${K[@]}" wait --for=condition=available deployment/api -n "$NAMESPACE" --timeout=120s
for _ in $(seq 1 60); do
  worker_pod=$("${K[@]}" get pods -n "$NAMESPACE" -l app=worker \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -n "$worker_pod" ]] && checkpoint=$("${K[@]}" exec -n "$NAMESPACE" "$worker_pod" -- \
    cat /state/checkpoint 2>/dev/null); then
    if [[ "$checkpoint" =~ ^[2-9][0-9]*$ ]]; then
      break
    fi
  fi
  sleep 1
done
if [[ -z "${worker_pod:-}" || ! "${checkpoint:-}" =~ ^[2-9][0-9]*$ ]]; then
  STATUS=1
  REASON="worker did not create a checkpoint before restart"
  exit 1
fi
before_restart="$checkpoint"
"${K[@]}" delete pod -n "$NAMESPACE" "$worker_pod" --wait=true --timeout=60s >/dev/null
"${K[@]}" wait --for=condition=complete job/worker -n "$NAMESPACE" --timeout=180s
if ! "${K[@]}" logs -n "$NAMESPACE" job/worker | grep -q 'WORKER_RESUMED_FROM='; then
  STATUS=1
  REASON="worker did not report PVC checkpoint resume"
  exit 1
fi
echo "WORKER_RESTART_RESUME=PASS checkpoint=$before_restart" | tee "$EVIDENCE_DIR/restart-resume.txt"

set +e
quota_output=$(cat <<EOF | "${K[@]}" apply -f - 2>&1
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: oversized-state
  namespace: $NAMESPACE
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 128Mi
EOF
)
quota_status=$?
set -e
printf '%s\n' "$quota_output" > "$EVIDENCE_DIR/quota-denial.txt"
if [[ "$quota_status" -eq 0 || ! "$quota_output" =~ (exceeded|quota|requests.storage) ]]; then
  STATUS=1
  REASON="oversized PVC was not rejected by ResourceQuota"
  exit 1
fi
echo "WORKSPACE_QUOTA=PASS" | tee "$EVIDENCE_DIR/quota-result.txt"

cat <<EOF | "${K[@]}" apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: blocked-probe
  namespace: $NAMESPACE
  labels: {app: blocked}
spec:
  restartPolicy: Never
  runtimeClassName: gvisor
  automountServiceAccountToken: false
  securityContext: {runAsNonRoot: true, runAsUser: 65532, runAsGroup: 65532}
  containers:
    - name: probe
      image: $IMAGE
      command: [python, /scripts/blocked_probe.py]
      resources: {requests: {cpu: 10m, memory: 32Mi}, limits: {cpu: 200m, memory: 128Mi}}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities: {drop: [ALL]}
      volumeMounts: [{name: scripts, mountPath: /scripts, readOnly: true}]
  volumes: [{name: scripts, configMap: {name: drill-scripts}}]
EOF
"${K[@]}" wait --for=jsonpath='{.status.phase}'=Succeeded pod/blocked-probe \
  -n "$NAMESPACE" --timeout=60s
"${K[@]}" logs -n "$NAMESPACE" pod/blocked-probe | tee "$EVIDENCE_DIR/blocked-probe-result.txt" | \
  grep -q 'BLOCKED_PROBE=PASS'
echo "NETWORK_POLICY=PASS" | tee "$EVIDENCE_DIR/network-policy-result.txt"
echo "ZEBRA_K8S_GVISOR_E2E_RESULT=PASS"
