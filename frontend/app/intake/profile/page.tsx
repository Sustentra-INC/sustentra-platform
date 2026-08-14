"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { CoverageMeter } from "../../../components/intake/CoverageMeter";
import {
  BUTTON_LINK,
  CARD,
  HEADING,
  LEDE,
  MUTED,
  NOTICE_ERROR,
  NOTICE_FLAG,
  NOTICE_INFO,
  SECTION_TITLE,
  SITE_BLOCK
} from "../../../components/intake/styles";
import { getProfile, getProfileHistory } from "../../../lib/api/intake-profile";
import { readableTime } from "../../../lib/intake-format";
import type {
  Profile,
  ProfileDatapoint,
  ProfileHistory,
  ProfileSite
} from "../../../lib/intake-types";

type Phase = "loading" | "ready" | "unauthenticated" | "error";

const HISTORY_PAGE = 40;

const SUBHEAD = "mb-2 text-sm font-semibold tracking-wide text-brand uppercase";

function describe(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.map(describe).join(", ") || "-";
  if (typeof value === "object") {
    return (
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== null && item !== undefined && item !== "")
        .map(([key, item]) => `${key.replace(/_/g, " ")}: ${describe(item)}`)
        .join(", ") || "-"
    );
  }
  return String(value);
}

function siteAddress(site: ProfileSite): string {
  const address = site.address ?? {};
  return [address.address_line, address.city, address.state_region, address.country_region]
    .filter(Boolean)
    .join(", ");
}

/** Colour is a hint, never the only signal - each row also states its status. */
function statusTone(status: string): string {
  if (status === "escalated") return "text-flag";
  if (status === "not_present") return "text-ink-soft";
  return "text-ink";
}

function DatapointRow({ entry }: { entry: ProfileDatapoint }) {
  return (
    <li className="border-t border-line py-3 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-semibold">{entry.question ?? entry.label}</span>
        {entry.scope_label ? <span className={MUTED}>{entry.scope_label}</span> : null}
      </div>

      <p className={statusTone(entry.status)}>
        {entry.status_label}
        {entry.value ? <> — {describe(entry.value)}</> : null}
      </p>

      <p className={MUTED}>
        {/* A derived value has no author, so it does not read "answered by". */}
        {entry.answered_by === "system"
          ? "Derived automatically"
          : entry.answered_by_label
            ? `Answered by ${entry.answered_by_label}`
            : "No answer yet"}
        {entry.answered_by !== "system" && entry.actor_id ? ` (${entry.actor_id})` : ""}
        {entry.value_basis ? ` · ${entry.value_basis}` : ""}
        {entry.ai_assisted ? " · read by AI, confirmed by the client" : ""}
      </p>

      {entry.note ? <p className={MUTED}>{entry.note}</p> : null}
    </li>
  );
}

export default function ProfilePage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [history, setHistory] = useState<ProfileHistory | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    let cancelled = false;

    Promise.all([getProfile(), getProfileHistory({ limit: HISTORY_PAGE })])
      .then(([loadedProfile, loadedHistory]) => {
        if (cancelled) return;
        setProfile(loadedProfile);
        setHistory(loadedHistory);
        setPhase("ready");
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const text = caught instanceof Error ? caught.message : "Could not load your profile.";
        if (text.toLowerCase().includes("sign-in")) {
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

  if (phase === "loading") {
    return (
      <section>
        <h1 className={HEADING}>Your carbon profile</h1>
        <p className={LEDE}>Gathering your record.</p>
      </section>
    );
  }

  if (phase === "unauthenticated") {
    return (
      <section>
        <h1 className={HEADING}>Please sign in</h1>
        <p className={LEDE}>Your session has expired or you are not signed in yet.</p>
        <Link href="/intake/login" className={BUTTON_LINK}>
          Go to sign in
        </Link>
      </section>
    );
  }

  if (phase === "error" || !profile) {
    return (
      <section>
        <h1 className={HEADING}>Your carbon profile</h1>
        <div className={NOTICE_ERROR} role="alert">
          <p>{message ?? "Could not load your profile."}</p>
        </div>
      </section>
    );
  }

  const { company, coverage } = profile;

  return (
    <section>
      <h1 className={HEADING}>{company.legal_name ?? "Your carbon profile"}</h1>
      <p className={LEDE}>
        Everything on your record, and where each answer came from. This page is the version
        an auditor reads, so every change to it is kept.
      </p>

      <CoverageMeter coverage={coverage} />

      {profile.with_the_team.length > 0 ? (
        <div className={NOTICE_INFO}>
          <p>
            {profile.with_the_team.length} question
            {profile.with_the_team.length === 1 ? " is" : "s are"} with our team. Nothing is
            needed from you — we will email you when they are answered.
          </p>
        </div>
      ) : null}

      {/* Company */}
      <div className={CARD}>
        <h2 className={`${SECTION_TITLE} mb-3`}>Company</h2>
        <dl className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
          {[
            ["Reporting year", company.reporting_year],
            [
              "Reporting period",
              company.reporting_period_start && company.reporting_period_end
                ? `${company.reporting_period_start} to ${company.reporting_period_end}`
                : null
            ],
            ["Year basis", company.fiscal_year_basis],
            ["Industry", company.industry],
            [
              "Responsible party",
              company.responsible_party
                ? `${company.responsible_party.name}, ${company.responsible_party.role}`
                : null
            ]
          ].map(([label, value]) => (
            <div key={String(label)} className="mb-1">
              <dt className={MUTED}>{label}</dt>
              <dd>{describe(value)}</dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Sites */}
      <div className={CARD}>
        <h2 className={`${SECTION_TITLE} mb-3`}>
          Sites ({profile.sites.length})
        </h2>
        {profile.sites.map((site) => (
          <div key={site.site_id} className={SITE_BLOCK}>
            <p className="font-semibold">{site.site_name}</p>
            <p className={MUTED}>{siteAddress(site)}</p>
            <p className={MUTED}>
              {describe(site.site_type)} · {describe(site.ownership)}
              {site.lease_type ? ` (${site.lease_type})` : ""} · {describe(site.operational_status)}
            </p>
            {site.ownership_note ? <p className={MUTED}>{site.ownership_note}</p> : null}
            {site.deferred_boundary_fields.length > 0 ? (
              <p className={`${MUTED} mt-1`}>
                {site.deferred_boundary_fields.length} boundary field
                {site.deferred_boundary_fields.length === 1 ? "" : "s"} left unset on purpose,
                pending confirmation.
              </p>
            ) : null}
          </div>
        ))}
      </div>

      {/* Boundary decisions get their own block: a verifier reads these first. */}
      {profile.boundary_decisions.length > 0 ? (
        <div className={CARD}>
          <h2 className={`${SECTION_TITLE} mb-1`}>Boundary decisions</h2>
          <p className={`${MUTED} mb-2`}>
            What counts as yours. Every one of these is confirmed by a person.
          </p>
          <ul className="list-none p-0">
            {profile.boundary_decisions.map((entry) => (
              <DatapointRow
                key={`${entry.datapoint_id}:${entry.scope_ref ?? "org"}`}
                entry={entry}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {/* Every question, by section. Boundary has its own block above, so it is
          not repeated here - the same six questions twice is noise, not detail.

          Collapsed by default. Every answer belongs on this page, but forty of
          them opened at once is a wall nobody reads; the counts above each one
          are what a client actually scans for. Plain <details> so it works
          without JavaScript and a screen reader announces the state. */}
      {profile.sections
        .filter((section) => section.section_id !== "boundary")
        .map((section) => (
          <details key={section.section_id} className={`${CARD} py-5`}>
            <summary className="flex cursor-pointer list-none items-baseline justify-between gap-4">
              <span className="font-display text-lg">{section.label}</span>
              <span className={MUTED}>
                {section.complete} of {section.total}
              </span>
            </summary>
            <ul className="mt-3 list-none p-0">
              {section.datapoints.map((entry) => (
                <DatapointRow
                  key={`${entry.datapoint_id}:${entry.scope_ref ?? "org"}`}
                  entry={entry}
                />
              ))}
            </ul>
          </details>
        ))}

      {/* These two are deliberately separate: absent is not the same as omitted. */}
      <div className={CARD}>
        <h2 className={`${SECTION_TITLE} mb-1`}>Screened and not present</h2>
        <p className={`${MUTED} mb-2`}>
          Sources we checked for and confirmed you do not have. This is a completeness
          record, not an exclusion — it shows an auditor that the question was asked.
        </p>
        {profile.completeness_records.length === 0 ? (
          <p className={MUTED}>Nothing screened out yet.</p>
        ) : (
          <ul className="list-none p-0">
            {profile.completeness_records.map((entry) => (
              <li key={`${entry.datapoint_id}:${entry.scope_ref ?? "org"}`} className="mb-1">
                {entry.question ?? entry.label}
                {entry.scope_label ? <span className={MUTED}> — {entry.scope_label}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className={CARD}>
        <h2 className={`${SECTION_TITLE} mb-1`}>Exclusions</h2>
        <p className={`${MUTED} mb-2`}>
          Sources that exist but are left out, with the reason. Recorded against EXC-010.
        </p>
        {profile.exclusions.length === 0 ? (
          <p className={MUTED}>Nothing excluded.</p>
        ) : (
          <ul className="list-none p-0">
            {profile.exclusions.map((item, index) => (
              <li key={index} className="mb-2">
                <p>{describe(item.value)}</p>
                <p className={MUTED}>
                  Confirmed by {item.confirmed_by ?? "unknown"}
                  {item.actor_id ? ` (${item.actor_id})` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Uncertainty */}
      {profile.uncertainty.length > 0 ? (
        <div className={CARD}>
          <h2 className={`${SECTION_TITLE} mb-1`}>How we know</h2>
          <p className={`${MUTED} mb-2`}>
            Whether each figure is metered, invoiced or estimated. This feeds the
            uncertainty assessment an auditor expects.
          </p>
          <ul className="list-none p-0">
            {profile.uncertainty.map((item, index) => (
              <li key={index} className="mb-1">
                {item.label ?? item.datapoint_id}
                {item.scope_label ? <span className={MUTED}> — {item.scope_label}</span> : null}
                <span className={MUTED}> · {describe(item.value_basis)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Provisional values */}
      {profile.provisional_values.length > 0 ? (
        <div className={NOTICE_FLAG}>
          <p className={SUBHEAD}>Awaiting expert sign-off</p>
          <ul className="list-none p-0">
            {profile.provisional_values.map((item, index) => (
              <li key={index}>
                {item.field_id.replace(/_/g, " ")}
                {item.scope_label ? ` (${item.scope_label})` : ""} — {item.requires_signoff}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* History */}
      <div className={CARD}>
        <h2 className={`${SECTION_TITLE} mb-1`}>History</h2>
        <p className={`${MUTED} mb-2`}>
          Every change to this profile, oldest first. {history?.count ?? 0} recorded.
        </p>
        <button
          type="button"
          className={BUTTON_LINK}
          aria-expanded={showHistory}
          onClick={() => setShowHistory((open) => !open)}
        >
          {showHistory ? "Hide history" : "Show history"}
        </button>

        {showHistory && history ? (
          <ul className="mt-3 list-none p-0">
            {history.entries.map((entry, index) => (
              <li key={index} className="mb-1">
                <span className={MUTED}>{readableTime(entry.at)}</span>{" "}
                {entry.label ?? entry.field ?? entry.action.replace(/_/g, " ")}
                {entry.old_value !== null && entry.old_value !== undefined ? (
                  <>
                    : {describe(entry.old_value)} → {describe(entry.new_value)}
                  </>
                ) : (
                  <>: {describe(entry.new_value)}</>
                )}
                <span className={MUTED}> ({entry.actor_id})</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
