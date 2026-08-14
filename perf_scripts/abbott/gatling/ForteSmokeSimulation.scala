import io.gatling.core.Predef._
import io.gatling.http.Predef._
import scala.concurrent.duration._

class ForteSmokeSimulation extends Simulation {
  private val project = sys.env.getOrElse("PROJECT", "forte")
  private val environment = sys.env.getOrElse("ENVIRONMENT", "local")
  private val testRunID = sys.env.getOrElse("TEST_RUN_ID", "local-001")
  private val scenarioName = sys.env.getOrElse("SCENARIO", "smoke")
  private val runDescription = sys.env.getOrElse("RUN_DESCRIPTION", "Local Gatling smoke run")

  private val httpProtocol = http
    .baseUrl("https://test.k6.io")
    .inferHtmlResources()

  private val smokeScenario = scenario(scenarioName)
    .exec(
      http("TX_Home")
        .get("/")
        .check(status.in(200, 301, 302))
        .resources()
    )

  setUp(
    smokeScenario.inject(atOnceUsers(1))
  ).protocols(httpProtocol)
    .assertions(global.failedRequests.percent.lt(5))
}
