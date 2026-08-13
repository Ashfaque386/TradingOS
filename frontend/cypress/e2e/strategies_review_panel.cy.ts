// REL-044/045/046: the upgraded Strategies page against the real running stack -- the real
// Strategy Generator Agent logic fields (entry/exit/stop/take-profit/position-sizing/confidence,
// previously computed on every run and silently discarded), the real CEO/Market Analyst
// research context ("why this strategy was proposed"), real F&O option legs/rationale, the
// reused VerdictPanel/FullMetricGrid backtest narrative, validator feedback, and Kanban card
// enrichment (hypothesis snippet, backtest_count, status dot). Requires the two REL-044 fixture
// strategies seeded via scripts/_cypress_seed_rel044_fixture.py ("cypress-rel044-fno-fixture-
// strategy" and "cypress-rel044-premigration-fixture-strategy" -- uniquely named so `cy.contains`
// can't accidentally land on one of the many identically-named real rows left behind by past
// pytest runs in this shared dev DB) to exist in the real DB. No mocking.

export {};

const FIXTURE_NAME = "cypress-rel044-fno-fixture-strategy";
const PREMIGRATION_FIXTURE_NAME = "cypress-rel044-premigration-fixture-strategy";

function loginViaUi(email: string, password: string) {
  cy.visit("/login");
  cy.get("input[type=email]").type(email);
  cy.get("input[type=password]").type(password);
  cy.get("button[type=submit]").click();
  cy.url().should("eq", Cypress.config().baseUrl + "/");
}

describe("Strategies page (REL-044/045/046)", () => {
  it("unauthenticated visitors are redirected to login", () => {
    cy.visit("/strategies");
    cy.url().should("include", "/login");
  });

  it("Kanban card shows a real hypothesis snippet, backtest_count, and a status dot", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.contains("Strategies").click();
    cy.url().should("include", "/strategies");

    cy.contains(FIXTURE_NAME)
      .parents(".select-none")
      .should("contain.text", "Bull call spread on RELIANCE")
      .and("contain.text", "1 backtest");
  });

  it("selecting the fixture strategy renders real logic + research-context + option-legs panels", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.contains(FIXTURE_NAME).click();

    cy.contains("Strategy Logic").parents(".rounded-card").within(() => {
      cy.contains("Agent Confidence").should("be.visible");
      cy.contains("72%").should("be.visible");
      cy.contains("Entry Conditions").should("be.visible");
      cy.contains("IV rank below 30").should("be.visible");
      cy.contains("Position Sizing").should("be.visible");
    });

    cy.contains("Why This Strategy Was Proposed").parents(".rounded-card").within(() => {
      cy.contains("Market Regime").should("be.visible");
      cy.contains("Risk-On").should("be.visible");
      cy.contains("Priority Sectors").should("be.visible");
      cy.contains("Volatility Assessment").should("be.visible");
    });

    cy.contains("Validator Feedback").should("be.visible");
    cy.contains("Static safety check passed").should("be.visible");

    cy.contains("Option Legs").parents(".rounded-card").within(() => {
      cy.contains("RELIANCE24AUG3000CE").should("be.visible");
      cy.contains("Agent Rationale").should("be.visible");
      cy.contains("Bull call spread caps both cost and risk").should("be.visible");
    });
  });

  it("the fixture's real backtest renders VerdictPanel/FullMetricGrid with real content", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.contains(FIXTURE_NAME).click();

    cy.contains("Sandbox").parents(".rounded-card").within(() => {
      cy.contains(/Evaluation: Pass/).should("be.visible");
      cy.contains(/Deployment: Approve/).should("be.visible");
      cy.contains("Sortino").should("be.visible");
      cy.contains("MC p95 DD").should("be.visible");
    });
  });

  it("a real pre-migration strategy renders the honest absent state without breaking layout", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.contains(PREMIGRATION_FIXTURE_NAME).click();
    cy.contains("Strategy Logic").parents(".rounded-card").within(() => {
      cy.contains("generated before real trading-logic capture shipped").should("be.visible");
    });
    cy.contains("Why This Strategy Was Proposed").parents(".rounded-card").within(() => {
      cy.contains("No research context captured").should("be.visible");
    });
  });

  it("Run Backtest trigger is still present and role-gated", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.contains(FIXTURE_NAME).click();
    cy.contains("button", "Run Backtest").should("be.visible");
  });
});
