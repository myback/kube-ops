from datetime import datetime

from kubernetes import client


def volume_from_secret(name: str, default_mode: oct = None, items: list[client.V1KeyToPath] = None,
                       optional: bool = None) -> client.V1Volume:
    return client.V1Volume(
        name=name,
        secret=client.V1SecretVolumeSource(secret_name=name, default_mode=default_mode, items=items, optional=optional)
    )


def volume_from_configmap(name: str, default_mode: oct = None, items: list[client.V1KeyToPath] = None,
                          optional: bool = None) -> client.V1Volume:
    return client.V1Volume(
        name=name,
        config_map=client.V1ConfigMapVolumeSource(name=name, default_mode=default_mode, items=items, optional=optional)
    )


def __value_from(name: str, k: str, o):
    value_from = client.V1EnvVarSource()
    setattr(value_from, k, o)

    return client.V1EnvVar(name=name, value_from=value_from)


def env_from_secret_key_ref(var_name: str, secret_name: str, secret_key: str,
                            optional: bool = None) -> client.V1EnvVar:
    sel = client.V1SecretKeySelector(name=secret_name, key=secret_key, optional=optional)

    return __value_from(var_name, 'secret_key_ref', sel)


def env_from_configmap_key_ref(var_name: str, configmap_name: str, configmap_key: str,
                               optional: bool = None) -> client.V1EnvVar:
    sel = client.V1ConfigMapKeySelector(name=configmap_name, key=configmap_key, optional=optional)

    return __value_from(var_name, 'config_map_key_ref', sel)


def env_from_field_ref(var_name: str, field_path: str, api_version: str = 'v1') -> client.V1EnvVar:
    sel = client.V1ObjectFieldSelector(api_version=api_version, field_path=field_path)

    return __value_from(var_name, 'field_ref', sel)


def env_from_secret(name: str, prefix: str = None, optional: bool = None) -> client.V1EnvFromSource:
    return client.V1EnvFromSource(
        secret_ref=client.V1SecretEnvSource(name=name, optional=optional),
        prefix=prefix)


def env_from_configmap(name: str, prefix: str = None, optional: bool = None) -> client.V1EnvFromSource:
    return client.V1EnvFromSource(
        config_map_ref=client.V1ConfigMapEnvSource(name=name, optional=optional),
        prefix=prefix)


def empty_dir(name: str = None, medium: str = None, size_limit: str = None) -> client.V1Volume:
    if not name:
        name = f'empty-dir-{datetime.now().microsecond}'
    return client.V1Volume(
        name=name,
        empty_dir=client.V1EmptyDirVolumeSource(
            medium=medium,
            size_limit=size_limit
        ))
