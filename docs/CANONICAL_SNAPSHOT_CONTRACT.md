# Canonical snapshot contract — v3, pending Claude review

This is the preprocessor's local file contract. Bridge application is not implemented or live-verified. Publish the reviewed contract through Bridge Codex after Preprocessor Claude reviews the implementation.

## Primary mileage

`canonical_workouts.csv.confirmed_training_distance_mi` is the bridge-facing confirmed intentional **foot-based** distance. It equals `training_distance_miles`; summary `training_miles` sums it once per active parent. Running, trail, intentional walking/hiking and measured foot movement inside the outing count. Cycling does not count here: use `cycling_distance_m`, `cycling_duration_s` and summary `cycling_miles` / `cycling_duration_s` separately.

An unclassified standalone walk has nullable `intentional_training`, null official training distance, measured `unclassified_training_distance_m`, `training_distance_status=unclassified` and a review row. Generic time-of-day watch names do not establish intent. Explicit persistent intent or a clearly named recovery/training walking workout does. Running/hiking recordings default to intentional workouts. Unknown or mixed source modality stays reviewable unless supported classification is supplied. Informational source rows remain unchanged.

Confirmed partial distance counts; incomplete distance and intent remain visible through flags and separate amounts. `candidate_training_distance_m` is an unconfirmed additional gap amount; `unclassified_training_distance_m` is known movement whose training eligibility is unsettled. Do not add both to official mileage. `provisional_training_distance_m` is not authoritative. Unknown stays null. Summary `known_unclassified_training_miles` retains quantified unclassified distance when another unknown amount prevents a complete subtotal.

## Scoped replacement and retirement

`canonical_dataset_manifest.json` defines a complete replacement snapshot for `snapshot_scope` (default `jay-training`). It is never an additive upsert batch. All active rows are in `workouts`; historical removed IDs are in `retired_workouts`, with `counts_toward_training_totals=false`, their prior revision/date/source IDs/stable source keys, replacement IDs and retirement reason. A split can have multiple replacement IDs. Tombstones persist across reruns so missing an intermediate import does not lose retirement lineage.

IDs are based on stable source identities; unchanged grouping retains its ID. Changed content, decisions or policy changes revision. Regrouping retires absent old IDs. Stable Intervals keys handle changed FIT hashes. An explicitly removed source may have no replacement. Restored identities become active again and lose their active tombstone.

The importer must atomically replace **only its canonical actuals store for this scope**, remove obsolete contributions before applying replacements, and recompute affected days/weeks from active rows. Preserve plans, personal notes, shoes, strength and other separately owned data. Use `recompute_local_dates` / `recompute_week_starting_dates`, which retain both old and new dates after moves. Replaying the same snapshot must leave values/totals unchanged; a dataset revision is a content identifier, not an ordering number. The bridge must reject stale concurrent imports using its own revision protocol and distinguish migration from raw imports.

The pipeline compares against the prior successful ZIP manifest (loose manifest fallback for initial migration). A shrinking source-key set requires `--allow-source-removals` after coverage verification. Changed scope requires a separate output directory. Never import a partial archive as an authoritative replacement. These guards do not prove an archive has all historic workouts; the producer must verify its intended coverage. A first snapshot supplies no history before the first stored manifest; the consumer still replaces its complete scope rather than relying solely on tombstones.

No bridge implementation, raw-to-canonical migration, transport contract or atomic application verification is supplied by this module. Canonical import remains blocked until those are implemented and reviewed. Local tests verify merges, splits, source removals, source reexports, restored identities, date changes and deterministic reruns, not Google Sheets behavior.
