import { useEffect, useState } from "react";
import { EqualizerMark } from "@/components/brand/EqualizerMark";
import { BigtappMark } from "@/components/brand/BigtappMark";
import { HomeLink } from "@/components/brand/HomeLink";
import { MicrosoftMark } from "@/components/auth/MicrosoftMark";
import { Lozenge } from "@/components/ui/lozenge";
import { signInWithMicrosoft, entraConfigured, completeRedirect, bounceOffLoopbackIp } from "@/lib/sso";

const BASE = import.meta.env.BASE_URL;
const VIDEO = `${BASE}videos/login-bee.mp4`;
const POSTER = `${BASE}videos/login-bee.jpg`;

const CLAIMS = [
  { k: "Next-best treatment", v: "Which account to work, on which channel, this hour." },
  { k: "Every contact is answerable", v: "Policy, score, gates and transcript on one record." },
  { k: "On-prem by default", v: "Models and recordings stay inside the bank perimeter." },
  { k: "Microsoft Entra SSO", v: "No password is stored on this product." },
];

export function LoginScreen() {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (bounceOffLoopbackIp()) return;
    let cancelled = false;
    if (!entraConfigured()) return;
    void (async () => {
      const account = await completeRedirect();
      if (cancelled || !account) return;
      window.location.assign(BASE);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onSignIn = async () => {
    if (!entraConfigured()) {
      if (import.meta.env.PROD) {
        setNotice("Microsoft sign-in is not connected on this deployment.");
        return;
      }
      window.location.assign(BASE);
      return;
    }
    setBusy(true);
    setNotice(null);
    const result = await signInWithMicrosoft();
    if (!result.ok) {
      setBusy(false);
      setNotice(result.reason);
    }
  };

  return (
    <div className="flex h-dvh max-h-dvh overflow-hidden bg-background">
      <aside className="relative hidden h-full w-[54%] overflow-hidden lg:block">
        <BeePlate />
      </aside>

      <main className="relative flex h-full min-h-0 flex-1 flex-col overflow-hidden">
        <div className="pointer-events-none absolute inset-0 lg:hidden">
          <BeePlate dimmed />
        </div>

        <div className="relative z-10 flex h-full min-h-0 flex-1 flex-col justify-between px-400 py-300 lg:px-600 lg:py-400">
          <header className="flex shrink-0 items-center gap-150">
            <HomeLink className="flex items-center gap-150 text-text">
              <EqualizerMark size={28} />
              <span className="heading-medium font-semibold">PayInt</span>
            </HomeLink>
            <Lozenge tone="information">Beeonix</Lozenge>
            <HomeLink className="ml-auto text-body-small text-text-subtle hover:underline">
              Home
            </HomeLink>
          </header>

          <div className="min-h-0 max-w-md py-200">
            <p className="text-body-small font-medium uppercase tracking-wide text-text-subtle">
              Autonomous Payment Intelligence
            </p>
            <h1 className="mt-100 heading-xlarge text-text">
              The floor is already working the book.
            </h1>
            <p className="mt-150 text-body text-text-subtle lg:text-body-large">
              Sign in with Microsoft to open the floor. A.P.I.S decides which account to work next,
              on which channel, and why.
            </p>

            <button
              type="button"
              onClick={() => void onSignIn()}
              disabled={busy}
              className="mt-300 flex h-12 w-full items-center justify-center gap-150 rounded-medium border border-border bg-surface text-body font-medium text-text transition-colors hover:bg-background-neutral-subtle-hovered focus-ring disabled:cursor-not-allowed disabled:opacity-50"
            >
              <MicrosoftMark size={18} />
              {busy ? "Redirecting to Microsoft…" : "Sign in with Microsoft"}
            </button>

            <p className="mt-150 text-body-small text-text-subtlest">
              Use your <span className="text-text-subtle">@bigtapp.ai</span> account. Microsoft
              collects the password. This page does not.
            </p>

            {notice ? (
              <p className="mt-200 rounded-medium border border-border-warning bg-background-warning-subtler px-200 py-150 text-body-small text-text-warning-bolder">
                {notice}
              </p>
            ) : null}

            <ul className="mt-300 hidden space-y-150 [@media(min-height:800px)]:block">
              {CLAIMS.map((c) => (
                <li key={c.k}>
                  <p className="text-body-small font-medium text-text">{c.k}</p>
                  <p className="mt-025 hidden text-body-small text-text-subtle [@media(min-height:900px)]:block">
                    {c.v}
                  </p>
                </li>
              ))}
            </ul>
          </div>

          <footer className="flex shrink-0 flex-wrap items-center gap-150 text-body-small text-text-subtlest">
            <BigtappMark size={22} />
            <span>A Bigtapp product</span>
            <span aria-hidden="true">·</span>
            <span>Restricted to @bigtapp.ai</span>
            <span aria-hidden="true">·</span>
            <a className="text-link hover:underline" href="mailto:info@bigtapp.ai">
              Need access? info@bigtapp.ai
            </a>
          </footer>
        </div>
      </main>
    </div>
  );
}

function BeePlate({ dimmed = false }: { dimmed?: boolean }) {
  const [motion, setMotion] = useState(true);
  const [videoOk, setVideoOk] = useState(true);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setMotion(!mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  return (
    <div className="absolute inset-0 bg-[#f7f9fb]">
      <img src={POSTER} alt="" className="h-full w-full object-cover object-center" />
      {motion && videoOk ? (
        <video
          className="absolute inset-0 h-full w-full object-cover object-center"
          src={VIDEO}
          poster={POSTER}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          tabIndex={-1}
          aria-hidden="true"
          onError={() => setVideoOk(false)}
        />
      ) : null}
      {dimmed ? <div className="absolute inset-0 bg-background/80" /> : null}
    </div>
  );
}
