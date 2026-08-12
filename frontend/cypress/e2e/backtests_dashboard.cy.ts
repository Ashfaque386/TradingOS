// REL-040/041/042/043: the upgraded Backtests dashboard against the real running stack -- real
// backtest_count on the strategy picker, the real AI-pipeline verdict panel (a real chip or an
// honest "Not yet evaluated" state, never a fabricated one), ?strategy=&run= URL deep-linking
// cross-checked against the real API, the real server-side "latest per strategy" cross-strategy
// table, the Run New Backtest trigger's role gating, the multi-run Comparison Workspace
// (?compare=, real GET /strategies/backtests/compare), the Monte Carlo histogram tab (real
// GET /strategies/backtests/{id}/monte-carlo), the client-local Win/Loss trade filter, and the
// real CSV/NDJSON export endpoint (verified via a direct authenticated request, not a UI download
// event -- jsdom/Electron's synthetic-anchor Blob download isn't something Cypress observes
// reliably). No mocking.

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

/** REL-043 test helper: `total_trades` (BacktestResult's own persisted metrics column) and the
 * real per-trade ledger (`trades`, REL-022) are two independently-populated columns -- a
 * pre-REL-022 backtest row can genuinely have a positive total_trades count with an empty/absent
 * trades array. Rather than trust total_trades as a proxy, this checks the real /trades endpoint
 * directly for each candidate and returns the first with real, non-empty data. */
type BacktestWithTrades = { id: string; strategy_id: string; trades: { pnl: number }[] };

function findBacktestWithRealTrades(
  token: string,
  rows: { id: string; strategy_id: string }[],
): Cypress.Chainable<BacktestWithTrades | null> {
  let found: BacktestWithTrades | null = null;
  rows.forEach((r) => {
    cy.request({
      url: `${API_URL}/api/v1/strategies/backtests/${r.id}/trades`,
      headers: { Authorization: `Bearer ${token}` },
    }).then((res) => {
      const trades = res.body as { pnl: number }[];
      if (!found && trades.length > 0) {
        found = { id: r.id, strategy_id: r.strategy_id, trades };
      }
    });
  });
  return cy.wrap<BacktestWithTrades | null>(null).then(() => found);
}

describe("Backtests dashboard (REL-040/041/042)", () => {
  it("unauthenticated visitors are redirected to login", () => {
    cy.visit("/backtests");
    cy.url().should("include", "/login");
  });

  it("shows a real backtest_count-aware strategy picker and a real verdict panel", () => {
    loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
    cy.contains("Backtests").click();
    cy.url().should("include", "/backtests");

    // The picker's options are real <option> text -- "N runs"/"N run" is real backtest_count,
    // not a placeholder, for whichever strategy the app defaulted to.
    cy.get("main select")
      .first()
      .find("option")
      .first()
      .invoke("text")
      .should("match", /\d+ runs?/);

    // A Go/No-Go verdict panel renders for the selected run only once a real backtest exists --
    // either real chips or the honest pending state, never silently missing.
    cy.get("main").then(($main) => {
      if ($main.text().includes("Go / No-Go Verdict")) {
        cy.contains("Go / No-Go Verdict")
          .parents(".rounded-card")
          .contains(/Evaluation:|Risk:|Deployment:/)
          .should("be.visible");
      } else {
        cy.log("Selected default strategy has no backtests yet -- verdict panel correctly absent.");
      }
    });
  });

  it("deep-links ?strategy=&run= to the exact real backtest the API itself returns", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((token) => {
      cy.request({
        url: `${API_URL}/api/v1/strategies`,
        headers: { Authorization: `Bearer ${token}` },
      }).then((strategiesRes) => {
        const withBacktests = (strategiesRes.body as { id: string; backtest_count: number }[]).find(
          (s) => s.backtest_count > 0,
        );
        if (!withBacktests) {
          cy.log("No strategy with a real backtest exists in this environment -- skipping deep-link check.");
          return;
        }
        cy.request({
          url: `${API_URL}/api/v1/strategies/${withBacktests.id}`,
          headers: { Authorization: `Bearer ${token}` },
        }).then((detailRes) => {
          const realBacktestId = detailRes.body.backtests[0].id as string;

          loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
          cy.visit(`/backtests?strategy=${withBacktests.id}&run=${realBacktestId}`);
          cy.get("main select").first().should("have.value", withBacktests.id);
          cy.get("main").contains("Key Metrics").should("be.visible");
          cy.url().should("include", `run=${realBacktestId}`);
        });
      });
    });
  });

  it("cross-strategy card renders the real server-side latest-per-strategy view", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((token) => {
      cy.request({
        url: `${API_URL}/api/v1/strategies/backtests/latest`,
        headers: { Authorization: `Bearer ${token}` },
      }).then((latestRes) => {
        const realRows = latestRes.body as { strategy_name: string }[];
        loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
        cy.visit("/backtests");
        cy.contains("Latest backtest per strategy").should("be.visible");
        if (realRows.length > 0) {
          cy.get("main").contains(realRows[0].strategy_name).should("be.visible");
        }
      });
    });
  });

  it("Run New Backtest is visible to a RiskManager and absent for a ReadOnlyAuditor", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((adminToken) => {
      const suffix = Date.now();
      const auditorEmail = `cy-backtests-auditor-${suffix}@example.invalid`;
      const auditorPassword = "cy-test-password-123";
      cy.request({
        method: "POST",
        url: `${API_URL}/api/v1/users`,
        headers: { Authorization: `Bearer ${adminToken}` },
        body: { email: auditorEmail, password: auditorPassword, role: "ReadOnlyAuditor" },
      }).then(() => {
        loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
        cy.visit("/backtests");
        cy.contains("Run New Backtest").should("be.visible");

        loginViaUi(auditorEmail, auditorPassword);
        cy.visit("/backtests");
        cy.contains("Run New Backtest").should("not.exist");
      });
    });
  });

  it("selecting 2 real runs in the cross-strategy table populates ?compare= and renders the Comparison Workspace", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((token) => {
      cy.request({
        url: `${API_URL}/api/v1/strategies/backtests/latest`,
        headers: { Authorization: `Bearer ${token}` },
      }).then((latestRes) => {
        const realRows = latestRes.body as { strategy_name: string }[];
        if (realRows.length < 2) {
          cy.log("Fewer than 2 strategies have a real backtest -- skipping compare-selection check.");
          return;
        }
        loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
        cy.visit("/backtests");
        cy.contains("Select at least 2 runs above").should("be.visible");

        // Re-queries the checkbox list fresh before each click (rather than reusing one stale
        // jQuery collection) -- each click causes a real ?compare= URL update and re-render, and
        // clicking a jQuery-cached reference to a since-unmounted checkbox silently no-ops.
        function checkboxes() {
          return cy
            .get("main")
            .contains("Latest backtest per strategy")
            .parents(".rounded-card")
            .find('input[type="checkbox"]');
        }
        checkboxes().eq(0).click();
        // Waits for the first click's real ?compare= URL update (a client-side router.replace,
        // not instantaneous) to actually land before querying+clicking the second checkbox --
        // otherwise the second click can race the first navigation and only one id ever lands.
        cy.url().should("match", /compare=[0-9a-f-]+$/i);
        checkboxes().filter(":not(:checked)").eq(0).click();

        cy.url().should("match", /compare=[^&]+(,|%2C)[^&]+/i);
        cy.contains("Select at least 2 runs above").should("not.exist");
        cy.contains("REL-042").parents(".rounded-card").contains("Comparison Workspace").should("be.visible");
      });
    });
  });

  it("Monte Carlo tab reflects the real per-trade return distribution (histogram or the honest <2-trades state)", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((token) => {
      cy.request({
        url: `${API_URL}/api/v1/strategies`,
        headers: { Authorization: `Bearer ${token}` },
      }).then((strategiesRes) => {
        const withBacktests = (strategiesRes.body as { id: string; backtest_count: number }[]).find(
          (s) => s.backtest_count > 0,
        );
        if (!withBacktests) {
          cy.log("No strategy with a real backtest exists -- skipping Monte Carlo tab check.");
          return;
        }
        cy.request({
          url: `${API_URL}/api/v1/strategies/${withBacktests.id}`,
          headers: { Authorization: `Bearer ${token}` },
        }).then((detailRes) => {
          const backtest = detailRes.body.backtests[0] as { id: string; total_trades: number | null };

          loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
          cy.visit(`/backtests?strategy=${withBacktests.id}&run=${backtest.id}&tab=monte-carlo`);
          cy.contains("Monte Carlo").click();

          if (backtest.total_trades !== null && backtest.total_trades >= 2) {
            cy.contains("resamples of this backtest").should("be.visible");
            // ReactECharts (opts.renderer: "svg") mounts a real <svg> chart, not a placeholder.
            cy.get("main svg").should("exist");
          } else {
            cy.contains("Not enough real closed trades").should("be.visible");
          }
        });
      });
    });
  });

  it("Win/Loss trade filter narrows the real trade list to the exact real win/loss counts", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((token) => {
      cy.request({
        url: `${API_URL}/api/v1/strategies/backtests/latest`,
        headers: { Authorization: `Bearer ${token}` },
      }).then((latestRes) => {
        const rows = latestRes.body as { id: string; strategy_id: string }[];
        findBacktestWithRealTrades(token, rows).then((withTrades) => {
          if (!withTrades) {
            cy.log("No real backtest with closed trades exists -- skipping trade filter check.");
            return;
          }
          const { trades } = withTrades;
          const winCount = trades.filter((t) => t.pnl >= 0).length;
          const lossCount = trades.length - winCount;

          loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
          cy.visit(`/backtests?strategy=${withTrades.strategy_id}&run=${withTrades.id}&tab=trades`);
          cy.contains(`All (${trades.length})`).should("be.visible");
          cy.contains(`Win (${winCount})`).should("be.visible");
          cy.contains(`Loss (${lossCount})`).should("be.visible");

          // Scoped to the "Per-Run Analysis" card specifically -- `main tbody tr` alone also
          // matches the Cross-run/Cross-strategy/Comparison Workspace tables elsewhere on the
          // same page, over-counting rows that have nothing to do with this filter.
          function tradeRows() {
            return cy.contains("Per-Run Analysis").parents(".rounded-card").find("tbody tr");
          }
          if (winCount > 0) {
            cy.contains(`Win (${winCount})`).click();
            tradeRows().should("have.length", winCount);
          }
          if (lossCount > 0) {
            cy.contains(`Loss (${lossCount})`).click();
            tradeRows().should("have.length", lossCount);
          }
        });
      });
    });
  });

  it("the real CSV/NDJSON trade export endpoints return the exact real per-trade ledger", () => {
    loginViaApi(Cypress.env("adminEmail"), Cypress.env("adminPassword")).then((token) => {
      cy.request({
        url: `${API_URL}/api/v1/strategies/backtests/latest`,
        headers: { Authorization: `Bearer ${token}` },
      }).then((latestRes) => {
        const rows = latestRes.body as { id: string; strategy_id: string }[];
        findBacktestWithRealTrades(token, rows).then((withTrades) => {
          if (!withTrades) {
            cy.log("No real backtest with closed trades exists -- skipping export check.");
            return;
          }
          const expectedCount = withTrades.trades.length;

          loginViaUi(Cypress.env("adminEmail"), Cypress.env("adminPassword"));
          cy.visit(`/backtests?strategy=${withTrades.strategy_id}&run=${withTrades.id}`);
          cy.contains("button", "CSV").should("be.visible");
          cy.contains("button", "NDJSON").should("be.visible");

          cy.request({
            url: `${API_URL}/api/v1/strategies/backtests/${withTrades.id}/export`,
            headers: { Authorization: `Bearer ${token}` },
          }).then((csvRes) => {
            // csv.writer's dialect always emits \r\n row terminators regardless of platform, so
            // this counts non-empty lines after a CRLF-aware split rather than assuming \n alone.
            const lines = (csvRes.body as string).split(/\r\n/).filter((l) => l.length > 0);
            expect(csvRes.headers["content-type"]).to.include("text/csv");
            expect(lines[0]).to.include("entry_date");
            expect(lines.length - 1).to.eq(expectedCount);
          });

          cy.request({
            url: `${API_URL}/api/v1/strategies/backtests/${withTrades.id}/export?format=ndjson`,
            headers: { Authorization: `Bearer ${token}` },
          }).then((ndjsonRes) => {
            const lines = (ndjsonRes.body as string).trim().split("\n");
            expect(lines).to.have.length(expectedCount);
            expect(JSON.parse(lines[0])).to.have.property("entry_date");
          });
        });
      });
    });
  });
});
