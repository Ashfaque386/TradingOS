// REL-009 E9.6 (TEST-014 Performance Tests -- NFR-02's "under 500+ concurrent WS connections
// matching the HPA threshold" scenario, per Phase_8_DevOps_Architecture.md §3's HPA rule).
// Real WebSocket load against the real running `app` service's real
// GET /api/v1/stream/market/{symbol} relay (src/api/routers/streams.py) -- no mocked transport.
//
// Run manually (not a blocking CI gate -- host-performance-dependent, same honest-measurement
// reasoning as REL-008's ONNX latency test and this same directory's locustfile.py). k6 is a Go
// binary, not a Python package -- it runs via its own official Docker image (same "one-shot
// external tool container" pattern as gitleaks/zaproxy elsewhere in this project), not installed
// into the `app` image:
//   1. In one terminal: docker compose exec app python tests/perf/publish_synthetic_ticks.py \
//        RELIANCE --rate 20 --duration 90
//      (this dev environment has no continuously-running live broker feed -- see that script's
//      own docstring for why this is necessary, and why it's a separate, visible step rather
//      than data silently baked into the measured numbers)
//   2. In another terminal: docker run --rm --network tradingos_default \
//        -v "${PWD}/tests/perf:/scripts" -e WS_BASE=ws://app:8000 \
//        grafana/k6 run /scripts/websocket_load.js
//
// Reports real p95/p99 relay latency (ticks/close-to-open) across real concurrent connections,
// via k6's own connection/message metrics -- WS_STREAM_LATENCY_SECONDS (Prometheus, scraped by
// the real E9.1 Prometheus instance) is the second, independent measurement of the same real
// relay from the server side.

import ws from "k6/ws";
import { check } from "k6";
import { Trend } from "k6/metrics";

const WS_BASE = __ENV.WS_BASE || "ws://app:8000";
const SYMBOL = __ENV.SYMBOL || "RELIANCE";
const CONCURRENT_CONNECTIONS = parseInt(__ENV.VUS || "50", 10);

export const options = {
  scenarios: {
    concurrent_ws_relay: {
      executor: "constant-vus",
      vus: CONCURRENT_CONNECTIONS,
      duration: __ENV.DURATION || "60s",
    },
  },
};

const messageGap = new Trend("tick_relay_message_gap_ms", true);

export default function () {
  const url = `${WS_BASE}/api/v1/stream/market/${SYMBOL}`;
  let lastMessageAt = null;

  const res = ws.connect(url, {}, function (socket) {
    socket.on("open", () => {
      lastMessageAt = Date.now();
    });

    socket.on("message", (data) => {
      const now = Date.now();
      if (lastMessageAt !== null) {
        messageGap.add(now - lastMessageAt);
      }
      lastMessageAt = now;

      const parsed = JSON.parse(data);
      check(parsed, {
        "message has the real relay shape (symbol, ltp, ts)": (m) =>
          "symbol" in m && "ltp" in m && "ts" in m,
      });
    });

    socket.setTimeout(() => {
      socket.close();
    }, 30000);
  });

  check(res, { "real WS handshake succeeded (status 101)": (r) => r && r.status === 101 });
}
