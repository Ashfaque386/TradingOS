// REL-009 E9.6 (TEST-008: "Critical paths (Kill Switch button...) require explicit interaction
// tests regardless of aggregate %"). Real role-gating test against the real running stack:
// a ReadOnlyAuditor genuinely cannot trigger the kill switch from the UI, matching the real
// client-side gate REL-004 built (KILL_SWITCH_ROLES, frontend/src/lib/auth.tsx) and the real
// server-side gate behind it (src/api/deps.py::require_role, enforced independently -- the UI
// gate only spares the wrong role a round trip, per kill-switch-button.tsx's own comment).
//
// Setup uses cy.request() directly against the real API (not the UI) to get into a known state
// first: log in as the real seeded SystemAdministrator, ensure the kill switch is armed (not
// left tripped by a previous run), and create a real, fresh ReadOnlyAuditor user via the real
// POST /users endpoint -- exactly the same real user-creation path an admin would use.

const API_URL = Cypress.env("apiUrl");

function loginViaApi(email: string, password: string) {
  return cy
    .request("POST", `${API_URL}/api/v1/auth/login`, { email, password })
    .its("body")
    .then((body) => {
      expect(body.mfa_required, "MFA is currently disabled project-wide, see this spec's header comment").to.eq(false);
      return body.access_token as string;
    });
}

describe("Kill switch role gating", () => {
  let auditorEmail: string;
  const auditorPassword = "cy-test-password-123";

  before(() => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((adminToken) => {
      // Ensure armed (not left TRIPPED by a prior manual test run) before this spec's own checks.
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/system/kill-switch/reset`,
        headers: { Authorization: `Bearer ${adminToken}` },
        body: { confirmation: true },
        failOnStatusCode: false, // 400 if it was already armed -- not an error for this setup step
      });

      auditorEmail = `cy-auditor-${Date.now()}@example.invalid`;
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/users`,
        headers: { Authorization: `Bearer ${adminToken}` },
        body: { email: auditorEmail, password: auditorPassword, role: "ReadOnlyAuditor" },
      });
    });
  });

  it("SystemAdministrator sees a real, interactive (non-locked) slider", () => {
    cy.visit("/login");
    cy.get("input[type=email]").type(Cypress.env("adminEmail"));
    cy.get("input[type=password]").type(Cypress.env("adminPassword"));
    cy.get("button[type=submit]").click();
    cy.url().should("eq", Cypress.config().baseUrl + "/");

    cy.get("[data-testid=kill-switch-armed-panel]").should("be.visible");
    cy.contains("Slide to confirm").should("be.visible");
    cy.contains("Insufficient role").should("not.exist");
  });

  it("ReadOnlyAuditor sees the kill switch locked, real drag does not trip it", () => {
    cy.visit("/login");
    cy.get("input[type=email]").type(auditorEmail);
    cy.get("input[type=password]").type(auditorPassword);
    cy.get("button[type=submit]").click();
    cy.url().should("eq", Cypress.config().baseUrl + "/");

    cy.get("[data-testid=kill-switch-armed-panel]").should("be.visible");
    cy.contains("Insufficient role").should("be.visible");

    // A real drag attempt on the locked slider -- framer-motion's `drag={false}` means this
    // dispatches no drag events the component listens to, so nothing should change.
    cy.get("[data-testid=kill-switch-slider]").trigger("mousedown", { force: true });
    cy.get("[data-testid=kill-switch-track]").trigger("mousemove", { clientX: 300, force: true });
    cy.get("[data-testid=kill-switch-slider]").trigger("mouseup", { force: true });
    cy.contains("Insufficient role").should("be.visible");

    // The real, independent server-side gate: even a forged direct API call from this role 403s.
    loginViaApi(auditorEmail, auditorPassword).then((auditorToken) => {
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/system/kill-switch`,
        headers: { Authorization: `Bearer ${auditorToken}` },
        body: { reason: "cypress attempted bypass" },
        failOnStatusCode: false,
      }).its("status").should("eq", 403);
    });
  });
});
