import http from 'k6/http';
import { sleep } from 'k6';

// k6 keeps its own native metrics (http_req_duration, http_reqs, http_req_failed, ...) rather
// than writing performance_http_request like the other tools - see docs/metric-model.md. The
// required tags below are attached to every one of those native metrics instead: `tags` in
// options applies to the whole run, `tags` per request adds `transaction` on top of it.

const PROJECT = __ENV.PROJECT || 'httpbin-demo';
const ENVIRONMENT = __ENV.ENVIRONMENT || 'local';
const TEST_RUN_ID = __ENV.TEST_RUN_ID || 'k6-local';
const SCENARIO = __ENV.SCENARIO || 'httpbin-smoke';

export const options = {
  vus: Number(__ENV.USERS || 3),
  duration: __ENV.RUN_TIME || '20s',
  tags: {
    project: PROJECT,
    environment: ENVIRONMENT,
    testRunID: TEST_RUN_ID,
    tool: 'k6',
    scenario: SCENARIO,
  },
};

export default function () {
  http.get('https://httpbin.org/get', { tags: { transaction: 'GET_/get' } });
  sleep(1);
  http.get('https://httpbin.org/delay/1', { tags: { transaction: 'GET_/delay/1' } });
  sleep(1);
  http.get('https://httpbin.org/status/200,200,200,200,500', { tags: { transaction: 'GET_/status' } });
  sleep(1);
}
