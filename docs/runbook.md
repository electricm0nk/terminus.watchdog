# Terminus Watchdog Agent — Runbook

**Version:** 0.1 (stub — expanded in Epic 7)  
**Service:** `terminus-watchdog`  
**Namespace:** `terminus-watchdog`  
**Repository:** `github.com/electricm0nk/terminus.watchdog`  
**Discord channels:** `#platform-alerts`, `#platform-info`

---

## Overview

The Terminus Watchdog Agent is an autonomous platform monitoring service that polls ArgoCD, Temporal, and Kubernetes for anomalies and delivers structured Discord alerts. This runbook covers operational procedures for the watchdog itself.

---

## Quick Reference

| Scenario | Action |
|----------|--------|
| Watchdog not posting alerts | Check pod logs; verify Discord token; check `/healthz` |
| Alerts flooding (no deduplication) | Restart pod — resets in-memory suppress map |
| ArgoCD poll errors | Verify `ARGOCD_TOKEN` secret; check ArgoCD availability |
| Temporal poll errors | Verify mTLS certs in Vault; check Temporal frontend |
| k8s API errors | Verify ServiceAccount RBAC in `terminus-watchdog` namespace |
| Heartbeat missing | `kubectl logs -n terminus-watchdog deploy/terminus-watchdog` |

---

## Health Check

```bash
# Liveness probe (returns 200 when event loop is responsive)
kubectl exec -n terminus-watchdog deploy/terminus-watchdog -- wget -qO- http://localhost:9090/healthz

# Prometheus metrics (includes watchdog_last_heartbeat_timestamp_seconds)
kubectl exec -n terminus-watchdog deploy/terminus-watchdog -- wget -qO- http://localhost:9090/metrics | grep watchdog_
```

---

## Pod Logs

```bash
# Recent structured logs
kubectl logs -n terminus-watchdog deploy/terminus-watchdog --tail=100

# Follow live
kubectl logs -n terminus-watchdog deploy/terminus-watchdog -f

# Previous pod (if restarted)
kubectl logs -n terminus-watchdog deploy/terminus-watchdog --previous
```

---

## Secret Verification

```bash
# Verify ESO sync worked
kubectl get secret watchdog-secrets -n terminus-watchdog -o jsonpath='{.data}' | python3 -c "import sys,json,base64; d=json.load(sys.stdin); [print(k, len(base64.b64decode(v)), 'bytes') for k,v in d.items()]"
```

---

## ArgoCD Token Rotation

1. Generate a new token: `argocd account generate-token --account watchdog`
2. Store in Vault: `vault kv put secret/terminus/watchdog/argocd-token value=<token>`
3. Wait for ESO to sync (default: 60s) or force: `kubectl annotate externalsecret watchdog-argocd-token -n terminus-watchdog force-sync=$(date +%s)`
4. Restart watchdog: `kubectl rollout restart deploy/terminus-watchdog -n terminus-watchdog`

---

## Discord Bot Token Rotation

1. Revoke and regenerate token in Discord Developer Portal
2. Store in Vault: `vault kv put secret/terminus/watchdog/discord-bot-token value=<token>`
3. Wait for ESO sync, then restart watchdog pod

---

## Restarting the Watchdog

```bash
kubectl rollout restart deploy/terminus-watchdog -n terminus-watchdog
kubectl rollout status deploy/terminus-watchdog -n terminus-watchdog
```

**Note:** Restarting clears the in-memory suppress map and active_alerts dict. The 30-minute cold-start grace window activates on restart — no alerts will post during this window to prevent alert storms from pre-existing conditions.

---

## ArgoCD Application

| App name | `terminus-watchdog-dev` (dev), `terminus-watchdog` (prod) |
|----------|------------------------------------------------------------|
| Repo | `github.com/electricm0nk/terminus.watchdog` |
| Chart path | `helm/terminus-watchdog/` |

Force sync:
```bash
argocd app sync terminus-watchdog --force
```

---

## Detection Patterns Reference

| Pattern | Severity | Source | Threshold | Cooldown |
|---------|----------|--------|-----------|----------|
| `argocd-live-drift` | High | ArgoCD | Any OutOfSync (non-image diff) | 30 min |
| `argocd-image-promotion` | Informational | ArgoCD | OutOfSync image-only diff | 30 min |
| `argocd-stuck-sync` | Medium | ArgoCD | Progressing > 5 min | 30 min |
| `argocd-order-day-unsync` | High | ArgoCD | Any OutOfSync in etailpet ns during window | Bypass |
| `temporal-zombie-activity` | Medium | Temporal | Running workflow > 2 hours | 30 min |
| `temporal-zombie-critical` | High | Temporal | Running workflow > 24 hours | 30 min |
| `temporal-stale-workflow` | Medium | Temporal | No history events > 30 min | 30 min |
| `temporal-postgres-connectivity` | High | Loki | Temporal postgres error in logs | 30 min |
| `k8s-crashloopbackoff` | Medium→High | k8s | Pod not recovered in 2 min; >5 restarts → High | Bypass on escalation |
| `k8s-deployment-unavailable` | Medium | k8s | 0 replicas available > 5 min | 30 min |
| `k8s-node-notready` | High | k8s | Node NotReady > 2 min | 30 min |

---

## Escalation Path

1. **#platform-alerts** — High severity; @mention ops users (except during quiet hours 22:00–07:00 CT)
2. **#platform-info** — Medium and Informational alerts; no @mention
3. **Heartbeat** — every 6 hours in #platform-alerts; if missed > 6 hours, Alertmanager fires `WatchdogHeartbeatMissed`

---

## Common Issues

### Watchdog posts duplicate alerts

Restart the pod. The in-memory suppress map is cleared on restart, triggering the cold-start grace window which prevents immediate re-alerting.

### ArgoCD token expired (HTTP 401)

Rotate the ArgoCD token (see above). The watchdog will log `ArgoCDAuthError` at ERROR level.

### Temporal mTLS cert expired

Re-provision certs in Vault. Look for `TEMPORAL_CERT_PEM` / `TEMPORAL_KEY_PEM` rotation procedure in the Temporal admin runbook.

### Loki query returning 0 results unexpectedly

Verify Loki is reachable from the watchdog pod. Check Loki endpoint and auth headers in `LOKI_URL` configmap value.

---

## ConfigMap Threshold Tuning

```bash
kubectl edit configmap watchdog-config -n terminus-watchdog
```

Key threshold fields (see `helm/terminus-watchdog/templates/configmap.yaml` for full list):

| Key | Default | Description |
|-----|---------|-------------|
| `ARGOCD_STUCK_SYNC_THRESHOLD_MINUTES` | `5` | Minutes before stuck-sync fires |
| `COOLDOWN_MINUTES` | `30` | Cooldown between repeated alerts for same resource |
| `COLD_START_GRACE_MINUTES` | `30` | Grace window on startup |
| `ZOMBIE_ACTIVITY_HOURS` | `2` | Temporal zombie-activity threshold |
| `ZOMBIE_CRITICAL_HOURS` | `24` | Temporal zombie-critical threshold |
| `STALE_WORKFLOW_MINUTES` | `30` | Temporal stale-workflow threshold |
| `CRASHLOOP_RECOVERY_SECONDS` | `120` | k8s crashloop recovery window |
| `DEPLOYMENT_UNAVAILABLE_MINUTES` | `5` | k8s deployment-unavailable threshold |
| `NODE_NOTREADY_MINUTES` | `2` | k8s node-notready threshold |

After editing, restart the watchdog:
```bash
kubectl rollout restart deploy/terminus-watchdog -n terminus-watchdog
```

---

*This runbook stub covers core operational procedures. Full observability details (Prometheus metrics, Grafana dashboard, Alertmanager rule) are expanded in Epic 7.*
