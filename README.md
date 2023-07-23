# kube-py
Use OOP to manage Kubernetes objects 

### Usages
```python
import kube

# Make container
container = kube.Container('nginx')
container.set_image('nginx:alpine')

# Add environment variables to from configmap
## Make configmap
cm = kube.ConfigMap('nginx')
cm.set_data(NGINX_ENTRYPOINT_QUIET_LOGS='true')

## Make env from configmap
env = kube.env_from_configmap(cm.name)
container.add_env_from(env)

# Add port to container
container.add_port('http', 80)

# Make deployment
deploy = kube.Deployment('nginx-test', container)
deploy.set_pod_labels(key='value', app='nginx', name='nginx-test')
deploy.add_volume_to_container(container.name, kube.empty_dir(), '/mnt')

# Add volume from secret with cert and private key
with open('server.crt') as f:
    crt = f.read()

with open('server.key') as f:
    key = f.read()

## Make secret with type kubernetes.io/tls
sec = kube.SecretTLS('nginx')
sec.set(crt, key)

## Add secret as volume
sec_vol = kube.volume_from_secret(sec.name)
deploy.add_volume_to_container(sec.name, sec_vol, '/etc/nginx/certs')

# Disable service link in pod's containers
deploy.enable_service_links(False)

# Add service and link by selector
selector = {'app': 'nginx', 'name': 'nginx-test'}
deploy.set_selector_match_labels(**selector)

## Make service
svc = kube.Service('www-nginx')
svc.add_port('http', 80, 'http')
svc.set_type(kube.ServiceType.ClusterIP)
svc.set_selector(**selector)

# Create objects in Kubernetes
k = kube.KubeApi()
k.secret_create(sec.manifest)
k.configmap_create(cm.manifest)
k.deployment_create(deploy.manifest)
k.service_create(svc.manifest)
```
