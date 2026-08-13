# k8s-exercise

A throwaway learning artifact for the compose -> Kubernetes exercise. It is
**not** part of the `tg-core` package, is not published, and is not covered
by the project's usual test/lint/type-check discipline — feel free to let it
rot once the exercise is done.

It exposes a couple of read-only endpoints over a `Graph` (from
[`graph.py`](../graph.py)) loaded from [`example.py`](../example.py)'s toy
`Person`/`Organization`/`Vehicle` domain:

- `GET /healthz` — liveness/readiness probe target
- `GET /entities/{id}` — describe an entity or statement by id
- `GET /entities/{id}/edges?direction=out|in` — edges touching an entity
- `GET /bfs?seed=alice&max_hops=2` — BFS layers from a seed entity

Try ids like `alice`, `bob`, `acme`, `car1`.

## Run locally

```bash
cd k8s-exercise
pip install -r requirements.txt
uvicorn app:app --reload
curl localhost:8000/entities/alice
```

## Run via Compose (the thing to translate into K8s manifests)

```bash
cd k8s-exercise
docker compose up --build
curl localhost:8000/bfs?seed=alice
```

## Run via Kubernetes (`configmap.yaml` + `deployment.yaml` + `service.yaml`)

```bash
cd k8s-exercise
docker build -t tg-core-graph-api:local -f Dockerfile ..
kind load docker-image tg-core-graph-api:local   # or: minikube image load tg-core-graph-api:local
kubectl apply -f configmap.yaml -f deployment.yaml -f service.yaml
kubectl wait --for=condition=ready pod -l app=graph-api --timeout=60s
kubectl get pods,svc
kubectl port-forward svc/graph-api 8000:8000
curl localhost:8000/bfs?seed=alice
```

From here: poke at it with `kubectl get/describe/logs/exec`, put an Ingress
in front of it, then try `kompose convert` on `docker-compose.yml` to see
how it compares to the hand-written manifests above.

## So what are these YAML files all about?

### configmap.yaml

Just a named bag of key/value strings, decoupled from the Pod spec so config
can change without rebuilding the image. All we have here is:

    UVICORN_LOG_LEVEL: "info"
    UVICORN_PORT: "8000"

`deployment.yaml` pulls these in wholesale via `envFrom.configMapRef` (every
key becomes an env var in the container). The alternative, `env: - name: X
valueFrom: configMapKeyRef: {...}`, lets you cherry-pick one key and rename
it — useful when the ConfigMap's key names don't match what the app expects.
A `Secret` is the same shape (also usable via `envFrom`/`valueFrom`) but
base64-encoded at rest and treated a bit more carefully by tooling; it's the
right place for passwords/tokens instead of a ConfigMap.

### deployment.yaml

A Deployment doesn't run Pods directly — it creates and owns a **ReplicaSet**,
which is what actually keeps `replicas` copies of the Pod template running.
`kubectl get deployment,rs,pods` shows all three; `kubectl describe deploy
graph-api` shows the chain via `OwnerReferences`. This indirection is what
makes rolling updates work: changing the Pod template (e.g. the image tag)
makes the Deployment create a *new* ReplicaSet and scale it up while scaling
the old one down (`RollingUpdate` is the default `strategy`), instead of
deleting and recreating Pods in place.

`selector.matchLabels` is how the Deployment finds "its" Pods — it's a label
query, not a name or parent/child pointer. The Pod `template.metadata.labels`
must satisfy that selector or the Deployment can't see its own Pods. This
same label-matching mechanism is reused by `service.yaml`'s `selector` below —
labels are the one general-purpose "glue" primitive in K8s, used for
selection, not identity.

Other things in this file worth naming:

- `livenessProbe` vs `readinessProbe` hit the *same* `/healthz` endpoint here
  but mean different things to the control plane: a failed liveness probe
  gets the container **killed and restarted**; a failed readiness probe just
  gets the Pod **removed from the Service's endpoint list** (traffic stops
  routing to it) without killing anything. A `startupProbe` (not used here)
  exists for slow-booting apps, to delay when the other two even start
  counting failures.
- `imagePullPolicy: IfNotPresent` matters specifically because this image was
  side-loaded with `minikube image load` / `kind load docker-image` rather
  than pushed to a registry — `Always` (the default when the tag is
  `:latest` or omitted) would make the kubelet try to pull from a registry
  and fail, since the image only exists in the node's local cache.
- There are no `resources.requests`/`resources.limits` here — in a real
  cluster their absence means the scheduler has no idea how much CPU/memory
  this Pod needs, and there's nothing capping it from starving its node.

### service.yaml

Three port fields, three different jobs:

- `containerPort` (in `deployment.yaml`) — documentation of what the
  container listens on; not enforced, just informational for tooling/humans.
- `targetPort` — where the Service actually sends traffic *inside* the Pod
  (must match what the process really listens on).
- `port` — what the Service itself exposes, i.e. what other things in the
  cluster dial (`graph-api:8000` from any other Pod, via cluster DNS).

`type: ClusterIP` (the default) is only reachable from inside the cluster,
which is exactly why the exercise needs `kubectl port-forward` to reach it
from the host. Two other types worth knowing about: `NodePort` (exposes a
static high port on every node's IP — reachable from `minikube ip`) and
`LoadBalancer` (asks the cloud provider for an external IP; meaningless on
minikube without `minikube tunnel`). An `Ingress` resource sits in front of a
`ClusterIP` Service to do host/path-based HTTP routing plus TLS termination —
that's the natural next thing to add once there's more than one service to
route between.

## Concepts not yet explored here

The exercise so far covers Deployment + ConfigMap + Service, which is maybe
20% of what you'll run into. Worth poking at next, roughly in order of how
often you'll hit them:

- **Scaling & self-healing**: `kubectl scale deployment/graph-api --replicas=3`,
  then `kubectl delete pod <one-of-them>` and watch the ReplicaSet replace it.
  This is the core value proposition of K8s in one demo.
- **Rolling updates & rollback**: bump the image tag, `kubectl apply`, watch
  `kubectl rollout status deploy/graph-api`, then `kubectl rollout undo
  deploy/graph-api` to see it revert. `kubectl rollout history` shows past
  revisions.
- **`kubectl logs -f`, `kubectl exec -it <pod> -- sh`, `kubectl describe pod`**
  — the actual debugging loop; `describe` in particular surfaces scheduling
  failures and probe failures that `get` won't show.
- **Namespaces** — everything above is implicitly in `default`; real clusters
  isolate teams/environments with namespaces, and `kubectl config
  set-context --current --namespace=foo` to stop typing `-n foo` everywhere.
- **Resource requests/limits & the scheduler** — requests affect where a Pod
  can be scheduled; limits affect what happens when it misbehaves (CPU
  throttling vs. OOM-kill for memory). Missing requests is why the
  Kubernetes Horizontal Pod Autoscaler couldn't work here even if added.
- **Secrets** vs ConfigMaps (see above) — try converting one config value
  into a Secret and mounting it as a file instead of an env var
  (`volumeMounts` + `volumes.secret`), which is the more common real-world
  pattern for credentials.
- **Persistent storage** — `PersistentVolumeClaim` for anything that needs to
  survive a Pod restart; this app is stateless so there's nothing to try it
  on yet, but it's the biggest conceptual jump from "container orchestration"
  to "stateful services."
- **RBAC & ServiceAccounts** — every Pod runs as a ServiceAccount whether you
  specify one or not; `Role`/`RoleBinding` govern what the K8s API itself
  will let a Pod's credentials do (irrelevant for this app since it doesn't
  call the K8s API, but foundational once something does, e.g. an operator).
- **`kubectl explain <resource>.<field>`** — the built-in, always-in-sync
  documentation for any field in any manifest (e.g. `kubectl explain
  deployment.spec.strategy`), better than guessing from examples.
- **`kompose convert`** on `docker-compose.yml` — already flagged above as a
  todo; comparing its output to the hand-written manifests here is a good
  way to see what a generator considers "idiomatic" vs. what's hand-tuned
  here (e.g. it won't add probes or split config into a ConfigMap on its
  own).
