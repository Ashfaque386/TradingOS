// US5 (spec 001-ceo-led-trading-org, quickstart Scenario 5, SC-007/008/009): the Organization
// Command Center renders real backend state, live, with no fabricated status strings.

export {};

const API_URL = Cypress.env("apiUrl");

function login() {
  cy.visit("/login");
  cy.get("input[type=email]").type(Cypress.env("adminEmail"));
  cy.get("input[type=password]").type(Cypress.env("adminPassword"));
  cy.get("button[type=submit]").click();
  cy.url().should("eq", Cypress.config().baseUrl + "/");
}

function token() {
  return cy.window().its("localStorage").invoke("getItem", "tradingos_access_token");
}

describe("Organization Command Center", () => {
  it("redirects an unauthenticated visitor to /login", () => {
    cy.visit("/console");
    cy.url().should("include", "/login");
  });

  it("shows the nav entry and the live command centre home", () => {
    login();
    cy.get("nav").contains("Organization").click();
    cy.url().should("include", "/console");
    cy.contains("Organization Command Center").should("be.visible");
    cy.contains("Organisation status").should("be.visible");
    cy.contains("Approvals").should("be.visible");
    cy.contains("Attention").should("be.visible");
  });

  it("run counts on the home match the backend records", () => {
    login();
    token().then((t) => {
      cy.request({
        url: `${API_URL}/api/v1/organization/runs`,
        headers: { Authorization: `Bearer ${t}` },
      }).then((res) => {
        expect(res.status).to.eq(200);
        const runs = res.body as Array<{ run_id: string; status: string }>;
        cy.visit("/console");
        if (runs.length === 0) {
          cy.contains("No organisation runs yet.").should("be.visible");
        } else {
          const active = runs.filter((r) =>
            ["planning", "running", "waiting", "stalled", "queued"].includes(r.status),
          ).length;
          cy.contains(`${active} active`).should("be.visible");
          // Opening the newest run's workspace renders its real task graph + activity stream.
          cy.get('a[href^="/console/runs/"]').first().click();
          cy.contains("Task graph").should("be.visible");
          cy.contains("Activity stream").should("be.visible");
        }
      });
    });
  });

  it("the built console bundle contains no hard-coded run/task status literal", () => {
    // SC (FR-089): the console derives every status from backend state. A grep of the shipped
    // source for an *assigned* status literal in the console tree must find nothing.
    cy.exec(
      "grep -rnE '([Ss]tatus[[:space:]]*[:=][[:space:]]*|useState\\([[:space:]]*)\"(Running|Idle|Waiting|Blocked|Failed|Completed|Planning|Stalled)\"' " +
        "src/components/console src/hooks/useOrganizationStream.ts src/app/'(app)'/console || true",
      { failOnNonZeroExit: false },
    ).then((r) => {
      expect(r.stdout.trim(), "no fabricated status literal in the console source").to.eq("");
    });
  });
});
