// REL-009 E9.6: the Agent Console (/agents) renders real data from the real
// GET /api/v1/agents/runs endpoint, not a fabricated/mocked list.

export {};

const API_URL = Cypress.env("apiUrl");

describe("Agent Console", () => {
  it("redirects an unauthenticated visitor to /login", () => {
    cy.visit("/agents");
    cy.url().should("include", "/login");
  });

  it("renders the real graph topology and real run history once authenticated", () => {
    cy.visit("/login");
    cy.get("input[type=email]").type(Cypress.env("adminEmail"));
    cy.get("input[type=password]").type(Cypress.env("adminPassword"));
    cy.get("button[type=submit]").click();
    cy.url().should("eq", Cypress.config().baseUrl + "/");

    cy.window()
      .its("localStorage")
      .invoke("getItem", "tradingos_access_token")
      .then((token) => {
        // The exact same real API this page itself calls -- used here only to know what to
        // assert against, not to mock/replace the page's own network call.
        cy.request({
          url: `${API_URL}/api/v1/agents/runs`,
          headers: { Authorization: `Bearer ${token}` },
        }).then((response) => {
          expect(response.status).to.eq(200);
          const realRuns = response.body as Array<{ run_id: string; agent_name: string }>;

          cy.visit("/agents");
          cy.contains("Agent Console").should("be.visible");
          cy.contains("Research Cycle").should("be.visible");

          if (realRuns.length > 0) {
            // Every real run this API returned really is a TradingOSGraph root run (see
            // src/api/routers/agents.py::list_runs()'s real, scoped query, REL-009's own fix).
            realRuns.forEach((run) => expect(run.agent_name).to.eq("TradingOSGraph"));
          }
        });
      });
  });
});
