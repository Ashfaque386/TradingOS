"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api, API_BASE, ApiError, type MfaEnrollResponse } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

// REL-007 E7.1: SystemAdministrator/PortfolioManager/RiskManager now require a TOTP second
// factor. `/auth/login` returns `mfa_required` (never a real token for those roles) plus a
// short-lived `pending_token` -- this page drives the rest of the challenge from there:
//   - mfa_required=false                -> already a real session, same as before REL-007.
//   - mfa_required=true, mfa_enrolled=false -> first-time enrollment (enroll -> confirm).
//   - mfa_required=true, mfa_enrolled=true  -> already enrolled, just needs a fresh code (verify).
type Step = "credentials" | "enroll" | "verify";

// A genuine 4xx from the backend (wrong credentials/code) is a real rejection; anything else --
// fetch() itself throwing, e.g. a TLS handshake the browser hasn't been told to trust yet, a DNS
// failure, the backend being down -- is a connection problem, not a bad password, and showing
// "Incorrect email or password" for that case is actively misleading (confirmed the hard way: a
// real user's login attempts against an untrusted self-signed cert never even reached this
// backend -- no LOGIN_FAILURE audit row existed for them -- yet they saw the same "incorrect
// password" message a real 401 would show).
// `login()` goes through lib/api.ts's post(), which throws a real ApiError carrying the HTTP
// status; the MFA calls (mfaEnroll/mfaConfirm/mfaVerify) still go through postWithToken(), which
// hasn't been migrated off the older `failed: ${status}` raw-text Error -- both are checked here
// so this stays correct for both paths without having to migrate postWithToken() just for this.
function isAuthRejection(err: unknown): boolean {
  if (err instanceof ApiError) return err.status >= 400 && err.status < 500;
  return err instanceof Error && /failed: 4\d\d/.test(err.message);
}

// A real, clickable link to the actual API origin, not just prose telling the user to go find
// it themselves -- the exact fix for a real report: a user stuck on this message had no way to
// know which URL to open.
function ConnectionErrorMessage() {
  return (
    <p className="text-xs text-down">
      Couldn&apos;t reach the server at{" "}
      <a
        href={API_BASE}
        target="_blank"
        rel="noreferrer"
        className="underline underline-offset-2 hover:brightness-110"
      >
        {API_BASE}
      </a>
      . If this is a fresh setup, open that link in a new tab and accept its certificate
      warning, then try again here.
    </p>
  );
}

// REL-012 Phase D (2026-08-04): the new design tokens' input treatment -- an inset `bg-bg` field
// (matches the reference screenshots' recessed-input look on a white card) with a hairline
// `card-edge` border, focusing to the brand gradient's mid stop rather than the retired cyan.
const inputClass =
  "w-full rounded-btn border border-card-edge bg-bg px-3 py-2 text-sm text-text outline-none focus:border-brand-via";
const labelClass = "mb-1 block text-[11px] uppercase tracking-wider text-text-faint";

export default function LoginPage() {
  const { login, completeSession } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState<Step>("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pendingToken, setPendingToken] = useState<string | null>(null);
  const [enrollment, setEnrollment] = useState<MfaEnrollResponse | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [backupCode, setBackupCode] = useState("");
  const [useBackupCode, setUseBackupCode] = useState(false);
  // `error` holds a plain-text auth-rejection message; `connectionError` is a separate flag
  // (not folded into `error`) so the render side can show the real, clickable ConnectionErrorMessage
  // instead of a plain string for that case -- see the module-level comment on isAuthRejection.
  const [error, setError] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  function resetErrors() {
    setError(null);
    setConnectionError(false);
  }

  async function handleCredentialsSubmit(e: React.FormEvent) {
    e.preventDefault();
    resetErrors();
    setSubmitting(true);
    try {
      const res = await login(email, password);
      if (!res.mfa_required) {
        await completeSession(res.access_token!, res.refresh_token!);
        router.replace("/");
        return;
      }
      setPendingToken(res.pending_token);
      if (res.mfa_enrolled) {
        setStep("verify");
      } else {
        const enrolled = await api.mfaEnroll(res.pending_token!);
        setEnrollment(enrolled);
        setStep("enroll");
      }
    } catch (err) {
      if (isAuthRejection(err)) {
        setError("Incorrect email or password.");
      } else {
        setConnectionError(true);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleConfirmEnrollment(e: React.FormEvent) {
    e.preventDefault();
    if (!pendingToken) return;
    resetErrors();
    setSubmitting(true);
    try {
      const session = await api.mfaConfirm(pendingToken, totpCode);
      await completeSession(session.access_token, session.refresh_token);
      router.replace("/");
    } catch (err) {
      if (isAuthRejection(err)) {
        setError("Incorrect code. Check your authenticator app and try again.");
      } else {
        setConnectionError(true);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    if (!pendingToken) return;
    resetErrors();
    setSubmitting(true);
    try {
      const session = await api.mfaVerify(
        pendingToken,
        useBackupCode ? { backup_code: backupCode } : { totp_code: totpCode },
      );
      await completeSession(session.access_token, session.refresh_token);
      router.replace("/");
    } catch (err) {
      if (!isAuthRejection(err)) {
        setConnectionError(true);
      } else {
        setError(useBackupCode ? "Incorrect or already-used backup code." : "Incorrect code.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-bg p-6">
      {/* REL-012 Phase D: the reference screenshots' subtle blurred radial-gradient background
          texture (Phase 7 §1.1) -- login is the first real page to carry it, since it's the
          simplest, data-free surface to prove the new direction on. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0">
        <div className="absolute -left-32 -top-32 h-96 w-96 rounded-full bg-brand-from/20 blur-3xl" />
        <div className="absolute -right-32 top-1/3 h-96 w-96 rounded-full bg-brand-via/15 blur-3xl" />
        <div className="absolute bottom-[-8rem] left-1/3 h-96 w-96 rounded-full bg-brand-to/15 blur-3xl" />
      </div>

      {step === "credentials" && (
        <Card className="relative w-full max-w-sm" title="Sign in" eyebrow="TradingOS">
          <form onSubmit={handleCredentialsSubmit} className="flex flex-col gap-4">
            <div>
              <label className={labelClass}>Email</label>
              <input
                type="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label className={labelClass}>Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputClass}
              />
            </div>
            {connectionError ? (
              <ConnectionErrorMessage />
            ) : (
              error && <p className="text-xs text-down">{error}</p>
            )}
            <Button type="submit" disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </Card>
      )}

      {step === "enroll" && enrollment && (
        <Card
          className="relative w-full max-w-md"
          title="Set up two-factor authentication"
          eyebrow="TradingOS"
        >
          <div className="flex flex-col gap-4 text-sm text-text-dim">
            <p>
              This role requires a TOTP authenticator app (Google Authenticator, Authy, 1Password,
              etc). Scan or manually add this secret, then enter a code below to finish.
            </p>
            <div>
              <div className={labelClass}>Manual entry secret</div>
              <code className="block break-all rounded-btn border border-card-edge bg-bg px-3 py-2 text-xs text-brand-via">
                {enrollment.secret_base32}
              </code>
            </div>
            <div>
              <div className={labelClass}>Or add via URI</div>
              <code className="block break-all rounded-btn border border-card-edge bg-bg px-3 py-2 text-xs text-text-dim">
                {enrollment.otpauth_uri}
              </code>
            </div>
            <div>
              <div className={labelClass}>Backup codes — save these now, shown only once</div>
              <div className="grid grid-cols-2 gap-1 rounded-btn border border-warn/30 bg-warn/10 p-3 font-mono text-xs text-warn">
                {enrollment.backup_codes.map((code) => (
                  <span key={code}>{code}</span>
                ))}
              </div>
            </div>
            <form onSubmit={handleConfirmEnrollment} className="flex flex-col gap-3">
              <div>
                <label className={labelClass}>Code from your authenticator app</label>
                <input
                  type="text"
                  inputMode="numeric"
                  autoFocus
                  required
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  className={inputClass}
                />
              </div>
              {connectionError ? (
                <ConnectionErrorMessage />
              ) : (
                error && <p className="text-xs text-down">{error}</p>
              )}
              <Button type="submit" disabled={submitting}>
                {submitting ? "Confirming…" : "Confirm and sign in"}
              </Button>
            </form>
          </div>
        </Card>
      )}

      {step === "verify" && (
        <Card
          className="relative w-full max-w-sm"
          title="Two-factor authentication"
          eyebrow="TradingOS"
        >
          <form onSubmit={handleVerify} className="flex flex-col gap-4">
            {!useBackupCode ? (
              <div>
                <label className={labelClass}>Authenticator code</label>
                <input
                  type="text"
                  inputMode="numeric"
                  autoFocus
                  required
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  className={inputClass}
                />
              </div>
            ) : (
              <div>
                <label className={labelClass}>Backup code</label>
                <input
                  type="text"
                  autoFocus
                  required
                  value={backupCode}
                  onChange={(e) => setBackupCode(e.target.value)}
                  className={inputClass}
                />
              </div>
            )}
            {connectionError ? (
              <ConnectionErrorMessage />
            ) : (
              error && <p className="text-xs text-down">{error}</p>
            )}
            <Button type="submit" disabled={submitting}>
              {submitting ? "Verifying…" : "Verify and sign in"}
            </Button>
            <button
              type="button"
              onClick={() => {
                setUseBackupCode(!useBackupCode);
                resetErrors();
              }}
              className="text-xs text-text-faint underline underline-offset-2 hover:text-text-dim"
            >
              {useBackupCode ? "Use authenticator code instead" : "Use a backup code instead"}
            </button>
          </form>
        </Card>
      )}
    </main>
  );
}
