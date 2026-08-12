// REL-036: the global Paper/Live/Both account-scope selector (TopNav) against the real running
// stack -- confirms the dashboard's Paper and Live sections toggle correctly, the selection
// persists across a reload (localStorage), and the Orders page's unified history card renders
// under every scope. No mocking -- real login, real API responses (whatever the real seeded
// Paper account and real/absent broker connection currently return).

export {};

function login() {
  cy.visit("/login");
  cy.get("input[type=email]").type(Cypress.env("adminEmail"));
  cy.get("input[type=password]").type(Cypress.env("adminPassword"));
  cy.get("button[type=submit]").click();
  cy.url().should("eq", Cypress.config().baseUrl + "/");
}

describe("Account scope selector", () => {
  it("defaults to Both, showing both the Paper and Live sections tagged", () => {
    login();
    cy.get('[aria-label="Account scope"]').should("be.visible");
    cy.contains("Live Account").should("be.visible");
    cy.contains("Paper Account").should("be.visible");
    cy.contains("Total P&L").should("be.visible");
    cy.contains("Account Equity").should("be.visible");
  });

  it("Paper scope hides the Live section and shows only the Paper account block", () => {
    login();
    cy.get('[aria-label="Account scope"]').contains("Paper").click();
    cy.contains("Total P&L").should("not.exist");
    cy.contains("Account Equity").should("be.visible");
  });

  it("Live scope hides the Paper section and shows only the Live account block", () => {
    login();
    cy.get('[aria-label="Account scope"]').contains("Live").click();
    cy.contains("Account Equity").should("not.exist");
    cy.contains("Total P&L").should("be.visible");
  });

  it("persists the selected scope across a reload", () => {
    login();
    cy.get('[aria-label="Account scope"]').contains("Paper").click();
    cy.contains("Total P&L").should("not.exist");
    cy.reload();
    cy.contains("Account Equity").should("be.visible");
    cy.contains("Total P&L").should("not.exist");
    // Reset to Both so later specs in the same browser session see the default.
    cy.get('[aria-label="Account scope"]').contains("Both").click();
  });

  it("Orders page renders the unified Order & Trade History card under every scope", () => {
    // Scoped to <main> throughout -- the page's own usePageStatus subtitle also contains the
    // literal string "Order & Trade History" (it lives in TopNav's fixed-position status line,
    // <header>, not <main>), so an unscoped cy.contains matches both and can pick the covered,
    // non-visible one. Same trap class already found and fixed in audit_view.cy.ts/
    // agent_runs.cy.ts (REL-033) -- scoping to a container that excludes TopNav is the
    // established fix.
    login();
    cy.visit("/orders");
    cy.get("main").contains("Order & Trade History").should("be.visible");

    cy.get('[aria-label="Account scope"]').contains("Paper").click();
    cy.get("main").contains("Order & Trade History").should("be.visible");
    cy.get("main").contains("Local Engine Ledger").should("not.exist");

    cy.get('[aria-label="Account scope"]').contains("Live").click();
    cy.get("main").contains("Order & Trade History").should("be.visible");
    cy.get("main").contains("Local Engine Ledger").should("be.visible");

    cy.get('[aria-label="Account scope"]').contains("Both").click();
  });
});
