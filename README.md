# kube-py
Use OOP to manage Kubernetes objects 

### Usages
```python
import kube_ops

# Create configmap
cm = kube_ops.ConfigMap("nginx")
cm.set(NGINX_ENTRYPOINT_QUIET_LOGS=True)
cm.create()

# Create secret with type kubernetes.io/tls
sec = kube_ops.SecretTLS("nginx")
with open("server.crt") as f:
    crt = f.read()
with open("server.key") as f:
    key = f.read()
sec.set(crt, key)
sec.create()

# Make container
container = kube_ops.Container("nginx")
container.set_image("nginx:alpine")
## Add port to container
container.add_port("http", 80)
## Make envFrom link to configmap and add to the container
env = kube_ops.env_from_configmap(cm.name)
container.add_env_from(env)

# Make deployment
deploy = kube_ops.Deployment("nginx-test", container)
deploy.add_volume_to_container(container.name, kube_ops.empty_dir(), "/mnt")

## Set labels
lbl = dict(key="value", app="nginx", name="nginx-test")
deploy.set_labels(**lbl)
deploy.set_pod_labels(**lbl)
deploy.set_selector_match_labels(**lbl)

## Add secret as volume to deployment
sec_vol = kube_ops.volume_from_secret(sec.name)
deploy.add_volume_to_container(sec.name, sec_vol, "/etc/nginx/certs")

## Create deployment
deploy.create()

## Create service from deployment definition
deploy.service().create()
```
