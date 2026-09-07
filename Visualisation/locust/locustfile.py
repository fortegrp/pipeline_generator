import os

import requests
from locust import HttpUser, between, events, task

INFLUX_URL = os.environ.get("INFLUX_URL", "http://localhost:8086")
INFLUX_ORG = os.environ.get("INFLUX_ORG", "performance")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "performance")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN", "change-me-super-secret-token")
PROJECT = os.environ.get("PROJECT", "httpbin-demo")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "local")
TEST_RUN_ID = os.environ.get("TEST_RUN_ID", "locust-local")
SCENARIO = os.environ.get("SCENARIO", "httpbin-smoke")

_write_url = (
    f"{INFLUX_URL}/api/v2/write?org={INFLUX_ORG}&bucket={INFLUX_BUCKET}&precision=ms"
)
_write_headers = {
    "Authorization": f"Token {INFLUX_TOKEN}",
    "Content-Type": "text/plain; charset=utf-8",
}


def _tag(value):
    text = str(value) if value else "unknown"
    return text.replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


@events.request.add_listener
def write_metric(request_type, name, response_time, response, exception, **kwargs):
    status_code = response.status_code if response is not None else 0
    failed = exception is not None or status_code < 200 or status_code >= 400
    line = (
        f"performance_http_request,project={_tag(PROJECT)},environment={_tag(ENVIRONMENT)},"
        f"testRunID={_tag(TEST_RUN_ID)},tool=locust,scenario={_tag(SCENARIO)},transaction={_tag(name)} "
        f"response_time_ms={round(response_time)}i,status_code={status_code}i,failed={'true' if failed else 'false'}"
    )
    try:
        requests.post(_write_url, headers=_write_headers, data=line.encode("utf-8"), timeout=5)
    except requests.RequestException as e:
        print(f"InfluxDB write error: {e}")


class HttpbinUser(HttpUser):
    wait_time = between(1, 1)

    @task
    def get_root(self):
        self.client.get("/get", name="GET_/get")

    @task
    def get_delay(self):
        self.client.get("/delay/1", name="GET_/delay/1")

    @task
    def get_status(self):
        self.client.get("/status/200,200,200,200,500", name="GET_/status")
