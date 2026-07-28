import http from "k6/http";
import { check, group, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";
import { randomString } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";
import { htmlReport } from "https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js";

export const options = {
  scenarios: {
    load_test: {
      executor: "constant-arrival-rate",
      rate: 4,
      timeUnit: "1m",
      duration: "5m",
      preAllocatedVUs: 5,
      maxVUs: 20,
      tags: { test_scenario: "load_test" },
    },
    stress_test: {
      executor: "ramping-arrival-rate",
      startRate: 2,
      timeUnit: "1m",
      preAllocatedVUs: 5,
      maxVUs: 50,
      stages: [
        { target: 10, duration: "1m" },
        { target: 30, duration: "2m" },
        { target: 60, duration: "2m" },
        { target: 120, duration: "2m" },
        { target: 0, duration: "1m" },
      ],
      tags: { test_scenario: "stress_test" },
    },
    soak_test: {
      executor: "constant-arrival-rate",
      rate: 10,
      timeUnit: "1m",
      duration: "30m",
      preAllocatedVUs: 10,
      maxVUs: 25,
      tags: { test_scenario: "soak_test" },
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<10000"],
    register_duration: [{ threshold: "p(95)<8000", abortOnFail: false }],
    verify_otp_duration: [{ threshold: "p(95)<5000", abortOnFail: false }],
    full_flow_duration: [{ threshold: "p(95)<15000", abortOnFail: false }],
    otp_sent_rate: ["rate>0.20"],
    validation_errors_rate: ["rate>=0.20"],
  },
  tags: {
    test: "registration",
    service: "accounts",
  },
  setupTimeout: "30s",
  teardownTimeout: "30s",
};

const registerDuration = new Trend("register_duration");
const verifyOtpDuration = new Trend("verify_otp_duration");
const fullFlowDuration = new Trend("full_flow_duration");
const otpSentRate = new Rate("otp_sent_rate");
const otpVerifiedRate = new Rate("otp_verified_rate");
const validationErrorsRate = new Rate("validation_errors_rate");
const throttledRate = new Rate("throttled_rate");

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000/api/v2";
const REGISTER_ENDPOINT = `${BASE_URL}/accounts/auth/register/`;
const VERIFY_OTP_ENDPOINT = `${BASE_URL}/accounts/auth/verify-otp/`;

const DEV_OTP_CODE = "123456";

function uniqueIdentifier(vu, iter) {
  const suffix = randomString(8);
  return `t${vu}_${iter}_${suffix}`;
}

function buildRegisterPayload(identifier) {
  return {
    username: identifier.slice(0, 40),
    email: `${identifier}@example.com`,
    password: "P@ssw0rd!x",
  };
}

function buildVerifyPayload(identifier) {
  return {
    email: `${identifier}@example.com`,
    code: DEV_OTP_CODE,
  };
}

function clientIp(vu, iter) {
  const octet = ((vu * 17 + iter * 29) % 250) + 2;
  return `203.0.113.${octet}`;
}

function requestParams(vu, iter, tags = {}) {
  const ip = clientIp(vu, iter);
  return {
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-Forwarded-For": ip,
      "X-Real-IP": ip,
    },
    tags: {
      vu: vu.toString(),
      iteration: iter.toString(),
      ...tags,
    },
  };
}

export default function () {
  const vu = __VU;
  const iter = __ITER;
  const identifier = uniqueIdentifier(vu, iter);
  const fullFlowStart = Date.now();

  group("Full registration flow", function () {
    group("1. Register", function () {
      const payload = buildRegisterPayload(identifier);
      const params = requestParams(vu, iter, { step: "register" });

      const res = http.post(REGISTER_ENDPOINT, JSON.stringify(payload), params);
      registerDuration.add(res.timings.duration);

      if (res.status === 429) {
        throttledRate.add(1);
        return;
      }

      const checkPassed = check(res, {
        "register status 202": (r) => r.status === 202,
        "register has otp_expires_at": (r) => {
          try {
            return JSON.parse(r.body).data.otp_expires_at !== undefined;
          } catch { return false; }
        },
        "register next is verify_otp": (r) => {
          try {
            return JSON.parse(r.body).data.next === "verify_otp";
          } catch { return false; }
        },
        "register response < 5s": (r) => r.timings.duration < 5000,
      });

      if (checkPassed) {
        otpSentRate.add(1);
      }
    });

    group("2. Verify OTP", function () {
      const payload = buildVerifyPayload(identifier);
      const params = requestParams(vu, iter, { step: "verify_otp" });

      const res = http.post(VERIFY_OTP_ENDPOINT, JSON.stringify(payload), params);
      verifyOtpDuration.add(res.timings.duration);

      if (res.status === 429) {
        throttledRate.add(1);
        return;
      }

      const checkPassed = check(res, {
        "verify otp status 201": (r) => r.status === 201,
        "verify otp returns user_id": (r) => {
          try {
            return JSON.parse(r.body).data.user_id !== undefined;
          } catch { return false; }
        },
        "verify otp returns access token": (r) => {
          try {
            return JSON.parse(r.body).data.access !== undefined;
          } catch { return false; }
        },
        "verify otp returns refresh token": (r) => {
          try {
            return JSON.parse(r.body).data.refresh !== undefined;
          } catch { return false; }
        },
        "verify otp response < 3s": (r) => r.timings.duration < 3000,
      });

      if (checkPassed) {
        otpVerifiedRate.add(1);
      }
    });

    const fullFlowEnd = Date.now();
    fullFlowDuration.add(fullFlowEnd - fullFlowStart);
  });

  sleep(0.5);
}

function textSummary(data) {
  const { metrics } = data;
  let out = "";
  out += `checks.........................: ${metrics.checks ? `${metrics.checks.values.passes} / ${metrics.checks.values.passes + metrics.checks.values.fails}` : "N/A"}\n`;
  out += `otp_sent_rate.................: ${metrics.otp_sent_rate ? (metrics.otp_sent_rate.values.rate * 100).toFixed(2) + "%" : "N/A"}\n`;
  out += `otp_verified_rate.............: ${metrics.otp_verified_rate ? (metrics.otp_verified_rate.values.rate * 100).toFixed(2) + "%" : "N/A"}\n`;
  out += `validation_errors_rate........: ${metrics.validation_errors_rate ? (metrics.validation_errors_rate.values.rate * 100).toFixed(2) + "%" : "N/A"}\n`;
  out += `throttled_rate................: ${metrics.throttled_rate ? (metrics.throttled_rate.values.rate * 100).toFixed(2) + "%" : "N/A"}\n`;
  out += `register_duration p95.........: ${metrics.register_duration ? metrics.register_duration.values["p(95)"].toFixed(2) + "ms" : "N/A"}\n`;
  out += `verify_otp_duration p95.......: ${metrics.verify_otp_duration ? metrics.verify_otp_duration.values["p(95)"].toFixed(2) + "ms" : "N/A"}\n`;
  out += `full_flow_duration p95........: ${metrics.full_flow_duration ? metrics.full_flow_duration.values["p(95)"].toFixed(2) + "ms" : "N/A"}\n`;
  out += `http_req_failed...............: ${metrics.http_req_failed ? (metrics.http_req_failed.values.rate * 100).toFixed(2) + "%" : "N/A"}\n`;
  out += `http_req_duration p95.........: ${metrics.http_req_duration ? metrics.http_req_duration.values["p(95)"].toFixed(2) + "ms" : "N/A"}\n`;
  out += `http_reqs.....................: ${metrics.http_reqs ? metrics.http_reqs.values.count : 0}\n`;
  return out;
}

export function handleSummary(data) {
  return {
    stdout: textSummary(data),
    "registration-performance-report.html": htmlReport(data),
  };
}
