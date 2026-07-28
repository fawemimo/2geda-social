import http from "k6/http";
import { check, group, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const RATE_PER_MINUTE = Number(__ENV.DISPLAY_FEED_RATE_PER_MINUTE || 30);
const DURATION = __ENV.DISPLAY_FEED_DURATION || "2m";
const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000/api/v2";
const LOGIN_ENDPOINT = `${BASE_URL}/accounts/auth/login/`;
const FEED_ENDPOINT = `${BASE_URL}/displays/feed/`;

const USERNAME = __ENV.DISPLAY_FEED_USERNAME || __ENV.DISPLAY_FEED_EMAIL || "dev@2geda.net";
const EMAIL = __ENV.DISPLAY_FEED_EMAIL || "dev@2geda.net";
const PASSWORD = __ENV.DISPLAY_FEED_PASSWORD || "password@1234";

const feedSuccessRate = new Rate("feed_success_rate");
const feedDuration = new Trend("feed_duration");

export const options = {
  scenarios: {
    feed_load: {
      executor: "constant-arrival-rate",
      rate: RATE_PER_MINUTE,
      timeUnit: "1m",
      duration: DURATION,
      preAllocatedVUs: 5,
      maxVUs: 20,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<2000"],
    feed_success_rate: ["rate>0.95"],
  },
  tags: {
    test: "displays-feed",
    service: "displays",
  },
};

export function setup() {
  if (!USERNAME || !PASSWORD) {
    throw new Error(
      "Set DISPLAY_FEED_USERNAME/EMAIL and DISPLAY_FEED_PASSWORD before running this test.",
    );
  }

  const payload = {
    password: PASSWORD,
  };

  if (EMAIL) {
    payload.email = EMAIL;
  } else {
    payload.username = USERNAME;
  }

  const res = http.post(LOGIN_ENDPOINT, JSON.stringify(payload), {
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    tags: {
      scenario: "login",
    },
  });

  const body = res.json();
  const accessToken = body?.data?.access;

  if (res.status !== 200 || !accessToken) {
    throw new Error(`Login failed: ${res.status} ${res.body}`);
  }

  return accessToken;
}

export default function (accessToken) {
  group("GET /displays/feed/", function () {
    const params = {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: "application/json",
      },
      tags: {
        endpoint: "displays-feed",
      },
    };

    const res = http.get(`${FEED_ENDPOINT}?page=1&page_size=20`, params);
    feedDuration.add(res.timings.duration);

    const success = check(res, {
      "status is 200": (r) => r.status === 200,
      "response has success envelope": (r) => {
        const body = r.json();
        return Boolean(
          body && body.status === true && Array.isArray(body.data),
        );
      },
      "response time is acceptable": (r) => r.timings.duration < 2000,
    });

    if (success) {
      feedSuccessRate.add(1);
    } else {
      feedSuccessRate.add(0);
    }

    sleep(0.5);
  });
}

function textSummary(data) {
  const { metrics } = data;
  return [
    `feed_success_rate..............: ${metrics.feed_success_rate ? (metrics.feed_success_rate.values.rate * 100).toFixed(2) + "%" : "N/A"}`,
    `feed_duration p95..............: ${metrics.feed_duration ? metrics.feed_duration.values["p(95)"].toFixed(2) + "ms" : "N/A"}`,
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
