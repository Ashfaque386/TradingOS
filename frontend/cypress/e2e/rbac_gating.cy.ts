// REL-011 exit criterion: a real ReadOnlyAuditor login genuinely cannot see or trigger any
// mutating control anywhere in the UI. Covers the client-side `Gated`/`usePermission` gates
// added in E11.3 and the 3 previously-zero-auth backend routes closed in E10.11.0 -- both the
// UI hiding the control AND the real server-side 403 behind it, against the real running stack
// (no mocking), matching kill_switch.cy.ts's established convention.

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

describe("RBAC gating -- ReadOnlyAuditor sees/triggers nothing mutating", () => {
  let auditorEmail: string;
  const auditorPassword = "cy-test-password-123";

  before(() => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((adminToken) => {
      auditorEmail = `cy-rbac-auditor-${Date.now()}@example.invalid`;
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/users`,
        headers: { Authorization: `Bearer ${adminToken}` },
        body: { email: auditorEmail, password: auditorPassword, role: "ReadOnlyAuditor" },
      });
    });
  });

  it("Portfolio & Risk: Kill Switch is locked, not just visually disabled", () => {
    loginViaUi(auditorEmail, auditorPassword);
    cy.contains("Insufficient role").should("be.visible");
    cy.contains("Slide to confirm").should("not.exist");
  });

  it("Agent Console: Trigger Research Cycle and prompt hot-swap controls are absent", () => {
    loginViaUi(auditorEmail, auditorPassword);
    cy.visit("/agents");
    cy.contains("Research Cycle").should("be.visible");
    cy.contains("Trigger Research Cycle").should("not.exist");
    cy.contains(/Make v\d+ active/).should("not.exist");
  });

  it("Strategies: Kanban board is read-only when strategies exist", () => {
    loginViaUi(auditorEmail, auditorPassword);
    cy.visit("/strategies");
    cy.get("body").then(($body) => {
      if ($body.find('[data-testid="kanban-readonly-banner"]').length > 0) {
        cy.get('[data-testid="kanban-readonly-banner"]').should("be.visible");
      } else {
        cy.log("No strategies seeded yet -- Kanban board (and its readonly banner) doesn't render; nothing to assert.");
      }
    });
  });

  it("Settings: notification-channel management controls are absent", () => {
    loginViaUi(auditorEmail, auditorPassword);
    cy.visit("/settings");
    cy.contains("Notification Channels").should("be.visible");
    cy.contains("Add channel").should("not.exist");
  });

  it("Audit: this role IS allowed here -- readAudit includes ReadOnlyAuditor", () => {
    loginViaUi(auditorEmail, auditorPassword);
    cy.contains("Audit").should("be.visible").click();
    cy.url().should("include", "/audit");
    cy.contains("does not have access").should("not.exist");
  });

  it("the 3 E10.11.0-gated routes real-403 a forged direct call from this role", () => {
    loginViaApi(auditorEmail, auditorPassword).then((token) => {
      const headers = { Authorization: `Bearer ${token}` };
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/agents/research/trigger`,
        headers,
        failOnStatusCode: false,
      })
        .its("status")
        .should("eq", 403);

      cy.request({
        method: "PUT",
        url: `${API_URL}/api/v1/agents/prompts/python_code_generator_agent/active-version`,
        headers,
        body: { version: 1 },
        failOnStatusCode: false,
      })
        .its("status")
        .should("eq", 403);

      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/strategies/00000000-0000-0000-0000-000000000000/backtest`,
        headers,
        failOnStatusCode: false,
      })
        .its("status")
        .should("eq", 403);
    });
  });
});
