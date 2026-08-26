# Service Mesh and mTLS

This document outlines how to deploy GateFlow in an Istio-enabled Kubernetes cluster with mutual TLS (mTLS) between all service-to-service calls.

## Goals

- Encrypt all in-cluster traffic using mTLS.
- Restrict east-west traffic to explicitly allowed services.
- Provide service identity (SPIFFE) for downstream authorisation.

## Prerequisites

- Kubernetes cluster with Istio installed and sidecar injection enabled.
- `istioctl` and `kubectl` configured.

## Istio configuration

### 1. Enable sidecar injection

```bash
kubectl label namespace gateflow istio-injection=enabled --overwrite
```

### 2. Enforce strict mTLS

Apply a `PeerAuthentication` resource to require mTLS for all workloads in the `gateflow` namespace.

```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: gateflow
spec:
  mtls:
    mode: STRICT
```

### 3. Authorisation policy

```yaml
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: gateflow-allow-ingress
  namespace: gateflow
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: gateflow
  action: ALLOW
  rules:
    - from:
        - source:
            principals: ["cluster.local/ns/ingress-nginx/sa/ingress-nginx"]
      to:
        - operation:
            methods: ["GET", "POST", "PUT", "PATCH", "DELETE"]
```

## Network policy

A baseline `NetworkPolicy` is provided in `k8s/base/network-policy.yaml`. When combined with Istio, this creates defence in depth: the network layer restricts IP traffic and the mesh layer provides identity-based authorisation.

## Validation

```bash
istioctl authn tls-check gateflow-<pod>.gateflow
kubectl get peerauthentication -n gateflow
```

## Next steps

- Integrate `X-Forwarded-Client-Cert` headers into `auth.py` for SPIFFE identity-based routing.
- Add fine-grained `AuthorizationPolicy` per downstream route prefix.
