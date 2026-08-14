FROM justb4/jmeter:latest

COPY entrypoint.sh /usr/local/bin/performance-jmeter-entrypoint.sh
RUN chmod +x /usr/local/bin/performance-jmeter-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/performance-jmeter-entrypoint.sh"]
