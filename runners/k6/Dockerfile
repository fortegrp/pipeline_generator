FROM golang:1.25-alpine AS builder

ARG XK6_K6_VERSION=v0.49.0
ARG XK6_VERSION=v1.4.3
ARG XK6_INFLUXDB_VERSION=v0.7.0

RUN apk add --no-cache git ca-certificates \
    && go install "go.k6.io/xk6/cmd/xk6@${XK6_VERSION}" \
    && xk6 build "${XK6_K6_VERSION}" \
      --with "github.com/grafana/xk6-output-influxdb@${XK6_INFLUXDB_VERSION}" \
      --output /tmp/k6

FROM alpine:3.20

RUN apk add --no-cache bash ca-certificates curl tzdata

COPY --from=builder /tmp/k6 /usr/local/bin/k6
COPY entrypoint.sh /usr/local/bin/performance-k6-entrypoint.sh
RUN chmod +x /usr/local/bin/k6 /usr/local/bin/performance-k6-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/performance-k6-entrypoint.sh"]
