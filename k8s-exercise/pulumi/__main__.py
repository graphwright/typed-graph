"""Pulumi program for the graph-api exercise -- a code-first equivalent of
../configmap.yaml + ../deployment.yaml + ../service.yaml. Same resources,
same names, so it's a drop-in alternative to `kubectl apply -f ...`.

Not part of the tg-core package; see ../README.md.
"""

import pulumi
import pulumi_kubernetes as k8s

labels = {"app": "graph-api"}

config_map = k8s.core.v1.ConfigMap(
    "graph-api-config",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="graph-api-config"),
    data={
        # uvicorn's CLI reads UVICORN_-prefixed env vars automatically.
        "UVICORN_LOG_LEVEL": "info",
        "UVICORN_PORT": "8000",
    },
)

deployment = k8s.apps.v1.Deployment(
    "graph-api",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="graph-api", labels=labels),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        replicas=1,
        selector=k8s.meta.v1.LabelSelectorArgs(match_labels=labels),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(labels=labels),
            spec=k8s.core.v1.PodSpecArgs(
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="graph-api",
                        image="tg-core-graph-api:local",
                        # side-loaded via `minikube image load`, never pulled from a registry.
                        image_pull_policy="IfNotPresent",
                        ports=[k8s.core.v1.ContainerPortArgs(container_port=8000)],
                        env_from=[
                            k8s.core.v1.EnvFromSourceArgs(
                                config_map_ref=k8s.core.v1.ConfigMapEnvSourceArgs(
                                    name=config_map.metadata.name,
                                )
                            )
                        ],
                        liveness_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(
                                path="/healthz", port=8000
                            ),
                            period_seconds=10,
                            timeout_seconds=3,
                            failure_threshold=3,
                        ),
                        readiness_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(
                                path="/healthz", port=8000
                            ),
                            period_seconds=10,
                            timeout_seconds=3,
                            failure_threshold=3,
                        ),
                    )
                ],
            ),
        ),
    ),
)

service = k8s.core.v1.Service(
    "graph-api",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="graph-api"),
    spec=k8s.core.v1.ServiceSpecArgs(
        type="ClusterIP",
        selector=labels,
        ports=[k8s.core.v1.ServicePortArgs(port=8000, target_port=8000)],
    ),
)

pulumi.export("deployment_name", deployment.metadata.name)
pulumi.export("service_name", service.metadata.name)
pulumi.export("configmap_name", config_map.metadata.name)
