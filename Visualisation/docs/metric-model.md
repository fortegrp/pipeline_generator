# Metric Model

Use one measurement for performance test output:

```text
performance
```

Recommended tags:

- `run`: unique benchmark run identifier. Use this to compare baseline, candidate, branch, commit, release, or environment results.
- `suite`: stable benchmark suite name, for example `checkout`.
- `test`: stable test or scenario name, for example `submit_order`.
- `request`: unique request, endpoint, transaction, or sampler name inside a test, for example `GET_/cart` or `POST_/orders`.
- `branch`: optional source branch.
- `commit`: optional commit SHA.
- `environment`: optional target environment, for example `local`, `staging`, or `ci`.

Recommended fields:

- `latency_ms`: response time in milliseconds.
- `throughput_ops_s`: requests per second.
- `error_rate`: fraction from `0` to `1`.
- `cpu_percent`: CPU usage percentage.
- `memory_mb`: memory usage in MB.

Example line protocol:

```text
performance,run=build-1042-candidate,suite=checkout,test=submit_order,request=POST_/orders,branch=main,commit=abc1234,environment=ci latency_ms=95,throughput_ops_s=940,error_rate=0.006,cpu_percent=58,memory_mb=512
```

Keep `suite`, `test`, and `request` names stable across runs. Grafana comparisons are only meaningful when the selected runs represent the same benchmark scenario and request names.
