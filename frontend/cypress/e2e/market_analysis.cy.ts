// REL-067: the Market Analysis tab against the real running stack -- real login, real
// GET /market/pulse (India VIX + NSE sector-index data), real GET /market/ohlcv/{symbol}/
// indicators (previously dead-code technical-indicator math, now wired), and real
// GET /market/datalake/status. No mocking.
// REL-071 (Phase 2): the 4th "Instruments" tab, against the real, locally-synced Upstox
// instrument master (GET /market/instruments/search).

export {};

const API_URL = Cypress.env("apiUrl");

function login() {
  cy.visit("/login");
  cy.get("input[type=email]").type(Cypress.env("adminEmail"));
  cy.get("input[type=password]").type(Cypress.env("adminPassword"));
  cy.get("button[type=submit]").click();
  cy.url().should("eq", Cypress.config().baseUrl + "/");
}

describe("Market Analysis", () => {
  it("is reachable from the nav and shows all 4 real tabs", () => {
    login();
    cy.contains("a", "Market Analysis").click();
    cy.url().should("include", "/market-analysis");
    cy.get('[role="tab"]').contains("Market Pulse").should("be.visible");
    cy.get('[role="tab"]').contains("Technical Analysis").should("be.visible");
    cy.get('[role="tab"]').contains("Data Freshness").should("be.visible");
    cy.get('[role="tab"]').contains("Instruments").should("be.visible");
  });

  it("Market Pulse tab shows a real India VIX figure or an honest unavailable message", () => {
    cy.request(`${API_URL}/api/v1/market/pulse`).then((response) => {
      expect(response.status).to.eq(200);
      const pulse = response.body as { india_vix: { value: number } | null };

      login();
      cy.visit("/market-analysis");
      cy.contains("India VIX").should("be.visible");
      // Branches on the same real data the API just returned -- never assumed available.
      if (pulse.india_vix !== null) {
        cy.contains(pulse.india_vix.value.toFixed(2)).should("be.visible");
      } else {
        cy.contains("No real India VIX data available").should("be.visible");
      }
      cy.contains("Sector Performance").should("be.visible");
    });
  });

  it("Technical Analysis tab renders the real symbol universe and 3 real charts", () => {
    cy.request(`${API_URL}/api/v1/market/symbols`).then((response) => {
      expect(response.status).to.eq(200);
      const realSymbols = response.body as string[];

      login();
      cy.visit("/market-analysis");
      cy.get('[role="tab"]').contains("Technical Analysis").click();

      if (realSymbols.length > 0) {
        cy.get("select").should(($select) => {
          const values = Array.from(($select[0] as HTMLSelectElement).options).map(
            (o) => o.value,
          );
          expect(values).to.include(realSymbols[0]);
        });
        cy.get("canvas").its("length").should("be.gte", 1);
      } else {
        cy.log("No symbols ingested into the EOD lake yet -- nothing to assert about chart data.");
      }

      cy.contains("RSI (14)").should("be.visible");
      cy.contains("MACD (12, 26, 9)").should("be.visible");
    });
  });

  it("Data Freshness tab shows the real datalake status", () => {
    login();
    cy.visit("/market-analysis");
    cy.get('[role="tab"]').contains("Data Freshness").click();
    cy.contains(/^(Fresh|Stale)$/).should("be.visible");
    cy.contains(/\d+ symbols tracked/).should("be.visible");
  });

  it("Instruments tab searches the real, locally-synced Upstox instrument master", () => {
    cy.request(`${API_URL}/api/v1/market/instruments/search?q=RELIANCE&exchange=NSE`).then(
      (response) => {
        expect(response.status).to.eq(200);
        const body = response.body as { total: number; items: { symbol: string }[] };
        // A real live Upstox sync run against this environment already confirmed RELIANCE is
        // present (this phase's own REL-071 verification) -- if that ever changes, this test's
        // failure is the honest signal, not a reason to weaken the assertion to "skip".
        expect(body.total).to.be.greaterThan(0);

        login();
        cy.visit("/market-analysis");
        cy.get('[role="tab"]').contains("Instruments").click();
        cy.contains(/\d+ matches?$/).should("be.visible");

        cy.get('input[placeholder="Search symbol or name…"]').type("RELIANCE");
        cy.contains(body.items[0].symbol).should("be.visible");

        cy.get('input[placeholder="Search symbol or name…"]').clear();
        cy.contains("button", "Index").click();
        // A real NSE index (e.g. Nifty 50) must show up once the search is cleared and only
        // the Index type filter is active -- proves the filter chip actually re-queries the
        // server rather than silently filtering an already-fetched equities page.
        cy.contains("INDEX").should("be.visible");
      },
    );
  });
});
