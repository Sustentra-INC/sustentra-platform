"use client";

import { useSyncExternalStore } from "react";

import { ACTOR_KEY, getActor, SESSION_CHANGE_EVENT, type Actor } from "./session";

// Cache by raw string so the snapshot is stable between renders
// (getActor() parses JSON and returns a new object every call).
let cachedRaw: string | null = null;
let cachedActor: Actor | null = null;

function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(SESSION_CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(SESSION_CHANGE_EVENT, onChange);
  };
}

function getSnapshot(): Actor | null {
  const raw = window.localStorage.getItem(ACTOR_KEY);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedActor = raw ? getActor() : null;
  }
  return cachedActor;
}

function getServerSnapshot(): Actor | null {
  return null;
}

/** The signed-in actor from local storage; re-renders on login/logout (this tab or others). */
export function useActor(): Actor | null {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
