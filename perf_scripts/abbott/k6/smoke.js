import http from 'k6/http';
import { check, group } from 'k6';

const targetUrl = 'https://test.k6.io';
const project = __ENV.PROJECT || 'forte';
const environment = __ENV.ENVIRONMENT || 'local';
const testRunID = __ENV.TEST_RUN_ID || 'local-001';
const scenario = __ENV.SCENARIO || 'smoke';
const runDescription = __ENV.RUN_DESCRIPTION || 'Local smoke run';

export const options = {
  scenarios: {
    [scenario]: {
      executor: 'shared-iterations',
      vus: 1,
      iterations: 1,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<1000'],
  },
  tags: {
    project,
    environment,
    testRunID,
    tool: 'k6',
    scenario,
    runDescription,
  },
};

export default function () {
  group('TX_Home', () => {
    const response = http.get(targetUrl, {
      tags: {
        transaction: 'TX_Home',
      },
    });

    check(response, {
      'TX_Home status is 2xx or 3xx': (res) => res.status >= 200 && res.status < 400,
    }, {
      transaction: 'TX_Home',
    });
  });
}
