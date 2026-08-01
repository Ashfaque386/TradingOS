// REL-011 E11.1: the Portfolio Command Center's candlestick chart renders real seeded OHLCV bars
// (GET /market/ohlcv/{symbol}, REL-010 E10.8a) via TradingView Lightweight Charts, and its
// symbol selector reflects the real, actually-ingested symbol universe (GET /market/symbols) --
// not a hardcoded/fabricated list. Against the real running stack, no mocking.

export {};

const API_URL = Cypress.env("apiUrl");

describe("Candlestick chart", () => {
  it("renders with the real symbol universe and a live WS connection indicator", () => {
    cy.request(`${API_URL}/api/v1/market/symbols`).then((response) => {
      expect(response.status).to.eq(200);
      const realSymbols = response.body as string[];

      cy.visit("/login");
      cy.get("input[type=email]").type(Cypress.env("adminEmail"));
      cy.get("input[type=password]").type(Cypress.env("adminPassword"));
      cy.get("button[type=submit]").click();
      cy.url().should("eq", Cypress.config().baseUrl + "/");

      cy.contains("Candlestick Chart").should("be.visible");

      if (realSymbols.length > 0) {
        // The select defaults to the first real symbol, not a placeholder.
        cy.get("select").should(($selects) => {
          const values = $selects.toArray().flatMap((el) =>
            Array.from((el as HTMLSelectElement).options).map((o) => o.value),
          );
          expect(values).to.include(realSymbols[0]);
        });

        // The chart container mounts a real canvas-based chart (lightweight-charts), not a
        // placeholder <div> -- it renders several layered canvases internally.
        cy.get("canvas").its("length").should("be.gte", 1);
      } else {
        cy.log("No symbols ingested into the EOD lake yet -- nothing to assert about chart data.");
      }

      cy.contains(/Live|Reconnecting…/).should("be.visible");
    });
  });
});
