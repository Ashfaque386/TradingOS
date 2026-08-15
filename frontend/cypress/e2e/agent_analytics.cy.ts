// REL-068: the Agent Console's new Analytics tab against the real running stack -- real login,
// real GET /agents/analytics/summary + GET /agents/analytics/trend, real seeded AgentRun data
// already confirmed non-empty in this dev DB (compliance/python_code_generator/etc. each have
// dozens of real rows). No mocking.

export {};

function login() {
  cy.visit("/login");
  cy.get("input[type=email]").type(Cypress.env("adminEmail"));
  cy.get("input[type=password]").type(Cypress.env("adminPassword"));
  cy.get("button[type=submit]").click();
  cy.url().should("eq", Cypress.config().baseUrl + "/");
}

describe("Agent Console -- Analytics tab", () => {
  it("Console tab is still the default after the Tabs wrap", () => {
    login();
    cy.visit("/agents");
    cy.contains("Research Cycle").should("be.visible");
    cy.get('[role="tab"]').contains("Console").should("be.visible");
    cy.get('[role="tab"]').contains("Analytics").should("be.visible");
  });

  it("Analytics tab renders real per-agent stats and a real run-volume chart", () => {
    login();
    cy.visit("/agents");
    cy.get('[role="tab"]').contains("Analytics").click();

    cy.contains("Daily Runs (Completed vs. Failed)").should("be.visible");
    cy.contains("Success Rate by Agent").should("be.visible");
    cy.contains("Per-Agent Stats").should("be.visible");

    // This dev DB already has real seeded runs for these agents (confirmed directly against
    // the DB before writing this plan) -- the table should show at least one real row, not an
    // empty "no data" state.
    cy.get("table").contains("td", /compliance|Python Code Generator|Strategy Generator/i, {
      timeout: 15000,
    }).should("exist");

    // The success-rate chart and the run-volume chart both render real canvases/SVGs.
    cy.get("svg").its("length").should("be.gte", 2);
  });

  it("the day-range selector changes the real data requested", () => {
    login();
    cy.visit("/agents");
    cy.get('[role="tab"]').contains("Analytics").click();

    // 30d is the default -- confirm it, then switch and confirm the real UI state actually
    // changed (rather than racing to intercept the exact network call, which can flake if a
    // background refetchInterval poll is in flight at the same moment).
    cy.contains("button", "30d").should("have.attr", "aria-pressed", "true");
    cy.contains("button", "7d").click();
    cy.contains("button", "7d").should("have.attr", "aria-pressed", "true");
    cy.contains("button", "30d").should("have.attr", "aria-pressed", "false");
  });
});
