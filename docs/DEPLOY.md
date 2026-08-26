# GateFlow Deployment

## Helm

A production-ready Helm chart is in `helm/gateflow`.

### Install

```bash
helm upgrade --install gateflow ./helm/gateflow \
  --namespace gateflow --create-namespace \
  --set image.repository=ghcr.io/example/gateflow \
  --set image.tag=1.0.0 \
  --set secrets.key_secret=<base64-secret> \
  --set secrets.admin_key=<base64-admin>
```

### Production overrides

Create a `values-production.yaml` and override at least:

- `replicaCount`
- `ingress.hosts`
- `config.redis_sentinels`
- `config.notification_webhook_url`
- `secrets.*`

## GitOps (ArgoCD)

Apply the ArgoCD Application:

```bash
kubectl apply -f k8s/gitops/argocd-application.yaml
```

ArgoCD will keep the cluster state in sync with the chart in Git.

## Canary deployments (Flagger)

Install Flagger and the Prometheus load tester, then apply:

```bash
kubectl apply -f k8s/canary/flagger-canary.yaml
```

Flagger will progressively shift traffic to the new version and promote it only if the success-rate and p95 latency gates pass.

## Redis HA

For production use either a managed HA Redis service or the Sentinel manifest in `k8s/ha/redis-sentinel.yaml`.
