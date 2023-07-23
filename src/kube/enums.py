import enum


class SecretType(enum.StrEnum):
    BasicAuth = 'kubernetes.io/basic-auth'
    BootstrapToken = 'bootstrap.kubernetes.io/token'
    DockerConfigJSON = 'kubernetes.io/dockerconfigjson'
    DockerCfg = 'kubernetes.io/dockercfg'
    Helm = 'helm.sh/release.v1'
    Opaque = 'Opaque'
    ServiceAccountToken = 'kubernetes.io/service-account-token'
    SshAuth = 'kubernetes.io/ssh-auth'
    TLS = 'kubernetes.io/tls'


class PVCAccessMode(enum.StrEnum):
    ReadWriteOnce = 'ReadWriteOnce'
    ReadWriteMany = 'ReadWriteMany'
    ReadOnlyMany = 'ReadOnlyMany'


class ServiceType(enum.StrEnum):
    ClusterIP = 'ClusterIP'
    LoadBalancer = 'LoadBalancer'
    NodePort = 'NodePort'
    ExternalName = 'ExternalName'


class IngressRulePathType(enum.StrEnum):
    ImplementationSpecific = 'ImplementationSpecific'
    Exact = 'Exact'
    Prefix = 'Prefix'


class ImagePullPolicy(enum.StrEnum):
    Always = 'Always'
    IfNotPresent = 'IfNotPresent'
    Never = 'Never'


class MatchExprOperator(enum.StrEnum):
    In = 'In'
    NotIn = 'NotIn'
    Exists = 'Exists'
    DoesNotExist = 'DoesNotExist'


class VolumeModes(enum.StrEnum):
    Filesystem = 'Filesystem'
    Block = 'Block'
