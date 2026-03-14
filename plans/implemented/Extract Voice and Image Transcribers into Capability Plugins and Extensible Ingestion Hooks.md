# Plan: Extract Voice/Image Transcribers into Capability Plugins + Extensible Ingestion Hooks

## Summary
This change will split XMPP-owned media transcribers into two standalone plugins (`voice_transcriber`, `image_transcriber`), expose their capabilities to other plugins through new hook contracts, register model-callable tools in both standard and research tool registries, and extend corpus ingestion to support plugin-provided file handlers. XMPP will depend on these plugins via manifest dependency metadata and consume them through capability hooks (not direct imports).  
Decisions locked from your inputs:
- Two separate plugins.
- Hook-based capability exposure.
- Tools exposed in standard + research modes.
- Model tools accept HTTPS only.
- Ingestion supports HTTPS and local files under configured roots.
- XMPP media URLs remain transcription-only (no auto corpus ingest).
- Plugin config files are hard cutover (no legacy `xmpp.voice_*` / `xmpp.image_*` fallback).
- Voice backend remains current behavior with clear failures on unsupported OS, but internals must be structured for future OS backends.
- Tools support optional prompt argument.

## Done Definition (Observable End State)
- `create_tool_registry()` and `create_research_tool_registry()` include `transcribe_audio_url` and `transcribe_image_url` when corresponding plugin tool config is enabled.
- Tool calls to `transcribe_*_url` reject `file://`, `local://`, and bare local paths with deterministic error text; HTTPS succeeds/fails with structured payload.
- Local corpus ingestion accepts plugin-supported media file extensions and indexes transcribed/captioned text into cache/vector store.
- XMPP daemon no longer imports `plugins.xmpp_daemon.voice_transcriber` or `plugins.xmpp_daemon.image_transcriber`; it resolves transcriber capabilities via hook registration.
- XMPP message flow for media URLs remains immediate transcription queue/ack behavior only.
- Plugin roster defines `xmpp_daemon` dependency on `voice_transcriber` and `image_transcriber`.
- Full test suite passes (`uv run pytest`).

## Public APIs / Interfaces / Types (Important Changes)
- New plugin hook constants and payloads in hook system:
  - `PLUGIN_CAPABILITY_REGISTER`
  - `LOCAL_SOURCE_HANDLER_REGISTER`
- New payload/spec dataclasses in plugin hook types:
  - `PluginCapabilityRegisterContext` with `capabilities: dict[str, Any]`
  - `LocalSourceHandlerSpec` (extension list + read callable + MIME metadata)
  - `LocalSourceHandlerRegisterContext` with `handlers: list[LocalSourceHandlerSpec]`
- New tool schemas (plugin-contributed via existing `TOOL_REGISTRY_BUILD`):
  - `transcribe_audio_url(url: str, prompt?: str, language?: str)`
  - `transcribe_image_url(url: str, prompt?: str)`
- Plugin manifest dependency metadata is explicitly used for transcriber->XMPP relationship (already supported by manager; now used by bundled roster).

## File Inventory

### Create
- [src/asky/plugins/voice_transcriber/__init__.py](/Users/evren/code/asky/src/asky/plugins/voice_transcriber/__init__.py)
- [src/asky/plugins/voice_transcriber/plugin.py](/Users/evren/code/asky/src/asky/plugins/voice_transcriber/plugin.py)
- [src/asky/plugins/voice_transcriber/service.py](/Users/evren/code/asky/src/asky/plugins/voice_transcriber/service.py)
- [src/asky/plugins/voice_transcriber/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/voice_transcriber/AGENTS.md)
- [src/asky/plugins/image_transcriber/__init__.py](/Users/evren/code/asky/src/asky/plugins/image_transcriber/__init__.py)
- [src/asky/plugins/image_transcriber/plugin.py](/Users/evren/code/asky/src/asky/plugins/image_transcriber/plugin.py)
- [src/asky/plugins/image_transcriber/service.py](/Users/evren/code/asky/src/asky/plugins/image_transcriber/service.py)
- [src/asky/plugins/image_transcriber/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/image_transcriber/AGENTS.md)
- [src/asky/data/config/voice_transcriber.toml](/Users/evren/code/asky/src/asky/data/config/voice_transcriber.toml)
- [src/asky/data/config/image_transcriber.toml](/Users/evren/code/asky/src/asky/data/config/image_transcriber.toml)
- [tests/test_plugin_capabilities.py](/Users/evren/code/asky/tests/test_plugin_capabilities.py)
- [tests/test_transcriber_tools.py](/Users/evren/code/asky/tests/test_transcriber_tools.py)
- [tests/test_local_source_handler_plugins.py](/Users/evren/code/asky/tests/test_local_source_handler_plugins.py)

### Modify
- [src/asky/plugins/hook_types.py](/Users/evren/code/asky/src/asky/plugins/hook_types.py)
- [src/asky/plugins/__init__.py](/Users/evren/code/asky/src/asky/plugins/__init__.py)
- [src/asky/plugins/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/AGENTS.md)
- [src/asky/research/adapters.py](/Users/evren/code/asky/src/asky/research/adapters.py)
- [src/asky/plugins/xmpp_daemon/document_ingestion.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/document_ingestion.py)
- [src/asky/plugins/xmpp_daemon/router.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/router.py)
- [src/asky/plugins/xmpp_daemon/xmpp_service.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/xmpp_service.py)
- [src/asky/plugins/xmpp_daemon/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/AGENTS.md)
- [src/asky/data/config/plugins.toml](/Users/evren/code/asky/src/asky/data/config/plugins.toml)
- [src/asky/data/config/xmpp.toml](/Users/evren/code/asky/src/asky/data/config/xmpp.toml)
- [src/asky/config/loader.py](/Users/evren/code/asky/src/asky/config/loader.py)
- [src/asky/config/__init__.py](/Users/evren/code/asky/src/asky/config/__init__.py)
- [src/asky/config/AGENTS.md](/Users/evren/code/asky/src/asky/config/AGENTS.md)
- [src/asky/research/AGENTS.md](/Users/evren/code/asky/src/asky/research/AGENTS.md)
- [tests/test_voice_transcription.py](/Users/evren/code/asky/tests/test_voice_transcription.py)
- [tests/test_image_transcription.py](/Users/evren/code/asky/tests/test_image_transcription.py)
- [tests/test_xmpp_daemon.py](/Users/evren/code/asky/tests/test_xmpp_daemon.py)
- [tests/test_xmpp_router.py](/Users/evren/code/asky/tests/test_xmpp_router.py)
- [tests/test_xmpp_document_ingestion.py](/Users/evren/code/asky/tests/test_xmpp_document_ingestion.py)
- [tests/test_research_adapters.py](/Users/evren/code/asky/tests/test_research_adapters.py)
- [tests/test_plugin_manager.py](/Users/evren/code/asky/tests/test_plugin_manager.py)
- [tests/test_config.py](/Users/evren/code/asky/tests/test_config.py)
- [ARCHITECTURE.md](/Users/evren/code/asky/ARCHITECTURE.md)
- [DEVLOG.md](/Users/evren/code/asky/DEVLOG.md)

### Delete
- [src/asky/plugins/xmpp_daemon/voice_transcriber.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/voice_transcriber.py)
- [src/asky/plugins/xmpp_daemon/image_transcriber.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/image_transcriber.py)

### Discovery Commands (Run Before Edits to Confirm No Missed Call Sites)
- `rg -n "xmpp_daemon.voice_transcriber|xmpp_daemon.image_transcriber|XMPP_VOICE_|XMPP_IMAGE_" src tests`
- `rg -n "LOCAL_SUPPORTED_EXTENSIONS|SUPPORTED_DOCUMENT_EXTENSIONS|fetch_source_via_adapter" src tests`
- `rg -n "TOOL_REGISTRY_BUILD|SUPPORTED_HOOK_NAMES" src tests`

## Before/After Mapping (By Concern)
- Before: XMPP plugin owns media transcriber classes directly. After: media logic lives in dedicated plugins and XMPP consumes capability providers via hook contracts.
- Before: only built-in local file extensions are supported by `research/adapters.py`. After: adapters merge built-in + plugin-provided handlers/extensions.
- Before: only existing tools are available unless plugin adds via `TOOL_REGISTRY_BUILD`; no media tools. After: transcriber plugins add two media URL tools in both standard and research registries.
- Before: media config lives in `xmpp.toml` and `asky.config` `XMPP_VOICE_*`/`XMPP_IMAGE_*` constants. After: media config lives in dedicated plugin config files; no legacy fallback.
- Before: XMPP transcriber imports are concrete class imports from package-local modules. After: XMPP uses capability objects and worker interfaces from hook registry.

## Sequential Atomic Steps

1. Add hook contracts for plugin capabilities and local source handlers.  
Files: [src/asky/plugins/hook_types.py](/Users/evren/code/asky/src/asky/plugins/hook_types.py), [src/asky/plugins/__init__.py](/Users/evren/code/asky/src/asky/plugins/__init__.py).  
Verification: `uv run pytest tests/test_plugin_hooks.py tests/test_plugin_integration.py -q`.

2. Implement dynamic plugin-handler resolution in local source adapter pipeline.  
Before: static extension sets + built-in readers only. After: built-in readers plus hook-contributed handlers and extension list aggregation.  
Files: [src/asky/research/adapters.py](/Users/evren/code/asky/src/asky/research/adapters.py).  
Verification: `uv run pytest tests/test_research_adapters.py tests/test_local_source_handler_plugins.py -q`.

3. Implement `voice_transcriber` plugin package with OS-strategy abstraction and reusable service API.  
Before: queue worker coupled to XMPP module. After: plugin-owned service supports background worker factory (for XMPP), synchronous transcribe interfaces (for tools/ingestion), and clear unsupported-OS errors.  
Files: [src/asky/plugins/voice_transcriber/service.py](/Users/evren/code/asky/src/asky/plugins/voice_transcriber/service.py), [src/asky/plugins/voice_transcriber/plugin.py](/Users/evren/code/asky/src/asky/plugins/voice_transcriber/plugin.py), [src/asky/plugins/voice_transcriber/__init__.py](/Users/evren/code/asky/src/asky/plugins/voice_transcriber/__init__.py).  
Verification: `uv run pytest tests/test_voice_transcription.py tests/test_transcriber_tools.py -q -k "voice"`.

4. Implement `image_transcriber` plugin package with reusable service API.  
Before: queue worker and multimodal call in XMPP module. After: plugin-owned service supports background worker factory, synchronous caption/transcribe API, and tool registration.  
Files: [src/asky/plugins/image_transcriber/service.py](/Users/evren/code/asky/src/asky/plugins/image_transcriber/service.py), [src/asky/plugins/image_transcriber/plugin.py](/Users/evren/code/asky/src/asky/plugins/image_transcriber/plugin.py), [src/asky/plugins/image_transcriber/__init__.py](/Users/evren/code/asky/src/asky/plugins/image_transcriber/__init__.py).  
Verification: `uv run pytest tests/test_image_transcription.py tests/test_transcriber_tools.py -q -k "image"`.

5. Register new model tools and enforce URL policy (HTTPS-only for model tools).  
Before: no media URL tools. After: `transcribe_audio_url` and `transcribe_image_url` appear in standard/research registries when plugin tool flags are enabled; local paths are rejected in tool executors.  
Files: [src/asky/plugins/voice_transcriber/plugin.py](/Users/evren/code/asky/src/asky/plugins/voice_transcriber/plugin.py), [src/asky/plugins/image_transcriber/plugin.py](/Users/evren/code/asky/src/asky/plugins/image_transcriber/plugin.py), [tests/test_transcriber_tools.py](/Users/evren/code/asky/tests/test_transcriber_tools.py).  
Verification: `uv run pytest tests/test_plugin_integration.py tests/test_transcriber_tools.py -q`.

6. Wire XMPP to capability providers and remove direct transcriber imports.  
Before: `xmpp_service` constructs concrete transcriber classes from `xmpp_daemon` package and router uses transcriber job dataclasses from those files. After: service resolves capability objects via hook, creates workers through provider API, router enqueues plain job payloads through worker interface.  
Files: [src/asky/plugins/xmpp_daemon/xmpp_service.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/xmpp_service.py), [src/asky/plugins/xmpp_daemon/router.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/router.py), [tests/test_xmpp_daemon.py](/Users/evren/code/asky/tests/test_xmpp_daemon.py), [tests/test_xmpp_router.py](/Users/evren/code/asky/tests/test_xmpp_router.py), [tests/test_safety_and_resilience_guards.py](/Users/evren/code/asky/tests/test_safety_and_resilience_guards.py).  
Verification: `uv run pytest tests/test_xmpp_daemon.py tests/test_xmpp_router.py tests/test_safety_and_resilience_guards.py -q`.

7. Extend document ingestion to use dynamic extension support while preserving selected UX behavior.  
Before: document ingestion extension list is static from built-in adapters. After: extension list includes plugin-provided handler extensions, ingestion remains synchronous, local-root guard remains enforced, and XMPP media URL flow remains transcription-only (no auto corpus ingest for media URLs in chat messages).  
Files: [src/asky/plugins/xmpp_daemon/document_ingestion.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/document_ingestion.py), [src/asky/plugins/xmpp_daemon/xmpp_service.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/xmpp_service.py), [tests/test_xmpp_document_ingestion.py](/Users/evren/code/asky/tests/test_xmpp_document_ingestion.py), [tests/test_xmpp_daemon.py](/Users/evren/code/asky/tests/test_xmpp_daemon.py).  
Verification: `uv run pytest tests/test_xmpp_document_ingestion.py tests/test_xmpp_daemon.py -q -k "ingest or split_document_urls"`.

8. Move configuration to plugin config files and remove legacy XMPP media config constants (hard cutover).  
Before: `xmpp.toml` + `XMPP_VOICE_*`/`XMPP_IMAGE_*` constants drive media behavior. After: `voice_transcriber.toml` and `image_transcriber.toml` drive media plugin behavior; legacy constants/keys removed; no fallback.  
Files: [src/asky/data/config/voice_transcriber.toml](/Users/evren/code/asky/src/asky/data/config/voice_transcriber.toml), [src/asky/data/config/image_transcriber.toml](/Users/evren/code/asky/src/asky/data/config/image_transcriber.toml), [src/asky/config/loader.py](/Users/evren/code/asky/src/asky/config/loader.py), [src/asky/config/__init__.py](/Users/evren/code/asky/src/asky/config/__init__.py), [src/asky/data/config/xmpp.toml](/Users/evren/code/asky/src/asky/data/config/xmpp.toml), [tests/test_config.py](/Users/evren/code/asky/tests/test_config.py).  
Verification: `uv run pytest tests/test_config.py -q`.

9. Add plugin roster entries and inter-plugin dependency metadata.  
Before: bundled roster has no media plugins and `xmpp_daemon` has no explicit dependencies. After: roster includes `voice_transcriber` and `image_transcriber`; `xmpp_daemon.dependencies = ["voice_transcriber","image_transcriber"]`; each plugin has `config_file` pointing to its dedicated file.  
Files: [src/asky/data/config/plugins.toml](/Users/evren/code/asky/src/asky/data/config/plugins.toml), [tests/test_plugin_manager.py](/Users/evren/code/asky/tests/test_plugin_manager.py), [tests/test_plugin_capabilities.py](/Users/evren/code/asky/tests/test_plugin_capabilities.py).  
Verification: `uv run pytest tests/test_plugin_manager.py tests/test_plugin_capabilities.py -q`.

10. Remove legacy XMPP transcriber modules and finalize import path updates.  
Before: old module files exist. After: files deleted and all references updated.  
Files: [src/asky/plugins/xmpp_daemon/voice_transcriber.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/voice_transcriber.py), [src/asky/plugins/xmpp_daemon/image_transcriber.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/image_transcriber.py), plus all call sites found by discovery rg.  
Verification: `rg -n "xmpp_daemon.voice_transcriber|xmpp_daemon.image_transcriber" src tests` should return no results.

11. Documentation and devlog updates required by repo policy.  
Files: [ARCHITECTURE.md](/Users/evren/code/asky/ARCHITECTURE.md), [DEVLOG.md](/Users/evren/code/asky/DEVLOG.md), [src/asky/plugins/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/AGENTS.md), [src/asky/plugins/xmpp_daemon/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/AGENTS.md), [src/asky/research/AGENTS.md](/Users/evren/code/asky/src/asky/research/AGENTS.md), [src/asky/config/AGENTS.md](/Users/evren/code/asky/src/asky/config/AGENTS.md), [src/asky/plugins/voice_transcriber/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/voice_transcriber/AGENTS.md), [src/asky/plugins/image_transcriber/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/image_transcriber/AGENTS.md).  
Verification: `rg -n "voice_transcriber|image_transcriber|PLUGIN_CAPABILITY_REGISTER|LOCAL_SOURCE_HANDLER_REGISTER" ARCHITECTURE.md src/asky/**/AGENTS.md DEVLOG.md`.

12. Final regression verification.  
Command: `uv run pytest`.  
Expected result: all tests pass with no newly introduced warnings.

## Edge Cases (Explicit Requirements)
- Tool URL validation must reject empty URL, non-HTTPS schemes, local file URIs, and bare local paths.
- Ingestion path handling must keep root boundary checks (`research.local_document_roots`) for local targets.
- Generic MIME (`application/octet-stream`) must continue extension-based inference; strict MIME checks remain for PDF/EPUB and text-like files.
- Voice backend on non-macOS must return explicit failure payload (no silent pass) while preserving future backend pluggability via strategy abstraction.
- Worker shutdown semantics must remain deterministic and graceful.
- If required transcriber capability is missing at runtime despite dependencies, XMPP startup must fail with clear user-facing error.
- XMPP media URL handling remains transcription-only and must not create duplicate ingestion actions for the same URL in normal chat flow.
- Tool registration must respect plugin disabled/tool flags and `disabled_tools`.

## Assumptions and Defaults
- Python/runtime dependencies remain unchanged; no new third-party packages.
- Tool names are `transcribe_audio_url` and `transcribe_image_url`.
- Optional prompt argument is supported in both tools; default prompts are used when omitted.
- Ingestion is synchronous.
- Hard config cutover is intentional; legacy `xmpp.voice_*` / `xmpp.image_*` keys are removed without fallback.
- Existing inter-plugin dependency metadata in manifest is sufficient; this plan uses it and does not introduce a second dependency system.

## Explicit Constraints (What Not to Do)
- Do not use direct imports from XMPP plugin to transcriber plugin internals; use hook-based capability exchange.
- Do not let model tools access local files.
- Do not add global singletons for transcriber sharing.
- Do not add unlisted dependencies.
- Do not reintroduce duplicate media logic in XMPP package.
- Do not broaden ingestion root permissions beyond configured corpus roots.
- Do not auto-ingest XMPP media URLs during normal transcription flow.

## Final Verification Commands
- `uv run pytest tests/test_plugin_hooks.py tests/test_plugin_integration.py tests/test_plugin_manager.py -q`
- `uv run pytest tests/test_voice_transcription.py tests/test_image_transcription.py tests/test_transcriber_tools.py -q`
- `uv run pytest tests/test_research_adapters.py tests/test_local_source_handler_plugins.py tests/test_xmpp_document_ingestion.py -q`
- `uv run pytest tests/test_xmpp_daemon.py tests/test_xmpp_router.py tests/test_xmpp_commands.py tests/test_safety_and_resilience_guards.py -q`
- `uv run pytest`

## Final Checklist
- [ ] New hooks and payload types added and documented.
- [ ] Voice/Image transcriber plugins created with clear service abstractions.
- [ ] XMPP uses capability hooks and depends on transcriber plugins via manifest metadata.
- [ ] Old XMPP transcriber modules deleted.
- [ ] Media tools available in standard and research registries with HTTPS-only policy.
- [ ] Ingestion file handler extension path implemented and root guard preserved.
- [ ] Config moved to plugin config files with hard cutover.
- [ ] AGENTS docs and ARCHITECTURE updated for all touched subdirectories.
- [ ] DEVLOG entry added with date, summary, gotchas, and follow-ups.
- [ ] Full test suite passes.
