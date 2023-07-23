from __future__ import annotations

import abc
import base64
import logging
import os
import time
import typing
from pathlib import Path

import yaml
from kubernetes import client, config as kube_config
from kubernetes.client.rest import ApiException
from kubernetes.config.incluster_config import SERVICE_HOST_ENV_NAME, \
    SERVICE_PORT_ENV_NAME, SERVICE_CERT_FILENAME
from kubernetes.stream import stream, ws_client

client.rest.logger.setLevel(logging.WARNING)


class CustomObjectDef(typing.NamedTuple):
    """
    Class helper for custom resources definition in Kubernetes

    :example: For
              `apiVersion: route.openshift.io/v1
               kind: Route`

              c = CustomObjectDef('route.openshift.io', 'v1', 'routes')
    """

    group: str
    version: str
    plural: str


def dict_to_labels(data: dict[str, str]) -> str:
    return ",".join([f'{k}={v}' for k, v in data.items()])


def is_pod_ready(pod: client.V1Pod) -> bool:
    statuses = pod.status.container_statuses or []
    return not pod.metadata.deletion_timestamp and all(map(lambda s: s.ready if s else False, statuses))


class Writer:
    @abc.abstractmethod
    def write(self, data):
        pass


class ResponseDataCollector(Writer, list):
    def write(self, s: str):
        super().extend(s.rstrip("\n").split("\n"))


class Logger(Writer):
    def __init__(self, log: logging.log):
        self._log = log

    def write(self, data):
        self._log(data)


class FileWriter(Writer):
    def __init__(self, file_path: Path, mode: str = "w"):
        self._fd = file_path.open(mode=mode)

    def write(self, data):
        self._fd.write(data)

    def close(self):
        self._fd.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class PodStatus:
    def __init__(self, status: str):
        self._status = status

    @property
    def status(self):
        return self._status

    def sys_exit(self):
        exit(int(self))

    def __int__(self):
        if self._status in ['Running', 'Succeeded']:
            return 0
        elif self._status in ['Failed']:
            return 1
        else:
            return 255

    def __str__(self):
        return self.status

    def __repr__(self):
        return f'Pod status: {self.status} ({int(self)})'

    def __eq__(self, other):
        return self.status == other

    @property
    def is_running(self) -> bool:
        return self.status == 'Running'

    @property
    def is_failed(self) -> bool:
        return self.status == 'Failed'

    @property
    def is_succeeded(self) -> bool:
        return self.status == 'Succeeded'


class JobStatus(PodStatus):
    def __init__(self, status: client.V1JobStatus):
        if status.active == 1:
            s = 'Running'
        elif status.succeeded == 1:
            s = 'Succeeded'
        elif status.failed == 1:
            s = 'Failed'
        else:
            s = 'Unknown'

        super().__init__(s)


class KubeApi:
    def __init__(self, namespace: str = None, conf: client.Configuration = None):
        self._ns = None
        self._conf = None

        if conf:
            client.Configuration().set_default(conf)
            self._conf = conf
        else:
            if self.is_use_in_cluster():
                kube_config.load_incluster_config()
                self._ns = Path(SERVICE_CERT_FILENAME).parent.joinpath('namespace').read_text()
            else:
                kube_config.load_kube_config()

        if namespace:
            self._ns = namespace
        else:
            if self._ns is None:
                _, curr_ctx = kube_config.list_kube_config_contexts()
                self._ns = curr_ctx.get('context', {}).get('namespace', 'default')

    @staticmethod
    def from_token(host: str, token: str, namespace: str = None,
                   ca_cert_data: str = None) -> KubeApi:
        """
        Return new instance of Kube with specific connection configuration.

        :param host: URL to a Kubernetes API server.
        :param token: The Bearer token for API authentication.
        :param namespace: Specific a Kubernetes namespace.
        :param ca_cert_data: The certificate file to verify the peer.

        :return: The new instance of Kube
        """

        conf = client.Configuration().get_default_copy()
        conf.host = host
        conf.api_key['authorization'] = token
        conf.api_key_prefix['authorization'] = 'Bearer'
        conf.ssl_ca_cert = ca_cert_data
        if not ca_cert_data:
            conf.verify_ssl = False

        return KubeApi(namespace, conf)

    @staticmethod
    def is_use_in_cluster() -> bool:
        return os.getenv(SERVICE_HOST_ENV_NAME, False) and \
            os.getenv(SERVICE_PORT_ENV_NAME, False)

    @property
    def apps_v1(self):
        return client.AppsV1Api(self._conf)

    @property
    def core_v1(self):
        return client.CoreV1Api(self._conf)

    @property
    def batch_v1(self):
        return client.BatchV1Api(self._conf)

    @property
    def networking_v1(self):
        return client.NetworkingV1Api(self._conf)

    @property
    def custom_object_api(self):
        return client.CustomObjectsApi(self._conf)

    def _exec(self,
              pod_name: str,
              command: list,
              stdout: Writer,
              stderr: Writer,
              **kwargs) -> tuple[Writer, Writer, dict] | None:
        """
        Execute a command in a container.

        See all parameters in core_v1.connect_post_namespaced_pod_exec function.
        """

        kwargs.setdefault('stdout', True)
        kwargs.setdefault('stderr', True)
        kwargs.setdefault('async_req', False)
        kwargs.setdefault('stdin', False)
        kwargs.setdefault('tty', False)
        _preload_content = kwargs.setdefault('_preload_content', False)
        kwargs['command'] = command

        ns = kwargs.pop('namespace', self._ns)
        r = stream(self.core_v1.connect_post_namespaced_pod_exec,
                   pod_name, self._ns, **kwargs)
        while r.is_open():
            r.update(timeout=1)
            if r.peek_stdout():
                stdout.write(r.read_stdout())
            if r.peek_stderr():
                stderr.write(r.read_stderr())

        e = r.read_channel(ws_client.ERROR_CHANNEL)
        err = yaml.safe_load(e)
        r.close()

        if _preload_content:
            return stdout, stderr, err

        if err['status'] != "Success":
            _code = int(err['details']['causes'][0]['message'])
            cmd = " ".join(command)

            logging.debug(err)
            raise Exception(f'command "{cmd}" ended with status code: {_code}')

    def run_command(self,
                    pod_name: str,
                    command: list,
                    container: str = None,
                    **kwargs) -> tuple[list, list, dict] | None:
        """
        Execute a command in a container.

        :param pod_name: Pod name.
        :param command: Remote command to execute.
        :param container: Container name from pod.

        :param kwargs: See all parameters in core_v1.connect_post_namespaced_pod_exec function.
        """

        if container:
            kwargs['container'] = container

        _preload_content = kwargs.get('_preload_content', False)

        if _preload_content:
            stdout, stderr = ResponseDataCollector(), ResponseDataCollector()
        else:
            stdout, stderr = Logger(logging.info), Logger(logging.error)

        return self._exec(pod_name, command, stdout, stderr, **kwargs)

    def get_logs(self, pod_name: str, container: str = None,
                 tail_lines: int = None, follow: bool = True, namespace: str = None):
        """
        Read logs from container.

        :param pod_name: Pod name.
        :param container: Print the logs of this container.
        :param tail_lines: Lines of recent log file to display.
        :param follow: Specify if the logs should be streamed.
        :param namespace: Specific namespace.
        """

        ns = self._ns
        if namespace:
            ns = namespace

        for line in self.core_v1.read_namespaced_pod_log(
                pod_name,
                ns,
                container=container,
                follow=follow,
                _preload_content=False,
                tail_lines=tail_lines).stream():
            logging.info(line.decode().rstrip('\n'))

    def copy_file_from_pod(self, name: str, remote_path: str, local_path: Path,
                           **kwargs):
        """
        Copy file from pod.

        :param name: Pod name.
        :param remote_path: Path in pod. Source path.
        :param local_path: Local path. Destination path.
        :param kwargs: See all parameters in core_v1.connect_post_namespaced_pod_exec function.
        """

        cmd = ['/bin/sh', '-c', f'cat {remote_path}']

        local_path.parent.mkdir(parents=True, exist_ok=True)
        logging.info(local_path)
        f = FileWriter(local_path)
        try:
            self._exec(name, cmd, f, Logger(logging.error), **kwargs)
        except Exception:
            raise
        finally:
            f.close()

    def read_configmap(self, name: str, namespace: str = None) -> dict[str, str] | None:
        """
        Get ConfigMap's data
        :param name: ConfigMap name.
        :param namespace: Specific namespace.
        :return: dict[str, str] or None if secret not found.
        """

        cm = self.configmap_get(name, namespace=namespace)
        if not cm:
            return

        return cm.data

    def read_secret(self, name: str, namespace: str = None) -> dict[str, str] | None:
        """
        Get Secret's data
        :param name: Secret name.
        :param namespace: Specific namespace.
        :return: dict[str, str] or None if secret not found.
        """

        sec = self.secret_get(name, namespace=namespace)
        if not sec:
            return

        return dict(
            map(
                lambda item: (item[0], base64.b64decode(item[1]).decode()),
                sec.data.items()
            )
        )

    def _wrapper(self, func, obj_name: str, check_err: bool, *,
                 namespaced: bool = True,
                 custom_object_def: CustomObjectDef = None,
                 **kwargs):
        """
        The wrapper function used for the Kubernetes API request handle.

        :param func: Function for wrapping.
        :param obj_name: Name of Deployment, StatefulSet, Service
                         or any other Kubernetes resource.
        :param check_err: Enable or disable throwing an exception
                          if an error occurs.
        :param namespaced: Switch wrapper for non-namespaced API request.
                           Example: ClusterRole, Namespace, Nodes e.g.
        :param custom_object_def: Custom resources definitions.
        :param kwargs: See all parameters in wrapped function.

        :return: Specific object for wrapped function
                 or None if resource not found.
        """

        ns = kwargs.pop('namespace', self._ns)
        try:
            if custom_object_def is not None:
                resp = func(
                    custom_object_def.group,
                    custom_object_def.version,
                    ns,
                    custom_object_def.plural,
                    obj_name,
                    **kwargs
                )
            else:
                if namespaced:
                    resp = func(obj_name, ns, **kwargs)
                else:
                    resp = func(obj_name, **kwargs)

            logging.debug('Kubernetes API Response: %s', resp)

            return resp
        except ApiException as e:
            if e.status == 404:
                logging.debug(e)
                return

            if check_err:
                raise

            logging.error(e)

    def _wrapper_create(self, func, obj, check_err: bool, *,
                        namespaced: bool = True, **kwargs):
        """
        The wrapper function used for the Kubernetes API request handle.
        Used only for create_* functions.

        :param func: Function for wrapping.
        :param obj: Definition of Kubernetes resource.
        :param check_err: Enable or disable throwing an exception if an error occurs.
        :param kwargs: See all parameters in wrapped function.

        :return: Specific object for wrapped function or None if resource not found.
        """

        ns = kwargs.pop('namespace', self._ns)
        try:
            resp = func(ns, obj, **kwargs) if namespaced else func(obj, **kwargs)
            logging.debug('Kubernetes API Response: %s', resp)

            return resp
        except ApiException as e:
            if e.status == 409:
                logging.debug(e)
                return

            if check_err:
                raise

            logging.error(e)

    def configmap_create(self, sec: client.V1ConfigMap, *,
                         check_err: bool = True, **kwargs) -> client.V1ConfigMap:
        """
        Create CongMap in current namespace.
        """

        return self._wrapper_create(self.core_v1.create_namespaced_config_map,
                                    sec, check_err=check_err, **kwargs)

    def configmap_delete(self, name: str, **kwargs) -> client.V1ConfigMap | None:
        """
        Delete Configmap by name in current namespace.
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.core_v1.delete_namespaced_config_map,
                             name, False, **kwargs)

    def configmap_get(self, name: str, *, check_err: bool = True,
                      **kwargs) -> client.V1ConfigMap | None:
        """
        Get Configmap by name in current namespace.
        """

        return self._wrapper(self.core_v1.read_namespaced_config_map,
                             name, check_err, **kwargs)

    def configmap_list(self, **kwargs) -> client.V1ConfigMapList:
        """
        List all Configmaps in current namespace.
        """

        ns = kwargs.pop('namespace', self._ns)
        return self.core_v1.list_namespaced_config_map(ns, **kwargs)

    def cron_job_create(self, cronjob: client.V1CronJob, *,
                        check_err: bool = True, **kwargs) -> client.V1CronJob:
        """
        Create CronJob in current namespace.
        """

        return self._wrapper_create(self.batch_v1.create_namespaced_cron_job,
                                    cronjob, check_err=check_err, **kwargs)

    def cron_job_delete(self, name: str, **kwargs) -> client.V1CronJob | None:
        """
        Delete CronJob by name in current namespace.
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.batch_v1.delete_namespaced_cron_job,
                             name, False, **kwargs)

    def cron_job_get(self, name: str, *, check_err: bool = True,
                     **kwargs) -> client.V1CronJob | None:
        """
        Get CronJob by name in current namespace.
        """

        return self._wrapper(self.batch_v1.read_namespaced_cron_job,
                             name, check_err, **kwargs)

    def cron_job_list(self, **kwargs) -> client.V1CronJobList:
        """
        List all CronJobs in current namespace.
        """

        ns = kwargs.pop('namespace', self._ns)
        return self.batch_v1.list_namespaced_cron_job(ns, **kwargs)

    def custom_object_create(self, body, co: CustomObjectDef, *,
                             namespaced: bool = True,
                             check_err: bool = True,
                             **kwargs):
        """
        Create Custom Object API by name in current namespace.
        """

        func = self.custom_object_api.create_cluster_custom_object
        if namespaced:
            func = self.custom_object_api.create_namespaced_custom_object

        return self._wrapper_create(func, body, check_err,
                                    namespaced=namespaced,
                                    custom_object_def=co,
                                    **kwargs)

    def custom_object_get(self, name: str, co: CustomObjectDef, *,
                          namespaced: bool = True,
                          check_err: bool = True,
                          **kwargs):
        """
        Get Custom Object API by name in current namespace.
        """

        func = self.custom_object_api.get_cluster_custom_object
        if namespaced:
            func = self.custom_object_api.get_namespaced_custom_object

        return self._wrapper(func, name, check_err,
                             namespaced=namespaced,
                             custom_object_def=co,
                             **kwargs)

    def custom_object_delete(self, name: str, co: CustomObjectDef, *,
                             namespaced: bool = True, **kwargs):
        """
        Delete Custom Object API by name in current namespace.
        """

        func = self.custom_object_api.delete_cluster_custom_object
        if namespaced:
            func = self.custom_object_api.delete_namespaced_custom_object

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(func, name, False,
                             namespaced=namespaced,
                             custom_object_def=co,
                             **kwargs)

    def custom_object_list(self, co: CustomObjectDef, *,
                           namespaced: bool = True,
                           **kwargs):
        """
        List all Custom Object API in current namespace.
        """

        args = [co.group, co.version, co.plural]
        if namespaced:
            args.insert(2, kwargs.pop('namespace', self._ns))

            return self.custom_object_api.list_namespaced_custom_object(
                *args, **kwargs)
        else:
            return self.custom_object_api.list_cluster_custom_object(
                *args, **kwargs)

    def job_create(self, job: client.V1Job, *, check_err: bool = True,
                   **kwargs) -> client.V1Job:
        """
        Create Job in current namespace.
        """

        return self._wrapper_create(self.batch_v1.create_namespaced_job,
                                    job, check_err=check_err, **kwargs)

    def job_delete(self, name: str, **kwargs) -> client.V1Job | None:
        """
        Delete Job by name in current namespace.
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.batch_v1.delete_namespaced_job,
                             name, False, **kwargs)

    def job_get(self, name: str, *, check_err: bool = True,
                **kwargs) -> client.V1Job | None:
        """
        Get Job by name in current namespace.
        """
        return self._wrapper(self.batch_v1.read_namespaced_job,
                             name, check_err, **kwargs)

    def job_list(self, **kwargs) -> client.V1JobList:
        """
        List all Jobs in current namespace.
        """

        ns = kwargs.pop('namespace', self._ns)
        return self.batch_v1.list_namespaced_job(ns, **kwargs)

    def deployment_create(self, deploy: client.V1Deployment, *, check_err: bool = True,
                          **kwargs) -> client.V1Deployment | None:
        """
        Create Deployment in current namespace.
        """

        return self._wrapper_create(self.apps_v1.create_namespaced_deployment,
                                    deploy, check_err=check_err, **kwargs)

    def deployment_delete(self, name: str, **kwargs) -> client.V1Deployment | None:
        """
        Delete Deployment in current namespace
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.apps_v1.delete_namespaced_deployment,
                             name, False, **kwargs)

    def deployment_get(self, name: str, *, check_err: bool = True,
                       **kwargs) -> client.V1Deployment | None:
        """
        Get Deployment by name in current namespace.
        """

        return self._wrapper(self.apps_v1.read_namespaced_deployment,
                             name, check_err, **kwargs)

    def deployment_list(self, **kwargs) -> client.V1DeploymentList:
        """
        List all Deployments in current namespace.
        """

        return self.apps_v1.list_namespaced_deployment(self._ns, **kwargs)

    def ingress_create(self, name: str, *, check_err: bool = True,
                       **kwargs) -> client.V1Ingress:
        """
        Get Ingres by name in current namespace.
        """

        return self._wrapper_create(self.networking_v1.create_namespaced_ingress,
                                    name, check_err, **kwargs)

    def ingress_delete(self, name: str, *, check_err: bool = True,
                       **kwargs) -> client.V1Ingress | None:
        """
        Get Ingresses by name in current namespace.
        """

        return self._wrapper(self.networking_v1.delete_namespaced_ingress,
                             name, check_err, **kwargs)

    def ingress_get(self, name: str, *, check_err: bool = True,
                    **kwargs) -> client.V1Ingress | None:
        """
        Get Ingresses by name in current namespace.
        """

        return self._wrapper(self.networking_v1.read_namespaced_ingress,
                             name, check_err, **kwargs)

    def ingress_list(self, **kwargs) -> client.V1Ingress:
        """
        List all Ingresses in current namespace.
        """

        ns = kwargs.pop('namespace', self._ns)
        return self.networking_v1.list_namespaced_ingress(ns, **kwargs)

    def namespace_create(self, ns: client.V1Namespace, *,
                         check_err: bool = False, **kwargs) -> client.V1Namespace:
        """
        Create Namespace.
        """

        return self._wrapper_create(self.core_v1.create_namespace,
                                    ns, check_err, namespaced=False, **kwargs)

    def namespace_delete(self, name: str, **kwargs) -> client.V1Namespace | None:
        """
        Delete Namespace by name.
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.core_v1.delete_namespace,
                             name, False, namespaced=False, **kwargs)

    def namespace_get(self, name: str, **kwargs) -> client.V1Namespace | None:
        """
        Get Namespace by name.
        """

        return self._wrapper(self.core_v1.read_namespace,
                             name, False, namespaced=False, **kwargs)

    def namespace_list(self, **kwargs) -> client.V1NamespaceList:
        """
        List all Namespaces.
        """

        return self.core_v1.list_namespace(**kwargs)

    def pod_create(self, pod: client.V1Pod, *, check_err: bool = True,
                   **kwargs) -> client.V1Pod:
        """
        Create Pod in current namespace.
        """

        return self._wrapper_create(self.core_v1.create_namespaced_pod,
                                    pod, check_err=check_err, **kwargs)

    def pod_delete(self, name: str, **kwargs) -> client.V1Pod | None:
        """
        Delete Pod by name in current namespace.
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.core_v1.delete_namespaced_pod,
                             name, False, **kwargs)

    def pod_get(self, name: str, *, check_err: bool = True,
                **kwargs) -> client.V1Pod | None:
        """
        Get Pod by name in current namespace.
        """

        return self._wrapper(self.core_v1.read_namespaced_pod,
                             name, check_err, **kwargs)

    def pod_list(self, **kwargs) -> client.V1PodList:
        """
        List all Pods in current namespace.
        """

        ns = kwargs.pop('namespace', self._ns)
        return self.core_v1.list_namespaced_pod(ns, **kwargs)

    def pvc_create(self, pvc: client.V1PersistentVolumeClaim, *,
                   check_err: bool = True, **kwargs) -> client.V1PersistentVolumeClaim:
        """
        Create PersistentVolumeClaim in current namespace.
        """

        return self._wrapper_create(
            self.core_v1.create_namespaced_persistent_volume_claim,
            pvc, check_err=check_err, **kwargs)

    def pvc_delete(self, name: str, **kwargs) -> client.V1PersistentVolumeClaim | None:
        """
        Delete PersistentVolumeClaim by name in current namespace.
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.core_v1.delete_namespaced_persistent_volume_claim,
                             name, False, **kwargs)

    def pvc_get(self, name: str, *, check_err: bool = True,
                **kwargs) -> client.V1PersistentVolumeClaim | None:
        """
        Get PersistentVolumeClaim by name in current namespace.
        """

        return self._wrapper(self.core_v1.read_namespaced_persistent_volume_claim,
                             name, check_err, **kwargs)

    def pvc_list(self, **kwargs) -> client.V1PersistentVolumeClaimList:
        """
        List all PersistentVolumeClaims in current namespace.
        """

        ns = kwargs.pop('namespace', self._ns)
        return self.core_v1.list_namespaced_persistent_volume_claim(ns, **kwargs)

    def secret_get(self, name: str, *, check_err: bool = True,
                   **kwargs) -> client.V1Secret | None:
        """
        Get Secret by name in current namespace.
        """

        return self._wrapper(self.core_v1.read_namespaced_secret,
                             name, check_err, **kwargs)

    def secret_create(self, sec: client.V1Secret, *, check_err: bool = True,
                      **kwargs) -> client.V1Secret:
        """
        Create Secret in current namespace.
        """

        return self._wrapper_create(self.core_v1.create_namespaced_secret,
                                    sec, check_err=check_err, **kwargs)

    def secret_delete(self, name: str, **kwargs) -> client.V1Secret | None:
        """
        Delete Secret by name in current namespace.
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.core_v1.delete_namespaced_secret,
                             name, False, **kwargs)

    def secret_list(self, **kwargs) -> client.V1SecretList:
        """
        List all Secrets in current namespace.
        """

        ns = kwargs.pop('namespace', self._ns)
        return self.core_v1.list_namespaced_secret(ns, **kwargs)

    def service_get(self, name: str, *, check_err: bool = True,
                    **kwargs) -> client.V1Secret | None:
        """
        Get Service by name in current namespace.
        """

        return self._wrapper(self.core_v1.read_namespaced_service,
                             name, check_err, **kwargs)

    def service_create(self, svc: client.V1Service, *, check_err: bool = True,
                       **kwargs) -> client.V1Service:
        """
        Create Service in current namespace.
        """

        return self._wrapper_create(self.core_v1.create_namespaced_service,
                                    svc, check_err=check_err, **kwargs)

    def service_delete(self, name: str, **kwargs) -> client.V1Service | None:
        """
        Delete Service by name in current namespace.
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.core_v1.delete_namespaced_service,
                             name, False, **kwargs)

    def service_list(self, **kwargs) -> client.V1Service:
        """
        List all Service in current namespace.
        """

        ns = kwargs.pop('namespace', self._ns)
        return self.core_v1.list_namespaced_service(ns, **kwargs)

    def stateful_set_create(self, sts: client.V1StatefulSet, *, check_err: bool = True,
                            **kwargs) -> client.V1StatefulSet | None:
        """
        Create StatefulSet in current namespace.
        """

        return self._wrapper_create(self.apps_v1.create_namespaced_stateful_set,
                                    sts, check_err=check_err, **kwargs)

    def stateful_set_delete(self, name: str, **kwargs) -> client.V1StatefulSet | None:
        """
        Delete StatefulSet by name in current namespace.
        """

        kwargs.setdefault('propagation_policy', "Foreground")
        return self._wrapper(self.apps_v1.delete_namespaced_stateful_set,
                             name, False, **kwargs)

    def stateful_set_get(self, name: str, *, check_err: bool = True,
                         **kwargs) -> client.V1StatefulSet | None:
        """
        Get StatefulSet by name in current namespace.
        """

        return self._wrapper(self.apps_v1.read_namespaced_stateful_set,
                             name, check_err, **kwargs)

    def stateful_set_list(self, **kwargs) -> client.V1StatefulSetList:
        """
        List all StatefulSets in current namespace.
        """

        ns = kwargs.pop('namespace', self._ns)
        return self.apps_v1.list_namespaced_stateful_set(ns, **kwargs)

    def scale_deployment(self, name: str, replicas: int, wait: bool = False,
                         **kwargs) -> client.V1Deployment:
        """
        Scale Deployment by name in current namespace.

        :param name: Deployment name.
        :param replicas: Set number of replicas.
        :param wait: Wait until a Deployment stops.
        :param kwargs: See all parameters in apps_v1.patch_namespaced_deployment
        """
        return self._scale(self.apps_v1.patch_namespaced_deployment,
                           name, replicas, wait, **kwargs)

    def scale_stateful_set(self, name: str, replicas: int, wait: bool = False,
                           **kwargs) -> client.V1StatefulSet:
        """
        Scale StatefulSet by name in current namespace.

        :param name: StatefulSet name.
        :param replicas: Set number of replicas.
        :param wait: Wait until a StatefulSet stops.
        :param kwargs: See all parameters in apps_v1.patch_namespaced_stateful_set
        """
        return self._scale(self.apps_v1.patch_namespaced_stateful_set,
                           name, replicas, wait, **kwargs)

    def _scale(self, func, name: str, replicas: int, wait: bool, **kwargs):
        """
        Scale down wrapper.
        """
        kwargs['body'] = {"spec": {"replicas": replicas}}
        resp = self._wrapper(func, name, check_err=True, **kwargs)
        msg = f'{resp.kind.lower()}.apps/{name} scaled to {replicas} replicas'
        logging.info(msg)

        if wait:
            labels = dict_to_labels(resp.spec.template.metadata.labels)
            self.wait_pods(labels, msg)

        return resp

    def scale_down_all(self):
        """
        Set replicas to 0 for all Deployments and StatefulSets
        """

        deployments = self.deployment_list()
        for item in deployments.items:
            if item.spec.replicas:
                self.scale_deployment(item.metadata.name, 0)

        stateful_sets = self.stateful_set_list()
        for item in stateful_sets.items:
            if item.spec.replicas:
                self.scale_stateful_set(item.metadata.name, 0)

    def wait_pods(self, label_selector: str, msg: str = '',
                  delay: int = 3, timeout: int = 120, start_delay: int = 3):
        """
        Waiting for Kubernetes object scaling by labels.
        """

        info_msg = f"wait {msg if msg else 'scaling'} ..."
        logging.info(info_msg)

        time.sleep(start_delay)

        while 1:
            obj = self.pod_list(field_selector='status.phase!=Succeeded',
                                label_selector=label_selector)
            # down to 0
            if not obj.items:
                return

            # replicas equal availableReplicas
            if all(map(lambda pod: is_pod_ready(pod), obj.items)):
                return

            if timeout <= 0:
                raise TimeoutError("Wait for scaling: timeout reached!")

            logging.info(info_msg)

            timeout -= delay
            time.sleep(delay)
