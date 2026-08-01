"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api, type MfaEnrollResponse } from "@/lib/api";
import { GlassCard } from "@/components/ui/glass-card";

// REL-007 E7.1: SystemAdministrator/PortfolioManager/RiskManager now require a TOTP second
// factor. `/auth/login` returns `mfa_required` (never a real token for those roles) plus a
// short-lived `pending_token` -- this page drives the rest of the challenge from there:
//   - mfa_required=false                -> already a real session, same as before REL-007.
//   - mfa_required=true, mfa_enrolled=false -> first-time enrollment (enroll -> confirm).
//   - mfa_required=true, mfa_enrolled=true  -> already enrolled, just needs a fresh code (verify).
type Step = "credentials" | "enroll" | "verify";

// A genuine 401 from the backend (wrong credentials/code) throws an Error whose message
// contains the real HTTP status (see lib/api.ts's post()/get() helpers: `POST ${path} failed:
// ${res.status} ...`). Anything else -- fetch() itself throwing, e.g. a TLS handshake the
// browser hasn't been told to trust yet, a DNS failure, the backend being down -- is a
// connection problem, not a bad password, and showing "Incorrect email or password" for that
// case is actively misleading (confirmed the hard way: a real user's login attempts against an
// untrusted self-signed cert never even reached this backend -- no LOGIN_FAILURE audit row
// existed for them -- yet they saw the same "incorrect password" message a real 401 would show).
function isAuthRejection(err: unknown): boolean {
  return err instanceof Error && /failed: 4\d\d/.test(err.message);
}
const CONNECTION_ERROR_MESSAGE =
  "Couldn't reach the server. If this is a fresh setup, you may need to open the API's own " +
  "URL directly once and accept its certificate warning, then try again.";

const inputClass =
  "w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-cyan-400/50";
const labelClass = "mb-1 block text-[11px] uppercase tracking-wider text-zinc-500";
const buttonClass =
  "mt-2 rounded-lg bg-cyan-500/90 py-2 text-sm font-medium text-black transition hover:bg-cyan-400 disabled:opacity-50";

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
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleCredentialsSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
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
      setError(isAuthRejection(err) ? "Incorrect email or password." : CONNECTION_ERROR_MESSAGE);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleConfirmEnrollment(e: React.FormEvent) {
    e.preventDefault();
    if (!pendingToken) return;
    setError(null);
    setSubmitting(true);
    try {
      const session = await api.mfaConfirm(pendingToken, totpCode);
      await completeSession(session.access_token, session.refresh_token);
      router.replace("/");
    } catch (err) {
      setError(
        isAuthRejection(err)
          ? "Incorrect code. Check your authenticator app and try again."
          : CONNECTION_ERROR_MESSAGE,
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    if (!pendingToken) return;
    setError(null);
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
        setError(CONNECTION_ERROR_MESSAGE);
      } else {
        setError(useBackupCode ? "Incorrect or already-used backup code." : "Incorrect code.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#09090B] p-6">
      {step === "credentials" && (
        <GlassCard className="w-full max-w-sm" title="Sign in" eyebrow="TradingOS">
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
            {error && <p className="text-xs text-rose-400">{error}</p>}
            <button type="submit" disabled={submitting} className={buttonClass}>
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </GlassCard>
      )}

      {step === "enroll" && enrollment && (
        <GlassCard className="w-full max-w-md" title="Set up two-factor authentication" eyebrow="TradingOS">
          <div className="flex flex-col gap-4 text-sm text-zinc-300">
            <p>
              This role requires a TOTP authenticator app (Google Authenticator, Authy, 1Password,
              etc). Scan or manually add this secret, then enter a code below to finish.
            </p>
            <div>
              <div className={labelClass}>Manual entry secret</div>
              <code className="block break-all rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-cyan-300">
                {enrollment.secret_base32}
              </code>
            </div>
            <div>
              <div className={labelClass}>Or add via URI</div>
              <code className="block break-all rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-zinc-400">
                {enrollment.otpauth_uri}
              </code>
            </div>
            <div>
              <div className={labelClass}>Backup codes — save these now, shown only once</div>
              <div className="grid grid-cols-2 gap-1 rounded-lg border border-amber-400/20 bg-amber-400/5 p-3 font-mono text-xs text-amber-200">
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
              {error && <p className="text-xs text-rose-400">{error}</p>}
              <button type="submit" disabled={submitting} className={buttonClass}>
                {submitting ? "Confirming…" : "Confirm and sign in"}
              </button>
            </form>
          </div>
        </GlassCard>
      )}

      {step === "verify" && (
        <GlassCard className="w-full max-w-sm" title="Two-factor authentication" eyebrow="TradingOS">
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
            {error && <p className="text-xs text-rose-400">{error}</p>}
            <button type="submit" disabled={submitting} className={buttonClass}>
              {submitting ? "Verifying…" : "Verify and sign in"}
            </button>
            <button
              type="button"
              onClick={() => {
                setUseBackupCode(!useBackupCode);
                setError(null);
              }}
              className="text-xs text-zinc-500 underline underline-offset-2 hover:text-zinc-300"
            >
              {useBackupCode ? "Use authenticator code instead" : "Use a backup code instead"}
            </button>
          </form>
        </GlassCard>
      )}
    </main>
  );
}
