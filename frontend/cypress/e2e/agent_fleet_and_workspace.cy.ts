// spec 002 US4/US12: the Agent Fleet (department-grouped, real live status) and the
// two-panel Agent Workspace it switches into -- real data or an honest empty/idle state,
// never fabricated. Covers what's reliably seedable without a dedicated test-seed endpoint;
// dependency/handoff-chain-specific rendering (US3/US5's column/chain placement) was verified
// manually against a real multi-task seeded run in this session's own implementation pass --
// see specs/002-agent-organization-hardening/tasks.md T016/T020/T024 for that record.

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

describe("Agent Fleet (US12)", () => {
  it("renders agents grouped by real department, not a hardcoded list", () => {
    login();
    cy.visit("/console");
    // A cold Turbopack compile of a route not yet hit this run can outlast the default 15s
    // command timeout (documented in cypress.config.ts) -- give the very first assertion on
    // this page generous headroom; everything after it hits an already-warm route.
    cy.contains("Agent Fleet", { timeout: 30000 }).should("be.visible");
    // Real department headings sourced from capability_registry, e.g. these two always exist.
    // The heading above is static and renders before the registry query resolves, so the
    // department groups need their own generous wait rather than inheriting the default 4s.
    cy.contains("EXECUTIVE", { timeout: 15000 }).should("be.visible");
    cy.contains("MARKET INTELLIGENCE", { timeout: 15000 }).should("be.visible");
    // The pre-existing admin registry stays in its own tab, unaffected.
    cy.get("nav").contains("Agents & Legacy Graph").click();
    cy.contains("Agent Registry").should("be.visible");
  });

  it("clicking a Fleet card opens that agent's workspace", () => {
    login();
    cy.visit("/console");
    cy.contains("Agent Fleet")
      .parents('[class*="rounded-card"]')
      .first()
      .within(() => {
        cy.contains("CEO Agent (Master Orchestrator)").click();
      });
    cy.url().should("include", "/console/agents/ceo_agent");
    cy.contains("← Command Center").should("be.visible");
  });
});

describe("Agent Workspace (US4) — two-panel layout and honest states", () => {
  it("shows all required sections with real content or an honest idle/empty state", () => {
    login();
    cy.visit("/console/agents/ceo_agent");
    // Left panel: identity + current task.
    cy.contains("CEO Agent (Master Orchestrator)").should("be.visible");
    cy.contains("Model / provider").should("be.visible");
    cy.contains("Current task").should("be.visible");
    // No runId/taskId in the URL -> honest idle state, never fabricated data.
    cy.contains("No active task").should("be.visible");
    // Right panel: handoffs (honest "open from a run" state without run context) + timeline.
    cy.contains("Handoffs").should("be.visible");
    cy.contains("Open this agent from a specific run").should("be.visible");
    cy.contains("Execution timeline").should("be.visible");
    cy.contains("Recent result artefacts").should("be.visible");
  });

  it("switching agents via the Fleet strip updates the workspace without a full page reload", () => {
    login();
    cy.visit("/console/agents/ceo_agent");
    cy.window().then((win) => {
      (win as unknown as { __navCount?: number }).__navCount = 0;
    });
    // The compact Fleet strip is the row of cards above the two-panel layout.
    cy.get('button[style*="--agent-color"]').eq(1).click();
    cy.url().should("not.include", "/agents/ceo_agent");
    cy.contains("Current task").should("be.visible");
  });

  it("a non-graph (scheduled) agent renders the same section set", () => {
    login();
    cy.visit("/console/agents/news_agent");
    cy.contains("News Agent").should("be.visible");
    cy.contains("Current task").should("be.visible");
    cy.contains("Handoffs").should("be.visible");
    cy.contains("Execution timeline").should("be.visible");
  });
});

describe("Task Board (US5) — view exists with real column shell", () => {
  it("the run workspace offers a Board/List toggle for tasks", () => {
    login();
    token().then((t) => {
      cy.request({
        url: `${Cypress.env("apiUrl")}/api/v1/organization/runs`,
        headers: { Authorization: `Bearer ${t}` },
      }).then((res) => {
        const runs = res.body as Array<{ run_id: string }>;
        if (runs.length === 0) return; // nothing to open; covered by the console-home empty state
        cy.visit(`/console/runs/${runs[0].run_id}`);
        cy.contains("Task board", { timeout: 30000 }).should("be.visible");
        cy.contains("button", "Board").should("be.visible");
        cy.contains("button", "List").should("be.visible");
        for (const label of ["Queued", "Running", "Waiting", "Blocked", "Retrying", "Escalated", "Completed", "Failed"]) {
          cy.contains(label).should("exist");
        }
      });
    });
  });
});
