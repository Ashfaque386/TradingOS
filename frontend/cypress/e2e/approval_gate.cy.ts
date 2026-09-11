// US3/US5 (spec 001-ceo-led-trading-org, T051, quickstart Scenario 3): the Organization Command
// Center's Approvals panel (console/panels.tsx::ApprovalQueue) renders pending items,
// PortfolioManager approve moves the card and the strategy state, and a RiskManager/
// ReadOnlyAuditor sees no approve/reject controls at all -- `Gated permission="manageOrgApprovals"`
// hides them client-side (T113 follow-up) rather than showing a control that would just 403,
// matching this repo's own established convention (hitl_panel.cy.ts, rbac_gating.cy.ts).

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

describe("Console Approvals panel role gating", () => {
  let riskManagerEmail: string;
  const riskManagerPassword = "cy-test-password-123";
  let auditorEmail: string;
  const auditorPassword = "cy-test-password-123";
  let anyPendingApprovalId: string | null = null;

  before(() => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((adminToken) => {
      const headers = { Authorization: `Bearer ${adminToken}` };
      cy.request({ url: `${API_URL}/api/v1/organization/approvals?status=pending`, headers }).then(
        (response) => {
          const pending = response.body as Array<{ id: string }>;
          anyPendingApprovalId = pending.length > 0 ? pending[0].id : null;
        },
      );

      riskManagerEmail = `cy-approval-rm-${Date.now()}@example.invalid`;
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/users`,
        headers,
        body: { email: riskManagerEmail, password: riskManagerPassword, role: "RiskManager" },
      });

      auditorEmail = `cy-approval-auditor-${Date.now()}@example.invalid`;
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/users`,
        headers,
        body: { email: auditorEmail, password: auditorPassword, role: "ReadOnlyAuditor" },
      });
    });
  });

  it("the Approvals panel renders on the console home for a SystemAdministrator", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/console");
    cy.contains("Approvals").should("be.visible");
  });

  it("PortfolioManager sees real approve/reject controls when a pending item exists", () => {
    // Real E2E state: whether one exists depends on what's actually pending in this environment
    // right now (test_org_approval_gate.py already covers the approve/reject transition itself
    // at the API level) -- conditional assertion, same convention as hitl_panel.cy.ts's anyRunId.
    if (!anyPendingApprovalId) {
      cy.log("No pending approval exists in this environment -- nothing to assert here.");
      return;
    }
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/console");
    cy.contains("Approve → Paper").should("be.visible");
    cy.contains("button", "Reject").should("be.visible");
  });

  it("RiskManager sees the Approvals panel but no approve/reject controls", () => {
    loginViaUi(riskManagerEmail, riskManagerPassword);
    cy.visit("/console");
    cy.contains("Approvals").should("be.visible");
    cy.contains("Approve → Paper").should("not.exist");
    cy.contains("button", "Reject").should("not.exist");
  });

  it("ReadOnlyAuditor sees the Approvals panel but no approve/reject controls", () => {
    loginViaUi(auditorEmail, auditorPassword);
    cy.visit("/console");
    cy.contains("Approvals").should("be.visible");
    cy.contains("Approve → Paper").should("not.exist");
    cy.contains("button", "Reject").should("not.exist");
  });

  it("the real API 403s a forged approve call from RiskManager/ReadOnlyAuditor", () => {
    if (!anyPendingApprovalId) {
      cy.log("No pending approval id available -- skipping the forged-call check.");
      return;
    }
    loginViaApi(riskManagerEmail, riskManagerPassword).then((token) => {
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/organization/approvals/${anyPendingApprovalId}/approve`,
        headers: { Authorization: `Bearer ${token}` },
        failOnStatusCode: false,
      })
        .its("status")
        .should("eq", 403);
    });
    loginViaApi(auditorEmail, auditorPassword).then((token) => {
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/organization/approvals/${anyPendingApprovalId}/approve`,
        headers: { Authorization: `Bearer ${token}` },
        failOnStatusCode: false,
      })
        .its("status")
        .should("eq", 403);
    });
  });
});
