package simulations;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

/**
 * Writes a single line-protocol point to InfluxDB v2, synchronously, the same way the JMeter
 * Groovy listener and the sample shell scripts do. Gatling has no public per-request callback
 * API (its own reporting is either an internal binary log or aggregated Graphite output), so
 * this is called directly from the simulation's session chain around each request. A blocking
 * HTTP call per request is fine at this demo's request volume; a high-throughput Gatling run
 * would need this decoupled onto its own thread pool instead of Gatling's Netty event loop.
 */
final class InfluxWriter {

  private InfluxWriter() {
  }

  static String tag(String value) {
    String text = (value == null || value.trim().isEmpty()) ? "unknown" : value;
    return text.replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=");
  }

  static void write(String influxUrl, String org, String bucket, String token, String line) {
    try {
      String endpoint = influxUrl + "/api/v2/write?org=" + URLEncoder.encode(org, "UTF-8")
          + "&bucket=" + URLEncoder.encode(bucket, "UTF-8") + "&precision=ms";
      HttpURLConnection connection = (HttpURLConnection) new URL(endpoint).openConnection();
      connection.setRequestMethod("POST");
      connection.setDoOutput(true);
      connection.setConnectTimeout(5000);
      connection.setReadTimeout(5000);
      connection.setRequestProperty("Authorization", "Token " + token);
      connection.setRequestProperty("Content-Type", "text/plain; charset=utf-8");
      try (OutputStream out = connection.getOutputStream()) {
        out.write(line.getBytes(StandardCharsets.UTF_8));
      }
      int status = connection.getResponseCode();
      if (status < 200 || status >= 300) {
        System.err.println("InfluxDB write failed. status=" + status + " line=" + line);
      }
      connection.disconnect();
    } catch (Exception e) {
      System.err.println("InfluxDB write error: " + e.getMessage());
    }
  }
}
