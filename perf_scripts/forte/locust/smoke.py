import os
import time

from locust import HttpUser, between, events, task
import requests


PROJECT = os.getenv("PROJECT", "forte")
ENVIRONMENT = os.getenv("ENVIRONMENT", "local")
TEST_RUN_ID = os.getenv("TEST_RUN_ID", "local-001")
SCENARIO = os.getenv("SCENARIO", "smoke")
RUN_DESCRIPTION = os.getenv("RUN_DESCRIPTION", "Local Locust smoke run")
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "").rstrip("/")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "perf_metrics")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "forte")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "local-token")


def escape_tag(value):
    return str(value).replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def write_influx_request(name, response_time, response, exception):
    if not INFLUXDB_URL:
        return

    status_code = getattr(response, "status_code", 0) or 0
    failed = exception is not None or status_code >= 400
    line = (
        "performance_http_request,"
        f"project={escape_tag(PROJECT)},"
        f"environment={escape_tag(ENVIRONMENT)},"
        f"testRunID={escape_tag(TEST_RUN_ID)},"
        "tool=locust,"
        f"scenario={escape_tag(SCENARIO)},"
        f"transaction={escape_tag(name)} "
        f"response_time_ms={int(response_time)}i,"
        f"status_code={int(status_code)}i,"
        f"failed={str(failed).lower()} "
        f"{int(time.time() * 1000)}"
    )

    try:
        requests.post(
            f"{INFLUXDB_URL}/api/v2/write",
            params={"org": INFLUXDB_ORG, "bucket": INFLUXDB_BUCKET, "precision": "ms"},
            headers={"Authorization": f"Token {INFLUXDB_TOKEN}"},
            data=line,
            timeout=2,
        )
    except requests.RequestException:
        pass


@events.request.add_listener
def add_execution_context(request_type, name, response_time, response_length, response, context, exception, start_time, url, **kwargs):
    if context is not None:
        context["project"] = PROJECT
        context["environment"] = ENVIRONMENT
        context["testRunID"] = TEST_RUN_ID
        context["tool"] = "locust"
        context["scenario"] = SCENARIO
        context["runDescription"] = RUN_DESCRIPTION

    write_influx_request(name, response_time, response, exception)


class ForteSmokeUser(HttpUser):
    wait_time = between(1, 2)

    @task
    def tx_home(self):
        self.client.get("/", name="TX_Home")
