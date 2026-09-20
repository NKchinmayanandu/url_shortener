import http from "k6/http";
import { check } from "k6";

const BASE_URL = "http://nginx";

export const options = {
    vus: 10,
    duration: "30s",

    thresholds: {
        http_req_failed: ["rate<0.01"],
        http_req_duration: ["p(95)<500"],
    },
};

export default function () {
    const url = `https://example.com/${__VU}-${__ITER}`;

    const res = http.post(
        `${BASE_URL}/shorten?url=${encodeURIComponent(url)}`,
        null,
        {
            tags: {
                endpoint: "shorten",
            },
        }
    );

    check(res, {
        "status is 200": (r) => r.status === 200,
        "short code returned": (r) => r.json("short_code") !== undefined,
    });
}