import metric_cache
from metric_cache import MetricResultCache, RedisMetricResultCache, build_metric_cache


def test_metric_cache_expires_entries(monkeypatch):
    now = {"value": 10.0}
    monkeypatch.setattr(metric_cache, "monotonic", lambda: now["value"])
    cache = MetricResultCache(ttl_seconds=5)
    cache.set(("metric",), {"rows": [[1]]})

    assert cache.get(("metric",)) == {"rows": [[1]]}
    now["value"] = 15.0
    assert cache.get(("metric",)) is None


def test_metric_cache_evicts_least_recently_used_entry():
    cache = MetricResultCache(max_entries=2)
    cache.set(("first",), {"rows": [[1]]})
    cache.set(("second",), {"rows": [[2]]})
    assert cache.get(("first",)) == {"rows": [[1]]}
    cache.set(("third",), {"rows": [[3]]})

    assert cache.get(("second",)) is None
    assert cache.get(("first",)) == {"rows": [[1]]}
    assert cache.get(("third",)) == {"rows": [[3]]}


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, *, px):
        assert px > 0
        self.values[key] = value


def test_redis_metric_cache_is_shared_by_independent_instances():
    backend = FakeRedis()
    first_worker = RedisMetricResultCache(backend)
    second_worker = RedisMetricResultCache(backend)
    scope_key = ("synthetic-ecommerce", "tenant-a", "analyst-a", "sha256")
    result = {"columns": ["sales_cents"], "rows": [[45000]], "returned_rows": 1}

    first_worker.set(scope_key, result)

    assert second_worker.get(scope_key) == result
    assert "tenant-a" not in next(iter(backend.values))


def test_redis_cache_failure_falls_back_to_query_execution(caplog):
    class UnavailableRedis:
        def get(self, key):
            raise ConnectionError("redis unavailable")

        def set(self, key, value, *, px):
            raise ConnectionError("redis unavailable")

    cache = RedisMetricResultCache(UnavailableRedis())

    assert cache.get(("metric",)) is None
    cache.set(("metric",), {"rows": [[1]]})
    assert "bypassing cache" in caplog.text


def test_metric_cache_uses_local_storage_without_redis_url():
    assert isinstance(build_metric_cache(), MetricResultCache)
