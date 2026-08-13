"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { IntakeField } from "../../../components/intake/IntakeField";
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

  const errorFor = useCallback(
    (fieldId: string, index?: number) =>
      errors.find(
        (error) =>
          error.field === fieldId && (index === undefined ? error.index === undefined : error.index === index)
      )?.message,
    [errors]
  );

  function updateCompany(fieldId: string, value: string) {
    setCompany((current) => ({ ...current, [fieldId]: value }));
  }

  function updateSite(index: number, fieldId: string, value: string) {
    setSites((current) =>
      current.map((site, position) =>
        position === index ? { ...site, [fieldId]: value } : site
      )
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
        <h1>Loading your form</h1>
        <p className="lede">One moment.</p>
      </section>
    );
  }

  if (phase === "unauthenticated") {
    return (
      <section>
        <h1>Please sign in</h1>
        <p className="lede">Your session has expired or you are not signed in yet.</p>
        <Link href="/intake/login" className="intake-button">
          Go to sign in
        </Link>
      </section>
    );
  }

  if (phase === "error") {
    return (
      <section>
        <h1>Something went wrong</h1>
        <div className="intake-notice error" role="alert">
          <p>{message}</p>
        </div>
      </section>
    );
  }

  if (phase === "done" && result) {
    const flagged = result.submission.provisional_values;
    return (
      <section>
        <h1>Thank you - that is saved</h1>
        <p className="lede">
          We have recorded {result.org.legal_name}, covering {result.org.reporting_period_start}{" "}
          to {result.org.reporting_period_end}.
        </p>

        <div className="intake-card">
          <h2>Your sites</h2>
          <dl className="intake-summary">
            {result.sites.map((site) => (
              <div key={site.site_id}>
                <dt>{site.site_name}</dt>
                <dd>
                  {site.site_type.replace(/_/g, " ")} &middot; {site.ownership}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        {flagged.length > 0 ? (
          <div className="intake-notice flag">
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
      <h1>About your company</h1>
      <p className="lede">
        This takes a few minutes. Nothing here needs carbon accounting knowledge - if you are
        unsure about anything, give your best answer and we will confirm it with you.
      </p>

      {message ? (
        <div className="intake-notice error" role="alert">
          <p>{message}</p>
        </div>
      ) : null}

      <form onSubmit={onSubmit} noValidate>
        {companyStep ? (
          <div className="intake-card">
            <header>
              <h2>{companyStep.label}</h2>
              <p>{companyStep.description}</p>
            </header>
            <div className="field-grid">
              {companyStep.fields.filter((field) => isVisible(field, company)).map((field) => (
                <div
                  key={field.field_id}
                  className={field.input === "textarea" ? "full" : undefined}
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
          <div className="intake-card">
            <header>
              <h2>{sitesStep.label}</h2>
              <p>{sitesStep.description}</p>
            </header>

            {errorFor("sites") ? (
              <div className="intake-notice error" role="alert">
                <p>{errorFor("sites")}</p>
              </div>
            ) : null}

            {sites.map((site, index) => (
              <div className="site-block" key={index}>
                <header>
                  <h3>Site {index + 1}</h3>
                  {sites.length > 1 ? (
                    <button
                      type="button"
                      className="intake-button link"
                      onClick={() => removeSite(index)}
                    >
                      Remove
                    </button>
                  ) : null}
                </header>
                <div className="field-grid">
                  {sitesStep.fields.filter((field) => isVisible(field, site)).map((field) => (
                    <div
                      key={field.field_id}
                      className={field.input === "textarea" ? "full" : undefined}
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

            <button type="button" className="intake-button secondary" onClick={addSite}>
              Add another site
            </button>
          </div>
        ) : null}

        <div className="intake-actions">
          <button type="submit" className="intake-button" disabled={submitting}>
            {submitting ? "Saving..." : "Save and continue"}
          </button>
          <span className="optional-tag">You can come back and change these later.</span>
        </div>
      </form>
    </section>
  );
}
