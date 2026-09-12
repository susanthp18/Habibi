"""Persona & Prompt Studio reads and writes.

Peeled from ``db.py`` (WP-036 peel 10). Reads and writes move together:
seventeen internal write→read edges make splitting them a mistake. Call
sites stay ``db.*`` via a bottom-of-file re-export. Reach the engine
through :func:`_db`, never ``from db_core import engine``: the ``db_tx``
fixture wraps ``db.engine``, and a name bound from ``db_core`` bypasses
that proxy.

``list_bot_ids``, ``_iso_ts``, ``get_latest_eval_report`` and
``_latest_twin_gate_report`` stay on ``db.py`` (inbox / db_evals). This
module reaches them through ``_db()``.
"""

from __future__ import annotations

from db_prompt_studio.common import (  # noqa: F401
    _BUNDLE_HASH_COL as _BUNDLE_HASH_COL,
    _CHAIN_HEADS_TABLE as _CHAIN_HEADS_TABLE,
    _COMPILED_COL as _COMPILED_COL,
    _FROZEN_TOOLS_COL as _FROZEN_TOOLS_COL,
    _bundle_hash_select as _bundle_hash_select,
    _column_exists as _column_exists,
    _compiled_select as _compiled_select,
    _db as _db,
    _frozen_tools_select as _frozen_tools_select,
)
from db_prompt_studio.voices import (  # noqa: F401
    _map_catalog_row as _map_catalog_row,
    _tts_sync_run_row as _tts_sync_run_row,
    get_tts_voice_catalog_entry as get_tts_voice_catalog_entry,
    get_tts_voice_warning as get_tts_voice_warning,
    latest_tts_sync_run as latest_tts_sync_run,
    list_persona_presets as list_persona_presets,
    list_tts_price_tiers as list_tts_price_tiers,
    list_tts_sync_runs as list_tts_sync_runs,
    list_tts_voice_catalog as list_tts_voice_catalog,
    list_tts_voice_locale_counts as list_tts_voice_locale_counts,
    list_tts_voice_provider_counts as list_tts_voice_provider_counts,
    list_tts_voices as list_tts_voices,
    resolve_prompt_azure_voice as resolve_prompt_azure_voice,
    tts_catalog_is_populated as tts_catalog_is_populated,
    voice_locale_facts as voice_locale_facts,
    voice_provider_facts as voice_provider_facts,
)
from db_prompt_studio.deployments import (  # noqa: F401
    DEFAULT_BOT_ID as DEFAULT_BOT_ID,
    _active_deployment_sql as _active_deployment_sql,
    _fetch_active_deployment_row as _fetch_active_deployment_row,
    _fetch_bot_deployment as _fetch_bot_deployment,
    _latest_kb_snapshot_id as _latest_kb_snapshot_id,
    _map_bot_deployment_row as _map_bot_deployment_row,
    get_active_deployment as get_active_deployment,
    get_deployment as get_deployment,
    list_bot_deployments as list_bot_deployments,
    rollback_bot_deployment as rollback_bot_deployment,
)
from db_prompt_studio.versions import (  # noqa: F401
    _DEFAULT_AZURE_TTS_VOICE as _DEFAULT_AZURE_TTS_VOICE,
    _DEFAULT_GUARDRAILS as _DEFAULT_GUARDRAILS,
    _DEFAULT_PERSONA as _DEFAULT_PERSONA,
    _DEFAULT_VOICE as _DEFAULT_VOICE,
    _PROMPT_VERSION_SELECT as _PROMPT_VERSION_SELECT,
    _fetch_prompt_version as _fetch_prompt_version,
    _map_prompt_version as _map_prompt_version,
    _prompt_flow as _prompt_flow,
    _prompt_guardrails as _prompt_guardrails,
    _prompt_id_from_label as _prompt_id_from_label,
    _prompt_persona as _prompt_persona,
    _prompt_version_status as _prompt_version_status,
    _prompt_voice as _prompt_voice,
    _refuses_flow_write as _refuses_flow_write,
    _restorable_voice as _restorable_voice,
    create_prompt_version as create_prompt_version,
    discard_prompt_version as discard_prompt_version,
    get_prompt_version as get_prompt_version,
    get_published_prompt_version as get_published_prompt_version,
    list_prompt_versions as list_prompt_versions,
    patch_prompt_version as patch_prompt_version,
    restore_prompt_version_as_draft as restore_prompt_version_as_draft,
)
from db_prompt_studio.cards import (  # noqa: F401
    _agent_studio_card_summary as _agent_studio_card_summary,
    _handoff_edges as _handoff_edges,
    _live_deployment_bot_ids as _live_deployment_bot_ids,
    _studio_card_versions as _studio_card_versions,
    _worst_eval_status as _worst_eval_status,
    agent_change_log as agent_change_log,
    archive_agent_studio_card as archive_agent_studio_card,
    get_agent_studio_card as get_agent_studio_card,
    list_agent_studio_cards as list_agent_studio_cards,
    list_entry_bindings as list_entry_bindings,
    policy_engines as policy_engines,
    remove_entry_binding as remove_entry_binding,
    restore_agent_studio_card as restore_agent_studio_card,
    set_entry_binding as set_entry_binding,
)
from db_prompt_studio.compile import (  # noqa: F401
    _fleet_members as _fleet_members,
    compile_agent_studio_card as compile_agent_studio_card,
    doors_merging as doors_merging,
    get_effective_contract as get_effective_contract,
    recompile_published_bundle as recompile_published_bundle,
)
from db_prompt_studio.publish import (  # noqa: F401
    _Compiled as _Compiled,
    _Deployed as _Deployed,
    _Frozen as _Frozen,
    _change_log_components as _change_log_components,
    _compile as _compile,
    _deploy as _deploy,
    _freeze as _freeze,
    _record as _record,
    publish_prompt_version as publish_prompt_version,
    rebuild_fleet_deployment as rebuild_fleet_deployment,
)
