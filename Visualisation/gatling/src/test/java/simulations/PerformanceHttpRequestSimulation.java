package simulations;

import static io.gatling.javaapi.core.CoreDsl.*;
import static io.gatling.javaapi.http.HttpDsl.*;

import io.gatling.javaapi.core.ChainBuilder;
import io.gatling.javaapi.core.ScenarioBuilder;
import io.gatling.javaapi.core.Simulation;
import io.gatling.javaapi.http.HttpProtocolBuilder;

/**
 * Hits httpbin.org and writes one performance_http_request point per request to InfluxDB v2,
 * matching the schema documented in docs/metric-model.md. See InfluxWriter for why this is done
 * with a per-request session hook instead of Gatling's own reporting pipeline.
 */
public class PerformanceHttpRequestSimulation extends Simulation {

  private static final String INFLUX_URL = System.getProperty("influx_url", "http://localhost:8086");
  private static final String INFLUX_ORG = System.getProperty("influx_org", "performance");
  private static final String INFLUX_BUCKET = System.getProperty("influx_bucket", "performance");
  private static final String INFLUX_TOKEN = System.getProperty("influx_token", "change-me-super-secret-token");
  private static final String PROJECT = System.getProperty("project", "httpbin-demo");
  private static final String ENVIRONMENT = System.getProperty("environment", "local");
  private static final String TEST_RUN_ID = System.getProperty("test_run_id", "gatling-local");
  private static final String SCENARIO_NAME = System.getProperty("scenario", "httpbin-smoke");
  private static final int USERS = Integer.getInteger("users", 2);

  private static final HttpProtocolBuilder httpProtocol = http.baseUrl("https://httpbin.org");

  private static ChainBuilder tracked(String transaction, String path) {
    return exec(session -> session.set("t0", System.currentTimeMillis()))
        .exec(http(transaction).get(path).check(status().saveAs("statusCode")))
        .exec(session -> {
          long elapsedMs = System.currentTimeMillis() - session.getLong("t0");
          int statusCode = session.contains("statusCode") ? session.getInt("statusCode") : 0;
          boolean failed = statusCode < 200 || statusCode >= 400;
          String line = String.format(
              "performance_http_request,project=%s,environment=%s,testRunID=%s,tool=gatling,scenario=%s,transaction=%s response_time_ms=%di,status_code=%di,failed=%b",
              InfluxWriter.tag(PROJECT),
              InfluxWriter.tag(ENVIRONMENT),
              InfluxWriter.tag(TEST_RUN_ID),
              InfluxWriter.tag(SCENARIO_NAME),
              InfluxWriter.tag(transaction),
              elapsedMs,
              statusCode,
              failed);
          InfluxWriter.write(INFLUX_URL, INFLUX_ORG, INFLUX_BUCKET, INFLUX_TOKEN, line);
          return session;
        });
  }

  private static final ScenarioBuilder httpbinSmoke = scenario("httpbin smoke")
      .exec(tracked("GET_/get", "/get"))
      .pause(1)
      .exec(tracked("GET_/delay/1", "/delay/1"))
      .pause(1)
      .exec(tracked("GET_/status", "/status/200,200,200,200,500"));

  {
    setUp(httpbinSmoke.injectOpen(atOnceUsers(USERS))).protocols(httpProtocol);
  }
}
