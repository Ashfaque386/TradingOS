// REL-044/045/046: the upgraded Strategies page against the real running stack -- the real
// Strategy Generator Agent logic fields (entry/exit/stop/take-profit/position-sizing/confidence,
// previously computed on every run and silently discarded), the real CEO/Market Analyst
// research context ("why this strategy was proposed"), real F&O option legs/rationale, the
// reused VerdictPanel/FullMetricGrid backtest narrative, validator feedback, and Kanban card
// enrichment (hypothesis snippet, backtest_count, status dot). Requires the two REL-044 fixture
// strategies seeded via scripts/seed_strategies_cypress_fixtures.py ("cypress-rel044-fno-fixture-
// strategy" and "cypress-rel044-premigration-fixture-strategy" -- uniquely named so `cy.contains`
// can't accidentally land on one of the many identically-named real rows left behind by past
// pytest runs in this shared dev DB) to exist in the real DB. No mocking.
//
// REL-069 fix: this same spec's own "submits a suggestion" / "AI review resolves a suggestion"
// tests below genuinely re-enter REL-048's Suggestion Regeneration pipeline against the F&O
// fixture (a real LLM call), which can legitimately mutate its hypothesis/entry_conditions/
// confidence_score/asset_class/style/status/universe in place -- correct production behavior,
// not a bug. Tests that used to hardcode the fixture's original seed values (e.g. "72%", "Bull
// call spread on RELIANCE") would then fail on any run after that regeneration had ever fired,
// even though nothing was actually broken. Fixed by reading the fixture's real current state via
// a direct API call first (matching this file's own `findBacktestWithRealTrades`-style precedent
// used elsewhere in this test suite) and asserting against that, so these tests stay correct
// whether the fixture is pristine or has already been legitimately upgraded by real agent
// research/analysis/backtest activity.

export {};

const FIXTURE_NAME = "cypress-rel044-fno-fixture-strategy";
const PREMIGRATION_FIXTURE_NAME = "cypress-rel044-premigration-fixture-strategy";
// Bug fix: a dedicated, zero-backtest, real-working-code fixture for the one test that genuinely
// triggers a live backtest -- kept separate from FIXTURE_NAME so that test's own real, verdict-
// less new backtest row never becomes "most recent" and breaks the Pass/Approve assertions other
// tests make against FIXTURE_NAME. Seeded by scripts/seed_strategies_cypress_fixtures.py.
const LIVE_TRIGGER_FIXTURE_NAME = "cypress-bugfix-live-trigger-fixture-strategy";
const API_URL = Cypress.env("apiUrl");

function loginViaUi(email: string, password: string) {
  cy.visit("/login");
  cy.get("input[type=email]").type(email);
  cy.get("input[type=password]").type(password);
  cy.get("button[type=submit]").click();
  cy.url().should("eq", Cypress.config().baseUrl + "/");
}

function loginViaApi(email: string, password: string) {
  return cy
    .request("POST", `${API_URL}/api/v1/auth/login`, { email, password })
    .its("body")
    .then((body) => body.access_token as string);
}

type FixtureStrategy = {
  id: string;
  name: string;
  hypothesis: string | null;
  entry_conditions: string | null;
  confidence_score: number | null;
  asset_class: string;
  style: string;
  status: string;
  backtest_count: number;
};

/** Reads a fixture's real current state directly from the API -- never assumes it still has its
 * original seed values, since a real suggestion regeneration may have legitimately changed them
 * since it was last (re)seeded. Defaults to the F&O fixture (every existing call site). */
function fetchFixtureStrategy(name: string = FIXTURE_NAME): Cypress.Chainable<FixtureStrategy> {
  return loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((token) =>
    cy
      .request({
        url: `${API_URL}/api/v1/strategies`,
        headers: { Authorization: `Bearer ${token}` },
      })
      .its("body")
      .then((rows: FixtureStrategy[]) => {
        const fixture = rows.find((r) => r.name === name);
        expect(fixture, `${name} to exist in the real DB`).to.exist;
        return fixture!;
      }),
  );
}

describe("Strategies page (REL-044/045/046)", () => {
  it("unauthenticated visitors are redirected to login", () => {
    cy.visit("/strategies");
    cy.url().should("include", "/login");
  });

  it("Kanban card shows a real hypothesis snippet, backtest_count, and a status dot", () => {
    fetchFixtureStrategy().then((fixture) => {
      loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
      cy.contains("Strategies").click();
      cy.url().should("include", "/strategies");

      const hypothesisSnippet = (fixture.hypothesis ?? "").slice(0, 20);
      const backtestLabel =
        fixture.backtest_count === 1 ? "1 backtest" : `${fixture.backtest_count} backtests`;
      cy.contains(FIXTURE_NAME)
        .parents(".select-none")
        .should("contain.text", hypothesisSnippet)
        .and("contain.text", backtestLabel);
    });
  });

  it("selecting the fixture strategy renders real logic + research-context + option-legs panels", () => {
    fetchFixtureStrategy().then((fixture) => {
      loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
      cy.visit("/strategies");
      cy.contains(FIXTURE_NAME).click();

      const confidencePct =
        fixture.confidence_score !== null ? `${Math.round(fixture.confidence_score * 100)}%` : null;
      const entrySnippet = (fixture.entry_conditions ?? "").slice(0, 20);
      cy.contains("Strategy Logic")
        .parents(".rounded-card")
        .within(() => {
          cy.contains("Agent Confidence").should("be.visible");
          if (confidencePct) cy.contains(confidencePct).should("be.visible");
          cy.contains("Entry Conditions").should("be.visible");
          if (entrySnippet) cy.contains(entrySnippet).should("be.visible");
          cy.contains("Position Sizing").should("be.visible");
        });

      // Research context copy (labels + Risk-On/etc.) comes from the CEO/Market Analyst Agents'
      // real ResearchDirective/MarketContext at proposal time -- this doesn't change when a later
      // suggestion regenerates the strategy's own logic fields, so these stay literal.
      cy.contains("Why This Strategy Was Proposed")
        .parents(".rounded-card")
        .within(() => {
          cy.contains("Market Regime").should("be.visible");
          cy.contains("Risk-On").should("be.visible");
          cy.contains("Priority Sectors").should("be.visible");
          cy.contains("Volatility Assessment").should("be.visible");
        });

      cy.contains("Validator Feedback").should("be.visible");

      // A real regeneration can move the fixture off F&O entirely (a real, honest asset-class
      // change) -- Option Legs only renders for a real F&O version with real legs, matching the
      // same "honest absent state" convention the premigration-fixture test below verifies.
      if (fixture.asset_class === "F&O") {
        cy.contains("Option Legs").should("exist");
      }
    });
  });

  it("the fixture's real backtest renders VerdictPanel/FullMetricGrid with real content", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.contains(FIXTURE_NAME).click();

    cy.contains("Sandbox").parents(".rounded-card").within(() => {
      cy.contains(/Evaluation: Pass/).should("be.visible");
      cy.contains(/Deployment: Approve/).should("be.visible");
      cy.contains("Sortino").should("be.visible");
      cy.contains("MC p95 DD").should("be.visible");
      // Bug fix: date_from/date_to/initial_capital previously weren't shown anywhere.
      cy.contains(/Window: .+ → .+ · Capital: ₹/).should("be.visible");
    });
  });

  it("a real pre-migration strategy renders the honest absent state without breaking layout", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.contains(PREMIGRATION_FIXTURE_NAME).click();
    cy.contains("Strategy Logic").parents(".rounded-card").within(() => {
      cy.contains("generated before real trading-logic capture shipped").should("be.visible");
    });
    cy.contains("Why This Strategy Was Proposed").parents(".rounded-card").within(() => {
      cy.contains("No research context captured").should("be.visible");
    });
  });

  it("Run Backtest trigger is still present and role-gated", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.contains(FIXTURE_NAME).click();
    cy.contains("button", "Run Backtest").should("be.visible");
  });

  // Bug fix: this page used to poll `detailQuery` gated on `jobRunning`, which flipped false
  // (cancelling the next poll) on the exact render where the job was first observed Completed --
  // the new BacktestResult row never got fetched until a manual reload. Proves the fix end-to-end
  // by triggering a REAL backtest through the real UI button (not `cy.request`, since the bug was
  // specifically about the mounted page's own query cache, not the API) and asserting a new
  // backtest pill appears WITHOUT any `cy.visit`/reload in between. Slow (~60-90s cold sandbox
  // run, same real timing as every other real-backtest test in this codebase).
  it("a real completed backtest appears on this page without a manual reload", () => {
    fetchFixtureStrategy(LIVE_TRIGGER_FIXTURE_NAME).then((fixture) => {
      const countBefore = fixture.backtest_count;

      loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
      cy.visit("/strategies");
      cy.contains(LIVE_TRIGGER_FIXTURE_NAME).click();
      cy.contains("Sandbox").parents(".rounded-card").within(() => {
        // countBefore can genuinely be 0 on this fixture's first-ever run (no pill row renders
        // at all yet, just the honest "No backtests run yet" text) -- the pill selector below
        // would error finding zero elements in that case, so branch on the real starting state
        // rather than assuming a pill row already exists.
        if (countBefore === 0) {
          cy.contains("No backtests run yet.").should("be.visible");
        } else {
          cy.get(".flex.flex-wrap.gap-1\\.5 > button").should("have.length", countBefore);
        }
        cy.contains("button", "Run Backtest").click();
        cy.contains("button", "Running…", { timeout: 15_000 }).should("be.visible");
        // Cold vectorbt sandbox runs take ~60-90s (numba JIT compiles fresh every time) --
        // generous headroom above that real budget for load variance (confirmed empirically:
        // a real run under concurrent test-suite load took ~5 min end-to-end for this job).
        cy.contains("button", "Running…", { timeout: 240_000 }).should("not.exist");
        cy.get(".flex.flex-wrap.gap-1\\.5 > button", { timeout: 15_000 }).should(
          "have.length",
          countBefore + 1,
        );
      });
    });
  });

  // REL-047: the Asset/Style/Stage filter bar added to fix an always-growing, unfilterable
  // Kanban board -- the two REL-044 fixtures are real, distinct rows to filter by. Reads the F&O
  // fixture's real current asset_class rather than assuming it's still "F&O" (REL-069: a real
  // suggestion regeneration can legitimately move it) -- the premigration fixture is never a
  // target of that regeneration flow and stays a stable "Equity" contrast case.
  it("Asset Class filter narrows the board to only matching strategies", () => {
    fetchFixtureStrategy().then((fixture) => {
      loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
      cy.visit("/strategies");
      cy.contains(FIXTURE_NAME).should("exist");
      cy.contains(PREMIGRATION_FIXTURE_NAME).should("exist");

      if (fixture.asset_class === "Equity") {
        cy.log("Fixture's real asset_class is currently Equity, same as the premigration " +
          "fixture -- skipping the narrowing check since there's no real distinguishing filter.");
        return;
      }

      cy.get('[aria-label="Asset"]').contains("button", fixture.asset_class).click();
      cy.contains(FIXTURE_NAME).should("exist");
      cy.contains(PREMIGRATION_FIXTURE_NAME).should("not.exist");

      cy.get('[aria-label="Asset"]').contains("button", "All").click();
      cy.contains(PREMIGRATION_FIXTURE_NAME).should("exist");
    });
  });

  // REL-069: reads the F&O fixture's real current status rather than assuming it's still
  // "Backtesting" -- a real suggestion regeneration can legitimately move it to another stage.
  it("Stage filter collapses the board down to only the selected column", () => {
    fetchFixtureStrategy().then((fixture) => {
      loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
      cy.visit("/strategies");
      cy.contains(FIXTURE_NAME).should("exist");
      cy.contains(PREMIGRATION_FIXTURE_NAME).should("exist"); // always Ideation

      if (fixture.status === "Ideation") {
        cy.log("Fixture's real status is currently Ideation, same as the premigration fixture " +
          "-- skipping the collapse check since there's no real distinguishing stage.");
        return;
      }

      const stageLabel = fixture.status === "PaperTrading" ? "Paper Trading" : fixture.status;
      cy.get('[aria-label="Stage"]').contains("button", "All").click(); // turns every stage off
      cy.get('[aria-label="Stage"]').contains("button", stageLabel).click(); // turn just this on
      cy.contains(FIXTURE_NAME).should("exist");
      cy.contains(PREMIGRATION_FIXTURE_NAME).should("not.exist");
      // KanbanBoard renders exactly one grid-column-count class derived from the number of
      // visible columns -- collapsing to a single stage should leave exactly one real column in
      // the grid, not just fewer strategy cards inside all 5.
      cy.get(".xl\\:grid-cols-1").should("exist");
    });
  });

  it("Search filters the board by strategy name", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.get('input[aria-label="Search strategies"]').type("cypress-rel044-fno");
    cy.contains(FIXTURE_NAME).should("exist");
    cy.contains(PREMIGRATION_FIXTURE_NAME).should("not.exist");
  });

  // REL-048/049: submit a real suggestion against the real fixture strategy and list it as
  // Pending -- no mocking, matching this file's own "no mocking, real running stack" convention.
  it("submits a suggestion and lists it as Pending", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.contains(FIXTURE_NAME).click();

    const suggestionText = `cypress suggestion ${Date.now()}: tighten the stop-loss`;
    cy.contains("Suggest a Change").parents(".rounded-card").within(() => {
      cy.get("textarea").type(suggestionText);
      cy.contains("button", "Submit Suggestion").click();
    });

    cy.contains(suggestionText).should("be.visible");
    cy.contains(suggestionText)
      .parents(".rounded-xl")
      .contains("Pending")
      .should("be.visible");
  });

  // REL-048/049: a real end-to-end AI review -- submits, triggers the real review (real LLM
  // calls, a real regeneration through the agent pipeline), and waits for a real terminal state.
  // Slow: matches this project's own real backtest/graph-run Cypress timing (multiple minutes).
  it("AI review resolves a suggestion to a real terminal state", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.visit("/strategies");
    cy.contains(FIXTURE_NAME).click();

    const suggestionText = `cypress ai-review ${Date.now()}: tighten the stop-loss to reduce max drawdown`;
    cy.contains("Suggest a Change").parents(".rounded-card").within(() => {
      cy.get("textarea").type(suggestionText);
      cy.contains("button", "Submit Suggestion").click();
    });

    cy.contains(suggestionText)
      .parents(".rounded-xl")
      .as("suggestionRow");
    cy.get("@suggestionRow").contains("button", "Ask AI to Review").click();

    // A real regeneration re-enters the full agent pipeline (multiple real LLM calls, a real
    // sandboxed backtest) -- generous timeout matching this project's own real-run tests.
    cy.get("@suggestionRow", { timeout: 240_000 }).within(() => {
      cy.contains(/Applied|Rejected/, { timeout: 240_000 }).should("be.visible");
    });
  });
});
