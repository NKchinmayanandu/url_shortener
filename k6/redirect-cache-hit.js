import http from "k6/http";
import { check } from "k6";

const BASE_URL = "http://nginx";
const SHORT_CODE = "WwzPM"; // replace this

export const options = {
    vus: 10,
    duration: "30s",

    thresholds: {
        http_req_failed: ["rate<0.01"],
        http_req_duration: ["p(95)<300"],
    },
};

export default function () {
    const res = http.get(
        `${BASE_URL}/${SHORT_CODE}`,
        {
            redirects: false,
            tags: {
                endpoint: "redirect-cache-hit",
            },
        }
    );

    check(res, {
        "status is 307": (r) => r.status === 307,
        "location exists": (r) => r.headers["Location"] !== undefined,
    });
}