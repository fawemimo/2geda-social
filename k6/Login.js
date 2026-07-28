import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const RATE_PER_MINUTE = Number(__ENV.LOGIN_RATE_PER_MINUTE || 300);
const DURATION = __ENV.DURATION || "5m";
const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000/api/v2";
const LOGIN_ENDPOINT = `${BASE_URL}/accounts/auth/login/`;

const LOGIN_USERNAME = __ENV.LOGIN_USERNAME || "admin";
const LOGIN_EMAIL = __ENV.LOGIN_EMAIL || "dev@2geda.net";
const LOGIN_PASSWORD = __ENV.LOGIN_PASSWORD || "password@1234";

const loginSuccessRate = new Rate("login_success_rate");
const loginDuration = new Trend("login_duration");

export const options = {
  scenarios: {
    login_load: {
      executor: "constant-arrival-rate",
      rate: RATE_PER_MINUTE,
      timeUnit: "1m",
      duration: DURATION,
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.02"],
    http_req_duration: ["p(95)<1500"],
    login_success_rate: ["rate>0.95"],
  },
  tags: {
    test: "login",
    service: "accounts",
  },
};

export default function () {
  if (!LOGIN_USERNAME && !LOGIN_EMAIL) {
    throw new Error(
      "Set LOGIN_USERNAME or LOGIN_EMAIL and LOGIN_PASSWORD before running this test.",
    );
  }

  const payload = {
    password: LOGIN_PASSWORD,
  };

  if (LOGIN_EMAIL) {
    payload.email = LOGIN_EMAIL;
  } else {
    payload.username = LOGIN_USERNAME;
  }

  const ip = `203.0.113.${((Number(__VU) * 17 + Number(__ITER) * 29) % 250) + 2}`;

  const params = {
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-Forwarded-For": ip,
      "X-Real-IP": ip,
    },
    tags: {
      endpoint: "accounts-login",
    },
  };

  const res = http.post(LOGIN_ENDPOINT, JSON.stringify(payload), params);
  loginDuration.add(res.timings.duration);

  const success = check(res, {
    "status is 200": (r) => r.status === 200,
    "response has access token": (r) => {
      const body = r.json();
      return Boolean(
        body && body.status === true && body.data && body.data.access,
      );
    },
    "response time is acceptable": (r) => r.timings.duration < 2000,
  });

  loginSuccessRate.add(success ? 1 : 0);
  sleep(0.1);
}

function textSummary(data) {
  const { metrics } = data;
  return [
    `login_success_rate............: ${metrics.login_success_rate ? (metrics.login_success_rate.values.rate * 100).toFixed(2) + "%" : "N/A"}`,
    `login_duration p95............: ${metrics.login_duration ? metrics.login_duration.values["p(95)"].toFixed(2) + "ms" : "N/A"}`,
    `http_req_failed...............: ${metrics.http_req_failed ? (metrics.http_req_failed.values.rate * 100).toFixed(2) + "%" : "N/A"}`,
    `http_req_duration p95.........: ${metrics.http_req_duration ? metrics.http_req_duration.values["p(95)"].toFixed(2) + "ms" : "N/A"}`,
    `http_reqs.....................: ${metrics.http_reqs ? metrics.http_reqs.values.count : 0}`,
  ].join("\n");
}

export function handleSummary(data) {
  return {
    stdout: textSummary(data),
  };
}
