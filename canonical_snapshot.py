"""Complete, scoped canonical snapshots with explicit retirement (no bridge writes)."""
from __future__ import annotations
from datetime import date, timedelta
import json
from canonical_workouts import SCHEMA_VERSION, stable_id


def build_snapshot(workouts, source_count, previous=None, scope='jay-training', allow_source_removals=False, source_keys=None):
    """Replace the entire scope atomically downstream; never add snapshot totals.

    Historical tombstones retain lineage even when an intermediate export is skipped.
    Shrinking source coverage requires explicit acknowledgement to protect against
    accidental partial imports. Same-input reruns retain identical manifests.
    """
    previous = previous or {}
    if previous.get('snapshot_scope', scope) != scope:
        raise ValueError('Snapshot scope changed; use a separate output directory')
    active = []
    for w in workouts:
        entry = {k: w[k] for k in ('canonical_workout_id', 'revision', 'source_activity_ids', 'local_date')}
        entry['source_activity_keys'] = sorted({(source_keys or {}).get(s, s) for s in w.get('source_activity_keys', w['source_activity_ids'])})
        active.append(entry)
    active.sort(key=lambda w: w['canonical_workout_id'])
    if len({w['canonical_workout_id'] for w in active}) != len(active):
        raise ValueError('Duplicate canonical IDs in snapshot')
    old = {w['canonical_workout_id']: w for w in previous.get('workouts', [])}
    new = {w['canonical_workout_id']: w for w in active}
    old_sources = {s for w in old.values() for s in w.get('source_activity_keys', w['source_activity_ids'])}
    new_sources = {s for w in active for s in w.get('source_activity_keys', w['source_activity_ids'])}
    if old_sources - new_sources and not allow_source_removals:
        raise ValueError('Source coverage shrank; verify inventory, then use --allow-source-removals for deliberate removal')
    retired = {w['canonical_workout_id']: dict(w) for w in previous.get('retired_workouts', [])}
    for cid, w in old.items():
        if cid in new:
            continue
        replacements = sorted(nid for nid, n in new.items() if set(w.get('source_activity_keys', w['source_activity_ids'])) & set(n.get('source_activity_keys', n['source_activity_ids'])))
        retired[cid] = {**w, 'status': 'retired', 'counts_toward_training_totals': False,
                       'replacement_canonical_workout_ids': replacements,
                       'reason': 'regrouped' if replacements else 'source_removed'}
    # If a previous identity returns, the current snapshot is authoritative.
    for cid in new: retired.pop(cid, None)
    retired_rows = sorted(retired.values(), key=lambda w: w['canonical_workout_id'])
    dates = sorted(set(previous.get('recompute_local_dates', [])) | {w['local_date'] for w in [*active, *retired_rows, *old.values()] if w.get('local_date')})
    weeks = sorted({(date.fromisoformat(d) - timedelta(days=date.fromisoformat(d).weekday())).isoformat() for d in dates})
    manifest = {'schema_version': SCHEMA_VERSION, 'snapshot_scope': scope,
        'timezone': 'America/Los_Angeles', 'counting_basis': 'canonical_confirmed_intentional_foot_training',
        'training_mileage_field': 'confirmed_training_distance_mi', 'summary_training_mileage_field': 'training_miles',
        'modality_fields': ['running_distance_m', 'walking_distance_m', 'hiking_distance_m', 'unknown_training_distance_m', 'cycling_distance_m'],
        'candidate_policy': 'excluded_from_official_totals; confirmed_partial_foot_mileage_retained; ambiguous_intent_separate',
        'units': {'distance':'meters', 'display_distance':'miles', 'duration':'seconds', 'pace':'minutes/mile', 'elevation':'meters', 'heart_rate':'bpm'},
        'calendar_allocation': 'whole_workout_by_local_start_date',
        'lifecycle': 'complete_scope_replacement; retire_absent_ids_before_recompute; bridge_apply_not_implemented',
        'source_activity_count': source_count, 'canonical_workout_count': len(active),
        'workouts': active, 'retired_workouts': retired_rows,
        'recompute_local_dates': dates, 'recompute_week_starting_dates': weeks,
        'bridge_application': 'atomically replace all canonical records in snapshot_scope; recompute affected dates/weeks from active records; never increment totals'}
    manifest['dataset_revision'] = stable_id('dataset_', [json.dumps(manifest, sort_keys=True)])
    return manifest
