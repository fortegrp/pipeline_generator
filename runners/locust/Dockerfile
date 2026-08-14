FROM locustio/locust:2.31.5

COPY --chmod=755 entrypoint.sh /usr/local/bin/performance-locust-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/performance-locust-entrypoint.sh"]
