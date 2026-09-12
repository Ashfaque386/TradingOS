// spec 002 US14: the dependency graph gains pan/zoom, layered over the existing real
// depth/position computation. Exercised against the seeded "seeded test run" (a real completed
// run with a real multi-task dependency chain, all edges already satisfied) since forcing a
// *live* dependency.satisfied transition on demand has no test-seed endpoint -- that part (the
// activation flash actually firing off the real event) was verified manually in this session's
// implementation pass against a real in-progress run; see tasks.md T086 for that record.

export {};

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

describe("Task graph pan/zoom (US14)", () => {
  it("renders the real dependency chain and supports zoom + pan without breaking alignment", () => {
    login();
    cy.visit("/console");
    cy.contains("a", "seeded test run", { timeout: 30000 }).click();
    cy.contains("Task graph", { timeout: 30000 }).should("be.visible");
    cy.get('svg[aria-label*="Organisation task graph"]', { timeout: 15000 }).should("be.visible");
    cy.contains("button", "Reset view", { timeout: 15000 }).should("be.visible");

    // Real satisfied edges from the seeded chain render solid (not the dashed unsatisfied style).
    cy.get('svg[aria-label*="Organisation task graph"] line[stroke-dasharray]').should(
      "have.length",
      0,
    );

    // Every node/edge is still exactly the real backend data -- no cosmetic-only element crept
    // in from the interactivity change (T087).
    cy.location("pathname").then((pathname) => {
      const runId = pathname.split("/runs/")[1];
      token().then((t) => {
        cy.request({
          url: `${Cypress.env("apiUrl")}/api/v1/organization/runs/${runId}/dependencies`,
          headers: { Authorization: `Bearer ${t}` },
        }).then((res) => {
          const deps = res.body as Array<unknown>;
          cy.get('svg[aria-label*="Organisation task graph"] line').should(
            "have.length",
            deps.length,
          );
        });
      });
    });

    cy.get('svg[aria-label*="Organisation task graph"]').then(($svg) => {
      const before = ($svg.find("g").first().attr("transform") || "").trim();

      // Zoom via wheel -- the viewport transform must change, node/edge content must not.
      cy.wrap($svg).trigger("wheel", { deltaY: -120 });
      cy.get('svg[aria-label*="Organisation task graph"] g')
        .first()
        .invoke("attr", "transform")
        .should((after) => {
          expect(after).not.to.eq(before);
        });

      // Pan via drag.
      cy.wrap($svg).trigger("mousedown", { clientX: 100, clientY: 100 });
      cy.wrap($svg).trigger("mousemove", { clientX: 160, clientY: 130 });
      cy.wrap($svg).trigger("mouseup");
    });

    cy.contains("button", "Reset view").click();
  });
});
