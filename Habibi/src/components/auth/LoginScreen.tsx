import { useEffect, useState } from "react";
import { EqualizerMark } from "@/components/brand/EqualizerMark";
import { MicrosoftMark } from "@/components/auth/MicrosoftMark";
import { Lozenge } from "@/components/ui/lozenge";
import { signInWithMicrosoft } from "@/lib/sso";

const VIDEO = "/videos/login-bee.mp4";
const POSTER = "/videos/login-bee.jpg";

const CLAIMS = [
  {
    k: "Next-best treatment",
    v: "Which account to work, on which channel, this hour — not a dialer.",
  },
  {
    k: "Every contact is answerable",
    v: "Policy version, score, gate results and transcript on the same record.",
  },
  {
    k: "On-prem by default",
    v: "Models, recordings and customer data stay inside the bank perimeter.",
  },
  {
    k: "Microsoft Entra SSO",
    v: "Signed in through Microsoft. No password is stored on this product.",
  },
];

export function LoginScreen() {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    // The bee plate is authored on the light landing ground. Dark mode would
    // put a navy shell around a pale clip — force light for this route only.
    const root = document.documentElement;
    const hadDark = root.classList.contains("dark");
    root.classList.remove("dark");
    return () => {
      if (hadDark) root.classList.add("dark");
    };
  }, []);

  const onSignIn = () => {
    setBusy(true);
    setNotice(null);
    const result = signInWithMicrosoft();
    setBusy(false);
    if (!result.ok) setNotice(result.reason);
  };

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="relative hidden min-h-screen w-[54%] overflow-hidden lg:block">
        <BeePlate />
      </aside>

      <main className="relative flex min-h-screen flex-1 flex-col">
        <div className="pointer-events-none absolute inset-0 lg:hidden">
          <BeePlate dimmed />
        </div>

        <div className="relative z-10 flex min-h-screen flex-1 flex-col justify-between px-400 py-400 lg:px-600 lg:py-600">
          <header className="flex items-center gap-150">
            <EqualizerMark size={28} />
            <span className="heading-medium font-semibold text-text">PayInt</span>
            <Lozenge tone="information">Beeonix</Lozenge>
          </header>

          <div className="max-w-md py-600">
            <p className="text-body-small font-medium uppercase tracking-wide text-text-subtle">
              Autonomous Payment Intelligence
            </p>
            <h1 className="mt-150 heading-xxlarge text-text">
              The floor is already working the book.
            </h1>
            <p className="mt-200 text-body-large text-text-subtle">
              Sign in with Microsoft to open the floor. A.P.I.S decides which account to work next,
              on which channel, and why.
            </p>

            <button
              type="button"
              onClick={() => void onSignIn()}
              disabled={busy}
              className="mt-400 flex h-12 w-full items-center justify-center gap-150 rounded-medium border border-border bg-surface text-body font-medium text-text transition-colors hover:bg-background-neutral-subtle-hovered focus-ring disabled:cursor-not-allowed disabled:opacity-50"
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

            <ul className="mt-600 space-y-200">
              {CLAIMS.map((c) => (
                <li key={c.k}>
                  <p className="text-body font-medium text-text">{c.k}</p>
                  <p className="mt-025 text-body-small text-text-subtle">{c.v}</p>
                </li>
              ))}
            </ul>
          </div>

          <footer className="flex flex-wrap items-center gap-150 text-body-small text-text-subtlest">
            <img src="/brand/bigtapp.png" alt="" width={22} height={22} className="rounded-small" />
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
