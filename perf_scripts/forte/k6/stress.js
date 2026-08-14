import http from 'k6/http';
import { check, group, sleep } from 'k6';

const targetUrl = 'https://test.k6.io';
const project = __ENV.PROJECT || 'forte';
const environment = __ENV.ENVIRONMENT || 'local';
const testRunID = __ENV.TEST_RUN_ID || 'local-001';
const scenario = __ENV.SCENARIO || 'stress';
const runDescription = __ENV.RUN_DESCRIPTION || 'Local stress run';

export const options = {
  scenarios: {
    [scenario]: {
      executor: 'ramping-vus',
      stages: [
        { duration: '30s', target: 10 },
        { duration: '30s', target: 20 },
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.20'],
    checks: ['rate>0.90'],
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

  sleep(1);
}
