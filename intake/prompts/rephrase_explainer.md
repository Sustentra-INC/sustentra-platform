---
prompt_id: rephrase_explainer
version: 1.0.0
purpose: >
  Explain an onboarding question a second way, for a client who read the
  standard explanation and still was not sure.
variables:
  - question
  - explainer
  - context
returns: json
---

A small business owner was asked the question below. They read the standard
explanation and told us they are still not sure. Explain it again, differently.

## The question

{question}

## The explanation they already read (do not repeat it)

{explainer}

## What we already know about this client

{context}

## Rules

1. Do not restate the explanation they just read. Come at it from another angle:
   a concrete example, or what they might physically look for.
2. Use their world, not ours. If they run a film studio, talk about the things
   in a film studio. Never use the words scope, boundary, consolidation,
   emissions factor, or activity data.
3. Keep it under sixty words. Two or three short sentences.
4. Tell them what to look at or where to check, not what the answer should be.
   Never suggest an answer.
5. If the honest position is that someone would need to check the building or
   the paperwork, say so plainly. "It is fine not to know this" is a good
   answer; guessing is not.
6. Never imply the question is simple or that they should already know it.

## Output

Return only a JSON object, with no commentary around it:

```json
{
  "explainer": "",
  "suggests_escalation": false
}
```

- `explainer` - the new explanation, in plain language.
- `suggests_escalation` - true if this genuinely needs someone from the
  Sustentra team to answer rather than the client.
