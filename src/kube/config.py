from __future__ import annotations

import base64
import hashlib
import os
import warnings
from pathlib import Path
from urllib.parse import urlparse

import yaml
from kubernetes import client
from kubernetes.config.incluster_config import SERVICE_HOST_ENV_NAME, SERVICE_PORT_ENV_NAME, SERVICE_CERT_FILENAME
from urllib3.exceptions import InsecureRequestWarning
from urllib3.exceptions import MaxRetryError

from .api import KubeApi


class Kubeconfig:
    def __init__(self):
        self.__current_context = None
        self.__clusters = {}
        self.__contexts = {}
        self.__users = {}

    def set_default_context(self, name: str) -> Kubeconfig:
        """
        Set a context entry in kubeconfig.
        """
        if self.__contexts.get(name):
            self.__current_context = name

        return self

    def add_from_cluster_config(self, namespace: str = None) -> Kubeconfig:
        """
        Set kubeconfig parameters entry from cluster config.
        """
        token_file = Path(SERVICE_CERT_FILENAME)
        token = token_file.read_text()

        if not namespace:
            namespace = token_file.parent.joinpath('namespace').read_text()

        svc_host = os.getenv(SERVICE_HOST_ENV_NAME)
        svc_port = os.getenv(SERVICE_PORT_ENV_NAME)

        return self.add(f'https://{svc_host}:{svc_port}', token, namespace=namespace)

    def add(self, server: str, token: str, **kwargs) -> Kubeconfig:
        """
        Set API server parameters entry in kubeconfig.

        :param str server: Kubernetes API Server URL.
        :param str token: Bearer token for authentication to the API server.
        :param str namespace: Object name and auth scope, such as for teams and projects.
        :param str cluster_name: Cluster name use in context.
        :param str context_name: Context name for cluster.
        :param str user: User use in context.
        :param str ca_cert: Certificate authority data.
        :param bool skip_tls_verify: If true, the server's certificate will not be checked for validity. This will make
                                     your HTTPS connections insecure.
        """

        if not server.startswith('https'):
            raise ValueError('Invalid server URL. URL must be start with https://...')

        parsed_url = urlparse(server)
        if not parsed_url.port:
            server = f'{server}:443'
            parsed_url = urlparse(server)

        namespace = kwargs.get('namespace', 'default')

        try:
            KubeApi.from_token(server, token, namespace).configmap_get('kube-root-ca.crt')
        except MaxRetryError as e:
            raise ValueError(e.reason)
        except client.exceptions.ApiException as e:
            if e.status == 401:
                raise ValueError("The token provided is invalid or expired")

            raise

        tok = base64.b64encode(hashlib.sha256(token.encode()).digest()).decode()[:12]

        cluster_name = kwargs.get('cluster_name', f'{parsed_url.netloc.replace(".", "-")}')
        ctx_name = kwargs.get('context_name', f'{namespace}/{cluster_name}/token-{tok}')
        user = kwargs.get('user', f'token-{tok}/{cluster_name}')
        ca_cert = kwargs.get('ca_cert')
        insecure_skip_tls_verify = kwargs.get('skip_tls_verify', False)

        if not insecure_skip_tls_verify and not ca_cert:
            raise ValueError('Add CA data or set `skip_tls_verify=True`')

        cluster = {"server": server}
        if insecure_skip_tls_verify:
            cluster['insecure-skip-tls-verify'] = insecure_skip_tls_verify
            warnings.simplefilter(action="ignore", category=InsecureRequestWarning)

        if ca_cert:
            if ca_cert.startswith('-----BEGIN CERTIFICATE-----'):
                ca_cert = base64.b64encode(ca_cert).decode()
            cluster['certificate-authority-data'] = ca_cert

        self.__clusters.setdefault(cluster_name, cluster)
        self.__contexts.setdefault(ctx_name, {"cluster": cluster_name, "namespace": namespace, "user": user})
        self.__users.setdefault(user, {"token": token})

        if not self.__current_context:
            self.__current_context = ctx_name

        return self

    def save(self, filepath: Path | str = None):
        """
        Save kubeconfig file.
        """
        if filepath is None:
            filepath = Path.home().joinpath('.kube/config')
        elif isinstance(filepath, str):
            filepath = Path(filepath)

        filepath.parent.mkdir(0o755, True, True)

        with open(filepath, 'w') as f:
            yaml.safe_dump({
                "apiVersion": "v1",
                "kind": "Config",
                "current-context": self.__current_context,
                "preferences": {},
                "clusters": [{"name": k, "cluster": v} for k, v in self.__clusters.items()],
                "contexts": [{"name": k, "context": v} for k, v in self.__contexts.items()],
                "users": [{"name": k, "user": v} for k, v in self.__users.items()]
            }, f)

        os.chmod(filepath, 0o600)
