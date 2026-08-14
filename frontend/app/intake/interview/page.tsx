"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { CoverageMeter } from "../../../components/intake/CoverageMeter";
import { QuestionCard } from "../../../components/intake/QuestionCard";
import { StageStepper } from "../../../components/intake/StageStepper";
import {
  BUTTON,
  BUTTON_LINK,
  HEADING,
  LEDE,
  NOTICE_ERROR,
  NOTICE_FLAG,
  NOTICE_INFO
} from "../../../components/intake/styles";
import {
  getNextQuestion,
  sayNotSure,
  startInterview,
  submitAnswer
} from "../../../lib/api/intake";
import {
  Coverage,
  FieldError,
  InterviewQuestion,
  SeedFormError
} from "../../../lib/intake-types";

type Phase = "loading" | "asking" | "done" | "unauthenticated" | "error";

/**
 * How long a save may take before we admit to it.
 *
 * Most saves come back in well under this, and flashing "Saving…" for 60ms
 * reads as the app struggling. Past this the client deserves to know something
 * is happening.
 */
const BUSY_VISIBLE_AFTER_MS = 300;

export default function InterviewPage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [question, setQuestion] = useState<InterviewQuestion | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showBusy, setShowBusy] = useState(false);
  const busyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function beginWork() {
    setBusy(true);
    busyTimer.current = setTimeout(() => setShowBusy(true), BUSY_VISIBLE_AFTER_MS);
  }

  function endWork() {
    if (busyTimer.current) clearTimeout(busyTimer.current);
    busyTimer.current = null;
    setBusy(false);
    setShowBusy(false);
  }

  useEffect(() => {
    let cancelled = false;

    startInterview()
      .then((result) => {
        if (cancelled) return;
        setQuestion(result.next);
        setCoverage(result.coverage);
        setPhase(result.next ? "asking" : "done");
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const text = caught instanceof Error ? caught.message : "Could not start.";
        if (text.toLowerCase().includes("sign-in") || text.includes("401")) {
          setPhase("unauthenticated");
        } else {
          setMessage(text);
          setPhase("error");
        }
      });

    return () => {
      cancelled = true;
      if (busyTimer.current) clearTimeout(busyTimer.current);
    };
  }, []);

  async function onAnswer(answer: Record<string, unknown>, aiAssisted = false) {
    if (!question) return;
    beginWork();
    setErrors([]);
    setMessage(null);

    try {
      const result = await submitAnswer({
        datapoint_id: question.datapoint_id,
        scope_ref: question.scope_ref,
        answer,
        ai_assisted: aiAssisted
      });
      setHandoff(
        result.escalated
          ? "That one needs a specialist. It is with our team now — nothing for you to do."
          : null
      );
      setCoverage(result.coverage);
      setQuestion(result.next);
      if (!result.next) setPhase("done");
    } catch (caught) {
      if (caught instanceof SeedFormError) {
        setErrors(caught.errors);
        setMessage("Just one or two things to check below.");
      } else {
        setMessage(caught instanceof Error ? caught.message : "Could not save that answer.");
      }
    } finally {
      endWork();
    }
  }

  async function onNotSure() {
    if (!question) return;
    beginWork();
    setErrors([]);
    setMessage(null);

    try {
      const result = await sayNotSure({
        datapoint_id: question.datapoint_id,
        scope_ref: question.scope_ref
      });
      // The rephrase is shown alongside the hand-over, so they still get a
      // clearer explanation even though the question is now with our team.
      setHandoff([result.another_way, result.message].filter(Boolean).join(" "));
      setCoverage(result.coverage);
      setQuestion(result.next);
      if (!result.next) setPhase("done");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Could not do that just now.");
    } finally {
      endWork();
    }
  }

  if (phase === "loading") {
    return (
      <section>
        <h1 className={HEADING}>Getting your questions ready</h1>
        <p className={LEDE}>One moment.</p>
      </section>
    );
  }

  if (phase === "unauthenticated") {
    return (
      <section className="intake-enter">
        <h1 className={HEADING}>Please sign in</h1>
        <p className={LEDE}>Your session has expired.</p>
        <Link href="/intake/login" className={`${BUTTON} inline-block no-underline`}>
          Go to sign in
        </Link>
      </section>
    );
  }

  if (phase === "error") {
    return (
      <section className="intake-enter">
        <h1 className={HEADING}>Something went wrong</h1>
        <div className={NOTICE_ERROR} role="alert">
          <p>{message}</p>
        </div>
      </section>
    );
  }

  if (phase === "done") {
    return (
      <section className="intake-enter">
        <StageStepper current="profile" />
        <h1 className={HEADING}>That is everything</h1>
        <p className={LEDE}>
          Thank you — you have answered everything we can ask at this stage.
        </p>

        {coverage && coverage.escalated > 0 ? (
          <div className={NOTICE_FLAG}>
            <p>
              {coverage.escalated} question{coverage.escalated === 1 ? " is" : "s are"} with
              our team. We will email you when they are answered.
            </p>
          </div>
        ) : null}

        <Link href="/intake/profile" className={`${BUTTON} inline-block no-underline`}>
          See your profile
        </Link>
      </section>
    );
  }

  return (
    <section>
      <StageStepper current="questions" />

      <h1 className={HEADING}>A few questions about your operations</h1>
      <p className={LEDE}>
        Mostly yes or no. If you are unsure about any of them, say so — we will sort it out.
      </p>

      {coverage ? <CoverageMeter coverage={coverage} /> : null}

      {handoff ? (
        <div className={`${NOTICE_INFO} intake-enter`}>
          <p>{handoff}</p>
        </div>
      ) : null}

      {message ? (
        <div className={NOTICE_ERROR} role="alert">
          <p>{message}</p>
        </div>
      ) : null}

      {question ? (
        <QuestionCard
          key={`${question.datapoint_id}:${question.scope_ref ?? "org"}`}
          question={question}
          errors={errors}
          busy={busy}
          showBusy={showBusy}
          onAnswer={onAnswer}
          onNotSure={onNotSure}
          onHandedOver={async (text) => {
            setHandoff(text);
            const step = await getNextQuestion();
            setCoverage(step.coverage);
            setQuestion(step.next);
            if (!step.next) setPhase("done");
          }}
        />
      ) : null}
    </section>
  );
}
