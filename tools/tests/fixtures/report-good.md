# Crew report

## Root cause

The `my-app` pods crash because the `my-config` ConfigMap lacks the `LOG_LEVEL` key.

## Knock-on effects

The `my-app` Service has no ready endpoints.

## Separate issues

None found.

## Fixes

Add the missing key:

```bash
# Undo: kubectl -n my-namespace patch configmap my-config --type=json -p '[{"op":"remove","path":"/data/LOG_LEVEL"}]'
kubectl -n my-namespace patch configmap my-config --type=merge -p '{"data":{"LOG_LEVEL":"info"}}'
```

## What was checked

Pods, events, ConfigMaps in `my-namespace`.

## Helper details

Three helpers ran; all agreed.
