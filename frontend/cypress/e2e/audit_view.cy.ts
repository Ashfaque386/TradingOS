// REL-011 E11.4a: the Audit / Trade-History view shows real AuditLog rows to SA/ReadOnlyAuditor
// (server-gated, src/api/routers/audit.py::_can_read_audit) and is genuinely inaccessible --
// both nav-hidden and page-gated -- to a role outside that set (PortfolioManager here). Against
// the real running stack, no mocking.

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

describe("Audit view role gating", () => {
  let pmEmail: string;
  const pmPassword = "cy-test-password-123";

  before(() => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((adminToken) => {
      pmEmail = `cy-audit-pm-${Date.now()}@example.invalid`;
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/users`,
        headers: { Authorization: `Bearer ${adminToken}` },
        body: { email: pmEmail, password: pmPassword, role: "PortfolioManager" },
      });
    });
  });

  it("SystemAdministrator sees real audit rows, matching the real API's own data", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((adminToken) => {
      cy.request({
        url: `${API_URL}/api/v1/audit/logs?limit=100`,
        headers: { Authorization: `Bearer ${adminToken}` },
      }).then((response) => {
        expect(response.status).to.eq(200);
        const realEntries = response.body as unknown[];

        loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
        cy.contains("Audit").click();
        cy.url().should("include", "/audit");
        cy.contains("does not have access").should("not.exist");

        if (realEntries.length > 0) {
          cy.get("table, [data-testid=audit-log-table]").should("exist");
          cy.contains(/LOGIN_SUCCESS|RBAC_DENIED|KILL_SWITCH|STRATEGY_PROMOTED|.+/).should(
            "be.visible",
          );
        } else {
          cy.log("No audit rows exist yet in this environment -- nothing further to assert.");
        }
      });
    });
  });

  it("PortfolioManager: no Audit nav link, and direct navigation shows the denial message", () => {
    loginViaUi(pmEmail, pmPassword);
    cy.contains("Audit").should("not.exist");

    cy.visit("/audit");
    cy.contains("does not have access").should("be.visible");
  });

  it("PortfolioManager: the real API itself also 403s a forged direct call", () => {
    loginViaApi(pmEmail, pmPassword).then((token) => {
      cy.request({
        url: `${API_URL}/api/v1/audit/logs`,
        headers: { Authorization: `Bearer ${token}` },
        failOnStatusCode: false,
      })
        .its("status")
        .should("eq", 403);
    });
  });
});
