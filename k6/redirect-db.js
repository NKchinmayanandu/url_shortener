import http from "k6/http";
import { check } from "k6";

const BASE_URL = "http://nginx";
const SHORT_CODES = [
    // we'll populate these
];

export const options = {
    scenarios: {
        db_read: {
            executor: "per-vu-iterations",
            vus: 10,
            iterations: 100,
            maxDuration: "2m",
        },
    },

    thresholds: {
        http_req_failed: ["rate<0.01"],
        http_req_duration: ["p(95)<500"],
    },
};

export default function () {
    const index = (__VU - 1) * 100 + __ITER;
    const shortCode = SHORT_CODES[index];

    const res = http.get(
        `${BASE_URL}/${shortCode}`,
        {
            redirects: false,
        }
    );

    check(res, {
        "status is 307": (r) => r.status === 307,
        "location exists": (r) => r.headers["Location"] !== undefined,
    });
}