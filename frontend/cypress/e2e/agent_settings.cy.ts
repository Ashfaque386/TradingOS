// US6 (spec 001-ceo-led-trading-org, quickstart Scenario 6): the per-agent Settings area --
// prompt version history + diff + activate, provider/model pickers limited to configured
// options, a real test panel, and no picker for a deterministic agent.

export {};

const API_URL = Cypress.env("apiUrl");

function login() {
  cy.visit("/login");
  cy.get("input[type=email]").type(Cypress.env("adminEmail"));
  cy.get("input[type=password]").type(Cypress.env("adminPassword"));
  cy.get("button[type=submit]").click();
  cy.url().should("eq", Cypress.config().baseUrl + "/");
}

describe("Agent Settings", () => {
  it("lists agents from the Settings page and opens one", () => {
    login();
    cy.visit("/settings");
    cy.contains("Agent Settings").should("be.visible");
    cy.contains("a", "market_analyst_agent").click();
    cy.url().should("include", "/settings/agents/market_analyst_agent");
    cy.contains("Effective configuration").should("be.visible");
    cy.contains("Version history").should("be.visible");
  });

  it("prompt history shows the seeded active version and a diff control", () => {
    login();
    cy.visit("/settings/agents/strategy_generator_agent");
    // strategy_generator_agent has v1 + v2 seeded (v2 active per registry.yaml).
    cy.contains("v2").should("be.visible");
    cy.contains("active").should("be.visible");
    cy.get("button").contains("diff L").should("exist");
  });

  it("the provider picker only offers configured providers", () => {
    login();
    cy.window()
      .its("localStorage")
      .invoke("getItem", "tradingos_access_token")
      .then((token) => {
        cy.request({
          url: `${API_URL}/api/v1/providers`,
          headers: { Authorization: `Bearer ${token}` },
        }).then((res) => {
          const configured = (res.body as Array<{ provider: string }>).map((p) => p.provider);
          cy.visit("/settings/agents/market_analyst_agent");
          cy.contains("label", "CUSTOM").find("input").click();
          cy.get("select").eq(1).find("option").then((opts) => {
            const shown = [...opts].map((o) => o.value).filter(Boolean);
            shown.forEach((p) => expect(configured).to.include(p));
          });
        });
      });
  });

  it("a deterministic agent shows no model picker", () => {
    login();
    cy.visit("/settings/agents/python_validator_agent");
    cy.contains("deterministic").should("be.visible");
    cy.contains("there is no model to configure").should("exist");
    cy.contains("label", "CUSTOM").should("not.exist");
  });

  it("spec 002 US9/C-4: activation is gated behind actually viewing the diff, and requires a second confirm", () => {
    login();
    cy.visit("/settings/agents/strategy_generator_agent");
    // v1 is seeded inactive, v2 is the seeded active version (per the test above).
    cy.contains("li", "v1").within(() => {
      cy.contains("button", "Activate").should("be.disabled");
    });
    // Opening the diff for both v1 and v2 is what unlocks activation for either.
    cy.contains("li", "v1").within(() => cy.contains("button", "diff L").click());
    cy.contains("li", "v2").within(() => cy.contains("button", "diff R").click());
    cy.contains("v1 → v2").should("be.visible");
    // Activation still requires a second explicit confirm click, not a single click.
    cy.contains("li", "v1").within(() => {
      cy.contains("button", "Activate").should("not.be.disabled").click();
      cy.contains("Activate v1?").should("be.visible");
      cy.contains("button", "Confirm").click();
    });
    cy.contains("li", "v1").within(() => cy.contains("active").should("be.visible"));
    // Restore the original active version (v2 was already diffed above, so this is unlocked too).
    cy.contains("li", "v2").within(() => {
      cy.contains("button", "Activate").should("not.be.disabled").click();
      cy.contains("button", "Confirm").click();
    });
    cy.contains("li", "v2").within(() => cy.contains("active").should("be.visible"));
  });
});
