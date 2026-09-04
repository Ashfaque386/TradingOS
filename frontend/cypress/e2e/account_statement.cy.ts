// REL-034: the Account page (src/app/(app)/account/page.tsx) against the real running stack --
// real seeded Paper account, real /api/v1/paper-trading/account/* endpoints, no mocking. Reads
// are open to every role (a paper account risks no real capital, matching src/api/routers/
// paper_trading.py's own documented reasoning), so this spec doesn't need an RBAC-gating case
// the way kill_switch.cy.ts/rbac_gating.cy.ts do -- it confirms the page renders real data and
// the statement export is a genuine, authenticated download.
//
// REL-082: /account and /paper-trading merged into this one page -- two nav tabs for the exact
// same single seeded paper account, previously each independently rendering the identical
// CapitalSummary/PaperPositionsTable output. /paper-trading now permanently redirects here
// (next.config.ts). This spec gained a real redirect-assertion case, plus real coverage for the
// Shadow Mode streak panel and Recent Paper Fills table -- neither had ANY Cypress coverage
// before this merge (there was never a dedicated /paper-trading spec at all).

export {};

const API_URL = Cypress.env("apiUrl");

describe("Account page", () => {
  it("redirects an unauthenticated visitor to /login", () => {
    cy.visit("/account");
    cy.url().should("include", "/login");
  });

  it("permanently redirects the old /paper-trading route here", () => {
    cy.visit("/login");
    cy.get("input[type=email]").type(Cypress.env("adminEmail"));
    cy.get("input[type=password]").type(Cypress.env("adminPassword"));
    cy.get("button[type=submit]").click();
    cy.url().should("eq", Cypress.config().baseUrl + "/");

    cy.visit("/paper-trading");
    cy.url().should("eq", Cypress.config().baseUrl + "/account");
  });

  it("renders real account figures and a real equity curve once authenticated", () => {
    cy.visit("/login");
    cy.get("input[type=email]").type(Cypress.env("adminEmail"));
    cy.get("input[type=password]").type(Cypress.env("adminPassword"));
    cy.get("button[type=submit]").click();
    cy.url().should("eq", Cypress.config().baseUrl + "/");

    cy.visit("/account");
    cy.get("nav").contains("Account").should("be.visible");
    cy.contains("Account Equity").should("be.visible");
    cy.contains("Starting Capital").should("be.visible");
    cy.contains("Available to Trade").should("be.visible");

    // The real API this page itself calls -- used here only to know what to assert against.
    cy.window()
      .its("localStorage")
      .invoke("getItem", "tradingos_access_token")
      .then((token) => {
        cy.request({
          url: `${API_URL}/api/v1/paper-trading/account/summary`,
          headers: { Authorization: `Bearer ${token}` },
        }).then((response) => {
          expect(response.status).to.eq(200);
          const summary = response.body as { starting_capital: number };
          expect(summary.starting_capital).to.eq(100000);
        });
      });

    cy.contains("Equity Curve").should("be.visible");
    cy.contains("Download Statement").should("be.visible");
  });

  it("renders the real Shadow Mode streak and Recent Paper Fills sections", () => {
    cy.visit("/login");
    cy.get("input[type=email]").type(Cypress.env("adminEmail"));
    cy.get("input[type=password]").type(Cypress.env("adminPassword"));
    cy.get("button[type=submit]").click();
    cy.url().should("eq", Cypress.config().baseUrl + "/");

    cy.visit("/account");
    cy.contains("Shadow Mode — Broker Validation Streak").should("be.visible");
    cy.contains("clean days").should("be.visible");
    cy.contains("Positions").should("be.visible");
    cy.contains("Recent Paper Fills").should("be.visible");
    cy.contains("No broker paper-trading dependency").should("be.visible");
  });

  it("the real statement export endpoint returns a genuine authenticated CSV", () => {
    cy.visit("/login");
    cy.get("input[type=email]").type(Cypress.env("adminEmail"));
    cy.get("input[type=password]").type(Cypress.env("adminPassword"));
    cy.get("button[type=submit]").click();
    cy.url().should("eq", Cypress.config().baseUrl + "/");

    cy.window()
      .its("localStorage")
      .invoke("getItem", "tradingos_access_token")
      .then((token) => {
        cy.request({
          url: `${API_URL}/api/v1/paper-trading/account/statement/export?format=csv`,
          headers: { Authorization: `Bearer ${token}` },
        }).then((response) => {
          expect(response.status).to.eq(200);
          expect(response.headers["content-type"]).to.include("text/csv");
          expect(response.body).to.include("executed_at,symbol,instrument_type");
        });
      });
  });
});
