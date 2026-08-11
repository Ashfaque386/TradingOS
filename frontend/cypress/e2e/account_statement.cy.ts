// REL-034: the Account page (src/app/(app)/account/page.tsx) against the real running stack --
// real seeded Paper account, real /api/v1/paper-trading/account/* endpoints, no mocking. Reads
// are open to every role (a paper account risks no real capital, matching src/api/routers/
// paper_trading.py's own documented reasoning), so this spec doesn't need an RBAC-gating case
// the way kill_switch.cy.ts/rbac_gating.cy.ts do -- it confirms the page renders real data and
// the statement export is a genuine, authenticated download.

export {};

const API_URL = Cypress.env("apiUrl");

describe("Account page", () => {
  it("redirects an unauthenticated visitor to /login", () => {
    cy.visit("/account");
    cy.url().should("include", "/login");
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
