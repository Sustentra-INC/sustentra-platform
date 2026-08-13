"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { CoverageMeter } from "../../../components/intake/CoverageMeter";
import { QuestionCard } from "../../../components/intake/QuestionCard";
import {
  BUTTON,
  HEADING,
  LEDE,
  NOTICE_ERROR,
  NOTICE_FLAG,
  NOTICE_INFO
} from "../../../components/intake/styles";
import { sayNotSure, startInterview, submitAnswer } from "../../../lib/api/intake";
import {
  Coverage,
  FieldError,
  InterviewQuestion,
  SeedFormError
} from "../../../lib/intake-types";

type Phase = "loading" | "asking" | "done" | "unauthenticated" | "error";

export default function InterviewPage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [question, setQuestion] = useState<InterviewQuestion | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    };
  }, []);

  async function onAnswer(answer: Record<string, unknown>) {
    if (!question) return;
    setBusy(true);
    setErrors([]);
    setMessage(null);

    try {
      const result = await submitAnswer({
        datapoint_id: question.datapoint_id,
        scope_ref: question.scope_ref,
        answer
      });
      setHandoff(
        result.escalated
          ? "That one needs a specialist - we have passed it to our team and will come back to you."
          : null
      );
      setCoverage(result.coverage);
      setQuestion(result.next);
      if (!result.next) setPhase("done");
    } catch (caught) {
      if (caught instanceof SeedFormError) {
        setErrors(caught.errors);
        setMessage("Please check the highlighted answers.");
      } else {
        setMessage(caught instanceof Error ? caught.message : "Could not save that answer.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function onNotSure() {
    if (!question) return;
    setBusy(true);
    setErrors([]);
    setMessage(null);

    try {
      const result = await sayNotSure({
        datapoint_id: question.datapoint_id,
        scope_ref: question.scope_ref
      });
      setHandoff(result.message);
      setCoverage(result.coverage);
      setQuestion(result.next);
      if (!result.next) setPhase("done");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Could not do that just now.");
    } finally {
      setBusy(false);
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
      <section>
        <h1 className={HEADING}>Please sign in</h1>
        <p className={LEDE}>Your session has expired or you are not signed in yet.</p>
        <Link href="/intake/login" className={`${BUTTON} inline-block no-underline`}>
          Go to sign in
        </Link>
      </section>
    );
  }

  if (phase === "error") {
    return (
      <section>
        <h1 className={HEADING}>Something went wrong</h1>
        <div className={NOTICE_ERROR} role="alert">
          <p>{message}</p>
        </div>
      </section>
    );
  }

  if (phase === "done") {
    return (
      <section>
        <h1 className={HEADING}>That is everything for now</h1>
        <p className={LEDE}>
          Thank you - you have answered everything we can ask at this stage.
        </p>
        {coverage ? <CoverageMeter coverage={coverage} /> : null}
        {coverage && coverage.escalated > 0 ? (
          <div className={NOTICE_FLAG}>
            <p>
              {coverage.escalated} question{coverage.escalated === 1 ? " is" : "s are"} with our
              team. We will email you as soon as they are answered - nothing is needed from you.
            </p>
          </div>
        ) : null}
        <p>Next, we will ask for the documents that back this up.</p>
      </section>
    );
  }

  return (
    <section>
      <h1 className={HEADING}>A few questions about your operations</h1>
      <p className={LEDE}>
        Short questions, mostly yes or no. If you are unsure about any of them, say so - we will
        sort it out and keep you moving.
      </p>

      {coverage ? <CoverageMeter coverage={coverage} /> : null}

      {handoff ? (
        <div className={NOTICE_INFO}>
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
          onAnswer={onAnswer}
          onNotSure={onNotSure}
        />
      ) : null}
    </section>
  );
}
