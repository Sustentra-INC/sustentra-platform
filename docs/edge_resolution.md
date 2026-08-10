# Edge Resolution

Subsystem 2 PR8 adds a runtime interpretation layer for methodology EDGES.

PR3 made edges queryable by field. PR8 classifies each edge by runtime
treatment so later services can distinguish real joins from rule inputs,
applicability context, and disclosure relationships.

## Runtime Treatments

| `Reference_Type` | Runtime treatment | Join? |
|---|---|---:|
| `fk` | `foreign_key_join` | yes |
| `rule_input` | `rule_input` | no |
| `scope` | `applicability_scope` | no |
| `writes_to` | `scope_writes_to_gen` | no |
| `disclosed_via` | `scope_disclosed_via_gen` | no |
| other/blank | `unsupported_reference_type` | no |

The most important invariant is:

```text
rule_input must not be treated as a foreign key join.
```

Rules may read a GEN value, but that does not mean the schema should be joined
through that edge.

## Usage

```python
service = EdgeResolutionService(methodology_registry)

all_edges = service.list_edges_for_field("INV-010")
join_edges = service.list_join_edges_for_field("INV-010")
non_join_edges = service.list_non_join_edges_for_field("INV-010")
```

Resolved edges include:

```text
edge
treatment
is_join
field_id
reason
```

## Wildcards

Wildcard expansion is owned by the methodology registry from PR3. PR8 consumes
that behavior, so wildcard-backed edges such as `S2-EFS-*` are returned for
matching concrete fields such as `S2-EFS-010`.

## Non-Goals

PR8 does not:

- execute rules,
- run joins against engagement data,
- compute derived values,
- evaluate completeness,
- execute formulas.

Those belong to later S2 PRs.
