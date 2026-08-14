FROM eclipse-temurin:17-jre

ARG GATLING_VERSION=3.10.5

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip wget \
    && wget -q -O /tmp/gatling.zip "https://repo1.maven.org/maven2/io/gatling/highcharts/gatling-charts-highcharts-bundle/${GATLING_VERSION}/gatling-charts-highcharts-bundle-${GATLING_VERSION}-bundle.zip" \
    && unzip -q /tmp/gatling.zip -d /opt \
    && mv "/opt/gatling-charts-highcharts-bundle-${GATLING_VERSION}" /opt/gatling \
    && rm -f /tmp/gatling.zip \
    && rm -rf /var/lib/apt/lists/*

ENV GATLING_HOME=/opt/gatling
ENV PATH="/opt/gatling/bin:${PATH}"

COPY entrypoint.sh /usr/local/bin/performance-gatling-entrypoint.sh
RUN chmod +x /usr/local/bin/performance-gatling-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/performance-gatling-entrypoint.sh"]
