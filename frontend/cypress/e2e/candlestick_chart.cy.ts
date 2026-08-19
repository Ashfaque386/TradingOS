// REL-011 E11.1: the Portfolio Command Center's candlestick chart renders real seeded OHLCV bars
// (GET /market/ohlcv/{symbol}, REL-010 E10.8a) via TradingView Lightweight Charts, and its
// symbol selector reflects the real, actually-ingested symbol universe (GET /market/symbols) --
// not a hardcoded/fabricated list. Against the real running stack, no mocking.
//
// REL-076: the plain <select> symbol picker was replaced by SymbolCombobox, a debounced
// search-and-select input over the full 2,776-row real NSE/BSE instrument universe (GET
// /market/instruments/search), with on-demand real ingestion (POST /market/ingest/trigger) for
// any real instrument not yet in the local data lake. These specs cover the combobox rendering
// real search results, an already-cached symbol selecting instantly, and a real not-yet-cached
// symbol going through a real fetching state to completion.

export {};

const API_URL = Cypress.env("apiUrl");

function loginViaApi(email: string, password: string) {
  return cy
    .request("POST", `${API_URL}/api/v1/auth/login`, { email, password })
    .its("body")
    .then((body) => body.access_token as string);
}

function loginViaUi(email: string, password: string) {
  cy.visit("/login");
  cy.get("input[type=email]").type(email);
  cy.get("input[type=password]").type(password);
  cy.get("button[type=submit]").click();
  cy.url().should("eq", Cypress.config().baseUrl + "/");
}

const symbolSearchInput = () => cy.get('input[aria-label="Search symbol or name"]').first();

/** Finds a real, currently-uncached NSE equity to exercise the on-demand ingest path -- picked
 * dynamically (not hardcoded) so the check keeps working on every rerun even after a prior run
 * has already ingested whichever symbol it used, exactly like the equivalent backend test's own
 * `WIPRO`-selection rationale in test_market_data_router.py. */
function findAnUncachedRealEquitySymbol(token: string) {
  return cy
    .request({
      url: `${API_URL}/api/v1/market/symbols`,
      headers: { Authorization: `Bearer ${token}` },
    })
    .then((symbolsRes) => {
      const cached = new Set(symbolsRes.body as string[]);
      return cy
        .request({
          url: `${API_URL}/api/v1/market/instruments/search?q=A&instrument_type=EQ&page_size=100`,
          headers: { Authorization: `Bearer ${token}` },
        })
        .then((searchRes) => {
          const items = searchRes.body.items as { symbol: string }[];
          const candidate = items.find((i) => !cached.has(i.symbol));
          expect(candidate, "a real EQ instrument not already in the data lake").to.exist;
          return candidate!.symbol;
        });
    });
}

describe("Candlestick chart", () => {
  it("renders with the real symbol universe and a live WS connection indicator", () => {
    cy.request(`${API_URL}/api/v1/market/symbols`).then((response) => {
      expect(response.status).to.eq(200);
      const realSymbols = response.body as string[];

      loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));

      cy.contains("Candlestick Chart").should("be.visible");

      if (realSymbols.length > 0) {
        // The combobox defaults to the first real symbol, not a placeholder.
        symbolSearchInput().should("have.value", realSymbols[0]);

        // The chart container mounts a real canvas-based chart (lightweight-charts), not a
        // placeholder <div> -- it renders several layered canvases internally.
        cy.get("canvas").its("length").should("be.gte", 1);
      } else {
        cy.log("No symbols ingested into the EOD lake yet -- nothing to assert about chart data.");
      }

      cy.contains(/Live|Reconnecting…/).should("be.visible");
    });
  });

  it("searching the combobox surfaces real matching instruments, not a fabricated list", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((token) => {
      cy.request({
        url: `${API_URL}/api/v1/market/instruments/search?q=A&instrument_type=EQ&page_size=1`,
        headers: { Authorization: `Bearer ${token}` },
      }).then((searchRes) => {
        const real = (searchRes.body.items as { symbol: string; name: string }[])[0];

        loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
        cy.contains("Candlestick Chart").should("be.visible");

        symbolSearchInput().focus().clear().type(real.symbol);
        cy.contains(real.symbol).should("be.visible");
        cy.contains(real.name).should("be.visible");
      });
    });
  });

  it("selecting an already-cached symbol switches instantly, with no fetching state", () => {
    cy.request(`${API_URL}/api/v1/market/symbols`).then((response) => {
      const realSymbols = response.body as string[];
      if (realSymbols.length < 2) {
        cy.log("Fewer than 2 cached symbols exist -- skipping instant-switch check.");
        return;
      }
      const target = realSymbols[1];

      loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
      cy.contains("Candlestick Chart").should("be.visible");

      symbolSearchInput().focus().clear().type(target);
      // Scoped to the symbol span specifically, not the row's name/exchange line -- several real
      // NSE company names can contain another real symbol's own text as a substring (e.g. several
      // "Reliance ..." companies), so a plain cy.contains(target) can click the wrong row.
      cy.contains("span.font-medium", target).should("be.visible").click();
      symbolSearchInput().should("have.value", target);
      cy.contains("Fetching real data").should("not.exist");
      cy.contains(/Live|Reconnecting…/).should("be.visible");
    });
  });

  it("selecting a real not-yet-cached symbol shows a real fetching state and completes with live data", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((token) => {
      findAnUncachedRealEquitySymbol(token).then((symbol) => {
        loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
        cy.contains("Candlestick Chart").should("be.visible");

        symbolSearchInput().focus().clear().type(symbol);
        cy.contains("span.font-medium", symbol).should("be.visible").click();

        cy.contains(`Fetching real data for ${symbol}…`, { timeout: 15_000 }).should("be.visible");
        // Real Upstox V3/yfinance ingestion of ~2 years of daily bars for one symbol -- generous
        // timeout to match useEnsureSymbolIngested's own 120s poll deadline.
        cy.contains(`Fetching real data for ${symbol}…`, { timeout: 130_000 }).should("not.exist");
        symbolSearchInput().should("have.value", symbol);
        cy.contains(/Live|Reconnecting…/).should("be.visible");

        // Now instantly available to any other consumer of GET /market/symbols too, with no
        // second fetch required.
        cy.request({
          url: `${API_URL}/api/v1/market/symbols`,
          headers: { Authorization: `Bearer ${token}` },
        }).then((res) => {
          expect(res.body as string[]).to.include(symbol);
        });
      });
    });
  });
});
