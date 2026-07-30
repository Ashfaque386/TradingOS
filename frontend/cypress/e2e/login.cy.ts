// REL-009 E9.6: real login flow against the real running stack (frontend + app + postgres).
// MFA is currently administratively disabled project-wide (REL-007's MFA_MANDATORY_ROLES =
// frozenset(), per explicit user request) -- so a correct SystemAdministrator login goes
// straight through to a real session, matching this test's expectations. If MFA enforcement is
// ever re-enabled, this spec's "signs in and reaches the dashboard" case will start hitting the
// enroll/verify steps instead and will need updating alongside that change.

describe("Login", () => {
  it("shows an error for incorrect credentials, without revealing which field was wrong", () => {
    cy.visit("/login");
    cy.get("input[type=email]").type("nobody@example.invalid");
    cy.get("input[type=password]").type("wrong-password");
    cy.get("button[type=submit]").click();
    cy.contains("Incorrect email or password.").should("be.visible");
  });

  it("signs in with real admin credentials and reaches the dashboard", () => {
    cy.visit("/login");
    cy.get("input[type=email]").type(Cypress.env("adminEmail"));
    cy.get("input[type=password]").type(Cypress.env("adminPassword"));
    cy.get("button[type=submit]").click();

    cy.url().should("eq", Cypress.config().baseUrl + "/");
    // A real authenticated request the dashboard makes on load -- proves the session is real,
    // not just that the URL changed.
    cy.window()
      .its("localStorage")
      .invoke("getItem", "tradingos_access_token")
      .should("be.a", "string").and("have.length.greaterThan", 10);
  });
});
