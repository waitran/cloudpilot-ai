import asyncio
import time
from datetime import UTC
from decimal import Decimal

from kubernetes import client, config

from cloudpilot.modules.collection.connectors.base import Batch, CollectionError
from cloudpilot.modules.collection.normalizers.values import quantity
from cloudpilot.modules.collection.schemas import ResourceInput, SyncRequest


def container_resources(spec, kind):
    """Effective pod scheduling quantity, including restartable init sidecars and overhead."""
    result = {}
    for key in ("cpu", "memory"):

        def amount(container):
            resources = getattr(container, "resources", None)
            values = getattr(resources, kind, None) or {}
            return quantity(values.get(key), memory=key == "memory")

        regular = [amount(c) for c in (spec.containers or [])]
        unbounded_init = any(amount(c) is None for c in spec.init_containers or [])
        sidecars = Decimal(0)
        peak = Decimal(0)
        known = any(v is not None for v in regular)
        for c in spec.init_containers or []:
            v = amount(c)
            known |= v is not None
            if getattr(c, "restart_policy", None) == "Always":
                sidecars += v or 0
                peak = max(peak, sidecars)
            else:
                peak = max(peak, sidecars + (v or 0))
        total = max(sum((v or 0 for v in regular), Decimal(0)) + sidecars, peak)
        pod_resources = getattr(spec, "resources", None)
        pod_values = getattr(pod_resources, kind, None) or {}
        if key in pod_values:
            total, known = quantity(pod_values[key], memory=key == "memory"), True
        overhead = quantity((spec.overhead or {}).get(key), memory=key == "memory")
        if overhead is not None:
            total += overhead
            known = True
        # A missing limit on any app container means no finite aggregate pod limit.
        if (
            kind == "limits"
            and (any(v is None for v in regular) or unbounded_init)
            and key not in pod_values
        ):
            known = False
        result[key] = total if known else None
    return result


class KubernetesConnector:
    def __init__(self, mode, filename=None, context=None, api_client=None):
        self.mode, self.filename, self.context = mode, filename, context
        self.api_client = api_client

    async def collect(self, window: SyncRequest) -> Batch:
        return await asyncio.to_thread(self._collect)

    def _collect(self):
        if self.mode == "disabled" and not self.api_client:
            raise CollectionError("kubernetes_not_configured", 503)
        self.deadline = time.monotonic() + 180
        api = self.api_client
        try:
            if not api:
                cfg = client.Configuration()
                if self.mode == "incluster":
                    config.load_incluster_config(client_configuration=cfg)
                else:
                    config.load_kube_config(
                        config_file=self.filename,
                        context=self.context,
                        client_configuration=cfg,
                        persist_config=False,
                    )
                if not cfg.verify_ssl:
                    raise CollectionError("kubernetes_tls_verification_required")
                cfg.debug = False
                cfg.retries = 0
                api = client.ApiClient(cfg)
            core, apps = client.CoreV1Api(api), client.AppsV1Api(api)
            batch = Batch()
            namespaces = self._pages(core.list_namespace)
            batch.discovery_metadata = {"namespaces": [n.metadata.name for n in namespaces]}
            for kind, method in [
                ("node", core.list_node),
                ("pod", core.list_pod_for_all_namespaces),
                ("deployment", apps.list_deployment_for_all_namespaces),
                ("statefulset", apps.list_stateful_set_for_all_namespaces),
            ]:
                for obj in self._pages(method):
                    batch.records_read += 1
                    meta = obj.metadata
                    if not meta.uid:
                        raise CollectionError("kubernetes_uid_missing")
                    labels = {
                        k: v
                        for k, v in (meta.labels or {}).items()
                        if not any(
                            w in k.lower() for w in ("secret", "token", "password", "credential")
                        )
                    }
                    values = dict(
                        external_id=meta.uid,
                        resource_type=f"kubernetes_{kind}",
                        provider="kubernetes",
                        name=meta.name,
                        namespace=meta.namespace,
                        labels=labels,
                        status="observed",
                        configuration={},
                    )
                    if kind == "node":
                        ready = next(
                            (c.status for c in obj.status.conditions or [] if c.type == "Ready"),
                            "Unknown",
                        )
                        values["status"] = (
                            "Ready"
                            if ready == "True"
                            else "NotReady"
                            if ready == "False"
                            else "Unknown"
                        )
                        for field, source in [
                            ("capacity", obj.status.capacity),
                            ("allocatable", obj.status.allocatable),
                        ]:
                            source = source or {}
                            values[f"cpu_{field}"] = quantity(source.get("cpu"))
                            values[f"memory_{field}_bytes"] = quantity(
                                source.get("memory"), memory=True
                            )
                        values["region"] = labels.get("topology.kubernetes.io/region")
                        values["availability_zone"] = labels.get("topology.kubernetes.io/zone")
                    else:
                        spec = obj.spec if kind == "pod" else obj.spec.template.spec
                        for field in ("requests", "limits"):
                            amounts = container_resources(spec, field)
                            values[f"cpu_{field}"] = amounts["cpu"]
                            values[f"memory_{field}_bytes"] = amounts["memory"]
                        values["configuration"] = {
                            "request_scope": "pod" if kind == "pod" else "per_replica",
                            "created_at": meta.creation_timestamp.astimezone(UTC).isoformat()
                            if meta.creation_timestamp
                            else None,
                            "owner_uids": [r.uid for r in meta.owner_references or []],
                        }
                        if kind == "pod":
                            values["status"] = obj.status.phase or "unknown"
                            values["configuration"]["node_name"] = spec.node_name
                        else:
                            values["configuration"]["replicas"] = obj.spec.replicas
                    batch.resources.append(ResourceInput.model_validate(values))
            batch.discovery_metadata["complete_inventory"] = True
            return batch
        except CollectionError:
            raise
        except Exception:
            # API errors and kubeconfig can contain credentials. Persist codes only.
            raise CollectionError("kubernetes_unavailable_or_invalid", 503) from None
        finally:
            if api and not self.api_client:
                api.close()

    def _pages(self, method):
        items, continuation = [], None
        for _ in range(10):
            if time.monotonic() > self.deadline:
                raise CollectionError("kubernetes_collection_timeout")
            page = method(limit=500, _continue=continuation, _request_timeout=(3, 15))
            items.extend(page.items)
            if len(items) > 5000:
                raise CollectionError("kubernetes_inventory_limit")
            continuation = page.metadata._continue
            if not continuation:
                return items
        raise CollectionError("kubernetes_inventory_limit")
