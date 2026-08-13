# cd k8s-exercise
# docker build -t tg-core-graph-api:local -f Dockerfile ..

# (inf-typed-graph) @wware ➜ /workspaces/tg-core/k8s-exercise (k8s) $ curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
# sudo install minikube-linux-amd64 /usr/local/bin/minikube
# rm minikube-linux-amd64
#   % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
#                                  Dload  Upload   Total   Spent    Left  Speed
# 100  128M  100  128M    0     0   155M      0 --:--:-- --:--:-- --:--:--  155M
# (inf-typed-graph) @wware ➜ /workspaces/tg-core/k8s-exercise (k8s) $ curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
# sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
# rm kubectl
#   % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
#                                  Dload  Upload   Total   Spent    Left  Speed
# 100 56.7M  100 56.7M    0     0   148M      0 --:--:-- --:--:-- --:--:--  148M
# (inf-typed-graph) @wware ➜ /workspaces/tg-core/k8s-exercise (k8s) $ minikube start --driver=docker
# 😄  minikube v1.38.1 on Ubuntu 24.04 (docker/amd64)
# ✨  Using the docker driver based on user configuration
# ❗  Starting v1.39.0, minikube will default to "containerd" container runtime. See #21973 for more info.
# 📌  Using Docker driver with root privileges
# 👍  Starting "minikube" primary control-plane node in "minikube" cluster
# 🚜  Pulling base image v0.0.50 ...
# 💾  Downloading Kubernetes v1.35.1 preload ...
#     > preloaded-images-k8s-v18-v1...:  272.45 MiB / 272.45 MiB  100.00% 164.52 
#     > gcr.io/k8s-minikube/kicbase...:  519.58 MiB / 519.58 MiB  100.00% 31.34 M
# 🔥  Creating docker container (CPUs=2, Memory=3072MB) ...
# 🐳  Preparing Kubernetes v1.35.1 on Docker 29.2.1 ...
# 🔗  Configuring bridge CNI (Container Networking Interface) ...
# 🔎  Verifying Kubernetes components...
#     ▪ Using image gcr.io/k8s-minikube/storage-provisioner:v5
# 🌟  Enabled addons: storage-provisioner, default-storageclass
# 🏄  Done! kubectl is now configured to use "minikube" cluster and "default" namespace by default
# (inf-typed-graph) @wware ➜ /workspaces/tg-core/k8s-exercise (k8s) $ minikube status
# minikube
# type: Control Plane
# host: Running
# kubelet: Running
# apiserver: Running
# kubeconfig: Configured

# (inf-typed-graph) @wware ➜ /workspaces/tg-core/k8s-exercise (k8s) $ kubectl get nodes
# NAME       STATUS   ROLES           AGE   VERSION
# minikube   Ready    control-plane   44s   v1.35.1

###########################################
# curl -L https://github.com/kubernetes/kompose/releases/download/v1.36.0/kompose-linux-amd64 -o kompose
# chmod +x kompose
# sudo mv ./kompose /usr/local/bin/kompose
# history | tail -5

############################################
# one of these two
# kind load docker-image tg-core-graph-api:local
minikube image load tg-core-graph-api:local

kubectl apply -f configmap.yaml -f deployment.yaml -f service.yaml
kubectl wait --for=condition=ready pod -l app=graph-api --timeout=60s
kubectl get pods,svc
kubectl port-forward svc/graph-api 8000:8000 &
sleep 1
curl localhost:8000/bfs?seed=alice
