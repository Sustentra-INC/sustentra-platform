"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { IntakeField } from "../../../components/intake/IntakeField";
import {
  BUTTON,
  BUTTON_LINK,
  BUTTON_SECONDARY,
  CARD,
  FIELD_GRID,
  HEADING,
  LEDE,
  MUTED,
  NOTICE_ERROR,
  NOTICE_FLAG,
  SITE_BLOCK
} from "../../../components/intake/styles";
import { getCurrentUser, getSeedFormSchema, submitSeedForm } from "../../../lib/api/intake";
import {
  FieldError,
  FormValues,
  SeedFormError,
  SeedFormField,
  SeedFormSchema,
  SeedFormSubmitResult
} from "../../../lib/intake-types";

type Phase = "loading" | "ready" | "submitting" | "done" | "unauthenticated" | "error";

function isVisible(field: SeedFormField, values: FormValues): boolean {
  if (field.input === "derived") return false;
  if (!field.visible_when) return true;
  return values[field.visible_when.field_id] === field.visible_when.equals;
}

function blankValues(fields: SeedFormField[]): FormValues {
  return Object.fromEntries(fields.map((field) => [field.field_id, ""]));
}

export default function SeedFormPage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [schema, setSchema] = useState<SeedFormSchema | null>(null);
  const [company, setCompany] = useState<FormValues>({});
  const [sites, setSites] = useState<FormValues[]>([]);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<SeedFormSubmitResult | null>(null);

  const companyStep = useMemo(
    () => schema?.steps.find((step) => step.step_id === "company"),
    [schema]
  );
  const sitesStep = useMemo(
    () => schema?.steps.find((step) => step.step_id === "sites"),
    [schema]
  );

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        await getCurrentUser();
        const loaded = await getSeedFormSchema();
        if (cancelled) return;

        const companyFields = loaded.steps.find((s) => s.step_id === "company")?.fields ?? [];
        const siteFields = loaded.steps.find((s) => s.step_id === "sites")?.fields ?? [];

        setSchema(loaded);
        setCompany(blankValues(companyFields));
        setSites([blankValues(siteFields)]);
        setPhase("ready");
      } catch (caught) {
        if (cancelled) return;
        const text = caught instanceof Error ? caught.message : "Could not load the form.";
        if (text.toLowerCase().includes("sign-in") || text.includes("401")) {
          setPhase("unauthenticated");
        } else {
          setMessage(text);
          setPhase("error");
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // The industry chosen in step 1 selects the vocabulary overlay that step 2's
  // site-type question depends on. The org has no industry yet the first time
  // through, so the form starts on the general overlay and re-fetches once the
  // client picks one - otherwise a film client would get a free-text site type
  // instead of the mapped soundstage/backlot/office/workshop list.
  const selectedOverlay = useMemo(() => {
    const industryField = companyStep?.fields.find((field) => field.field_id === "industry");
    return industryField?.options?.find((option) => option.value === company.industry)
      ?.overlay_id;
  }, [companyStep, company.industry]);

  useEffect(() => {
    if (!schema || !selectedOverlay || selectedOverlay === schema.overlay_id) return;

    let cancelled = false;
    getSeedFormSchema(selectedOverlay)
      .then((next) => {
        if (cancelled) return;
        setSchema(next);
        // A site type valid under one overlay may not exist under another.
        setSites((current) => current.map((site) => ({ ...site, site_type: "" })));
      })
      .catch(() => {
        // Keep the current schema; the server validates the submission regardless.
      });

    return () => {
      cancelled = true;
    };
  }, [schema, selectedOverlay]);

  const errorFor = useCallback(
    (fieldId: string, index?: number) =>
      errors.find(
        (error) =>
          error.field === fieldId &&
          (index === undefined ? error.index === undefined : error.index === index)
      )?.message,
    [errors]
  );

  function updateCompany(fieldId: string, value: string) {
    setCompany((current) => ({ ...current, [fieldId]: value }));
  }

  function updateSite(index: number, fieldId: string, value: string) {
    setSites((current) =>
      current.map((site, position) => (position === index ? { ...site, [fieldId]: value } : site))
    );
  }

  function addSite() {
    if (!sitesStep) return;
    setSites((current) => [...current, blankValues(sitesStep.fields)]);
  }

  function removeSite(index: number) {
    setSites((current) => current.filter((_, position) => position !== index));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPhase("submitting");
    setErrors([]);
    setMessage(null);

    try {
      const submitted = await submitSeedForm({ company, sites });
      setResult(submitted);
      setPhase("done");
    } catch (caught) {
      if (caught instanceof SeedFormError) {
        setErrors(caught.errors);
        setMessage("Please check the highlighted answers.");
      } else {
        setMessage(caught instanceof Error ? caught.message : "Could not save your answers.");
      }
      setPhase("ready");
    }
  }

  if (phase === "loading") {
    return (
      <section>
        <h1 className={HEADING}>Loading your form</h1>
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

  if (phase === "done" && result) {
    const flagged = result.submission.provisional_values;
    return (
      <section>
        <h1 className={HEADING}>Thank you - that is saved</h1>
        <p className={LEDE}>
          We have recorded {result.org.legal_name}, covering {result.org.reporting_period_start}{" "}
          to {result.org.reporting_period_end}.
        </p>

        <div className={CARD}>
          <h2 className="mb-3 text-lg font-semibold">Your sites</h2>
          <dl>
            {result.sites.map((site) => (
              <div key={site.site_id} className="mt-2 first:mt-0">
                <dt className="font-semibold">{site.site_name}</dt>
                <dd className="text-ink-soft">
                  {site.site_type.replace(/_/g, " ")} &middot; {site.ownership}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        {flagged.length > 0 ? (
          <div className={NOTICE_FLAG}>
            <p>
              {flagged.length} answer{flagged.length === 1 ? "" : "s"} used a wording our team is
              still agreeing a standard list for. We have recorded them and someone will confirm -
              nothing is wrong with what you entered.
            </p>
          </div>
        ) : null}

        <p>Next, we will walk through each site with a short set of questions.</p>
      </section>
    );
  }

  const submitting = phase === "submitting";

  return (
    <section>
      <h1 className={HEADING}>About your company</h1>
      <p className={LEDE}>
        This takes a few minutes. Nothing here needs carbon accounting knowledge - if you are
        unsure about anything, give your best answer and we will confirm it with you.
      </p>

      {message ? (
        <div className={NOTICE_ERROR} role="alert">
          <p>{message}</p>
        </div>
      ) : null}

      <form onSubmit={onSubmit} noValidate>
        {companyStep ? (
          <div className={CARD}>
            <header className="mb-5">
              <h2 className="text-lg font-semibold">{companyStep.label}</h2>
              <p className={MUTED}>{companyStep.description}</p>
            </header>
            <div className={FIELD_GRID}>
              {companyStep.fields
                .filter((field) => isVisible(field, company))
                .map((field) => (
                  <div
                    key={field.field_id}
                    className={field.input === "textarea" ? "sm:col-span-2" : undefined}
                  >
                    <IntakeField
                      field={field}
                      value={company[field.field_id] ?? ""}
                      error={errorFor(field.field_id)}
                      onChange={updateCompany}
                    />
                  </div>
                ))}
            </div>
          </div>
        ) : null}

        {sitesStep ? (
          <div className={CARD}>
            <header className="mb-5">
              <h2 className="text-lg font-semibold">{sitesStep.label}</h2>
              <p className={MUTED}>{sitesStep.description}</p>
            </header>

            {errorFor("sites") ? (
              <div className={NOTICE_ERROR} role="alert">
                <p>{errorFor("sites")}</p>
              </div>
            ) : null}

            {sites.map((site, index) => (
              <div className={SITE_BLOCK} key={index}>
                <header className="mb-4 flex items-baseline justify-between">
                  <h3 className="font-semibold">Site {index + 1}</h3>
                  {sites.length > 1 ? (
                    <button
                      type="button"
                      className={BUTTON_LINK}
                      onClick={() => removeSite(index)}
                    >
                      Remove
                    </button>
                  ) : null}
                </header>
                <div className={FIELD_GRID}>
                  {sitesStep.fields
                    .filter((field) => isVisible(field, site))
                    .map((field) => (
                      <div
                        key={field.field_id}
                        className={field.input === "textarea" ? "sm:col-span-2" : undefined}
                      >
                        <IntakeField
                          field={field}
                          value={site[field.field_id] ?? ""}
                          error={errorFor(field.field_id, index)}
                          onChange={(fieldId, value) => updateSite(index, fieldId, value)}
                          idPrefix={`site-${index}-`}
                        />
                      </div>
                    ))}
                </div>
              </div>
            ))}

            <button type="button" className={BUTTON_SECONDARY} onClick={addSite}>
              Add another site
            </button>
          </div>
        ) : null}

        <div className="mt-6 flex items-center gap-3">
          <button type="submit" className={BUTTON} disabled={submitting}>
            {submitting ? "Saving..." : "Save and continue"}
          </button>
          <span className={MUTED}>You can come back and change these later.</span>
        </div>
      </form>
    </section>
  );
}
