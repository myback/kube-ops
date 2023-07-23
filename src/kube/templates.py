from copy import deepcopy

from kubernetes import client

from .enums import ImagePullPolicy


def dict_str(**kwargs):
    if not kwargs:
        return

    return dict(map(lambda kv: (kv[0], str(kv[1])), kwargs.items()))


class ObjectMetadata:
    def __init__(self, name: str):
        self._metadata = client.V1ObjectMeta(name=name)

    def set_namespace(self, namespace: str):
        self._metadata.namespace = namespace

    def set_annotations(self, **kwargs):
        self._metadata.annotations = dict_str(**kwargs)

    def set_labels(self, **kwargs):
        self._metadata.labels = dict_str(**kwargs)

    def set_generate_name(self, name: str):
        self._metadata.generate_name = name

    def add_finalizers(self, finalizer: str):
        if self._metadata.finalizers is None:
            self._metadata.finalizers = []
        else:
            if finalizer in self._metadata.finalizers:
                return

        self._metadata.finalizers.append(finalizer)

    @property
    def name(self) -> str:
        return self._metadata.name


class V1Primitive:
    def __init__(self):
        self._string_data = {}
        self._binary_data = {}
        self._immutable = None

    def set_immutable(self, b: bool):
        self._immutable = b

    def set(self, k: str, v):
        self._string_data[k] = v

    def set_default(self, k: str, v):
        return self._string_data.setdefault(k, v)

    # TODO: will be encoded twice if set to base64 encoded value
    def set_data(self, **kwargs):
        self._string_data = dict_str(**kwargs)

    def set_string(self, k: str, v: str):
        self._string_data[k] = v

    def set_default_string(self, k: str, v: str) -> str:
        return self._string_data.setdefault(k, v)

    def set_string_data(self, **kwargs):
        self._string_data = dict_str(**kwargs)


class Container:
    def __init__(self, name: str):
        self._c = client.V1Container(name=name)

    @property
    def name(self):
        return self._c.name

    @property
    def manifest(self) -> client.V1Container:
        return deepcopy(self._c)

    def set_command(self, *args):
        self._c.command = list(args)

    def set_args(self, *args):
        self._c.args = list(args)

    def set_image(self, image: str):
        self._c.image = image

    def set_working_dir(self, path: str):
        self._c.working_dir = path

    def set_image_pull_policy(self, policy: ImagePullPolicy):
        self._c.image_pull_policy = policy.value

    def set_startup_probe(self, probe: client.V1Probe):
        self._c.startup_probe = probe

    def set_liveness_probe(self, probe: client.V1Probe):
        self._c.liveness_probe = probe

    def set_readiness_probe(self, probe: client.V1Probe):
        self._c.readiness_probe = probe

    def set_resources(self, res: client.V1ResourceRequirements):
        self._c.resources = res

    def set_security_context(self, sc: client.V1SecurityContext):
        self._c.security_context = sc

    def add_port(self, name: str, container_port: int, protocol: str = None, host_ip: str = None,
                 host_port: int = None):
        if self._c.ports is None:
            self._c.ports = []
        else:
            for p in self._c.ports:
                if p.name == name:
                    return

        self._c.ports.append(client.V1ContainerPort(name=name, container_port=container_port, protocol=protocol,
                                                    host_ip=host_ip, host_port=host_port))

    def _is_volume_mount_exists(self, name: str) -> bool:
        for vm in self._c.volume_mounts:
            if vm.name == name:
                return True
        return False

    def add_volume_mount(self, vm: client.V1VolumeMount):
        if self._c.volume_mounts:
            if self._is_volume_mount_exists(vm.name):
                return
        else:
            self._c.volume_mounts = []

        self._c.volume_mounts.append(vm)

    def add_env_kv(self, k: str, v: str):
        if self._c.env is None:
            self._c.env = []
        else:
            for e in self._c.env:
                if e.name == k:
                    return

        self._c.env.append(client.V1EnvVar(name=k, value=v))

    def add_env(self, env: client.V1EnvVar):
        if self._c.env is None:
            self._c.env = []
        else:
            for e in self._c.env:
                if e.name == env.name:
                    return

        self._c.env.append(env)

    def add_env_from(self, env_from: client.V1EnvFromSource):
        if self._c.env_from is None:
            self._c.env_from = []
        else:
            for e in self._c.env_from:
                if e.secret_ref and e.secret_ref.name == env_from.secret_ref.name:
                    return

                if e.config_map_ref and e.config_map_ref.name == env_from.config_map_ref.name:
                    return

        self._c.env_from.append(env_from)


class PodSpec:
    def __init__(self, c: Container):
        self._containers: list[Container] = [c]
        self._init_containers: list[Container] = []

        self._pod_spec = client.V1PodSpec(containers=[])

    @property
    def manifest(self) -> client.V1PodSpec:
        o = deepcopy(self._pod_spec)
        o.containers = [c.manifest for c in self._containers]

        if self._init_containers:
            o.init_containers = [c.manifest for c in self._init_containers]
        return o

    def set_restart_policy(self, policy: str):
        self._pod_spec.restart_policy = policy

    def add_image_pull_secret(self, name: str):
        if self._pod_spec.image_pull_secrets is None:
            self._pod_spec.image_pull_secrets = []
        else:
            for s in self._pod_spec.image_pull_secrets:
                if s['name'] == name:
                    return

        self._pod_spec.image_pull_secrets.append({'name': name})

    def add_container(self, c: Container):
        for ce in self._containers:
            if ce.name == c.name:
                return

        self._containers.append(c)

    def add_init_container(self, c: Container):
        for ce in self._init_containers:
            if ce.name == c.name:
                return

        self._init_containers.append(c)

    def set_affinity(self, af: client.V1Affinity):
        self._pod_spec.affinity = af

    def set_automount_service_account_token(self, b: bool):
        self._pod_spec.automount_service_account_token = b

    def set_dns_config(self, dns_conf: client.V1PodDNSConfig):
        self._pod_spec.dns_config = dns_conf

    def set_dns_policy(self, policy: str):
        self._pod_spec.dns_policy = policy

    def enable_service_links(self, b: bool):
        self._pod_spec.enable_service_links = b

    # def add_ephemeral_containers(self):
    #     pass

    def add_host_aliases(self, hosts: list[str], ip: str):
        if self._pod_spec.host_aliases:
            for h in self._pod_spec.host_aliases:
                if h.ip == ip:
                    return
        else:
            self._pod_spec.host_aliases = []

        self._pod_spec.host_aliases.append(client.V1HostAlias(hostnames=hosts, ip=ip))

    def set_host_ipc(self, b: bool):
        self._pod_spec.host_ipc = b

    def set_host_network(self, b: bool):
        self._pod_spec.host_network = b

    def set_host_pid(self, b: bool):
        self._pod_spec.host_pid = b

    def set_host_users(self, b: bool):
        self._pod_spec.host_users = b

    def set_hostname(self, host: str):
        self._pod_spec.hostname = host

    def set_node_selector(self, **kwargs):
        self._pod_spec.node_selector = dict_str(**kwargs)

    def set_service_account_name(self, sa: str):
        self._pod_spec.service_account_name = sa

    def set_share_process_namespace(self, b: bool):
        self._pod_spec.share_process_namespace = b

    def set_termination_grace_period_seconds(self, n: int):
        self._pod_spec.termination_grace_period_seconds = n

    def add_tolerations(self, t: client.V1Toleration):
        if not self._pod_spec.tolerations:
            self._pod_spec.tolerations = []

        self._pod_spec.tolerations.append(t)

    def _add_volume(self, vol: client.V1Volume):
        if self._pod_spec.volumes:
            for v in self._pod_spec.volumes:
                if v.name == vol.name:
                    return
        else:
            self._pod_spec.volumes = []

        self._pod_spec.volumes.append(vol)

    def _add_volume_mount(self, container_name: str, container_list: list[Container],
                          volume_name: str, mount_path: str, sub_path: str = None, read_only: bool = None) -> bool:
        for i, c in enumerate(container_list):
            if c.name == container_name:
                vm = client.V1VolumeMount(name=volume_name, mount_path=mount_path,
                                          sub_path=sub_path, read_only=read_only)
                self._containers[i].add_volume_mount(vm)
                return True
        return False

    def add_volume_to_container(self, container_name: str, vol: client.V1Volume, mount_path: str,
                                sub_path: str = None, read_only: bool = None):
        self._add_volume(vol)

        if not self._add_volume_mount(container_name, self._containers, vol.name, mount_path, sub_path, read_only):
            raise ValueError(f'`Container` with name `{container_name}` not found in `podSpec`')

    def add_volume_to_init_container(self, container_name: str, vol: client.V1Volume, mount_path: str,
                                     sub_path: str = None, read_only: bool = None):
        self._add_volume(vol)

        if not self._add_volume_mount(container_name, self._init_containers, vol.name, mount_path, sub_path, read_only):
            raise ValueError(f'`InitContainer` with name `{container_name}` not found in `podSpec`')


class _TemplateSpec(PodSpec):
    def __init__(self, c: Container, template_spec: client.V1PodTemplateSpec | client.V1JobTemplateSpec):
        super().__init__(c)

        self._template_spec = template_spec

    @property
    def manifest(self):
        o = deepcopy(self._template_spec)
        o.spec = super().manifest

        return o

    def _check_metadata(self):
        if self._template_spec.metadata is None:
            self._template_spec.metadata = client.V1ObjectMeta()

    def set_pod_annotations(self, **kwargs):
        self._check_metadata()
        self._template_spec.metadata.annotations = dict_str(**kwargs)

    def set_pod_labels(self, **kwargs):
        self._check_metadata()
        self._template_spec.metadata.labels = dict_str(**kwargs)


class PodTemplateSpec(_TemplateSpec):
    def __init__(self, c: Container):
        super().__init__(c, client.V1PodTemplateSpec())


class JobTemplateSpec(_TemplateSpec):
    def __init__(self, c: Container):
        super().__init__(c, client.V1JobTemplateSpec())
