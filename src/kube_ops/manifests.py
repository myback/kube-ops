from __future__ import annotations

import json
from copy import deepcopy
from typing import Optional

from kubernetes import client

from .api import KubeApi, CustomObjectDef
from .enums import (
    SecretType,
    ServiceType,
    StatefulSetUpdateStrategy,
    IngressRulePathType,
    PVCAccessMode,
    VolumeModes,
    DeploymentUpdateStrategy,
    PodManagementPolicy,
)
from .templates import (
    PodSpec,
    PodTemplateSpec,
    JobTemplateSpec,
    Container,
    V1Primitive,
    ObjectMetadata,
    LabelSelector,
    dict_str,
)


class Job(PodTemplateSpec, ObjectMetadata):
    def __init__(self, name: str, c: Container):
        super().__init__(c)
        ObjectMetadata.__init__(self, name)

        self._job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            spec=client.V1JobSpec(template=client.V1PodTemplateSpec()),
        )

    @property
    def manifest(self) -> client.V1Job:
        o = deepcopy(self._job)
        o.metadata = self._metadata
        o.spec.template = super().manifest
        return o

    def set_backoff_limit(self, n: int):
        self._job.spec.backoff_limit = n

    def set_ttl_seconds_after_finished(self, n: int):
        self._job.ttl_seconds_after_finished = n

    def set_parallelism(self, n: int):
        self._job.parallelism = n

    def create(self, kube_api: KubeApi = None) -> client.V1Job:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.job_create(self.manifest)


class CronJob(JobTemplateSpec, ObjectMetadata):
    def __init__(self, name: str, c: Container):
        super().__init__(c)
        ObjectMetadata.__init__(self, name)

        self._cj = client.V1CronJob(
            api_version="batch/v1",
            kind="CronJob",
            metadata=client.V1ObjectMeta(name=name),
            spec=client.V1CronJobSpec(
                job_template=client.V1JobTemplateSpec(), schedule="0 0 * * *"
            ),
        )

    @property
    def manifest(self) -> client.V1CronJob:
        o = deepcopy(self._cj)
        o.spec.job_template = super().manifest
        return o

    def set_annotations(self, **kwargs):
        self._cj.metadata.annotations = dict_str(**kwargs)

    def set_labels(self, **kwargs):
        self._cj.metadata.labels = dict_str(**kwargs)

    def set_pod_annotations(self, **kwargs):
        super().set_annotations(**kwargs)

    def set_pod_labels(self, **kwargs):
        super().set_labels(**kwargs)

    def set_schedule(self, cron: str):
        self._cj.spec.schedule = cron

    def set_starting_deadline_seconds(self, n: int):
        self._cj.spec.starting_deadline_seconds = n

    def set_concurrency_policy(self, policy: str):
        self._cj.spec.concurrency_policy = policy

    def set_failed_jobs_history_limit(self, n: int):
        self._cj.spec.failed_jobs_history_limit = n

    def set_successful_jobs_history_limit(self, n: int):
        self._cj.spec.successful_jobs_history_limit = n

    def set_time_zone(self, tz: str):
        self._cj.spec.time_zone = tz

    def set_suspend(self, b: bool):
        self._cj.spec.suspend = b

    def create(self, kube_api: KubeApi = None) -> client.V1CronJob:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.cron_job_create(self.manifest)


class Ingress(ObjectMetadata):
    def __init__(self, name: str):
        super().__init__(name)

        self._obj = client.V1Ingress(
            api_version="networking.k8s.io/v1",
            kind="Ingress",
            spec=client.V1IngressSpec(),
        )

    @property
    def manifest(self) -> client.V1Ingress:
        o = deepcopy(self._obj)
        o.metadata = self._metadata

        return o

    def set_default_backend(
        self,
        service_name: str = None,
        service_port: int | str = None,
        ref: client.V1TypedLocalObjectReference = None,
    ):
        self._obj.spec.default_backend = self._ingress_backend(
            service_name, service_port, ref
        )

    def set_ingress_class_name(self, name: str):
        self._obj.spec.ingress_class_name = name

    def add_rule(
        self,
        host: str,
        service_name: str,
        path: str = None,
        service_port: Optional[str, int] = "http",
        path_type: IngressRulePathType = IngressRulePathType.Prefix,
        ref: client.V1TypedLocalObjectReference = None,
    ):
        if not path:
            path = "/"

        backend_path = client.V1HTTPIngressPath(
            backend=self._ingress_backend(service_name, service_port, ref),
            path=path,
            path_type=path_type.value,
        )

        if self._obj.spec.rules is None:
            self._obj.spec.rules = []

        for i, rule in enumerate(self._obj.spec.rules):
            if rule.host == host:
                for p in rule.http.paths:
                    if p.path == path:
                        return

                rule.http.paths.append(backend_path)

                self._obj.spec.rules[i] = rule
                return

        self._obj.spec.rules.append(
            client.V1IngressRule(
                host=host,
                http=client.V1HTTPIngressRuleValue(paths=[backend_path]),
            )
        )

    def add_tls(self, *hosts: str, secret_name: str = None):
        if self._obj.spec.tls:
            for tls in self._obj.spec.tls:
                if secret_name == tls.secret_name:
                    return
        else:
            self._obj.spec.tls = []

        self._obj.spec.tls.append(
            client.V1IngressTLS(hosts=hosts, secret_name=secret_name)
        )

    @staticmethod
    def _ingress_backend(
        service_name: str = None,
        service_port: int | str = None,
        ref: client.V1TypedLocalObjectReference = None,
    ) -> client.V1IngressBackend:
        backend = client.V1IngressBackend()
        if ref:
            backend.resource = ref
            return backend

        if isinstance(service_port, int):
            port_def = client.V1ServiceBackendPort(number=service_port)
        else:
            port_def = client.V1ServiceBackendPort(name=service_port)

        backend.service = client.V1IngressServiceBackend(
            name=service_name, port=port_def
        )

        return backend

    def create(self, kube_api: KubeApi = None) -> client.V1Ingress:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.ingress_create(self.manifest)


class Route(ObjectMetadata):
    def __init__(self, name: str):
        super().__init__(name)
        self._route = {
            "apiVersion": "route.openshift.io/v1",
            "kind": "Route",
            "metadata": {},
            "spec": {},
        }

    @property
    def manifest(self) -> dict:
        o = self._route.copy()
        o["metadata"] = self._metadata.to_dict()

        return o

    def add_rule(
        self,
        host: str,
        service_name: str,
        path: str = None,
        service_port: Optional[str, int] = "http",
        weight: int = 100,
    ):
        self._route["spec"]["host"] = host
        self._route["spec"]["to"] = {
            "kind": "Service",
            "name": service_name,
            "weight": weight,
        }
        self._route["spec"]["port"] = {
            "targetPort": service_port,
        }

        if path:
            self._route["spec"]["path"] = path

    def add_tls(
        self,
        termination_type=None,
        tls_insecure_policy=None,
        tls_ca_cert=None,
        tls_cert=None,
        tls_key=None,
        tls_dest_ca_cert=None,
    ):
        if not termination_type:
            self._route["spec"]["tls"] = None
            return

        route_tls = {"termination": termination_type.capitalize()}
        if tls_insecure_policy:
            if termination_type == "edge":
                route_tls["insecureEdgeTerminationPolicy"] = (
                    tls_insecure_policy.capitalize()
                )
            elif termination_type == "passthrough":
                # if tls_insecure_policy != "redirect":
                #     self.fail_json(
                #         "'redirect' is the only supported insecureEdgeTerminationPolicy for passthrough routes"
                #     )
                route_tls["insecureEdgeTerminationPolicy"] = (
                    tls_insecure_policy.capitalize()
                )
            elif termination_type == "reencrypt":
                ...
                # self.fail_json(
                #     "'tls.insecure_policy' is not supported with reencrypt routes"
                # )
        else:
            route_tls["insecureEdgeTerminationPolicy"] = None

        if tls_ca_cert:
            # if termination_type == "passthrough":
            #     self.fail_json(
            #         "'tls.ca_certificate' is not supported with passthrough routes"
            #     )
            route_tls["caCertificate"] = tls_ca_cert
        if tls_cert:
            # if termination_type == "passthrough":
            #     self.fail_json(
            #         "'tls.certificate' is not supported with passthrough routes"
            #     )
            route_tls["certificate"] = tls_cert
        if tls_key:
            # if termination_type == "passthrough":
            #     self.fail_json("'tls.key' is not supported with passthrough routes")
            route_tls["key"] = tls_key
        if tls_dest_ca_cert:
            # if termination_type != "reencrypt":
            #     self.fail_json(
            #         "'destination_certificate' is only valid for reencrypt routes"
            #     )
            route_tls["destinationCACertificate"] = tls_dest_ca_cert

        self._route["spec"]["tls"] = route_tls

    def set_wildcard_policy(self, policy: str):
        self._route["spec"]["wildcardPolicy"] = policy

    def create(self, kube_api: KubeApi = None):
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.custom_object_create(
            self.manifest,
            CustomObjectDef("route.openshift.io", "v1", "routes"),
        )


class Service(ObjectMetadata):
    def __init__(self, name: str):
        super().__init__(name)

        self._svc = client.V1Service(
            api_version="v1", kind="Service", spec=client.V1ServiceSpec()
        )

    @property
    def manifest(self) -> client.V1Service:
        svc = deepcopy(self._svc)
        svc.metadata = self._metadata
        return svc

    def set_selector(self, **kwargs):
        self._svc.spec.selector = dict_str(**kwargs)

    def set_type(self, t: ServiceType):
        self._svc.spec.type = t.value

    def add_port(
        self,
        name: str,
        port: int,
        target_port_or_name,
        proto: str = None,
        node_port: int = None,
        app_protocol: str = None,
    ):
        if self._svc.spec.ports:
            for p in self._svc.spec.ports:
                if p.name == name:
                    return
        else:
            self._svc.spec.ports = []

        self._svc.spec.ports.append(
            client.V1ServicePort(
                name=name,
                port=port,
                target_port=target_port_or_name,
                protocol=proto,
                node_port=node_port,
                app_protocol=app_protocol,
            )
        )

    # def ingress(self) -> Ingress: ...

    def create(self, kube_api: KubeApi = None) -> client.V1Service:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.service_create(self.manifest)


class Pod(PodSpec, ObjectMetadata):
    def __init__(self, name: str, c: Container):
        super().__init__(c)
        ObjectMetadata.__init__(self, name)

        self._pod = client.V1Pod(
            api_version="v1",
            kind="Pod",
        )

    @property
    def manifest(self) -> client.V1Pod:
        o = deepcopy(self._pod)
        o.metadata = self._metadata
        o.spec = super().manifest
        return o

    def set_annotations(self, **kwargs):
        self._pod.metadata.annotations = dict_str(**kwargs)

    def set_labels(self, **kwargs):
        self._pod.metadata.labels = dict_str(**kwargs)

    def create(self, kube_api: KubeApi = None) -> client.V1Pod:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.pod_create(self.manifest)


class _KubeObjectWrapper(PodTemplateSpec, ObjectMetadata, LabelSelector):
    def __init__(self, name: str, c: Container):
        super().__init__(c)
        ObjectMetadata.__init__(self, name)
        LabelSelector.__init__(self)

        self._obj = None

    @property
    def manifest(self):
        o = deepcopy(self._obj)
        o.metadata = self._metadata
        o.spec.selector = self._selector
        o.spec.template = super().manifest
        return o

    def set_replicas(self, n: int):
        self._obj.spec.replicas = n

    def service(self, name: str = None, port: int = 80) -> Service:
        if name is None:
            if isinstance(self._obj, client.V1StatefulSet):
                name = self._obj.spec.service_name
            else:
                name = self.name

        svc = Service(name)
        svc.set_selector(**self._selector.match_labels)

        for c in self._containers:
            m = c.manifest
            has_one_port = len(m.ports) == 1
            for p in m.ports:
                if p.protocol is None:
                    continue
                svc.add_port(
                    p.name,
                    port if has_one_port else p.container_port,
                    p.name,
                    app_protocol=p.protocol,
                )

        return svc


class Deployment(_KubeObjectWrapper):
    def __init__(self, name: str, c: Container):
        super().__init__(name, c)

        self._obj = client.V1Deployment(
            api_version="apps/v1",
            kind="Deployment",
            spec=client.V1DeploymentSpec(
                selector=client.V1LabelSelector(),
                template=client.V1PodTemplateSpec(
                    spec=client.V1PodSpec(containers=[]),
                ),
            ),
        )

    @property
    def manifest(self) -> client.V1Deployment:
        return super().manifest

    @property
    def selector_match_labels(self) -> dict[str, str]:
        return self._obj.spec.selector.match_labels.copy()

    def set_revision_history_limit(self, n: int):
        self._obj.spec.revision_history_limit = n

    def set_strategy(
        self,
        typ: DeploymentUpdateStrategy = DeploymentUpdateStrategy.RollingUpdate,
        max_surge: Optional[str, int] = None,
        max_unavailable: Optional[str, int] = None,
    ):
        self._obj.spec.strategy = client.V1DeploymentStrategy(
            type=typ.value,
            rolling_update=client.V1RollingUpdateDeployment(
                max_surge=max_surge, max_unavailable=max_unavailable
            ),
        )

    def create(self, kube_api: KubeApi = None) -> client.V1Deployment:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.deployment_create(self.manifest)


class StatefulSet(_KubeObjectWrapper):
    def __init__(self, name: str, c: Container):
        super().__init__(name, c)

        self._obj = client.V1StatefulSet(
            api_version="`apps/v1",
            kind="StatefulSet",
            spec=client.V1StatefulSetSpec(
                service_name="",
                selector=client.V1LabelSelector(),
                template=client.V1PodTemplateSpec(),
            ),
        )

    @property
    def manifest(self) -> client.V1StatefulSet:
        return super().manifest

    def set_revision_history_limit(self, n: int):
        self._obj.spec.revision_history_limit = n

    def set_strategy(
        self,
        typ: StatefulSetUpdateStrategy = StatefulSetUpdateStrategy.RollingUpdate,
        max_unavailable: Optional[str, int] = None,
        partition: Optional[int] = None,
    ):

        self._obj.spec.update_strategy = client.V1StatefulSetUpdateStrategy(
            type=typ.value,
            rolling_update=client.V1RollingUpdateStatefulSetStrategy(
                max_unavailable=max_unavailable, partition=partition
            ),
        )

    def set_service_name(self, name: str):
        self._obj.spec.service_name = name

    def set_persistent_volume_claim_retention_policy(
        self, when_deleted: str, when_scaled: str
    ):
        o = client.V1StatefulSetPersistentVolumeClaimRetentionPolicy(
            when_deleted=when_deleted, when_scaled=when_scaled
        )
        self._obj.spec.persistent_volume_claim_retention_policy = o

    def set_pod_management_policy(self, policy: PodManagementPolicy):
        self._obj.spec.pod_management_policy = policy.value

    def add_volume_claim_templates(self, pvc: client.V1PersistentVolumeClaim):
        if self._obj.spec.volume_claim_templates:
            for p in self._obj.spec.volume_claim_templates:
                if p.metadata.name == pvc.metadata.name:
                    return
        else:
            self._obj.spec.volume_claim_templates = []

        self._obj.spec.volume_claim_templates.append(pvc)

    def create(self, kube_api: KubeApi = None) -> client.V1StatefulSet:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.stateful_set_create(self.manifest)


class Secret(ObjectMetadata, V1Primitive):
    def __init__(self, name: str, typ: SecretType = SecretType.Opaque):
        super().__init__(name)
        V1Primitive.__init__(self)

        self._secret = client.V1Secret(
            api_version="v1", kind="Secret", type=typ.value
        )

    @property
    def manifest(self):
        sec = deepcopy(self._secret)
        sec.metadata = self._metadata
        sec.immutable = self._immutable
        if self._binary_data:
            sec.data = self._binary_data

        return sec

    def set(self, **kwargs):
        for k, v in kwargs.items():
            self._set_binary_data(k, v)

    def create(self, kube_api: KubeApi = None) -> client.V1Secret:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.secret_create(self.manifest)


class SecretImagePull(Secret):
    def __init__(self, name: str):
        super().__init__(name, SecretType.DockerConfigJSON)

        self._registries = {}

    def add_registry(
        self, registry: str, username: str, password: str, email: str
    ):
        if self._registries.get(registry):
            return

        self._registries[registry] = {
            "username": username,
            "password": password,
            "email": email,
            "auth": self.to_base64(f"{username}:{password}"),
        }

    @property
    def manifest(self):
        auth = json.dumps({"auths": self._registries})
        self.set(**{".dockerconfigjson": auth})

        return super().manifest


class SecretTLS(Secret):
    def __init__(self, name: str):
        super().__init__(name, SecretType.TLS)

    def set(self, tls_cert: str, tls_key: str, ca_crt: str = None):
        data = {"tls.crt": tls_cert, "tls.key": tls_key}
        if ca_crt:
            data["ca.crt"] = ca_crt

        super().set(**data)


class SecretServiceAccountToken(Secret):
    def __init__(self, name: str):
        super().__init__(name, SecretType.ServiceAccountToken)

    def set(self, namespace: str, token: str, ca_crt: str = None):
        data = {"namespace": namespace, "token": token}
        if ca_crt:
            data["ca.crt"] = ca_crt

        super().set(**data)


class ConfigMap(ObjectMetadata, V1Primitive):
    def __init__(self, name: str):
        super().__init__(name)
        V1Primitive.__init__(self)

        self._cm = client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
        )

    @property
    def manifest(self):
        cm = deepcopy(self._cm)
        cm.metadata = self._metadata
        cm.immutable = self._immutable
        if self._string_data:
            cm.data = self._string_data
        if self._binary_data:
            cm.binary_data = self._binary_data

        return cm

    def set_binary_data(self, **kwargs):
        for k, v in kwargs.items():
            self._set_binary_data(k, v)

    def create(self, kube_api: KubeApi = None) -> client.V1ConfigMap:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.configmap_create(self.manifest)


class Namespace(ObjectMetadata):
    def __init__(self, name: str):
        super().__init__(name)

        self._ns = client.V1Namespace(api_version="v1", kind="Namespace")

    @property
    def manifest(self) -> client.V1Namespace:
        ns = deepcopy(self._ns)
        ns.metadata = self._metadata
        return ns

    def create(self, kube_api: KubeApi = None) -> client.V1Namespace:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.namespace_create(self.manifest)


class PersistentVolumeClaim(ObjectMetadata, LabelSelector):
    def __init__(self, name: str):
        super().__init__(name)

        self._pvc = client.V1PersistentVolumeClaim(
            api_version="v1",
            kind="PersistentVolumeClaim",
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=[],
                resources=client.V1ResourceRequirements(),
            ),
        )

    @property
    def manifest(self) -> client.V1PersistentVolumeClaim:
        pvc = deepcopy(self._pvc)
        pvc.metadata = self._metadata
        pvc.spec.selector = self._selector
        return pvc

    def set_access_modes(self, *args: PVCAccessMode):
        self._pvc.spec.access_modes = [a.value for a in args]

    def set_data_source(self, name: str, api_group: str, kind: str):
        self._pvc.spec.data_source = client.V1TypedLocalObjectReference(
            api_group, kind, name
        )

    def set_data_source_ref(
        self, name: str, namespace: str, api_group: str, kind: str
    ):
        self._pvc.spec.data_source_ref = client.V1TypedObjectReference(
            api_group, kind, name, namespace
        )

    def set_storage_class_name(self, name: str):
        self._pvc.spec.storage_class_name = name

    def set_volume_mode(self, mode: VolumeModes):
        self._pvc.spec.volume_mode = mode.value

    def set_volume_name(self, name: str):
        self._pvc.spec.volume_name = name

    def set_resources_requests(self, size: str):
        self._pvc.spec.resources.requests = {"storage": size}

    def set_resources_limits(self, size: str):
        self._pvc.spec.resources.limits = {"storage": size}

    def create(
        self, kube_api: KubeApi = None
    ) -> client.V1PersistentVolumeClaim:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.pvc_create(self.manifest)


class ServiceAccount(ObjectMetadata):
    def __init__(self, name):
        super().__init__(name)

        self._sa = client.V1ServiceAccount(
            api_version="v1", kind="ServiceAccount"
        )

    @property
    def manifest(self) -> client.V1ServiceAccount:
        sa = deepcopy(self._sa)
        sa.metadata = self._metadata
        return sa

    def set_automount_service_account_token(self, b: bool):
        self._sa.automount_service_account_token = b

    def add_image_pull_secrets(self, name: str):
        self._sa.image_pull_secrets.append(
            client.V1LocalObjectReference(name=name)
        )

    def add_secret(self, ref: client.V1ObjectReference):
        self._sa.secrets.append(ref)

    def add_secret_name(self, name: str):
        self._sa.secrets.append(client.V1ObjectReference(name=name))

    def create(self, kube_api: KubeApi = None) -> client.V1ServiceAccount:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.service_account_create(self.manifest)


class _RoleWrapper(ObjectMetadata):
    def __init__(self, name: str, cluster_scope: bool = False):
        super().__init__(name)

        kind, obj = "Role", client.V1Role
        if cluster_scope:
            kind, obj = "ClusterRole", client.V1ClusterRole

        self._role = obj(
            api_version="rbac.authorization.k8s.io/v1", kind=kind, rules=[]
        )

    @property
    def manifest(self) -> client.V1Role | client.V1ClusterRole:
        role = deepcopy(self._role)
        role.metadata = self._metadata
        return role

    def add_rule(self, rule: client.V1PolicyRule):
        self._role.rules.append(rule)


class _RoleBindingWrapper(ObjectMetadata):
    def __init__(self, name: str, cluster_scope: bool = False):
        super().__init__(name)

        kind, obj = "Role", client.V1RoleBinding
        if cluster_scope:
            kind, obj = "ClusterRole", client.V1ClusterRoleBinding

        self._role_binding = obj(
            api_version="rbac.authorization.k8s.io/v1",
            kind=kind,
            role_ref=client.V1RoleRef(
                "rbac.authorization.k8s.io", kind, ""
            ),
            subjects=[],
        )

    @property
    def manifest(self) -> client.V1RoleBinding | client.V1ClusterRoleBinding:
        rb = deepcopy(self._role_binding)
        rb.metadata = self._metadata
        return rb

    def set_role_ref(
        self, name: str, api_group: str = None, kind: str = None
    ):
        self._role_binding.role_ref.name = name
        if api_group:
            self._role_binding.role_ref.api_group = api_group
        if kind:
            self._role_binding.role_ref.kind = kind

    def add_subject(
        self, kind: str, name: str, namespace: str, api_group: str = None
    ):
        self._role_binding.subjects.append(
            client.RbacV1Subject(
                api_group=api_group, kind=kind, name=name, namespace=namespace
            )
        )


class Role(_RoleWrapper):
    def __init__(self, name: str):
        super().__init__(name)

    @property
    def manifest(self) -> client.V1Role:
        return super().manifest

    def create(self, kube_api: KubeApi = None) -> client.V1Role:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.role_create(self.manifest)


class RoleBinding(_RoleBindingWrapper):
    def __init__(self, name: str):
        super().__init__(name)

    @property
    def manifest(self) -> client.V1RoleBinding:
        return super().manifest

    def create(self, kube_api: KubeApi = None) -> client.V1RoleBinding:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.role_binding_create(self.manifest)


class ClusterRole(_RoleWrapper):
    def __init__(self, name: str):
        super().__init__(name, True)

    @property
    def manifest(self) -> client.V1ClusterRole:
        return super().manifest

    def add_aggregation_rule(self, rule: client.V1LabelSelector):
        if not self._role.aggregation_rule:
            self._role.aggregation_rule = client.V1AggregationRule(
                cluster_role_selectors=[]
            )

        self._role.aggregation_rule.cluster_role_selectors.append(rule)

    def create(self, kube_api: KubeApi = None) -> client.V1ClusterRole:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.cluster_role_create(self.manifest)


class ClusterRoleBinding(_RoleBindingWrapper):
    def __init__(self, name: str):
        super().__init__(name, True)

    @property
    def manifest(self) -> client.V1ClusterRoleBinding:
        return super().manifest

    def create(self, kube_api: KubeApi = None) -> client.V1ClusterRoleBinding:
        if kube_api is None:
            kube_api = KubeApi()
        return kube_api.cluster_role_binding_create(self.manifest)
