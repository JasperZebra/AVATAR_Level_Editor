# AGENTS.md — Avatar Level Editor

> This file provides context for AI agents working in this repository.

---

## Agent Instructions

This project is heavily vibe-coded and evolves quickly. These rules are **mandatory** — not suggestions. Read all of them before touching any file.

### 1. Clarify Before You Code

**Always** achieve full understanding of the task before touching any file. This means:

- Read the relevant source files first — do not assume based on filenames alone
- Identify all files that will be affected by the change
- If anything about the requirements is ambiguous, **ask follow-up questions** until the intent is clear
- Do not stop at one clarifying question — keep asking until there is no remaining ambiguity
- Confirm your understanding of the expected behavior (inputs, outputs, edge cases) before proceeding

> **Rule:** If you are unsure about anything, ask. A wrong assumption wastes more time than a follow-up question.

### 2. Write a Unit Test for Every Bug Fix — Without Being Asked

**This is not optional.** Whenever you fix a bug, immediately write a unit test that proves the fix works. Do not wait for the user to ask.

**Keep tests minimal and focused.** The target is 1–3 tests per fix:
- One regression test that directly proves the bug is gone
- One or two tests for genuinely distinct related cases — only if they add clear value

Do **not** write tests for every permutation, every error path, or every edge case you can think of. Writing 7 tests for a single invariant is over-engineering. Quality and focus over quantity.

**Do NOT run the test suite.** The user runs tests themselves. Never invoke `pytest`, `bash run_tests.sh`, or any test runner unless explicitly told to.

### 3. Update AGENTS.md After Every Task

After completing any task — bug fix, feature, or investigation — update this file with anything a future agent would need to know:

- Add new test files to the **Modules with tests** table in the Testing section
- Document non-obvious patterns, gotchas, or couplings discovered during the task
- If a significant architectural decision was made, note it under the relevant section

This step is **mandatory**, not optional. If you finish a task without updating this file, the task is incomplete.

### 4. Keep setup.py in Sync After Every Change

After any task that adds, removes, or renames a Python module or data file, verify `setup.py` is up to date:

- **New `.py` file in `canvas/`** → add `'canvas.<module_name>'` to the `packages` list
- **New root-level `.py` file** → add it to both `root_files` (include_files) and `packages`
- **New data directory** → add it to `directories_to_include`
- **Deleted or renamed module** → remove the old entry from `packages` and `root_files`

Frozen builds (`python setup.py build`) will silently break at runtime if a module is missing from `packages` — there is no build-time error. This makes stale `setup.py` a common source of "works in dev, crashes in release" bugs.

**Quick audit command** (run from project root):
```bash
# Find canvas modules not in setup.py packages list
for f in canvas/*.py; do m="canvas.$(basename $f .py)"; grep -q "'$m'" setup.py || echo "MISSING: $m"; done
```

### 5. Update README.md on User-Facing Changes

When a change affects how the user interacts with the app (new feature, changed shortcut, new behaviour), update `README.md` to keep user-facing docs accurate.

Minor bug fixes and internal refactors do not need README updates. Use judgment.

### 5. Document Findings as You Discover Them

When you discover things that would help future agents, add them to this file immediately:

- A non-obvious pattern or convention in the codebase
- A gotcha or footgun (e.g., "XML elements are mutated in place — don't deepcopy")
- A dependency or coupling between modules not obvious from imports
- How a specific system works that isn't documented

Keep findings concise and factual. Do not duplicate what is already here.

### 6. Commit and Push After Every Task

After completing any task, always commit the changes and push so the GitHub repo stays current:

```bash
git add <changed files>
git commit -m "<message in the format below>"
git push
```

- Remote: `git@github.com:JasperZebra/AVATAR_Level_Editor.git` (branch `dev` for ongoing work; `master` is the PR target)
- Stage the specific files you changed — do not `git add -A` blindly
- **Note:** `AGENTS.md` is tracked — commit it whenever Rule 3 updates it. `.gitignore` still excludes `tests/`, `tools/`, `cache/`, `.vscode/`, and config files — those cannot be committed.
- Never commit `patch_config.json`, `converter_debug.txt`, or anything from the game's data folders

### 7. Commit Message Format

All commits must use this format:

```text
docs/feat/fix/perf/refactor(or another appropriate type): title of change

problem: <description of problem>
solution: <description of solution>
impact: <impact of this change>
reference: <reference to this change in the docs if applicable>
```

---

## Testing

### Stack
- **pytest** + **pytest-cov** for tests and coverage reporting
- Tests live in `tests/` — one file per module under test
- `conftest.py` adds the project root to `sys.path` so modules import without a package install
- Run everything: `bash run_tests.sh` (runs pytest with coverage, enforces 85% minimum)
- Manual: `python -m pytest tests/ -v --tb=short --cov=<module> --cov-report=term-missing`

### Coverage target
85% per module. The `--cov-fail-under=85` flag in `run_tests.sh` enforces this.

### Modules with tests

| Module | Test file | Coverage | Notes |
|--------|-----------|----------|-------|
| `cache_manager.py` | `tests/test_cache_manager.py` | 88% | Included in `run_tests.sh` coverage enforcement |
| `hash_parser.py` | `tests/test_hash_parser.py` | 98% | Included in `run_tests.sh` coverage enforcement |
| `entity_editor.py` | `tests/test_entity_editor_encoding.py` | — | Only encoding functions (lines 24–153) tested; rest is GUI code — excluded from `--cov` to avoid dragging down totals |
| `canvas/map_canvas_gpu.py` | `tests/test_sector_violations.py` | — | Only `check_sector_violations` logic tested; full canvas requires OpenGL + QApplication — excluded from `--cov` |
| `simplified_map_editor.py` | `tests/test_rebuild_sector_xml.py` | — | Only the `rebuild_sector_xml` new-MissionLayer code path tested; full module requires OpenGL + QApplication — excluded from `--cov` |
| `simplified_map_editor.py` | `tests/test_worlds_save_flags.py` | — | Regression for mapsdata/omnis modification flags + hash-based dirty detection; uses stub editor — excluded from `--cov` |
| `simplified_map_editor.py` + `all_in_one_copy_paste.py` | `tests/test_landmark_save.py` | — | Landmark save/dirty/delete logic; no QApplication needed — excluded from `--cov` |
| `entity_export_import.py` | `tests/test_import_group_placement.py` | — | Regression for group import pivot/delta logic; tests pure functions, no QApplication — excluded from `--cov` |
| `canvas/mp_spawn_creator.py` | — | — | GUI dialog, no QApplication — excluded from `--cov` |
| `movie_data.py` | `tests/test_movie_data.py` | — | Pure stdlib parser; tests parsing, linear interpolation, slerp, dirty detection, save round-trip, `find_moviedata_xml` — excluded from `--cov` |
| `canvas/gpu_driven_renderer.py` | `tests/test_gdr_frame_assembly.py` | — | Pure-numpy frame assembly (`assemble_frame` / `build_group_templates` / `build_group_commands`) verified against naive reference loops; module loaded by **file path** (canvas/__init__.py is GL-heavy) — excluded from `--cov` |
| `canvas/sky_shader_sources.py` + `canvas/sky_atmosphere.py` | `tests/test_sky_shader_sources.py` | — | Embedded atmosphere GLSL present + `_adapt_common`/`_wrap_buffer` adaptation works with no files on disk; modules loaded by **file path** — excluded from `--cov` |
| `canvas/sky_atmosphere.py` | `tests/test_sky_lut_cache.py` | — | `_sky_lut_needs_rebuild` caches the sky-view LUT by sun elevation (rebuild on first call + on sun movement, skip when static / sub-rounding jitter); instance via `object.__new__`, module by **file path** — excluded from `--cov` |
| `canvas/water_plane_renderer.py` | `tests/test_strip_baked_water.py` | — | `strip_baked_water` removes the 'Water'-node mesh from terrain models, no-ops without one; loaded by **file path** — excluded from `--cov` |
| `canvas/terrain_to_gltf.py` | `tests/test_terrain_avatar_remap.py` | — | `_remap_avatar_sectors_to_zero_based` shifts Avatar multi-part sector keys (e.g. Tantalus part 2 sd256-sd511) to 0-based so 3D textures match 2D; no-op for part 1 / empty; instances built via `object.__new__` (skip disk-touching `__init__`), module loaded by **file path** — excluded from `--cov` |
| `theme_settings.py` | `tests/test_theme_settings_merge.py` | — | `_save_settings` merge-write preserves foreign keys (e.g. `render_tier`); handles missing/corrupt file — excluded from `--cov` |
| `simplified_map_editor.py` | `tests/test_first_run_flow.py` | — | First-run dialog sequencing: `_prompt_first_run_setup` chains into the welcome screen, never schedules `select_level`; uses stub editor + fake QTimer/QMessageBox — excluded from `--cov` |
| `simplified_map_editor.py` | `tests/test_fc2_sector_math.py` | — | FC2 global sector-grid math (`sector_grid_stride` 16/80, `global_sector_coords` local→global lift + passthrough) and `rebuild_sector_xml` `pos_offset` cell-local write-back; helpers **mirrored** in the test (module needs GL/Qt) — excluded from `--cov` |
| `canvas/terrain_editor_dialog.py` | `tests/test_terrain_editor_fc2.py` | — | FC2 `TerrainData`: `.sdat` offset-592 read, global-sd-numbering remap (row stride 80), save writes back to the recorded per-index source file preserving header/trailer bytes; Avatar `.csdat`/708 default unchanged; module loaded by **file path** — excluded from `--cov` |
| `set_patch_folder.py` | `tests/test_scan_print_encoding.py` | — | Encoding-safe `print` shim: ✓/✗ scan-log glyphs on a cp1252 stdout no longer raise UnicodeEncodeError (which aborted the whole folder scan with "0 worlds found") — excluded from `--cov` |
| `simplified_map_editor.py` | `tests/test_unified_thread_safety.py` | — | AST scan of the real `load_all_worldsectors` source: every GUI call (`set_entities`/`update_entity_tree`/`update_entity_statistics`/`processEvents`/`showMessage`) must be guarded by `_on_main_thread` (FC2 world1 background-thread access-violation regression) — excluded from `--cov` |
| `canvas/texture_loader.py` | `tests/test_xbt_cache_eviction.py` | — | `_xbt_cache` FIFO cap (`_xbt_cache_put`): decode cache no longer pins every texture's raw RGBA for the session (FC2 full-world OOM → glTexImage2D access violation); module loaded by **file path** — excluded from `--cov` |
| `canvas/model_loader.py` | `tests/test_vbo_build_budget.py` | — | `_ensure_mesh_vbo` per-frame build budget: exhausted budget defers (None + `_vbo_stream_pending`), built meshes bypass, unbuildable meshes fail permanently without consuming budget; module loaded by **file path** — excluded from `--cov` |
| `cache_manager.py` | `tests/test_terrain_cache_key_fc2.py` | — | `generate_terrain_cache_key` includes `*.sdat` (FC2) — old `.csdat`-only glob pinned stale FC2 terrain images with a never-changing path key |
| `canvas/map_canvas_gpu.py` | `tests/test_pick_landmark_priority.py` | — | 3D pick two-track resolution (**mirrored**): landmark LOD twins at the same spot lose to the real entity within a 3-unit tie tolerance; genuinely-closer landmarks still win; hidden sources unpickable — excluded from `--cov` |
| `canvas/mesh.py` + `canvas/xbg_parser.py` | `tests/test_xbg_vertex_decode.py` | — | Flag-driven vertex decode (component offsets for 0x0BCA/0x0BDA, unsigned-BGRA authored normal/tangent/color decode vs synthetic buffer) + DNKS byte-budget multi-block parse (5 blocks survive a lod_count of 2); modules imported with `canvas/` on sys.path — excluded from `--cov` |
| `canvas/texture_loader.py` | `tests/test_texture_slot_resolution.py` | — | Addon-delta slot mappings (heighttexture1→height, alphatexture1[wrap]→alpha) + `resolve_xbt_full_path` lowercase-retry fallback (case-sensitive extracted packs), via monkeypatched `os.path.exists` — excluded from `--cov` |
| `canvas/hkx_parser.py` | `tests/test_hkx_parser.py` | — | Builds a minimal SYNTHETIC Havok 5.5 packfile (rigid body + box shape wired through real fixup tables, ± 16-byte game wrapper) and checks parse → wireframe end-to-end; plus sphere/capsule wire builders and the .xbg↔.hkx sibling lookup — excluded from `--cov` |
| `canvas/cs_camera_preview.py` | `tests/test_cs_camera_preview.py` | — | Pose math only (no Qt/GL): quat rotation, +Y-forward / +Z-up camera conventions, game→GL mapping, pose from rest vs animated tracks, camera-node name filtering — excluded from `--cov` |
| `canvas/xbg_parser.py` | `tests/test_part_assembly.py` | — | Rigid vehicle-part assembly (`_apply_part_transforms`): part placed by name-matched bone; skinned / unmatched / identity-bone meshes untouched; built on synthetic Mesh+Bone objects, no file IO — excluded from `--cov` |
| `canvas/mab_parser.py` | `tests/test_mab_parser.py` | — | Smallest-three quat codec round-trip (all 4 permutation flags, SIGNED third word, s<0 sentinel) + synthetic clip: group/mask keyframe decode (primary @ sub-frame 0, flagged keys @ bit+1), anim-mask routing, derived fps, bone-name resolution — excluded from `--cov` |
| `canvas/xbg_direct_loader.py` | `tests/test_vehicle_attachments.py` | — | Mounted-weapon merge: baked matrix applied to verts (normals unrotated on pure translation), material indices offset, bounds widened; no-entry models untouched; `_resolve_attachment_path` data-root anchoring — monkeypatched table/builder, no game files — excluded from `--cov` |
| `simplified_map_editor.py` | `tests/test_stats_softwrap.py` | — | `_softwrap`: short values untouched, ZWSP inserted after `.`/`_`/`/`/`\`/`:` in dotted archetype names and Windows paths, invisible when stripped back out — instantiated via `SimplifiedMapEditor.__new__` (plain `object.__new__` is blocked by real PyQt5's sip on a QMainWindow subclass) — excluded from `--cov` |
| `canvas/map_canvas_gpu.py` | `tests/test_terrain_tile_cull.py` | — | Terrain-tile frustum culling (**mirrored** `_tile_sphere` / `_sphere_in_view`): tile ahead drawn, tile behind culled, off-to-the-side culled, big-radius-behind-eye rescued, distance alone never culls, unknown bounds drawn — excluded from `--cov` |
| `canvas/quad_batch.py` + `canvas/entity_renderer.py` | `tests/test_quad_batch_2d.py` | — | Instanced 2D squares: `build_instances` (N,8) column layout the shader's attribute pointers read; `classify_source`/`source_mask` parity with `_filter_entities_by_source` across all 16 toggle combinations; searchsorted visible-row lookup — excluded from `--cov` |
| `setup.py` | `tests/test_setup_packages.py` | — | Rule-4 guard: every `canvas/*.py` is in `packages`, every root app module is in BOTH `packages` and `root_files`; setup.py scanned as **text** (importing it runs PyQt5/PIL discovery). `DEV_ONLY` exempts standalone scripts — excluded from `--cov` |
| `simplified_map_editor.py` + `canvas/map_canvas_gpu.py` | `tests/test_movie_preview_perf.py` | — | Sequence-playback lag fix: `_movie_entity_map` caching + `_movie_register_preview_entities` re-registering when the moving set changes (real code, `SimplifiedMapEditor.__new__`); preview row-index patching and the overlay-cache bypass decision **mirrored** (canvas needs GL/Qt) — excluded from `--cov` |

### Key patterns used
- **Dependency injection via constructor**: `CacheManager(cache_dir=str(tmp_path), enabled=True/False)` — no mocks needed for most tests
- **`tmp_path` fixture**: all filesystem side-effects are isolated in pytest's temp dir; tests never touch the real `cache/` directory
- **`monkeypatch.setattr(cache_manager, 'QPixmap', FakePixmap)`**: replaces the module-level `QPixmap` name to test terrain caching without a running `QApplication`
- **`FakePixmap`**: defined at the top of the test file; implements `isNull()`, `toImage()`, `save()` so it satisfies all callers
- **Singleton isolation**: use `monkeypatch.setattr(cm_module, '_cache_manager_instance', None)` before each singleton test to prevent cross-test pollution
- **Pure function tests**: `entity_editor.py` encoding functions can be imported and tested without a `QApplication` — PyQt6 can be imported at module level without a running display

### What is NOT tested (and why)
- `except ImportError` branch for PyQt6 (lines 28–30 of `cache_manager.py`) — PyQt6 is always installed in this environment
- `_init_cache_dirs` exception handler — requires filesystem permission failure, not worth faking
- `if __name__ == "__main__"` block — excluded by `[coverage:report] exclude_lines` in `pytest.ini`
- Most other uncovered lines are `except Exception` handlers that require injecting errors deep into stdlib calls
- GUI classes in `entity_editor.py` — all require a running `QApplication`; not tested

### hash_parser.py gotcha
Members are indexed from **all** class elements regardless of whether the parent class has a `hash` attribute. A class with no `hash` but with `<member hash="..." name="..."/>` children will still populate `member_hash_map`.

### Entity browser — left dock (tabs)

The left dock (`entity_browser_dock`) contains a shared filter bar and a `QTabWidget` (`self.browser_tabs`) with two tabs:

**Tab 0 — "Entities"**: the original `self.entity_tree` (QTreeWidget) with Select All / Select None / Refresh / +Angles buttons. Behaviour unchanged.

**Tab 1 — "Mission Layers"**: `self.mission_layer_tree` (QTreeWidget, columns: "Layer / Entity", "Type", "Position"). Groups entities by `text_hidMissionLayerPath` from `CMissionComponent`. Top-level = mission script (part before `\`), sub-level italic = layer name (part after `\`). Entities with no layer path → **"Main"** group.

- Expanded/collapsed state is saved before each rebuild and restored after — switching tabs does NOT reset collapsed items.
- Selection calls `self.on_entity_selected(primary_entity)` — identical to Tab 0; updates the Entity Editor, canvas highlight, gizmo, model preview, and property panel.
- `update_mission_layer_tree()` is called when Tab 1 is active during `update_entity_tree()` and `filter_entities()`.
- **Expand All / Collapse All** buttons sit in `TopRightCorner` of the tab bar via `setCornerWidget`; they act on whichever tab is currently active.

**Key field name:** Mission layer path is `text_hidMissionLayerPath` (value-String), NOT `hidMissionLayerPath` (ComputeHash32). XPath: `.//field[@name='text_hidMissionLayerPath']`.

### Statistics panel (side dock, right)
`create_side_panel` builds a `QGroupBox("Statistics")` with a `QFormLayout` containing individual `QLabel` instances: `stat_name_label`, `stat_id_label`, `stat_type_label`, `stat_source_label`, `stat_map_label`, `stat_pos_label`, and `stat_relations_label` (hidden when no relationships). Use `_clear_entity_stats()` to reset them. `on_entity_position_updated(entity, pos_tuple)` is connected to `canvas.position_update` for live updates during drag and arrow-key moves; it also updates the matching entity browser tree item via `_update_tree_item_position`.

### canvas.position_update signal
`MapCanvas.position_update = pyqtSignal(object, tuple)` — emitted with `(entity, (x, y, z))` after every drag step (in `input_handler.handle_mouse_move_2d`) and after arrow-key / comma-period key moves (in `map_canvas_gpu.keyPressEvent`). Connected in `simplified_map_editor.__init__` to `on_entity_position_updated`. The handler updates `stat_pos_label`, the entity browser tree position column, AND the status bar so all three stay in sync during a drag.

### resource_folder is game-specific in patch_config.json
`main_window.resource_folder` is the runtime attribute. It is saved/loaded via `set_resource_folder()` / `load_resource_folder_config()` in `set_patch_folder.py`. Keys in `patch_config.json`: `avatar_resource_folder` and `farcry2_resource_folder` (mirrors the patch folder pattern). The old `resource_folder` key in `editor_config.json` is no longer written; a one-time migration in `load_resource_folder_config` reads the old key and writes it under the correct game-specific key on first startup.

### First-run setup prompt (`_prompt_first_run_setup`)
On startup, if `patch_config.json` does not exist (true first run), `SimplifiedMapEditor.__init__` fires `_prompt_first_run_setup` via `QTimer.singleShot(500, ...)` after the startup dialog closes. The two checks are **independent**:
1. **Patch folder** — if `patch_manager.is_configured()` is False, shows a `QMessageBox.question` for the active game (Avatar / Far Cry 2). Yes → `patch_manager.set_patch_folder()` + `update_worlds_folder()`.
2. **Resource folder** — if `self.resource_folder` is None/falsy, shows a second `QMessageBox.question`. Yes → `set_resource_folder(self)` (handles its own file dialog + info dialog).
3. **Welcome screen last (June 2026)** — after both prompts, fires `show_welcome_message_conditionally` via `QTimer.singleShot(100, ...)`. The welcome screen's "Start Modding!" button is the **single** entry point to the level selector on first run — do NOT schedule `select_level` from `_prompt_first_run_setup`.
If `patch_config.json` exists but the game-specific patch folder is missing, the original status-bar tip is shown instead (no dialog).

**Welcome dialog content (June 2026):** `show_welcome_message_updated`'s Avatar text is a full beginner guide (setup folders, level loading, 2D/3D navigation, Space view/edit toggle, editing, saving, F1/G/backtick extras) — keep it in sync with actual shortcuts when they change. The content label sits inside a `QScrollArea` (`stretch=1`, no frame) because the text is taller than the dialog; the user's "Devs:" credit block at the top of `avatar_text` and the custom window/title labels are intentional — don't remove. Verified in code: right-click drag in 3D is mouse-look (`camera_3d.rotate`), NOT pan — the "3D right-click pan" section title elsewhere in this file is a misnomer (the anchor/warp mechanism it describes is correct).

**Sequencing gotcha (June 2026):** the dialogs used to race — `__init__` queued the welcome at +100ms and the setup at +500ms, so the setup prompts stacked on top of the (modal, `exec()`-blocked) welcome dialog, and the auto-opened level selector left the welcome screen modal underneath; after loading a level the user was blocked by it, and "Start Modding!" reopened the selector a second time. Now `__init__` sets `self._is_first_run` and skips the welcome timer on first run; `_prompt_first_run_setup` shows the welcome at its end instead. Keep the flow strictly sequential: folder prompts → welcome → "Start Modding!" → level selector. Regression test: `tests/test_first_run_flow.py`.

### FC2 sdat discovery — uses `generated/sdat` inside each sector folder
FC2 terrain data lives at `patch\levels\w1_c_3\generated\sdat\` — the same `generated/sdat` sub-path as Avatar, but inside each individual grid-sector folder (not the world folder). The discovery candidate list must include `lpath/generated/sdat` as the first (highest priority) option.

### FC2 sdat discovery — search world folder too, not just the sector folder
In `load_complete_level`, the FC2 sdat discovery must search beyond `lpath` (the grid sector folder, e.g. `w1_a_1`). The `.sdat` files typically live at the world level (`world1/sdat/`) rather than inside individual sector folders. The discovery now checks: `lpath/sdat`, `lpath`, `parent(lpath)/sdat`, `parent(lpath)`, `worlds_path/sdat`, `worlds_path` — in that priority order.

### FC2 parity — unified sectors, global sector grid, cell offsets (July 2026)

FC2 was brought to feature parity with Avatar. The invariants below are load-bearing — breaking any of them corrupts FC2 saves or splits the dirty-tracking ID space.

**Global sector grid.** All sector IDs are `sector_id = gy * stride + gx` with `stride = sector_grid_stride(game_mode)` (module-level in `simplified_map_editor.py`): 16 for Avatar, **80 for FC2** (5×5 cells × 16 sectors). FC2's own `sd` numbering confirms the scheme — cell `w1_c_3`'s sectors start at 2592 = 32·80+32. `global_sector_coords(gx, gy, cell_offset_units)` lifts a WorldSector header X/Y onto the global grid: coords < 16 get the owning cell's offset (in sectors) added; coords ≥ 16 pass through (they can only be global). Never hardcode `gy*16+gx` — game-aware call sites: `load_all_worldsectors`, `_save_unified_worldsectors`, `mark_sector_dirty` (canvas, via `is_fc2_world`), `_find_best_worldsector_for_entity` (paste), `_get_sector_id_from_path` (import), `object_library.place_archetype`, drag/gizmo sector-crossing checks in `input_handler.py`/`gizmo_renderer.py`, and the live sector label in `on_entity_position_updated`.

**Cell offsets and lossless round-trip.** FC2 worldsector files usually store cell-local (0–1024) entity positions. `load_all_worldsectors` (which now accepts a folder **list**) derives each file's cell offset from its path (`_get_fc2_world_offset('', fallback_path=xml_path)`), shifts that file's entities to global world coords ONLY when the header was cell-local AND positions look local (max ≤ 1100), and records whatever it applied in `self.worldsectors_cell_offsets[normcase(xml_path)] = (ox, oy)` — including `(0,0)` when it didn't shift. Save subtracts exactly the recorded offset (`rebuild_sector_xml(..., pos_offset=off)`; per-entity FCB flush in `map_canvas_gpu` prefers this dict over the legacy `fc2_cell_offset_x/y`). Because the subtraction always mirrors the recorded addition, a wrong local/global guess can only mis-display — it can never corrupt a save. The legacy single-offset shift in `load_complete_level` step 9 runs only when the unified loader didn't (`unified_thread is None or _unified_error[0]`).

**FC2 model loading.** The pre-unified `assign_models_to_entities` pass no longer requires the unified background thread — with no thread it is the only assignment pass (this was the bug that left every FC2 entity a colored box). FC2 cell folder paths are appended to `_all_worldsectors_paths` during object loading; the unified thread receives that list for FC2.

**MP Spawn creator is Avatar-only by design** — it writes `LeftForDeadTrigger`/`NPCSpawnPointCollection`, which FC2 doesn't use; the context-menu action is disabled with an explanatory label in FC2 mode. If real FC2 MP spawn support is added, research FC2's actual spawn archetypes first.

**Night sky** resolves `assets/<game_folder>/skybox/Night Sky.glb` and falls back to the Avatar dome; drop an FC2 GLB at `canvas/assets/fc2/skybox/Night Sky.glb` to give FC2 its own stars.

**Large-world render performance (July 2026 — BOTH games; user rule: every update applies to Avatar AND FC2).**
- *2D*: entity squares draw as ONE `painter.drawRects` per style group with antialiasing off for the axis-aligned pass (`entity_renderer.render_entities_2d`); `draw_sector_boundaries` caches its position grouping (`_sector_groups_cache`) and omnis cell set (`_omnis_cells_cache`, invalidated in `invalidate_entity_caches`), draws boxes as one fill + one outline `drawRects` per category, only draws labels when a box is ≥ 48 px wide on screen, and no longer prints per frame; the 2D grid line arrays are memoized by camera key (`_grid_2d_data_cache` in grid_renderer). Do NOT reintroduce per-entity drawRect loops, per-frame O(entities) scans, or per-frame prints into the 2D paint path.
- *3D*: lazy mesh-VBO builds (`_ensure_mesh_vbo`) are budgeted at `VBO_BUILDS_PER_FRAME` (48) per `render_batched_models` call — over-budget meshes return None (callers skip them for a frame) and `_vbo_stream_pending` makes the canvas schedule follow-up repaints until everything streamed in. The fixed-function mid-render display-list fallback respects the same budget. This replaced the unbounded first-visibility upload burst that froze the UI for minutes on FC2 world1. `None` = deferred (retry next frame), `False` = permanent failure — keep that distinction.
- *3D GPU-driven auto-enable (July 2026)*: the GDR (MDI + numpy array-native assembly) is auto-enabled at `initializeGL` via `detect_support()` when `editor_config.json` has NO `render_tier` key (`_render_tier_auto`). A present key — including an explicit `null` from toggling F2/F3 off — always wins over auto. Auto-detection does NOT write the config (so hardware/driver changes re-detect).
- *3D display lists are dead weight for entity models*: Phase B calls `_create_opengl_resources(model, build_display_lists=False)` — the shader/GDR paths render from mesh VBOs and never call the lists, so compiling thousands of `glNewList`s at load wasted time + VRAM. Terrain call sites keep the default `True` (terrain draw uses lists); the fixed-function fallback builds entity lists lazily (budgeted) if it ever actually runs. The "has a model" check in `_render_entities_3d` accepts `model.meshes` as renderable — don't tighten it back to `display_list`-only.

**XBG texture memory (July 2026, FC2 world1 crash #2).** `_load_xbg_textures` now dedupes GL textures via `ModelLoader._xbt_gl_cache` keyed `(normcase(xbt path), is_normal)` — FC2 worlds reuse the same texture files across thousands of models, and per-material re-upload exhausted memory (access violation in `glTexImage2D`; PyOpenGL error checking is globally disabled, so driver OOM = hard crash, not an exception). Rules: cache entries OWN their GL ids — `clear_cache` deletes them once and per-model deletion must skip `shared_ids`; raw RGBA for the preview dock is pinned only under `_RAW_PIN_BUDGET` (768 MB — past it previews degrade gracefully to untextured); `TextureLoader._xbt_cache` is FIFO-capped at `_XBT_CACHE_MAX` (32) via `_xbt_cache_put` — never insert into `_xbt_cache` directly; `_upload` skips any decode whose byte length < w*h*4 (a short buffer is an instant AV with error checking off).

**Known remaining FC2 limitations:** the Terrain Editor edits one sdat cell folder at a time (use Load Terrain to switch cells on multi-cell worlds); moviedata/cinematics work only if a level ships a `moviedata.xml`; FC2 3D models require the FC2 resource folder to be configured (File menu).

**Ground truth from real unpacked FC2 data (July 2026, Fortune's Edition GOG).** Verified against the user's unpacked `Data_Win32\worlds\...MODDING` folder (patch folder layout: `worlds/` + `levels/` + `graphics/` at its root; it doubles as the FC2 resource folder since `graphics/` with `_materials`/`_textures` is directly inside):
- Two open worlds: `worlds/world1` + `worlds/world2`, each matching 25 `levels/w{1,2}_{a-e}_{1-5}` cells; 15 `mp_*` maps + `ige_map` + `tmpla` match by exact name. Headless scanner run confirmed world1→25 / world2→25.
- Per cell: `generated/sdat/` (256 `sd{N}.sdat` + atlas XBTs), `generated/worldsectors/` (~230 `worldsector{N}.data.fcb` + 256 `landmarkfar_{N}` + 256 `landmarknear{N}`), `generated/nv/sectors/` navmeshes. Note worldsectors are in an Avatar-style `generated/worldsectors` subfolder — `find_worldsectors_folder_enhanced` finds it (≤2 deep), despite older comments claiming FC2 files sit directly in the cell folder.
- **Everything is globally numbered on the 80-wide grid and positions are GLOBAL world coords**: converted `worldsector2592.data.fcb` from `w1_c_3` has `Id=2592, X=32, Y=32` (32·80+32=2592) and entity `hidPos` like `2063,2100` (inside the cell's 2048–3072 range). So `global_sector_coords` passthrough applies (header ≥ 16) and the unified loader records `(0,0)` offsets — no coordinate shifting for real retail data; the cell-local handling remains as a safety net for repacked/modded data.
- Scale expectation: a full world is ~5.7K worldsector + ~12.8K landmark FCBs — first load converts them all (cached afterwards); MP maps are single-cell and fast.

### FC2 terrain — always pass `game_mode` when constructing `TerrainRenderer`
`TerrainRenderer(game_mode=...)` must be passed `"farcry2"` for FC2; the default is `"avatar"`. Without it, the renderer looks for `*.csdat` instead of `*.sdat` and finds nothing. Same applies to `generate_terrain_for_level(game_mode=...)` in `terrain_to_gltf.py`. In `map_canvas_gpu.py` use `getattr(self, 'game_mode', 'avatar')`; in `simplified_map_editor.py` use `self.game_mode`. The `load_terrain_for_level` path search and the water plane detection in `terrain_to_gltf.py` must also use `self._file_ext` rather than hardcoded `".csdat"`.

**Also pass `game_mode` to `TerrainData()`** — same trap (July 2026). The in-canvas 3D sculpt path `MapCanvas._load_terrain_data` built `TerrainData()` with no `game_mode`, so it globbed `.csdat` and silently loaded nothing on FC2 levels (the EDIT TERRAIN badge did nothing). Now uses `TerrainData(game_mode=getattr(self, 'game_mode', 'avatar'))`. The Terrain Editor **dialog** already passed it (`open_terrain_editor` → `game_mode=self.game_mode`), so dialog-based FC2 terrain editing already worked; this closes the in-canvas gap. `TerrainData.save_dirty_sectors` / `_write_sector` are game-aware (FC2 writes only the height low-bytes at offset 592, preserving the 2-byte pad, the whole header, and the trailing texture data — verified by round-trip on real FC2 data: +10 sculpt reproduced exactly, headers/pad/tail byte-identical). For multi-cell FC2 worlds `sdat_path` is the primary cell and `terrain_world_offset_x/y` positions the edit mesh on it — one cell at a time, matching the dialog.

### FC2 terrain feature parity — complete audit (July 2026)
User goal: FC2 must have the SAME terrain support as Avatar. Full sweep of every terrain code path; all now game-aware:
- **2D render** — `TerrainRenderer` (game_mode) ✓
- **3D render** — `terrain_to_gltf` (game_mode) ✓ + seam-free downsample ✓
- **Height sculpt** — Terrain Editor dialog ✓ AND in-canvas EDIT TERRAIN badge ✓ (`_load_terrain_data` now passes game_mode)
- **Water read/edit** — `water_editor_dialog` game-aware ✓ (still/river flags, material)
- **Texture painting** — `terrain_texture_painter` is game-agnostic (`atlas*{_mask,_diffuse,_color}.{xbt,dds}`); FC2 has the same atlas naming, verified loading all 3 types at 256/256 tiles. It was only blocked because `_load_texture_painter` → `_load_terrain_data` defaulted to Avatar; fixed by the TerrainData game_mode fix. No painter changes needed.
- **Folder detection/counting** — `set_patch_folder.py` used `'.dat' in name`, which does NOT match `.sdat` (no `.dat` substring). Fixed both the validate check and the terrain-file counter to test `.csdat`/`.sdat` suffixes.
- **`extract_water_height`** (dead code) made game-aware (0xB0 Avatar / 60 FC2) so a future revival can't read the wrong offset.

**Deliberately NOT read for either game (so parity holds):** the heightmap section is 65×65 × 4 bytes = TWO interleaved u16 channels. Bytes 0-1 = height (read/edited). Bytes 2-3 = a second per-vertex channel (correlates with slope; the engine's terrain has `TerrainHeights`/`TerrainNormals`/`TerrainParams` + `SurfaceTypeID` per the decompile — likely packed normals/surface params). Neither game reads it, but the sculpt writer preserves it byte-for-byte (only overwrites bytes 0-1). The ~6.5 KB tail after the heightmap is packed `_sdat_atlas`/normal data, also preserved, not decoded. If terrain data reading is ever extended, do it for BOTH games together.

### 3D right-click pan — mouse anchor/warp
In 3D mode, right-click-drag pans the camera. The cursor is hidden (`BlankCursor`) and warped back to its original click position after every move event using `QCursor.setPos(self._mouse_anchor_global)`. This lets the user pan indefinitely without the cursor drifting to a window edge. `_mouse_anchor_global` is a `QPoint` in global screen coordinates set on `RightButton` press via `self.mapToGlobal(event.position().toPoint())`. The warp generates a synthetic move event with dx=dy=0 which is skipped. All logic is in `canvas/map_canvas_gpu.py` → `mousePressEvent`, `mouseMoveEvent`.

### 2D rendering — GPU-style vectorised pipeline
`_get_visible_entities` (2D branch) now uses NumPy vectorised AABB culling (mirrors the existing 3D frustum cull) with a budget cap of 5000 entities. Position arrays `_valid_entities_2d` and `_positions_2d` (float32, shape N×2) are built once per level load inside `_get_map_filtered_entities` — same cache-key guard as the 3D arrays. Calling `invalidate_position_cache()` (which clears `_map_filter_cache_key`) also triggers a 2D array rebuild on the next frame.

`EntityRenderer.render_entities_2d` now groups entities by `(color_rgb, outline_width)` before drawing so `setPen/setBrush` fires once per style group (≈10–20 groups) instead of once per entity. World→screen transform is inlined arithmetic. Entities with `rotation==0.0` use the fast path (`drawRect(QRectF)`) with no `save/translate/rotate/restore` overhead; only rotating entities use the slow path. Fences, primitives, and labels are deferred to after all square drawing. Budget cap is 15000 (above any Avatar/FC2 level entity count); when exceeded (extreme zoom-out), uniform stride subsampling is used — NOT closest-to-centre circular sort, which would create a visible circle boundary.

### hidShapePoints — shape point drag system (2D edit mode)
Shape points are stored as `<Point>x,y,z</Point>` children of `<field name="hidShapePoints">` in absolute world coords. All coordinates are absolute world coordinates. **Pt0 always equals the entity's `hidPos`/`hidPos_precise`** — they must stay in sync. Rendered in `draw_shape_outline_2d` (entity_renderer.py). Hit-test lives in `_get_shape_point_at` (RADIUS=14px).

**Drag logic (`handle_mouse_move_2d` in `input_handler.py`):**
- **pt0:** `_shift_shape_points(entity, dx, dy)` shifts ALL `<Point>` entries by (dx,dy) including Pt0, then `entity.x += dx; entity.y += dy` updates the Python position. `_update_entity_xml` syncs hidPos/hidPos_precise per-frame.
- **pt1+:** `_move_shape_point(entity, pt_idx, dx, dy)` shifts only that one `<Point>` text. entity.x/y unchanged.
- Cache invalidated via `er.invalidate_entity_cache(entity)` inside both helpers.

**Save on release (`handle_mouse_release_2d`):** After any shape point drag (all indices), the release handler calls `_update_entity_xml(entity)` (syncs hidPos/hidPos_precise) then `_auto_save_entity_changes(entity)`, which writes `main_window.xml_tree` to disk. This is the same auto-save path used by regular entity drags.

**`_find_shape_point_at(screen_x, screen_y)` (input_handler.py):** checks selected entity first, then scans all entities with shape points. Lets the user grab any shape point in one click — no pre-selection required. Called from `handle_mouse_press` before the gizmo check; auto-selects the entity if not already selected.

**xml_element live-tree requirement:** `entity.xml_element` must be an element **inside** `main_window.xml_tree` for auto-save to work. For fresh loads (cache miss) this is guaranteed. For in-session reloads (cache hit), `parse_xml_file` now re-links every entity's `xml_element` to the freshly-parsed tree after setting `self.xml_tree = ET.parse(file_path)`.

**Gotcha:** All shape point drag state (`selected_shape_point`, `dragging_shape_point`, `_shape_drag_anchor`) lives on `InputHandler`. Release handler must reset all three even on cancel paths.

**+/- buttons (add/remove last point):** In edit mode, `draw_shape_outline_2d` draws a green `+` and red `−` button 14px to the right of the last point handle. Screen-space rects are stored on `canvas._shape_add_btn_rect`, `canvas._shape_remove_btn_rect`, `canvas._shape_btn_entity` each frame and reset to `None` at the start of `render_entities_2d`. `−` is hidden when only 1 point remains. Click handling via `_check_shape_btn_click` fires before the shape-point drag check in `handle_mouse_press`.
- `_add_shape_point`: appends a new `<Point>` at `(last_x - 5, last_y - 5, last_z)`. Preserves XML indentation by copying `.tail` from the previous last point and reassigning the closing tail to the new element.
- `_remove_last_shape_point`: removes the last `<Point>`, transfers its `.tail` (closing indent) to the new last point. Guards against removing pt0. Also clears drag state if it was pointing at the removed index.

### Terrain not resetting between levels — must clear at the top of load_complete_level
The root fix is in `simplified_map_editor.py` → `load_complete_level`: both `canvas.terrain_model` (3D) and `canvas.terrain_renderer` (2D) must be reset unconditionally at the start of every level load, **before** the sdat discovery. Without this, if the new level has no terrain or terrain loading fails, the previous level's terrain stays on screen.

Reset block added right after `self.selected_entity = None`:
```python
self.canvas.terrain_model = None
self.canvas.terrain_world_offset_x = 0.0
self.canvas.terrain_world_offset_y = 0.0
if hasattr(self.canvas, 'terrain_renderer'):
    self.canvas.terrain_renderer = TerrainRenderer(game_mode=self.game_mode)
```

A secondary fix was also applied in `canvas/map_canvas_gpu.py` → `load_terrain_for_level`: `self.terrain_model = None` is now set at the very top of the function (after the OpenGL check), so any early-return path (sdat not found, etc.) also clears the model. Additionally the dynamic `importlib.util.spec_from_file_location` import of `terrain_to_gltf.py` was replaced with `from canvas import terrain_to_gltf as terrain_gen` so it works in frozen-exe builds (where `.py` files don't exist as loose files).

### entity_editor.py — rotation cache not cleared on auto-save (May 2026)

`model_loader._entity_rs_cache` (keyed by `id(entity)`) caches each entity's rotation/scale so `prepare_batches` doesn't re-parse XML every frame. `mark_entity_modified` is the only thing that clears it. The entity editor's `auto_save` and `manual_save` called `canvas._auto_save_entity_changes` (which saves the file) but never called `mark_entity_modified`. Result: after editing `hidAngles` in the entity editor, the 3D view kept showing stale angles while the mini model preview (which reads XML directly, no cache) showed the correct ones.

**Fix:** Both `auto_save` and `manual_save` in `entity_editor.py` now call `canvas.mark_entity_modified(entity)` + `canvas.update()` after saving.

**Pattern to follow:** Any code path that modifies entity XML fields and saves without going through the gizmo/drag system MUST call `canvas.mark_entity_modified(entity)` + `canvas.update()` afterward.

### Landmark file dirty detection and deletion (April 2026)

Two bugs fixed — both in the landmark save/delete path:

**Bug 1 — false dirty (landmark always queued for FCB conversion):** Two contributing causes. (a) Load-time clean hash used `str(hash(text_string))` but the save-time dirty check serialized via `BytesIO` and hashed bytes — `hash(str) != hash(bytes)`, so always dirty. Fix: at load time, parse the XML into a tree, serialize via `BytesIO` (same as save), then hash the bytes. (b) The position-sync loop in `save_all_xml_files_before_conversion` always called `pos_field.set('value-Vector3', f"{entity.x},{entity.y},{entity.z}")` for every entity, even unmoved ones. Python float formatting (`7.62474e-06`) differs from the original XML string (`7.62474E-06`), causing the serialized bytes to differ from the clean hash. Fix: before updating, compare the existing float values; skip the element if `float(parts[i]) == entity.coord` for all three axes. Both fixes together make the hash stable for untouched landmark files.

**Bug 2 — deletions not persisted:** Landmark entities had `source_file = None` (only worldsectors got tagged). In `delete_selected_entities`, `source_file is None` fell into the mapsdata branch, which failed silently. Even if the right tree had been found, the save loop only synced positions — it never removed elements.

**Critical gotcha — landmark path contains 'worldsector':** Landmark files live INSIDE the worldsectors folder (e.g. `levels\level1_worldsectors\landmarkfar_73.data.fcb.converted.xml`). The original deletion code checked `'worldsector' in source_file_path.lower()` (full path) for the worldsectors branch — this matched landmark paths too, so landmark deletions were silently eaten by the worldsectors branch. Fix: the landmark check must come **first** (before the worldsectors elif), and use `os.path.basename()` for the substring check so the folder name doesn't interfere.

**Full fix:** Tag landmark entities with `entity.source_file = "landmark"` in `on_objects_loaded` (only worldsectors were tagged before). Move the landmark case **before** the worldsectors case in `delete_selected_entities`, checking `os.path.basename(source_file_path)` for 'landmark'. Add `_remove_entity_from_landmark_tree(entity, xml_path)` which walks the in-memory tree, finds the entity by `disEntityId`, and removes it from its parent. Use `os.path.normcase(os.path.normpath())` for the `landmark_trees` dict key lookup to handle Windows path separator/case variance. The save loop's BytesIO hash then detects the change and writes + queues for FCB conversion.

**`_remove_entity_from_landmark_tree` pattern:** Builds a `{child: parent}` map over `root.iter()`, then finds the entity element by ID, retrieves its parent, and calls `parent.remove(entity_elem)`. Returns True/False.

### MissionLayer PathId — use value-Int32, not value-ComputeHash32
When `rebuild_sector_xml` creates a new MissionLayer (no original exists), `PathId` must be written as `value-Int32` with the pre-computed djb2 hash integer, **not** `value-ComputeHash32` with the layer name string. FCBConverter outputs `value-Int32` for PathId when reading game FCBs; if the editor writes `value-ComputeHash32`, FCBConverter may recompute with a different algorithm on round-trip and produce the wrong value. PathId is **not** listed in `FCBConverterDefinitions.xml` — no definition change needed.

Formula: `hash = 0; for ch in name: hash = (hash*32 + hash + ord(ch)) & 0xFFFFFFFF`. For `"main"` this yields `4026341` (`E56F3D00` LE). Stored as `value-Int32="4026341"` with BinHex text `E56F3D00`.

### FCBConverter-only parsing (April 2026)
All entity parsing in `simplified_map_editor.py` now uses FCBConverter format exclusively:
- Entity search: `object[@name='Entity']` (not `object[@type='Entity']`)
- Name: `field[@name='hidName']` → `.get('value-String')`
- ID: `field[@name='disEntityId']` → `.get('value-Id64') or .get('value-String')`
- Position: `field[@name='hidPos']` → `.get('value-Vector3')` parsed as `"x,y,z"` comma string
- All Gibbed "Dunia Tools" fallback branches removed from entity removal functions
- `import_single_entity_to_mapsdata` in `entity_export_import.py` now inserts entities as-is (FCBConverter format) — the old `convert_fcb_to_mapsdata` call that produced Gibbed `<value type=...>` elements has been removed. Container discovery now finds the parent of an existing `object[@name='Entity']` (same pattern as `_remove_entity_from_main_xml`) instead of searching for the old Gibbed hash container `494C09F2`.

### FCBConverter-only conversion (April 2026)
All FCB ↔ XML conversion now goes through `FCBConverter.exe` — Gibbed tools removed. `convert_fcb_to_xml` in `file_converter.py` runs FCBConverter (produces `file.fcb.converted.xml`) then copies to `file.xml` and **deletes the intermediate** `file.fcb.converted.xml`. `convert_xml_to_fcb` copies `file.xml` → `file.fcb.converted.xml`, runs FCBConverter (produces `file_new.fcb`), renames to `file.fcb`. `has_gibbed_tools` and `convert_main_fcb_to_xml` removed. The same intermediate-cleanup applies to `convert_folder` and `convert_folder_batch` — after a successful copy to `.xml`, all three paths delete the `.fcb.converted.xml` so only the `.xml` working copy remains on disk.

### Dunia engine decompile — format verification + class hierarchy (July 2026)
A full Ghidra decompile of `Avatar_Dunia_Retail_1.02_decrypted.dll` (65 MB text, ~61k functions, local file in `Downloads\Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE\`) was mined for editor-relevant facts:
- **FCB format verified against the engine's own reader/writer** (`FUN_10111af0`/`FUN_10112430` in the dump): magic `0x4643626e` 'nbCF', version 2, varint counts, 1-byte attr size with `0xFE`/`0xFF` escape + value back-reference dedup. Our `tools/fcb_convert.py` matches (it round-trips byte-exact vs FCBConverter). FCB name hashing is standard reflected CRC-32 (plus a case-insensitive lowercase variant).
- **XBT verified**: engine parser accepts versions 10 (20-byte prefix) and 11 (28-byte prefix); payload offset lives at header dword[2] — exactly what `texture_loader.py::_extract_dds_from_xbt` reads. No change needed.
- **Name-dictionary idea measured and rejected**: all 12,396 string literals in the dump were CRC32'd and diffed against `tools/fcb_names_cache.n32.pkl` (509k entries) — 5,030 new hashes but **zero** of them resolve the remaining unnamed hashes in real converted XML from either game (sampled 1,200 files). The unknown hashes are not literal strings in the binary.
- **Class hierarchy scraped**: `tools/scrape_class_hierarchy.py` reconstructs the full inheritance tree of 1,530 gameplay classes from the self-registration getters (`FUN_100016b0("CClassName", parentGetter())`; roots like `CNomadObject`/`CResource` use an inline pattern). Outputs `tools/avatar_class_hierarchy.tsv` + `.txt` (local-only, tools/ is gitignored; rerun the script to regenerate). Notable: `CMetaSector` derives from `CWorldSector` (under `CResource`); `CEntity → COmniEntity → CSingletonEntity` holds all the manager singletons. Same class system applies to FC2 (shared engine family).
- Worldsector descriptor attribute names confirmed as engine strings: `SectorId`, `HasMainSectorData`, `isSectorAccessible`, `HasLandmarkNear`, `HasLandmarkFar`, `SectorCountX/Y`, `SectorOffsetX/Y`.

### FCBConverter — full command-line reference

Source: https://downloads.fcmodding.com/others/fcbconverter/ (confirmed April 2026)

**Single file — FCB → XML:**
```
FCBConverter.exe -source=<file.fcb>
```
Produces `file.fcb.converted.xml` in the same directory.

**Single file — XML → FCB:**
```
FCBConverter.exe -source=<file.fcb.converted.xml>
```
Produces `file_new.fcb` in the same directory. Note: the `_new` suffix must be renamed by the caller.

**Batch folder — convert all matching files:**
```
FCBConverter.exe -source=<folder> -filter=<pattern>
FCBConverter.exe -source=<folder> -filter=<pattern> -subfolders
```
- `folder` — directory path; use `\\` for current directory
- `filter` — glob pattern(s) e.g. `*.fcb`, `*.xbt,*.bin`, `character_*.fcb` (comma-separated for multiple)
- `-subfolders` — optional; recurses into subdirectories

**DAT/FAT unpacking:**
```
FCBConverter.exe -source=<fat file> -out=<output dir>
FCBConverter.exe -source=<fat file> -out=<output dir> -single=<desired file>
```

**DAT/FAT packing:**
```
FCBConverter.exe -source=<input folder> -fat=<fat file> <FAT version>
```
FAT version flags: `-v9` (FC4, FC3, FC3BD), `-v5` (FC2), default = v10 (FC5, New Dawn)

**Game mode flag:**
- `-fc2` — Far Cry 2 mode; not in official docs but confirmed in `file_converter.py::_fcb_cmd`. Append to any conversion command when processing FC2 files.

**Output naming rules (important for rename logic):**
| Input | Output |
|-------|--------|
| `file.fcb` | `file.fcb.converted.xml` |
| `file.fcb.converted.xml` | `file_new.fcb` (strips `.fcb.converted.xml`, adds `_new.fcb`) |
| `sector0.desc.fcb` | `sector0.desc.fcb.converted.xml` |
| `sector0.desc.fcb.converted.xml` | `sector0.desc_new.fcb` |

**Legacy single-arg syntax (also works):**
```
FCBConverter.exe <file>
```
The codebase uses this form in `_fcb_cmd` — confirmed working. The `-source=` form is required for batch/folder mode only.

**Worker count pattern used in `file_converter.py`:**
```python
# Caps at 8, always reserves 2 cores for the OS
num_workers = max(2, min(cpu_count() - 2, 8))
# For fewer than 4 files:
num_workers = max(1, min(file_count, cpu_count() - 2))
```

### 3D gizmo (`canvas/gizmo_3d.py`) (April 2026)

`Gizmo3D` class — translate and rotate selected entities in 3D mode.

**Handles:** `HANDLE_TRANS_X/Y/Z` (arrows) + `HANDLE_ROT_X/Y/Z` (rings) + `HANDLE_TRANS_XY` (centre cube, free XY move). Constants exported at module level.

**Colour scheme (after tuning):**
- TRANS_X / ROT_X → red
- TRANS_Z (height) / ROT_Z → blue
- TRANS_Y / ROT_Y → green
- Active / hovered → yellow highlight

**Coordinate mapping (world → GL):**
- World X → GL X (TRANS_X arrow along GL +X, red)
- World Z / height → GL Y (TRANS_Z arrow along GL +Y, blue)
- World Y → GL -Z (TRANS_Y arrow along GL -Z, green)
- Rotation rings: ROT_X around GL X, ROT_Z around GL Y, ROT_Y around GL Z

**Arrow shape:** bidirectional — shaft extends equally in both directions from the entity origin, with a cone at each tip. `_draw_arrow` computes both `tip` and `ntip = -tip`.

**Centre cube (`HANDLE_TRANS_XY`):** purple semi-transparent filled cube (half-size = `scale × 0.12`) drawn at gizmo origin via `_draw_center_cube`. Hit-tested from 8 projected corners + centre. On drag, `_drag_translate_xy` intersects the mouse ray with the horizontal GL plane at the gizmo's Y height, giving smooth free XY movement. Delta: `World X = GL X delta`, `World Y = -(GL Z delta)`. Object snap not applied for XY free-move (ambiguous axis). Undo/redo via `MoveCommand` (same path as single-axis drags since `HANDLE_TRANS_XY` is in `_TRANS_HANDLES`).

**`_perp(axis)` — critical fix:** picks the cardinal axis with the smallest absolute dot product against `axis` (not the old `< 0.8` threshold). The old logic picked `ref=(1,0,0)` for axis `(1,0,0)`, giving a zero cross-product and a degenerate fallback that placed the red and blue rings in the same (XY) plane. Current logic: pick the component index with `min(abs(ax), abs(ay), abs(az))` and use that cardinal as ref — guarantees non-parallel.

**Integration in `map_canvas_gpu.py`:**
- `setup_renderers()` creates `self.gizmo_3d = Gizmo3D()`
- `_render_3d_opengl()` calls `gizmo_3d.render(self)` after selection lines (depth test disabled — always on top)
- `mousePressEvent` (3D left-click): calls `gizmo_3d.reproject_for_hit(self)` then `hit_test(mx*dpr, my*dpr)`; hit → `start_drag()`, miss → normal entity selection
- `mouseMoveEvent` (3D): passes `mx*dpr, my*dpr` to `gizmo_3d.update_drag()`; takes priority over camera pan
- `mouseReleaseEvent` (3D left): calls `end_drag()` → pushes `MoveCommand` or `Rotate3DCommand`

**Why `reproject_for_hit` is needed:** `mousePressEvent` sets up FOV 60 for entity picking; the renderer uses FOV 50. The stored `_proj_handles` (built during `paintGL`) would be stale relative to the modified GL state at click time. `reproject_for_hit` sets up the render-time matrices (FOV 50, same `gluLookAt`) and rebuilds `_proj_handles` fresh before every hit-test.

**DPR fix:** `gluProject` returns physical-pixel coordinates (Qt sets the GL viewport to physical size). `event.position()` returns logical pixels. All mouse coordinates passed to gizmo methods (`hit_test`, `start_drag`, `update_drag`) must be multiplied by `self.devicePixelRatio()`.

**hit_test threshold:** 40px; samples arrow shaft at 10 points (both positive and negative halves) + ring at 24 points.

**Drag sign conventions (tuned to match game coordinates):**
- TRANS_X: `x = x0 + delta`
- TRANS_Z (height): `z = z0 - delta`
- TRANS_Y: `y = y0 + delta`
- ROT_X: `ax = (ax0 - screen_delta) % 360`
- ROT_Z: `az = (az0 + screen_delta) % 360`
- ROT_Y: `ay = (ay0 + screen_delta) % 360`

**Drag mechanics:**
- Translation: screen-projected axis (mouse delta dot axis_screen_dir / pixels_per_world_unit); uses initial entity GL position so drag is stable
- Rotation: angle-from-gizmo-center in screen space; `_drag_start_center_screen` is set from `_proj_center` at drag start
- Multi-entity translation: all `canvas.selected` move by the same delta
- Rotation: primary entity (`canvas.selected_entity`) only

**Undo/redo:**
- Translation → `MoveCommand` (same as 2D)
- Rotation → `Rotate3DCommand` (in `undo_redo.py`) stores `(entity, ax, ay, az)` game-coord tuples

**`angle_update` signal:** `MapCanvas.angle_update = pyqtSignal(object, tuple)` — emitted by `_write_angles` after every rotation tick with `(entity, (ax, ay, az))`. Connected in `SimplifiedMapEditor.__init__` to `on_entity_angle_updated`.

**hidAngles field:** `_read_angles` / `_write_angles` are static methods — also called by `Rotate3DCommand._apply`. Write always updates both `value-Vector3` attr and BinHex text, then emits `angle_update`.

**Browser selection → 3D gizmo:** `on_entity_selected` in `simplified_map_editor.py` now sets `canvas.selected_entity = entity` and `canvas.selected = group` (from `select_entity_with_children`) so that selecting from the entity browser fully arms the gizmo, identical to clicking in the canvas.

### Real-time angles display (Stats panel + Entity browser)

`hidAngles` is now shown live in two places:

**Stats panel (right dock):**
- `stat_angles_label` — shows `ax, ay, az` from `hidAngles`; updated on selection and on every `angle_update` signal tick
- `stat_angles_add_btn` ("+ Add") — appears in the same row when entity has no `hidAngles`; hidden once added. Height 28px.

**Entity browser:**
- 4th column **"Angles"** (110px) — populated at tree-build time via `_get_entity_angles_text(entity)`; updated live by `_update_tree_item_angles` on every `angle_update` tick
- **"+ Angles"** button at the bottom of the browser — shown when the selected entity lacks `hidAngles`, hidden otherwise

**Shared add logic — `_add_hidangles_to_entity(entity)`:** inserts a `<field name="hidAngles">` element immediately after `hidPos` (same hash/BinHex as entity editor: hash `6553B60B`, text `000000000000008000000000`). Calls `canvas.mark_entity_modified`. Returns `True` on success, `False` if field already exists.

### entity_editor.py — rewritten UI (April 2026)
`EntityEditorWindow` was rewritten from ~1600 lines to ~450 lines. The old design had 9 overlapping sections (Basic Properties, Main Entity Properties, Vehicle, Graphics, Physics, Other Components, Entity Root Objects, Detailed Component View × 2 — the last one was literally added twice via a bug). The new design is a single-pass XML renderer:

1. **Position group** — editable X/Y/Z bound to `entity.x/y/z` (same as before)
2. **Properties group** — all direct `<field>` children of `entity.xml_element` in a 2-column grid
3. **One group per component** inside `<object name="Components">`, each recursively rendering its own `<field>` and `<object>` children
4. **One group per other root object** (non-Components direct children)

Key methods: `populate_all_views`, `_add_fields_group`, `_render_object_as_group` (recursive), `_fmt_name`.

**Dedicated component panels** (handled by `_render_object_as_group` dispatch after generic field rendering):
- `CArmedVehicle` / `CVehicle` → `_render_initial_users` (seats / pilots)
- `CAvatarSkinComponent` → `_render_skin_component` (material XBM overrides)

`MaterialOverrides` is added to `hidden_obj_names` when rendering `CAvatarSkinComponent` so the generic child rendering is skipped.
All binhex functions, input widget classes (`ScaleInput`, `DecimalInput`, `IntegerInput`, `StringInput`), encoding logic, and `add_rotation_field`/`add_scale_field` are preserved unchanged.
`hidPos` and `hidPos_precise` fields in the Properties group are rendered disabled (auto-managed by the Position editor above them).
**BinHex routing (April 2026 update):** All field conversions now go through `_to_binhex(data_type, value)` (module-level), which uses `BinHexConvert` from `tools/binhex_convertor.py` when available (falls back to inline struct.pack if the import fails). `update_xml_field_with_binhex` and `update_scale_field` both call `_to_binhex`. String encoding is ASCII (null-terminated), matching binhex_convertor.py exactly.

**Field display rules (all funnelled through `_build_field_rows`):**
- `text_XYZ` / `XYZ` pairs: show `text_XYZ` as editable string, hide `XYZ` hash, live-update it via `_make_text_with_hash_widget`.
- `selXYZ` + companion `enumXYZ` object (sibling in same parent): rendered as QComboBox via `_make_enum_dropdown`; `enumXYZ` object is hidden from group rendering. Pattern: `'enum' + sel_name[3:]`. Both `_find_sel_enum_companions` (called in `populate_all_views` for entity-level and in `_render_object_as_group` for each nested element) and `_build_field_rows` participate. Enum option labels are decoded via `_parse_enum_options` — handles `value-String` labels directly and `value-Int32` labels via `_int32_to_str` (little-endian ASCII decode, e.g. 7892802 → "Box").
- Bare BinHex fields (no `value-*` attribute): 1-byte → boolean checkbox; multi-byte → read-only hex label. Detected by `_is_bare_binhex`. **Exception:** fields whose name starts with `ent` and whose BinHex is exactly 16 chars (8 bytes) are treated as entity references — see `_is_entity_ref_field` / `_make_entity_ref_widget`.
- `value-Id64` fields whose name starts with `ent`: editable `QLineEdit`; `FFFFFFFFFFFFFFFF` shown as blank; clearing writes `FFFFFFFFFFFFFFFF` back.
- Other `value-Id64` fields (e.g. `disEntityId`): read-only selectable label.
- `hidPos` / `hidPos_precise`: disabled (managed by Position editor).

The `test_entity_editor_encoding.py` tests still apply — they test the encoding functions at the top of the file, which were not touched.

### managers.xml vPos real-time sync (April 2026)

When an entity is moved on the canvas its `hidPos` changes in memory. `managers.xml` contains `PawnInteractionInfo` objects that cache those positions in a `vPos` field. Without syncing, the managers file goes stale.

**Architecture (3-layer):**

1. **Load-time map** (`load_managers_data` in `simplified_map_editor.py`): after parsing `managers.xml`, builds `self.managers_vpos_map = {entity_id_str: [vPos_element, ...]}`. This is an O(1) lookup dict — never re-scanned during drag.

2. **Selection-time links** (`map_canvas_gpu.py`): `select_entity_with_children` calls `_build_managers_vpos_links(selected_group)` which does O(1) dict lookups into `managers_vpos_map` and stores live XML element refs in `self._managers_vpos_links`. Cleared on deselect.

3. **Per-move update + async flush**: `_update_managers_vpos_for_entity(entity)` writes `value-Vector3` and BinHex in-memory per frame. `_flush_managers_xml()` is called on mouse release — it sets `managers_tree_modified = True` and writes to disk in a `threading.Thread(daemon=True)` background thread to avoid blocking the UI.

**`_sync_managers_vpos()` (full save):** Called in `save_all_xml_files_before_conversion`. Iterates ALL loaded entities (no source_file filter — omnis/mapsdata entities also appear in managers.xml). Always sets `managers_tree_modified = True` when `managers_tree` is loaded so FCB regeneration always runs.

**Gotcha:** Do NOT filter by `source_file` when syncing — entities in `managers.xml` can come from omnis or mapsdata, not just worldsector files.

### Archetype library — `archetype_library.py` (June 2026, replaces the old `entities/` folder)

Archetypes now come from the **loaded level's own patch-folder entitylibrary**, not a bundled local folder. The `entities/` folder (2,733 per-prototype XMLs + `archetype_names.json`) was **deleted** — it was an editor-invented decomposition of the game's native `EntityLibraries → EntityLibrary → EntityPrototype → Entity` structure, and a partial one (no `VO.`/`SO.` scenery).

**Source of truth:** `<worlds_path>/generated/entitylibrary.fcb` (the regular per-level library, ~0.9 MB → ~48 MB XML; **not** `entitylibrary_full.fcb`). It holds full prototype definitions for the entities in that level (e.g. Hells Gate = 775 prototype blocks / 583 unique Names, incl. `CFileDescriptorComponent` model paths). **No local fallback:** if a level's patch folder has no `entitylibrary.fcb`, archetype-driven UI is simply empty by design.

**`archetype_library.py`** — module-level singleton via `get_library()`:
- `ensure_converted_xml(fcb, converter, fc2=True)` — converts FCB→`.converted.xml` if stale (mtime-skip), FCBConverter **batch mode** `-source=<folder> -filter=*entitylibrary.fcb -fc2`. Blocking — run on a worker thread.
- `build_index(xml)` — one streaming pass building `name → (byte start, end)` over each `<object name="EntityPrototype">` block (depth-counted by `<object>`/`</object>` token, robust to formatting; self-closing `<… />` handled). Indexes the prototype `Name` and aliases the inner `Entity/hidName`. ~0.28 s for the 48 MB Hells Gate library.
- `get_prototype_element(*names)` — **seek+slice** one block and `ET.fromstring` it (never parses the whole 48 MB); LRU(64). `_candidates()` tries each name exact / instance-stripped (`_<N>`) / known-prefix-stripped / dot-suffix longest-first. Pass `hidName` then `tplCreatureType` to mirror old precedence. Returns the `<object name="EntityPrototype">` element — same shape the old per-file parse returned, so callers are unchanged.
- `all_names()` — prototype Names (for the MP-spawn autocomplete).

**Load hook (`simplified_map_editor.py`):** `load_complete_level` calls `_load_level_entity_library(log, progress_dialog)` right after `worlds_folder` is set. It locates `entitylibrary.fcb`, and if `.converted.xml` is missing/stale runs `_run_entitylib_conversion` — a `QThread` worker doing the blocking conversion while the **main thread busy-waits pumping the MAIN load dialog** (`progress_dialog.set_status("Loading entity library...")` animates; top-level `QApplication.processEvents()` + `time.sleep(0.05)`, the patch-scanner pattern). **No separate window** — the user wanted it inside the main "Loading Complete Level" dialog. The busy-wait is at the top level, NOT inside a signal handler, so it avoids the re-entrant-`processEvents` stack overflow documented elsewhere in this file. `_entitylib_converter_path()` prefers the rebuilt fixed binary `tools/FCBConverter-master/bin/net7.0-windows/win-x64/FCBConverter.exe` (the stock one crashes on the library). Then `build_index`. All wrapped so a failure just leaves archetypes unavailable, never breaks the load.

**Consumers routed through `get_library()`:** `entity_editor._load_archetype_root` (all "Add from archetype" panels), `model_loader._load_archetype_part_map` + `_load_archetype_active_ids` (kit `<part>` map / ActivePartOverwrite IDs — still cached by `tpl`), `mp_spawn_creator._load_archetypes` (uses `all_names()`).

**Status — Job 1 done; Job 2 pending:** reviving the dead library-based **model lookup** (`model_loader._load_local_entity_library`/`entity_patterns`/`assign_models_to_entities` STEP 2) to read model paths from this same loaded library is the next step. (STEP 1 = entity's own `.//resource[@fileName]` still works; STEP 2 has been empty/dead — the local asset file never existed and `_entity_library_loaded` is force-set True at `game_paths_config.py:217` / `map_canvas_gpu.py:6019`.)

**`setup.py`:** `entities` removed from `directories_to_include`; `archetype_library.py` added to `root_files`.

### Object Library — `object_library.py` (June 2026)

Places a **brand-new entity** into the loaded level by referencing an archetype that already lives in the level's entitylibrary (loaded via `archetype_library`). **No files are imported/copied** — the game merges the full archetype at runtime — so placing just writes the **minimal instance entity** into a worldsector `MissionLayer`. Unlike the AM3D object library (which imports models/textures), this is pure XML insertion.

**Minimal placed entity** (the smallest real shape found in the game's worldsectors — e.g. `STP_archetypes.Duty.Surveilance`): `tplCreatureType` (the archetype LINK), `hidName`, `disEntityId`, `hidPos`, `hidAngles`, `hidPos_precise`, and a `Components` → `CEventComponent` → empty `hidLinks`. **No `hidResourceCount`, no `CMissionComponent`** — the layer is structural (which `<MissionLayer>` the entity is nested under). Hashes are hardcoded verbatim from a real entity (`_H_*` constants in `object_library.py`).

**The "correct thing" to call:** `tplCreatureType` = the archetype's **inner `Entity/hidName`** (e.g. `vehicle.Avatar.Valkyrie_Scripted`), read from `get_prototype_element(proto_name)` via `_archetype_tpl`. The placed `hidName` = the EntityPrototype `Name` + `_<N>` (deduped against loaded entity names).

**`place_archetype(editor, proto_name, world_pos=None)`:** builds the minimal entity (`build_minimal_entity`, BinHex via `entity_editor.string_to_binhex/int64_to_binhex/vector3_to_binhex`; new id via `mp_spawn_creator._generate_id`), finds the target worldsector by position (`sid = int(y//64)*16 + int(x//64)`, else first loaded sector), picks the `main` layer (else first), **in-memory** appends the entity XML to that `<MissionLayer>` (no disk write — the unified save's `rebuild_sector_xml` rewrites the sector from `self.entities` by `source_sector_id`/`source_layer`), creates a `data_models.Entity` (with `source_file='worldsectors'`, `source_sector_id`, `source_layer`, `source_file_path`), appends to `editor.entities`, marks `canvas.dirty_sectors`, pushes `AddEntityCommand` (undo), refreshes caches + entity tree, and selects it.

**`AddEntityCommand` (`canvas/undo_redo.py`):** undo removes the entity from `editor.entities` (via `canvas.main_window`) + from its `MissionLayer` element + re-marks the sector dirty; redo re-adds. Shared `_refresh_after_add` rebuilds position caches + entity tree.

**UI — tabbed right panel (mirrors the AM3D editor):** `create_side_panel` now wraps the existing "Level Information" content (in a `QScrollArea`) as tab 0 of a `QTabWidget` (`self.right_tabs`), and adds `build_object_library_tab(self)` as tab 1 **"Object Library"**. `editor.open_object_library` (Tools → "📦 Object Library...") just focuses that tab.

`ObjectLibraryWidget` — a **searchable grid of model-thumbnail buttons** (`QToolButton`, 3 cols, `ToolButtonTextUnderIcon`): a filter box + a scroll grid of **`get_library().unique_model_names()`** (NOT `all_names()`). Clicking a button → `place_archetype` (view-center drop; drag with the gizmo to position).

**Deduped to one entry per unique model** (`ArchetypeLibrary.unique_model_names`): the index captures each prototype's model descriptor (first `text_fileName`, via `model_paths` built in `_record`); names are grouped by that descriptor and the **shortest** name in each group is the representative (e.g. `Avatar.Banshee` over `Avatar.Banshee_HunterPet_X`). So the user sees one Banshee / one Direhorse, not the 25/16 variants that reuse the same mesh — but genuinely different meshes (Banshee vs Banshee_Static) stay separate. Names with NO `text_fileName` (markerless logic entities) are excluded. ~2,436 archetypes → ~555 unique-model entries for hellsgate; of those ~234 resolve to a real renderable `.xbg` (the rest are FX/light/kit-only descriptors).

**Non-renderable entries are hidden**, not left blank: when `render_archetype_thumb` returns None, `_render_some` calls `_mark_failed(name)` (persisted to `_thumb_cache/objlib_v2/_no_model.txt`) and hides the button; `_populate` skips names in that set, so the library settles to only the actually-placeable models with pictures and doesn't re-attempt the failures every refresh.

**Thumbnails are real rendered models** (each archetype's own 3D mesh, like the AM3D library). `_resolve_model_for_archetype` resolves the model two ways: **Path A (reliable, the fix)** — `CFileDescriptorComponent.text_fileName` (e.g. `graphics\…\valkyrie.xml`) → `model_loader._extract_gltf_path_from_resource` (finds the real `.xbg`) → `load_static_xbg`. **Path B (kit/character)** — proxy entity → `assign_models_to_entities` → `get_model_for_entity`. (Path A covers ~1,500/2,436 hellsgate archetypes; the earlier proxy-only code matched a *texture* `<resource>` instead of the model — the "Tex Direhorse" bug.) `render_archetype_thumb` renders via the **mini model previewer** (`ModelPreviewWidget`) — a dedicated **offscreen** instance (`_get_thumb_previewer`): `auto_rotate` off, timer stopped, fixed 3/4 angle, and crucially `setAttribute(WA_DontShowOnScreen)` + `show()` so its GL context + framebuffer initialise **without the widget appearing** (`grabFramebuffer()` on a never-shown `QOpenGLWidget` returns black). Per thumbnail: `canvas.makeCurrent()` (so `load_static_xbg` builds GL resources in the main ctx) → `set_model(model)` (uploads `texture_raw_data` into the previewer's own ctx — it draws from raw mesh arrays, context-independent, so it textures correctly) → `grabFramebuffer()` → `QImage` scaled to the button. `load_static_xbg`'s `_load_xbg_textures` stores `texture_raw_data` (`store_raw=True`), which makes the texturing work.

**ALL thumbnails generate** (no item-count gate): every uncached button is queued and rendered **one per `QTimer` tick** (UI stays responsive; info shows `Generating… done/total`), then **disk-cached** to `_thumb_cache/objlib_v2/<name>.png` (v1 cached broken texture-only thumbnails — hence v2). **Memory bound:** `_resolve_model_for_archetype` returns an `evict_key` and `render_archetype_thumb` pops thumbnail-only models from `models_cache` after capture, so a full ~600-model sweep doesn't pin them all in RAM (models already used by the live scene are NOT evicted). `refresh()` reloads the list (called on level load, after the entity library loads). `_object_library_widget` is stashed on the editor.

**`ArchetypeLibrary._record` strips `Name`** before lowercasing (some prototype Names have trailing spaces) so `all_names()` entries all resolve via `get_prototype_element` (0 lookup misses).

**v1 = view-center drop + thumbnail grid; drag with the gizmo to position.** A cursor-ghost / click-to-place mode (AM3D-style) is a possible phase 2.

**Verified headless:** `build_minimal_entity` round-trips; the `disEntityId` BinHex matches the real game value (`520020DC96A3A01C`). **Needs in-app test:** place an object, confirm it appears/saves and the game spawns it (the minimal-field assumption is from one observed minimal entity — if something doesn't spawn in-game, compare against more real placed instances of that type).

### entity_editor.py — InitialUsers panel (April 2026)

The `InitialUsers` XML block inside `CArmedVehicle` or `CVehicle` is rendered by `_render_initial_users(parent_layout, vehicle_elem)`.

**Trigger components:** `elem.get('name') in ('CArmedVehicle', 'CVehicle')` — note both are needed:
- Samson, Dragon, Scorpion, Banshee → `CArmedVehicle`
- Buggy, Dove, ATV, Boat → `CVehicle`
- AmpSuit → no `InitialUsers` in its archetype at all

**hidSize field:** Shown as editable "Max Seats" int at the top. Auto-synced (incremented/decremented) when seats are added/removed.

**Add Seat cap:** The "+ Add Seat" button is disabled (grayed, tooltip explains) when current seat count equals `hidSize`. `_add_user` also enforces this silently.

**Auto-populate:** When the container exists with `hidSize > 0` but fewer seat entries than max, missing entries are auto-created at render time (before the UI is built). Seat bone names come from `_get_archetype_seat_bones()` which parses the archetype file. Fallback names: `Pilot_SitPoint_01` for index 0, `SITPOINT{N:02d}` for the rest.

**Per-seat structure:** Each seat entry has three fields:
- `text_SeatBone` (`value-String`) — editable; live-updates `SeatBone` hash
- `SeatBone` (`value-ComputeHash32`) — auto-computed from `text_SeatBone` on every keystroke
- `entUser` (`value-Id64` or bare `FFFFFFFFFFFFFFFF`) — editable entity ID; blank = no user

### entity_editor.py — CAvatarSkinComponent panel
`_render_skin_component(parent_layout, skin_elem)` — dedicated UI for editing material XBM overrides on avatar creatures (Thanator, Leo, etc.).

**XML structure inside `CAvatarSkinComponent`:**
```
<object name="MaterialOverrides">
  <object name="Material">
    <field hash="DD2929AC" [value-String="path.xbm"]>  ← original path as null-terminated ASCII BinHex (or "00" if empty)
    <field hash="E1C0931D" name="fileOriginalMaterial" [value-ComputeHash32="path.xbm"]>  ← djb2 hash BinHex (or "FFFFFFFF")
    <field hash="148E2F84" [value-String="path.xbm"]>  ← override path as null-terminated ASCII BinHex (or "00")
    <field hash="28679535" name="fileMaterialOverride" [value-ComputeHash32="path.xbm"]>  ← djb2 hash BinHex (or "FFFFFFFF")
  </object>
  ...
</object>
```

**UI:** Shows each Material slot as a labeled frame with "Original" and "Override" QLineEdit inputs. On edit: sets `value-String` + `string_to_binhex` on the unnamed field, sets `value-ComputeHash32` + `compute_hash32_to_binhex` on the named field. On clear: removes the `value-*` attrs, reverts to `00` / `FFFFFFFF`. "+ Add Material Slot" appends a new empty slot. "× Remove Slot" removes the slot from `MaterialOverrides`.

**Hook:** `_render_object_as_group` adds `'MaterialOverrides'` to `hidden_obj_names` when `name == 'CAvatarSkinComponent'`, then dispatches `_render_skin_component` after the generic field rendering.

### entity_editor.py — Add from archetype panels (April 2026)

Two panels auto-appear when an archetype file exists in `entities/`:

**1. "Add from archetype" (bottom of entity editor)** — `_add_archetype_components_panel`:
Shows entire top-level components that exist in the archetype's `Components` section but are missing from the entity. Clicking deep-copies the entire component subtree into the entity's XML.

**2. "Add to X from archetype" (bottom of each component group box)** — `_add_archetype_subobjects_panel`:
For each top-level component (`depth=0` in `_render_object_as_group`), shows missing direct **fields** (green buttons) and missing direct child **objects** (blue buttons). Recurses into child objects that exist in both but have missing content — shown under `↳ ChildName:` labels.

**Probe-before-render pattern:** Content is built into a hidden `QWidget` first; the `QGroupBox` wrapper only appears if there's at least one missing item.

**InitialUsers excluded** from sub-objects panel — it has its own dedicated panel.

### entity_editor.py — entity reference fields (April 2026)

`ent*` fields (e.g. `entUser`, `entInitialUser`) that hold 64-bit entity IDs were previously rendered as read-only hex labels when they had no `value-Id64` attribute (bare BinHex `FFFFFFFFFFFFFFFF`).

**Fix:** `_is_entity_ref_field(field_elem)` returns True when field name starts with `ent` AND raw BinHex is exactly 16 chars (8 bytes). These fields are routed to `_make_entity_ref_widget` instead of `_make_bare_binhex_widget`.

**`_make_entity_ref_widget`:** Renders an editable `QLineEdit`. `FFFFFFFFFFFFFFFF` → shown as blank. On edit: writes `value-Id64` attribute + recomputes BinHex. On clear: removes `value-Id64` attribute, writes `FFFFFFFFFFFFFFFF`.

**`create_id64_field` update:** Also shows blank for `ent*` fields when `value-Id64` is `FFFFFFFFFFFFFFFF`, and writes `FFFFFFFFFFFFFFFF` when the box is cleared.

### all_in_one_copy_paste.py — duplicate with users/pilots (April 2026)

When duplicating a vehicle/mount entity that has pilots/users referenced via `entUser` or `entInitialUser`, the copy must include those referenced entities and remap all IDs.

**copy_entities — new block 3 (after structure children and AIObject checks):**
Iterates ALL `field` elements in the entity XML tree. For any field with a name starting with `ent`, reads `value-Id64` (or decodes bare BinHex as little-endian int64). If the referenced ID maps to a loaded entity, that entity is added to `all_entities_to_copy` and its ID goes into `relationship_map['seated_npcs']`.

**paste_entities — fourth pass (after structure children and AIObject passes):**
After all new IDs are generated and `id_mapping` is complete, sweeps every `field` in every new entity's XML. Two cases:
- **Has `value-Id64`**: if the value is in `id_mapping`, update attribute + recompute BinHex
- **Bare BinHex** (16 chars, not `FFFFFFFFFFFFFFFF`): decode as little-endian int64, check `id_mapping`, update text in-place

This covers `entUser` in every `InitialUsers` seat slot AND `entInitialUser` in `AIObject`, without hard-coding component paths.

**Gotcha:** The existing "Third pass" uses `value-Hash64` to find AIObject NPC refs — this is a different attribute from `value-Id64` used by `entInitialUser`. The fourth pass handles `value-Id64` correctly; the third pass is kept for backward compatibility with `value-Hash64` refs.

### Group import placement — pivot + delta (May 2026)

`EntityImportDialog._import_to_worldsector_internal` and `_import_to_mapsdata_internal` now compute a **position delta** once before the loop instead of slamming every entity to the sector/viewport centre.

- `_compute_group_pivot(selected_items)` — returns the parent entity's `original_position` if one exists (`is_parent=True`), else the centroid of all original positions.
- Delta = `(target_centre - pivot)`. Every entity is placed at `orig_pos + delta`, preserving full 3D relative offsets.
- `import_single_entity` and `import_single_entity_to_mapsdata` both accept an optional `position_delta` kwarg; when `None` they fall back to the old single-entity centre behaviour.
- Mapsdata centre comes from `_get_viewport_center_world()` (canvas `screen_to_world` at widget midpoint). Worldsector centre from `_get_sector_center`.

### Mass export (`mass_export_level` in `entity_export_import.py`) (April 2026)

`mass_export_level(editor, output_root, progress_callback)` — exports all unique entity types from a loaded level.

**Output structure:** `mass_exported_objects/<level_name>/<category>/<type_name>/`
- `category` = first dot-segment of `tplCreatureType`; if absent, first dot-segment of `hidName`; if no dot, stripped `hidName` (no trailing `_N`)
- `type_name` = `re.sub(r'_\d+$', '', entity.name)` — strips instance number, so all `Generic.Dantetiger_N` map to `Generic.Dantetiger`

**Deduplication (two passes):**
1. First pass: collect all secondary IDs (children, seated NPCs, initial users) via `EntityRelationshipDetector.find_all_related_entities` — these are never exported as top-level collections
2. Second pass: track `seen_type_keys`; first encountered instance of each type is exported, the rest are skipped

**Group collection:** uses `EntityRelationshipDetector.collect_all_related_recursive` — same logic as normal single export.

**`collection_info.json`:** written per collection in the same format as `ExportDialog.export_entities` so the import dialog can read mass-exported objects normally.

**Import dialog (`EntityImportDialog.load_collections`):** scans both `objects/` (flat, 1 level) and `mass_exported_objects/` (recursive `os.walk`) for valid collections. Display label shows `level/category/type_name` so nested collections are identifiable. `browse_for_collection` defaults to `mass_exported_objects/` if it exists.

**UI:** `SimplifiedMapEditor.show_mass_export_dialog` — checks level loaded, checks if output folder exists (asks to overwrite), shows `QProgressDialog`, calls `mass_export_level`, shows summary.

**`_mass_export_safe_name`:** shared sanitiser for both category and type_name folder names.

### Avatar csdat water format (confirmed April 2026)

Binary structure of the pre-terrain header in `.csdat` files (terrain data starts at offset 708 = 0x2C4):

```
0xA8:        uint8   — SECONDARY water sub-flag (0/1). NOT the render indicator (see below).
0xA9–0xAF:  7 bytes — always zero padding
0xB0–0xB3: float32  — water height (world units)
0xB4–0xB8:  5 bytes — always zero padding
0xB9..null:  string  — null-terminated material path (e.g. graphics\_materials\editor\water_av_riverbank.mlm)
```

**Water render indicator (CORRECTED July 2026 — 0xA8 is NOT it):** a sector renders
water iff it has a **water material path assigned AND a non-zero water height** —
`has_mat_water and abs(height) > 1e-6`. The old rule (`data[0xA8] != 0`) is wrong: the
0xA8 flag **splits contiguous water bodies**. On `sp_drifting_sierra_fm_01_l1`, sectors
62/63/78/79/94/95/110/111 are ONE lake at height 73 (a 4×2 contiguous block), yet 0xA8 is
set only on the top half (94/95/110/111) and 0 on 62/63/78/79 — and sector 63 is 99% below
the water line. Rendering by 0xA8 floods only ~2/3 of each lake and leaves hard rectangular
edges mid-water (the user's "water doesn't look all correct"). The signals are strictly
nested `flag(20) ⊆ height≠0(30) ⊆ material(32)` per level; the **material assignment** is the
true extent. 0xA8 is a secondary per-sector sub-flag (partial coverage — likely a visible-
surface / reflection-probe anchor), kept in `WaterData.water_flag` for reference only.
The earlier `sp_sebastien` "flag authoritative" call was a misdiagnosis (it compared flag vs
height, never material). `water_plane_renderer` clips each watered sector to terrain < height,
so promoting the extra sectors can't reintroduce floating planes.

**Key gotchas:**
- There are NO polygon/shape structures. Water shape is implicitly terrain height < water height, per 64×64 sector.
- Material path length varies (rainforest = 50 chars, polluted variants = 58 chars). Always read null-terminated from 0xB9.
- `0xA0–0xA3` (200.0) and `0xA4–0xA7` (level-specific negative float) are terrain height bounds — DO NOT overwrite when adding water; they differ per level.

**Known materials** (avatar game):
- `graphics\_materials\editor\water_av_openfield.mlm`
- `graphics\_materials\editor\water_av_rainforest.mlm`
- `graphics\_materials\editor\water_av_rainforest_prolemuris_noreflection.mlm`
- `graphics\_materials\editor\water_av_riverbank.mlm` (most common)
- `graphics\_materials\editor\water_av_swamp.mlm`
- `graphics\_materials\editor\water_riverbank_polluted_top.mlm`
- `graphics\_materials\editor\water_riverbank_pollutedmix_top.mlm`
- `graphics\_materials\editor\df_water_default_top.mlm`

**`add_water_block` pattern:** Only write the water-specific bytes (flag=1, height=1.0, default material). Do NOT copy a template over the full header — the 0x00–0xA7 region contains level-specific terrain metadata that must be preserved.

**`parse_water_from_sector`:** `WaterData.water_flag` holds the raw 0xA8 sub-flag byte (reference only). `WaterData.has_water = (has_mat_water and abs(water_height) > 1e-6)` — material assignment + non-zero height, NOT the flag.

> **sp_sebastien caveat:** that level stores height=20 on all 256 sectors; under the material rule it needs re-checking in-game (if all 256 also carry a water material, the whole level floods — the terrain<height clip still bounds it). Verify visually if that level is edited.

### Avatar .csdat full format map (cracked July 2026)

Complete byte layout of an Avatar sector file, verified across all 512 sectors of `sp_drifting_sierra_fm_01_l1`+`_l2`. Total size = 708 (header) + 16900 (terrain) + variable trailer (~6.0–6.7 KB).

```
REGION            OFFSET        LEN      TYPE        MEANING (confidence)
header
  0x000           0            8        magic       52 10 00 e9 09 00 00 00  version/magic (confirmed const)
  0x024           36           8        version     03 02 01 00 | 5c 59 00 00  (const)
  0x034           52           ~38      ascii        WORLD NAME, e.g. "Avatar_SP_Tantalus_01_TheBansheeFields" (confirmed)
  0x07C           124          20       POINTERS     serialized WinXP DLL addrs (0x77c3xxxx) — runtime garbage, not data
  0x0A0           160          4        float32      terrain height bound (200.0) — preserve on edit
  0x0A4           164          4        float32      terrain height bound (level-specific) — preserve
  0x0A8           168          1        uint8        water SUB-flag (0/1) — NOT render extent; material path is (confirmed)
  0x0B0           176          4        float32      WATER HEIGHT (confirmed)
  0x0B9           185          var      string       water material path graphics\_materials\editor\water_*.mlm (0-filled if none) — RENDER INDICATOR
  0x1F8           504          60       descriptor   "DXT1" embedded-texture descriptor, dims 61x61 (per-sector baked tex meta)
  0x264 / 0x2AC   —            —        POINTERS     more serialized DLL/ntdll addrs (0x7c91xxxx) — runtime garbage
  0x2C4           708          —        —            end of header / start of terrain
terrain           708          16900    65x65 x 4 bytes-per-vertex sample:
  sample[0:2]     uint16 LE / 128       HEIGHT (world units) (confirmed, long-known)
  sample[2]       uint8                 NORMAL X (tangent-space): (b-127.5)/127.5; corr(-dH/dx)=0.93 (confirmed)
  sample[3]       uint8                 UNDERWATER FLAG: bimodal <96 dry / >=224 wet, empty 96..223 gap; threshold >150 (confirmed)
trailer           17608        var
  +0              0            1056     AO/light map (uint8; 0xFF=unoccluded; ~mean 254; flat sector=all 0xFF)
  +1056           —            4        marker       03 00 00 00 (channel count; const across all 512 sectors)
  +1060           —            4225     NORMAL Y map (65x65 uint8): (b-127.5)/127.5; corr(-dH/dy)=0.54..0.96 (confirmed)
  +5285           —            3        00 00 00
  +5288           —            var      record list (12-byte records; flat sector fills 672 bytes of 0x11) — engine LOD/feature data
  tail            —            ~20      footer       recurring 3-float (~1.49, 2.97, 6.99) + count — sector bounds/scale (likely)
```

**Full per-vertex normal recovery:** the engine bakes the real surface normal split across two places — **X** in terrain `sample[2]`, **Y** in trailer `+1060` (65x65). Reconstruct **Z** = `sqrt(1 - X² - Y²)` (mean Z ≈ 0.98 on real terrain; `X²+Y² ≤ 1` holds for 100% of vertices). This is more accurate than the current heightmap-gradient normals (which the code only uses byte[2] to *confirm*, corr 0.979) and can drive true per-vertex 3D lighting.

**"100%" caveat:** the format is not 100% *meaningful* — it embeds serialized runtime pointers (fixed WinXP DLL addresses, deterministically constant so they look like data but aren't) and an engine-internal LOD/feature record list in the trailer. Every byte is *categorized* (data-field / texture / pointer-garbage / records / padding), which is the real ceiling for a memory-serialized format.

### FC2 sdat water format + Water Editor parity (July 2026)

FC2 `.sdat` stores its per-sector water block near the START of the file (not at 0xA8 like Avatar). Ground-truthed against all 14,364 retail sdats (Fortune's Edition worlds + MP maps):

```
0x34 (52): uint8  — still-water flag  ("Water" render pass)
0x38 (56): uint8  — river-water flag  ("WaterRiver" render pass)
0x3C (60): float32 — water height (world units)
0x44 (68): string — null-terminated material path (graphics\_materials\editor\water_*.mlm)
```

**Two flags, one meaning for detection:** the engine exposes distinct `Water` / `WaterRiver` / `WaterBottom` render passes (confirmed in the Dunia decompile, `FUN_10002a00("Water")`/`("WaterRiver")` around dump lines 717371–717750). A sector renders water when **EITHER** flag is set. Open-world river cells (e.g. `w1_c_3`) are almost entirely river-flag; sea/pond MP maps (e.g. `mp_10_l_fishingvillage`) use the still flag; a few cells (`w1_b_3`) mix both. **Height alone is NOT a water indicator** — every cell stores a baseline water-table height (e.g. 16.0) on all sectors; only the flag renders it (same principle as Avatar's 0xA8).

**Bug fixed:** the old FC2 read path checked only the still flag AND required non-zero height (`flag@52 != 0 and height != 0`), so it hid the entire river in every open-world cell (110 river-flag sectors in w1_c_3). `parse_water_from_sector` now sets `has_water = (still_flag or river_flag)` and reads the material at 0x44. `WaterData.water_river_flag` holds the river byte (0 for Avatar).

**Safe write region:** material path region is `[68, 192)` — the longest retail path ends at 132 and real header data never resumes before offset 329, so 192 is a safe fixed bound. FC2 has **no** fix-byte slot (Avatar's `0x21` holds real FC2 header data — never write fix bytes for FC2). Terrain heightmap starts at 592. Round-trip verified on real data: prefix (0..52), mid-header (192..592), and terrain (592+) are all byte-preserved.

**`water_editor_dialog.py` is now game-aware** via `WaterFormat(game_mode)` — one code path, per-game offsets/material list/flag semantics. `SectorGridWidget` uses `scan_sector_files()` which globs `*{ext}` and remaps FC2 global sd numbering (row stride 80) / Avatar multi-part numbering to local 0-based grid indices (same algorithm as `TerrainEditor.load`), so grid indices line up with `terrain_renderer.water_data`. FC2 mode adds a Still/River type selector (enabling water sets the chosen flag and clears the other). `open_water_editor` in `simplified_map_editor.py` passes `game_mode=self.game_mode`. Tests: `tests/test_water_editor_fc2.py`.

### FC2 .sdat full format map (cracked July 2026)

Verified across 14,364 sectors / 67 levels (deep-dived shanty, w1_a_1, w2_a_1, fishingvillage). Size = 592 (header) + 16900 (terrain 65×65×4) + variable trailer (~6044+, 12-byte record quantum). Same architecture as Avatar (baked WinXP pointers, 12-byte trailer records) but **different field offsets and a different byte[3] meaning**.

```
0x00  u32   file magic 0xE9001052 (const all levels)
0x04  u32   version/type = 7
0x08  u32   TOTAL FILE SIZE (self-reference)
0x0C  u32   footer offset = filesize-20 (points at 20-byte LOD footer)
0x1C  f32   sector MIN terrain height (corr 1.000 with grid min)
0x20  f32   sector MAX terrain height (corr 1.000 with grid max)
0x34  u8/u32 STILL-water flag ; 0x38 RIVER-water flag ; 0x3C f32 water height
0x44  cstr  water-surface material path (graphics\...\water_*.mlm), region [68,192)
0x154 (340) .. 0x208 (520): serialized C++ object w/ baked ntdll 0x7c91xxxx +
            process-heap 0x07xxxxxx pointers — RUNTIME GARBAGE (heap ptrs vary
            per bake session), preserve verbatim, never interpret
0x250 (592)      terrain 65×65 × 4B/sample:
   [0:2] u16 height/128 LE ; [2] u8 normalX (corr -0.95 w/ dH/dx)
   [3]   u8  PACKED MATERIAL-LAYER INDEX (hi2=>>5, lo=&15; range 0-111) — NOT underwater
trailer  material-paint quadtree/RLE (layer ids 0x10-0x13) + optional 65×65 0x7f
   default layer + 12-byte palette records <f32=3.0><u16><u16><u32 layer-idx>
   + 20-byte LOD footer [u32 step*k][u32 0][f32×3 LOD/bounds]
```

**CRITICAL per-game divergence — byte[3]:** Avatar's `.csdat` byte[3] is an underwater flag (bimodal 0-95/224-239); **FC2's `.sdat` byte[3] is a material-layer index** (0-111, never ≥224, 0% >150 — confirmed on shanty/w1/fishingvillage). `terrain_renderer._load_single_sector` and `terrain_to_gltf.load_heightmap_from_csdat` now return `underwater_mask=None` for FC2 so the bogus all-False mask can't suppress FC2 beach/underwater blend layers. FC2 water is driven purely by the header flags (@52/@56) + heightmap clip, never byte[3]. @0x1C/@0x20 give the sector's authoritative min/max height without scanning the grid.

### pip installs must update requirements.txt
When installing any new Python package, always add it to `requirements.txt` before or immediately after installing. The file is at the project root and has sections for app deps, build, and testing.

### setup.py packages audit (April 2026)
`canvas/undo_redo.py` was missing from the `packages` list in `setup.py` despite being a hard import in `map_canvas_gpu.py` (top-level `from .undo_redo import ...`). This would have caused a frozen-build crash. It has been added. When adding new canvas modules, always add `canvas.<module>` to the packages list immediately.

### setup.py PyQt6 build size (May 2026)
The frozen build was ~2.3 GB larger than necessary because cx_Freeze copied the entire PyQt6 installation including the QML runtime, unused Qt modules, and all plugin folders.

**Fix — two-layer approach:**
1. `excludes` list in `build_options` tells cx_Freeze not to pull in unused PyQt6 modules at all: `QtQml`, `QtQuick`, `QtNetwork`, `QtPrintSupport`, `QtMultimedia`, `QtBluetooth`, `QtDesigner`, `QtSvg`, `QtHelp`, `QtPositioning`, `QtRemoteObjects`, `QtSensors`, `QtSql`, `QtDBus`, `QtPdf`, `QtShaderTools`, `QtSpatialAudio`, `QtTextToSpeech`, `QtCharts`, `QtDataVisualization`, all `Qt3D*`.
2. Post-build cleanup (runs after `setup()`) surgically deletes what cx_Freeze copied anyway:
   - `lib/PyQt6/Qt6/qml/` — **~2 GB** (entire QML runtime)
   - `lib/PyQt6/Qt6/translations/` — ~7 MB
   - All plugin folders **except** `platforms`, `imageformats`, `styles`, `iconengines` — uses a whitelist, so any new Qt plugin folders are also deleted automatically
   - Named unneeded Qt6 DLLs from `lib/PyQt6/` (Quick, Qml, Designer, Pdf, Multimedia, etc.)
   - Named unneeded `.pyd` binding files

**PyQt6 modules actually used by the app:** `QtCore`, `QtGui`, `QtWidgets`, `QtOpenGL`, `QtOpenGLWidgets`, `sip`. Do not add others to `packages` without confirming they are imported.

**If the app crashes after a build** and a DLL load failure appears in `converter_debug.txt`, add the missing plugin folder back to `_keep_plugins` in the post-build cleanup section.

### Terrain heightmap — shared-edge assembly (May 2026)

Each sector is 65×65 samples but spans only 64 world units. Adjacent sectors share their border pixel, so the correct combined heightmap is **1025×1025** for a 16×16 map (not 1040×1040).

**Old (wrong):** stacked 65-pixel blocks side-by-side → doubled sample at every boundary → visible seams in-game.

**Fix — `step = grid_size - 1 = 64`; sector `col` placed at `[col*64 : col*64+65]`.**

### Terrain downsample must preserve seams (July 2026, BOTH games)

`TerrainExporter.downsample_heightmap` (`canvas/terrain_to_gltf.py`) reduces the combined heightmap to the display-mesh budget. Adjacent sectors AND adjacent FC2 open-world cells share their boundary vertices EXACTLY — verified against real data: a sector's last row/col is byte-identical to its neighbour's first, and cell w1_c_3's right edge equals w1_c_4's left edge (maxdiff 0.000). So the shared boundaries live at combined-grid indices `0, 64, 128, …, dim-1`.

**Bug (caused visible gaps/seams between FC2 cells):** the old code did `new = width // factor` (1025 → 512, dropping the shared +1 edge) then `PIL Image.resize(..., LANCZOS)` (interpolates). Both break the seam — a cell's downsampled right edge no longer equals its neighbour's left edge in position OR height, so the two cell meshes don't weld.

**Fix:** decimate by an INTEGER factor that divides `(dim-1)` evenly (snap down to a divisor) and sample the source values directly via `heightmap[np.ix_(ys, xs)]` — no interpolation. Result width = `(dim-1)//factor + 1` (e.g. 1025 → 513 at stride 2), endpoints kept. Because both cells are full 16×16 → identical dims → identical stride, their shared edge downsamples to identical vertices (verified: adjacent-cell seam position + height mismatch = 0.0000). `create_gltf`'s own MAX_DIM decimation was already endpoint-preserving (appends `width-1`, exact `np.ix_` sampling), so only `downsample_heightmap` needed the fix. Cells render 1024 units apart (`col*1024`) matching each mesh's `sectors_x*64 = 1024` span, so seams coincide in world space. Tests: `tests/test_terrain_seam_fc2.py`.

Affected files (all changed together to stay consistent):
- `canvas/terrain_editor_dialog.py` — `_rebuild_combined`, `save_dirty_sectors`, `mark_dirty_from_brush`
- `canvas/terrain_renderer.py` — `_generate_terrain_image_procedural`, `get_height_at_world`, `load_sdat_cell`, `render_terrain_2d`
- `canvas/terrain_to_gltf.py` — `create_combined_heightmap`, `create_gltf` (world dimensions, water offsets)
- `canvas/map_canvas_gpu.py` — `_rebuild_terrain_edit_mesh`, `_world_to_heightmap_coords`, `_render_terrain_edit_gizmo`, `scale=1.0` default
- `canvas/water_plane_renderer.py` — `sector_w/h = float(w_px - 1) / sx` (fallback: 64.0)
- `canvas/water_mesh_editor.py` — `size = (grid_size - 1) * scale` = 64.0
- `simplified_map_editor.py` — `scale=1.0` in terrain load calls

**World extent formula:** `w_px - 1` where `w_px = 1025`. Replaces the old `w_px * 0.985` band-aid. Exact match to in-game 1024×1024 cell size.

**Do NOT reintroduce 0.985.** It was a workaround for the double-sampling bug, not a real coordinate correction.

### Avatar multi-part terrain — 3D needs the same 0-based sector remap as 2D (June 2026)

Stacked Avatar levels (e.g. **Tantalus** = `sp_drifting_sierra_fm_01_l1` + `_l2`) load as two separate 16×16 terrain tiles via the `use_avatar_multicell` branch in `load_complete_level` (2D → `terrain_renderer.load_sdat_cell`; 3D → `map_canvas_gpu.load_terrain_cell_3d`, each appended to `terrain_models` at its own world offset, e.g. part 2 at y=1024).

**Part 2's sector files are globally numbered** (`sd256.csdat`–`sd511.csdat`), and its atlas files start at `atlas256`. `build_atlas_mapping` ALWAYS produces **0-based** sector keys (`atlas_index*4` → 0..255) regardless of the atlas number. So sector keys MUST be 0-based for textures to resolve.

- **2D** (`terrain_renderer.load_sdat_folder`, the `else` branch ~line 194) already remaps `sd256-511` → local `0-255` for Avatar. That's why 2D textured both halves.
- **3D** (`terrain_to_gltf.load_all_sectors`) only had the **FC2** remap — Avatar part 2 kept keys 256-511, so every `load_sector_texture(256..511)` missed (`256 not in atlas_mapping`) → the whole tile rendered **untextured/white**, and `calculate_grid_dimensions` saw `max+1=512` → wrong (23×23) grid.

**Fix:** `load_all_sectors` now calls `_remap_avatar_sectors_to_zero_based()` (mirrors the 2D logic) when `game_mode != "farcry2"` and the lowest key > 0 — shifts both `sectors_data` and `_sector_file_paths` so the lowest key becomes 0. The atlas *number* (256+) is preserved in `atlas_mapping` **values**, so `load_sector_texture` still opens the correct `atlas256_*` files. No-op for single-part levels (part 1 already starts at 0). Regression: `tests/test_terrain_avatar_remap.py`.

### canvas/mp_spawn_creator.py — MP Spawn Point Creator (May 2026)

New dialog (`MPSpawnCreatorDialog`) accessible via 2D view right-click menu → "Add MP Spawn Point (LeftForDeadTrigger)..." — only shown when worldsectors are loaded.

**Creates two entities atomically:**
- `LeftForDeadTrigger_N` → inserted into the selected worldsector's MissionLayer
- `NPCSpawnPointCollection_*` (one per wave, if "Create New" chosen) → inserted into mapsdata

**Key design:**
- Trigger index N auto-detected by scanning entity names + worldsector trees for max `MapTriggerIndex`; user can override
- Target worldsector auto-selected by centroid proximity to right-click position; user can override via dropdown
- Each wave row has its own spawn point (can be different per wave, or the same existing one)
- Archetype dropdown loads from `entities/archetype_names.json` (2728 entries) with a `MatchContains` QCompleter
- All BinHex computed via `entity_editor.py` encoding functions
- `CEntity` hash hardcoded as `60CB79CE`; `CBasicShapeEntity` hardcoded as `E6026070` — `compute_hash32_to_binhex` produces different results for these names (algorithm variant mismatch)
- Blank sentinel `HordeWaveInfos` (all zeros) auto-appended after user waves
- Both trees written to disk immediately; `xml_tree_modified` and `worldsectors_modified` set for next save/convert cycle

**`entities/archetype_names.json`:** generated by scanning all `entities/*.xml` files for `hidName`. Regenerate with: `python3 -c "import os,json,xml.etree.ElementTree as ET; ..."` (see the scan script in the brainstorm session or re-run it manually).

### load_complete_level — render suspension + assign-once (June 2026)

**"Not responding" when loading a level from 3D mode — root cause + fix:** every `log()`/progress update in `load_complete_level` calls `QApplication.processEvents()`, which repaints the canvas mid-load. With the GPU-driven tier now restored from editor_config.json at startup, those mid-load paints ran the GDR against a CHURNING `models_cache` — `_ensure_built`'s rebuild key is `len(models_cache)`, so each repaint could trigger a full multi-second consolidate + bindless-material rebuild on the GUI thread. Fix: `model_loader.loading_suspended` is set True for the whole of `load_complete_level` (released in a `finally`, followed by one `canvas.update()` so the single rebuild happens after load). Gated entry points: `prepare_batches` (clears + returns), `prepare_gpu_frame` (returns True so the canvas skips prepare_batches too), `render_batched_models` (returns 0), `cast_shadows`. Mid-load paints draw terrain/cubes only — fine behind the progress dialog.

**Model assignment is now assign-once:** `assign_models_to_entities` marks each processed entity with `_model_assign_done` and skips marked entities on later passes. The unified-sectors swap (`load_all_worldsectors` step 3) **transfers** `model_file`/`bin_file`/`kit_model_files` + the marker from each replaced object to its new same-ID twin (log: "carried N model assignments over"), so the second (full-pool) pass skips essentially everything (log: "N already assigned (skipped)"). **Race rule:** the marker is set at the END of each assignment iteration, never before — the unified thread reads it concurrently for the transfer and must never see a marked-but-half-assigned entity. Additionally `_extract_gltf_path_from_resource` is now a memo wrapper around `_extract_gltf_path_uncached` keyed `(resource_path, game_mode)` incl. negative results (cleared in `clear_cache`; recursive depth>0 calls are NOT cached — truncated results near the recursion limit must not be reused). Together these collapse the duplicate per-entity directory walks the user reported ("assigns models twice").

### load_complete_level — parallel loading architecture (May 2026)

**New step order (replaces old sequential flow):**
1. World data (mapsdata / omnis / managers / sectorsdep)
2. Level objects (worldsectors FCB conversion + entity load)
3. Model loader setup (configure paths — fast)
4. **Start unified sectors on a background `threading.Thread`** (both games since July 2026 — Avatar passes `worldsectors_path`, FC2 passes the list of all cell folders in `_all_worldsectors_paths`) — XML parsing of the sector files runs concurrently with steps 5-6
5. Model assignment for mapsdata/omnis entities (quick lookup, main thread)
6. **Phase A — `concurrent.futures.ThreadPoolExecutor`** reads GLTF/BIN files and calls `_parse_gltf` in parallel. No OpenGL. Overlaps with the unified sectors thread from step 4.
7. Wait for unified sectors thread. Re-assign models to new worldsector entities. Run Phase A again for any worldsector-only models not already parsed.
8. **Phase B — main thread only** — `_load_embedded_textures` + `_create_opengl_resources` for all Phase A results. Must be sequential (GL context is thread-bound).
9. FC2 coordinate fix
10. Terrain loading
11. moviedata.xml
12. UI finalization

**Why:** Eliminates the old second model-assignment + second pre-load pass that ran after unified sectors. Previously, model assignment ran twice (once for mapsdata entities, once after unified sectors) and the full model pre-load ran twice. Now it runs once on the complete entity list.

**Thread safety notes:**
- `load_all_worldsectors` runs on a background thread; it emits no Qt signals. Only `print()` used as log callback (thread-safe via GIL). **July 2026 fix:** its tail used to call `canvas.set_entities` / `update_entity_tree` / `update_entity_statistics` / `statusBar().showMessage` directly — tolerated at Avatar scale but an access-violation crash on FC2 world1 (~50K entities; "QBasicTimer can only be used with threads started with QThread" spam, then death in `expand_all`). It now computes `_on_main_thread` and does GUI work ONLY when True (data + plain attribute writes otherwise); `load_complete_level`'s main-thread finalization refreshes the UI after the join. Guarded-call invariant enforced by `tests/test_unified_thread_safety.py` (AST scan of the real source). Never add unguarded widget/timer calls to this function.
- `_phase_a_worker` writes only to its local `GLTFModel` object — no shared state.
- `_load_embedded_textures` and `_create_opengl_resources` use the OpenGL context — always Phase B, always main thread.
- `QApplication.processEvents()` is called only on the main thread. Never called from background threads.

**Entity snapshot (`_pre_unified_entities`):** Taken as `list(self.entities)` immediately before the background thread starts. Step 5 and Phase A first pass use this snapshot instead of `self.entities`, making them immune to the background thread's concurrent modification of `self.entities`. The snapshot contains worldsector entities from step 2's load; mapsdata/omnis entity objects in the snapshot are never replaced by `load_all_worldsectors` (only worldsector objects are swapped), so their `model_file` assignments persist across unified sectors.

**Why two model assignments:** `load_all_worldsectors` creates **new** Python entity objects for worldsector entities (ID-based dedup swap). Those new objects don't inherit `model_file` from the old objects. Step 7's full re-assignment sets `model_file` on the new worldsector entity objects. The mapsdata/omnis entities only need one assignment (step 5, via snapshot) since their objects are never replaced.

**GL context and `processEvents()`:** `QApplication.processEvents()` inside Phase B can temporarily release the GL context when Qt paints other widgets. Fix: `canvas.makeCurrent()` is called at the top of every Phase B iteration, not just once before the loop. Without this, `glEndList` raises `GL_INVALID_OPERATION` (error 1282) for models processed after the first `processEvents()` call.

### moviedata.xml — cinematic sequence system (May 2026)

**`movie_data.py`** — parser + data model for `levels/<level>/generated/moviedata.xml`.

**Structure:**
- `MovieData.node_defs` — `dict[int, MovieNodeDef]` mapping integer node IDs to world entities (by `EntityId` = `disEntityId` decimal string)
- `MovieData.sequences` — `list[MovieSequence]`; each sequence has `nodes: list[MovieSeqNode]`
- `MovieSeqNode.tracks` — `dict[param_id, MovieTrack]`
  - ParamId 1 = Position keys (`PosKey`): x, y, z
  - ParamId 2 = Rotation keys (`RotKey`): w, x, y, z quaternion
  - ParamId 4 = Event keys (`EventKey`): particle start/stop events
  - ParamId 5 = Animation state triggers (no value; ignored)
  - ParamId 7 = One-shot sound events (`SoundKey`)
  - ParamId 8 = Loop/ambient sound (`SoundKey`)

**Interpolation:** `seq_node.pos_at(t)` → linear lerp between surrounding keys. `seq_node.rot_at(t)` → quaternion SLERP. Both clamp at sequence boundaries.

**Dirty detection + save:** hash-based identical to mapsdata/omnis. `movie_data.save()` writes directly to the XML file — no FCBConverter conversion needed.

**`find_moviedata_xml(level_info)`:** checks `levels_path/generated/moviedata.xml`, then each entry in `levels_paths`, then `worlds_path/generated/`.

**`canvas/movie_renderer.py`** — 2D and 3D rendering:
- `draw_movie_paths_2d(painter, canvas)` — called after `render_entities_2d` in the 2D paint loop
- `render_movie_paths_3d(canvas)` — called after `_render_shape_points_3d` in `_render_3d_opengl`
- Both functions read `canvas.main_window.movie_data` and `canvas.main_window.selected_movie_sequence`
- Only draws the selected sequence; if none selected, no-op
- Purple dashed lines connecting keyframe positions; diamond markers at each keyframe
- Orange dots for event keys (ParamId 4)
- Grey wireframe cube fallback for NodeDef entities not found in loaded entity list
- GL coordinate mapping: world(x, y, z) → gl(x, z, -y)

**`find_moviedata_xml(level_info, resource_folder=None)`:** search order: (1) `levels_path/generated/`, (2) each `levels_paths[]` entry, (3) `worlds_path/generated/`, (4) `resource_folder/data/levels/<name>/generated/`, (5) walk up to 6 ancestor directories of `levels_path` looking for `data/levels/<name>/generated/` — handles the common layout where the patch folder (`ATGE/patch/levels/<name>`) and game data (`data/levels/<name>`) sit under the same root.

**Left dock — Tab 3 "Sequences":** `self.sequences_tree` (QTreeWidget, 2 columns: Sequence / Duration). Top-level rows = sequences; child rows = nodes inside that sequence (stores `node_id` in `UserRole+1`). Selecting a top-level row sets `selected_movie_sequence` + clears `selected_movie_node_id` → all node paths drawn. Selecting a child row sets both → only that node's path drawn. ▶ Preview / ■ Stop / ↺ Reset buttons below the tree.

**`selected_movie_node_id`:** `int | None` on `SimplifiedMapEditor`. When set, `draw_movie_paths_2d` and `render_movie_paths_3d` only render the matching `MovieSeqNode`. Both renderers check `getattr(mw, 'selected_movie_node_id', None)` at the top of their loop.

**Preview animation:** `QTimer` at **16 ms (~60 fps)**. `_movie_preview_tick()` interpolates positions, writes to `entity.x/y/z` (no dirty detection), then calls `canvas.patch_preview_positions(updates)` + `canvas.update()`. `patch_preview_positions` directly patches the cached `_positions_3d` and `_positions_2d` numpy arrays for the handful of moving entities — O(k) instead of the O(n) full rebuild that `invalidate_position_cache()` would trigger. `_positions_centered_3d` is set to `_positions_3d` to keep frustum culling correct.

**Reset button (↺):** calls `_movie_preview_stop(restore=True)` — stops the timer and restores `entity.x/y/z` from `_movie_preview_saved`. Enabled whenever a sequence is selected. Visually-only guarantee: `save_level` calls `_movie_preview_stop(restore=True)` as its first action so interpolated positions can never be written to disk.

**Gotcha:** `patch_preview_positions` patches the live numpy arrays without invalidating the cache key. This is intentional — the next `_get_map_filtered_entities` call will still see a valid cache key and return the already-patched arrays. Do NOT call `invalidate_position_cache()` in the preview tick; that would force a full N-entity array rebuild every 16 ms.

### canvas/water_plane_renderer.py — procedural water planes (May 2026; sole water display June 2026)

New module added alongside `water_mesh_editor.py`. `WaterPlaneRenderer` renders translucent per-sector quads for all sectors where `wd.has_water` is True, using `glPolygonOffset(-1, -1)` to keep the plane in front of terrain at near-equal depth. Fully dynamic — no caching needed; `force_update_sector` is a no-op.

**Baked GLTF water REMOVED (June 2026):** terrain GLTFs used to ALSO embed per-sector water quads (a 'Water' node built by `terrain_to_gltf.create_water_planes`, dodger-blue texture × `baseColorFactor [0.118,0.565,1.0,0.7]`, alphaMode BLEND) — visible as a second slightly-transparent plane under the procedural one. Now: (1) `terrain_to_gltf.create_gltf` no longer emits it (`water_mesh_data = None`; the helper functions are kept unreferenced), and (2) `strip_baked_water(model)` (module-level in water_plane_renderer.py, GPU-free, tested) removes the 'Water'-node mesh from **cached** terrain GLTFs at load time — called in BOTH `load_terrain_for_level` and `load_terrain_cell_3d`, **before** the display-list rebuild (the list bakes all meshes; stripping after would be a no-op). The procedural quad color was deepened to `(0.09, 0.45, 0.95, 0.70)` to match the old baked look (it was 0.45 alpha — too pale alone). `water_mesh_editor.initialize_from_gltf_model` finds no Water mesh afterwards and returns False gracefully ("this is normal..."); water edits flow through csdat WaterData → the procedural renderer picks them up live.

**Water MUST write depth (`glDepthMask(GL_TRUE)`)** — the baked mesh wrote depth, so submerged models (drawn after water) were hidden under the surface. The procedural plane originally used `glDepthMask(GL_FALSE)`; once it became the only water, underwater entities painted OVER the surface and the user reported it as "rendering inside out". Don't switch back to no-depth-write translucency without reordering water after entities.

Must be listed in `setup.py` packages as `canvas.water_plane_renderer` (already added).

Also, the Tools menu no longer has a "⛰ Terrain Editor..." entry — it was removed from `simplified_map_editor.py`. The terrain editor is still accessible via the **EDIT TERRAIN** badge in the 3D view canvas.

---

## Project Overview

**Avatar Level Editor** is a Windows desktop GUI application for editing level files from two games:
- **Avatar: The Game** (2009, Ubisoft)
- **Far Cry 2: Fortune's Edition**

The editor reads proprietary binary `.fcb` files (via an external converter), displays entities on an interactive 2D/3D canvas, allows property editing, copy/paste, and writes changes back to binary. It is built with Python + PyQt6 + PyOpenGL.

**Current version:** 1.9.5
**Entry point:** `main.py`
**Platform:** Windows only (requires `tools/FCBConverter.exe`)

---

## Repository Structure

```
Avatar_Level_Editor/
│
├── main.py                      # App entry point — launches game selector then main window
├── simplified_map_editor.py     # Main window class (10k+ lines) — UI, level load/save, entity ops
├── entity_editor.py             # Entity property editor dialog
├── entity_export_import.py      # Export/import entities between levels
├── all_in_one_copy_paste.py     # Advanced clipboard with relationship tracking
├── file_converter.py            # Wrapper around FCBConverter.exe (FCB ↔ XML)
├── set_patch_folder.py          # Patch folder scanner + visual level selector dialog
├── cache_manager.py             # Caching layer for FCB conversions, XML, terrain, images
├── data_models.py               # Dataclasses: Entity, GridConfig, WorldSectorInfo, etc.
├── game_selector.py             # Game selection dialog (Avatar vs Far Cry 2)
├── theme_settings.py            # Dark/light theme preference
├── hash_parser.py               # Hash32/Hash64 computation for entity IDs
├── check_exe_arch.py            # Validates FCBConverter.exe architecture
├── fix_frozen_paths.py          # Path corrections for cx_Freeze frozen builds
├── import_scanner.py            # Import analysis/debug utility
├── init.py                      # Module initialization
│
├── canvas/                      # 3D rendering module (GPU-accelerated via PyOpenGL)
│   ├── map_canvas_gpu.py        # Main QOpenGLWidget — renders entities, terrain, grid
│   ├── terrain_renderer.py      # Heightmap rendering from .csdat / .sdat files
│   ├── entity_renderer.py       # Renders entities as colored points by type
│   ├── model_loader.py          # Loads 3D models DIRECTLY from .xbg (+ XBM/XBT); fixed-function renderer
│   ├── xbg_direct_loader.py     # GL-free .xbg → GLTFModel/GLTFMesh builder (no GLTF/.bin intermediates)
│   ├── camera_controller.py     # 2D pan/zoom + 3D FPS-style camera
│   ├── grid_renderer.py         # Adaptive grid (granularity changes with zoom)
│   ├── gizmo_renderer.py        # Rotation transform gizmos
│   ├── input_handler.py         # Keyboard/mouse input dispatch
│   ├── opengl_utils.py          # OpenGL init, shader helpers
│   ├── texture_loader.py        # XBM material parse + XBT/DDS decode (DXT5-GA normals) via PIL
│   ├── binary_reader.py         # Binary file reading utilities (used by xbg_parser)
│   ├── mesh.py                  # XBG mesh data structures + vertex/normal parsing
│   ├── skeleton.py              # XBG skeleton parsing (geometry only; not used by static render)
│   ├── xbg_parser.py            # Parses Avatar XBG models (geometry + materials + LODs)
│   ├── terrain_to_gltf.py       # Terrain data → GLTF (terrain only — NOT model loading)
│   ├── water_editor_dialog.py   # Water editing UI
│   ├── water_mesh_editor.py     # Water mesh editing (modifies GLTF model vertices)
│   ├── water_plane_renderer.py  # Procedural per-sector translucent water quads
│   ├── math_utils.py            # Math helpers
│   └── game_paths_config.py     # Game-specific path constants
│
├── icon/                        # App icons (avatar_icon.ico/png, fc2_icon.png)
├── cache/                       # Runtime cache dir — gitignored, auto-created
├── thumbnails/                  # Level preview images — auto-populated at runtime
│
├── objects/                     # Game object collections (30+ entity groups)
│   └── <ObjectName>/
│       └── collection_info.json
│
├── setup.py                     # cx_Freeze build config → produces .exe
├── build_level_editor.bat       # Windows build script (cleans build/, runs setup.py)
├── editor_config.json           # User preferences (theme, entity point size, paths)
└── .gitignore
```

### Gitignored Directories (not present in repo, generated at runtime)

| Path | Description |
|------|-------------|
| `tools/` | FCBConverter.exe, Gibbed tools, DLLs — must be provided separately |
| `objects/` | Game object collections |
| `__pycache__/` | Python bytecode |
| `cache/` | Runtime FCB conversion and XML cache |
| `patch_config.json` | User's selected patch folder path |
| `converter_debug.txt` | Debug log written on startup |

**Important:** `tools/FCBConverter.exe` is required for the app to function but is not in the repo. The app will degrade gracefully without it but cannot open/save `.fcb` files.

---

## How to Run

```bash
python main.py
```

The app will:
1. Show a **game selector dialog** (Avatar or Far Cry 2)
2. Prompt for a **patch folder** (game directory containing `levels/` and/or `worlds/`)
3. Display a **level selector** — visual grid of available levels with thumbnails
4. Load the selected level and display entities in the canvas

### Build as Windows Executable

```bash
python setup.py build
# or
build_level_editor.bat
```

Output: `build/Avatar_Level_Editor/Avatar_Level_Editor.exe`

The exe bundles all Python modules, PyQt6, OpenGL, PIL, numpy, and the `tools/` and `canvas/` directories.

---

## Dependencies

### Python Packages

| Package | Use |
|---------|-----|
| `PyQt6` | GUI framework (windows, dialogs, widgets) |
| `PyQt6.QtOpenGL`, `PyQt6.QtOpenGLWidgets` | OpenGL integration |
| `PyOpenGL` | 3D rendering |
| `numpy` | Math, array ops |
| `Pillow (PIL)` | Image loading (DDS, PNG, TGA, etc.) |

### External Bundled Tools (in `tools/`, not tracked by git)

| Tool | Purpose |
|------|---------|
| `FCBConverter.exe` | Core binary FCB ↔ XML conversion |
| `FCBConverterDefinitions.xml` | Schema for FCB conversion |
| `Gibbed.*.exe` | Far Cry 2 specific file tools |
| Various `.dll` files | Compression (lzo), audio (vorbis), .NET runtime |

---

## Key Architectural Concepts

### FCB ↔ XML Flow

Game levels are stored as binary `.fcb` files. The editor:
1. Calls `tools/FCBConverter.exe` to convert `.fcb` → `.xml`
2. Parses the XML into `Entity` dataclass instances
3. Displays/edits entities in the UI
4. On save, updates the XML and calls `FCBConverter.exe` again to write `.fcb`

This conversion is cached in `cache/fcb_conversions.json` (keyed by file hash) to avoid repeated expensive conversions.

### Entity Data Model

```python
@dataclass
class Entity:
    id: str                # 64-bit hash string (disEntityId)
    name: str              # hidName value
    type: str              # XML type attribute ("Object", "NPC", etc.)
    position: tuple        # (x, y, z) floats
    rotation: tuple        # (x, y, z, w) quaternion
    xml_element: Element   # Reference to the live XML element
```

### BinHex Encoding

All numeric values in the XML are stored as little-endian hex strings:

| Type | Example Value | Encoded |
|------|--------------|---------|
| float32 | `1.0` | `0000803F` |
| int32 | `12345` | `39300000` |
| int64 | `12345` | `3930000000000000` |
| Vector3 | `(1,2,3)` | three 4-byte float hex strings concatenated |
| String | `"Hello"` | `48656C6C6F00` (UTF-8 + null) |

Encoding/decoding helpers are in `entity_editor.py` and `entity_export_import.py`.

### Caching System (`cache_manager.py`)

- `CacheManager` is a singleton-like class passed through the app
- Caches: FCB conversions, parsed XML entity lists, terrain heightmaps, minimap images
- Cache invalidation: file content hash comparison
- LRU eviction for memory management

### Copy/Paste System

Two implementations exist:
- `entity_export_import.py` — cross-level export/import with dialog UI
- `all_in_one_copy_paste.py` — in-editor clipboard that preserves parent/child relationships and seated NPC references, auto-generates new unique entity IDs on paste

### 2D / 3D View Modes

The canvas (`canvas/map_canvas_gpu.py`) supports two modes:
- **2D mode**: Top-down orthographic, entities as colored dots, pan/zoom with mouse
- **3D mode**: FPS-style first-person camera (WASD + mouse look), GLTF model rendering

Toggle: `Tab` or `T` key.

---

## Game File Structure (Patch Folder)

```
patch_folder/
├── levels/
│   └── <LevelName>/
│       ├── mapsdata.fcb         # Map entities (primary editable file)
│       ├── managers.fcb         # System managers
│       ├── omnis.fcb            # Universal objects
│       └── sectorsdep.fcb       # Sector dependency data
└── worlds/
    └── <LevelName>_worldsectors/
        ├── worldsector_00_00.data.fcb
        ├── worldsector_00_01.data.fcb
        └── ...                  # Sector-specific object data
```

### Terrain Files

| Format | Game | Offset | Description |
|--------|------|--------|-------------|
| `.csdat` | Avatar | 708 | Heightmap data; water height at 0xB0 |
| `.sdat` | Far Cry 2 | 592 | Heightmap data; water height at offset 60 |

### Sector Grid Dimensions

| Game | Grid | Sector Size | Total Map |
|------|------|-------------|-----------|
| Avatar | 16×16 | 64 units | 1,024×1,024 |
| Far Cry 2 | 5×5 regions of 16×16 | 64 units | 5,120×5,120 |

---

## Entity Type Color Coding

| Color | Entity Types | hidName prefixes |
|-------|-------------|-----------------|
| Blue | Vehicles | `vehicle.*` |
| Green | NPCs / Characters | `enemy_archetypes.*`, `player.*`, `multiplayer.*`, `ghostpatrols.*` |
| Amber | Animals / Wildlife | `animals.*` (Viperwolf, Direhorse, Hexapede, Hammerhead, etc.) |
| Red | Weapons | `weapons.*`, `oa_explosives.*`, `turrets.*` |
| Orange | Spawn points | `stp_archetypes.*` |
| Purple | Mission objects | `avatar_scriptedevents.*`, `cameras.*`, `metagame.*` |
| Yellow | Triggers / Zones | `interactive.*` |
| Light Yellow | Lights | — |
| Teal | Effects / Particles | `stimemitters.*`, `postfxs.*`, `beautifiers.*` |
| Gray | Props / Static objects | `props.*`, `object_archetypes.*`, `breakable.*`, `plants.*`, `domino.*`, etc. |
| Dark Gray | Unknown types | — |

### Entity type classification (April 2026)
Both 2D (`entity_renderer.py::determine_entity_type`) and 3D (`map_canvas_gpu.py::_determine_entity_type_for_3d`) now use **prefix-based classification** from the first dot-segment of `hidName` via `_HIDNAME_PREFIX_TYPES` dict, before falling back to legacy substring patterns. The `tplCreatureType` XML field is also checked via `_get_candidate_names` / `_get_type_candidates_3d` when `hidName` is absent. The `Animal` type (amber `QColor(255, 200, 100)`) was added to distinguish Pandoran wildlife from enemy NPCs.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+O` | Open level |
| `Ctrl+S` | Save level |
| `Ctrl+E` | Entity Editor |
| `Ctrl+C / V / D` | Copy / Paste / Duplicate |
| `Delete` | Remove selected entities |
| `Tab` or `T` | Toggle 2D/3D mode |
| `Ctrl+R` | Reset camera |
| `` ` `` | Toggle entity visibility |
| `G` | Toggle grid |
| `W/A/S/D` | Pan (2D) or move (3D) |
| `Shift+W/A/S/D` | Fast move |
| `Mouse Wheel` | Zoom |

---

## Configuration

### `editor_config.json` (User preferences, tracked by git)

```json
{
  "force_dark_theme": true,
  "show_welcome": false,
  "invert_mouse_pan": false,
  "resource_folder": "<path to game worlds folder>",
  "entity_point_size": 4
}
```

### `patch_config.json` (Gitignored, user-specific)

Auto-generated on first run. Stores the patch folder path and cached level metadata.

---

## Code Conventions

- **GUI**: PyQt6 throughout; dialogs subclass `QDialog`, main window subclasses `QMainWindow`
- **Threading**: Long operations (FCB conversion, folder scanning) use `QThread` subclasses with signals
- **XML parsing**: `xml.etree.ElementTree` — XML elements are often passed and mutated directly
- **Frozen build detection**: `fix_frozen_paths.py` uses `getattr(sys, 'frozen', False)` to detect cx_Freeze builds and correct resource paths
- **Multiprocessing**: `multiprocessing.freeze_support()` is called early in `main.py` to support frozen builds; worker processes must not import PyQt6 or OpenGL

---

## Common Development Tasks

### Adding a new entity property type

1. Add encoding/decoding logic in `entity_editor.py` (see `float_to_binhex`, `string_to_binhex`, etc.)
2. Add handling in the property display loop in `EntityEditorDialog`

### Adding support for a new file format

1. Add conversion logic in `file_converter.py`
2. Register the file extension in `set_patch_folder.py` level scanner

### Modifying the canvas rendering

- Entity rendering: `canvas/entity_renderer.py`
- Terrain: `canvas/terrain_renderer.py`
- Camera: `canvas/camera_controller.py`
- Main paint loop: `canvas/map_canvas_gpu.py` → `paintGL()`

### Debugging FCB conversion issues

- Check `converter_debug.txt` in the project root (written on startup)
- `file_converter.py` logs conversion stdout/stderr
- Cache can be cleared via the UI or by deleting `cache/fcb_conversions.json`

---

## Recent Work (April 2026)

### Undo/Redo system (`canvas/undo_redo.py`)

New module implementing 100-edit undo/redo history using the Command pattern.

**Classes:**
- `UndoRedoManager` — `deque(maxlen=100)` for undo stack, separate deque for redo. `push(cmd)` clears redo stack. `undo(canvas)` / `redo(canvas)` apply the command and call `_post_op` to refresh display.
- `MoveCommand(before, after)` — stores `[(entity, x, y, z), ...]` snapshots. Restores positions via `_apply_entity_state`.
- `RotateCommand(before, after)` — stores `[(entity, x, y, z, rotation), ...]`. Includes positions because group rotation orbits entities around a centre point.
- Static helpers: `UndoRedoManager.snapshot_positions(entities)`, `snapshot_rotations(entities, canvas)`

**Integration points:**
- `map_canvas_gpu.py`: `self.undo_redo = UndoRedoManager()` at init. **Ctrl+Z** = undo, **Ctrl+Y** / **Ctrl+Shift+Z** = redo. (Ctrl+R was redo but is now Reset View.) Arrow key nudge, comma/period nudge, K/L rotation all snapshot before → operate → push command.
- `canvas/input_handler.py`: On left-click entity select (edit mode), saves `self._drag_before_positions`. On left-button release after drag, pushes `MoveCommand`.
- `canvas/gizmo_renderer.py`: `start_rotation()` saves `_undo_rotate_before` (rotation ring) or `_undo_center_before` (centre-square move) on the gizmo. `handle_gizmo_mouse_release()` pushes `RotateCommand` or `MoveCommand` after `end_rotation()`.

**Gotcha:** `_apply_entity_state` calls `update_entity_xml`, `mark_entity_modified`, and `invalidate_entity_cache` — all three must fire for the undo to be visually correct. `_post_op` additionally calls `invalidate_position_cache`, updates the gizmo, and emits `position_update`.

### 2D View/Edit mode (Space toggle)

- `input_handler.edit_mode_2d` — `False` = View (select + rotate only), `True` = Edit (full movement enabled)
- `canvas/map_canvas_gpu.py` Space key → `input_handler.toggle_edit_mode_2d()`
- Entity drag (`self.dragging`) only starts when `edit_mode_2d` is True
- Gizmo centre-square drag blocked in view mode (`start_rotation` checks `edit_mode_2d`)
- Arrow keys and comma/period blocked when `not edit_mode_2d and mode != MODE_3D`
- Visual indicator: `_draw_2d_mode_indicator(painter)` draws green "VIEW MODE" / amber "EDIT MODE" badge bottom-left with "Space: switch mode" hint

### Layout-independent keyboard controls

`canvas/opengl_utils.py` — `_SCAN_TO_ACTION` dict maps Windows native scan codes to action strings (`FORWARD`, `BACKWARD`, `LEFT`, `RIGHT`, `UP`, `DOWN`). `movement_action(event)` reads `event.nativeScanCode()` — works on AZERTY, DVORAK, Colemak, any layout.

`camera_controller.set_movement_flag(action, pressed)` accepts action strings instead of Qt.Key values.

`map_canvas_gpu.keyPressEvent` / `keyReleaseEvent` use `movement_action(event)` for 2D/3D camera controls.

### 2D middle-click panning

`input_handler.handle_mouse_press_2d` — `MiddleButton` sets `self.panning = True` + `ClosedHandCursor`. `handle_mouse_move_2d` panning branch: `offset_x += dx`, `offset_y -= dy` (Y must subtract due to the screen-Y flip in `world_to_screen`). `invert_mouse_pan` inverts both axes. Release resets cursor.

**Gotcha:** The canvas attribute is `invert_mouse_pan` (not `invert_mouse`). `world_to_screen` computes `screen_y = height - (world_y * scale + offset_y)` — dragging down (positive `dy`) must **subtract** from `offset_y` to scroll the world down, not add.

### Entity editor — XML tab + bidirectional sync

`EntityEditorWindow` now has a `QTabWidget` with:
- Tab 0 "Editor" — existing scroll area with field widgets
- Tab 1 "XML" — `QPlainTextEdit` (dark, Consolas 9pt, no wrap) showing the full entity XML, pretty-printed via `_pretty_xml` (minidom `toprettyxml`, 2-space indent, strips XML declaration)

`_refresh_xml_tab()` serialises current entity XML → sets in editor (re-entrancy guard `_xml_tab_refreshing`).
`_apply_xml_changes()` parses XML, calls `_recompute_binhex_for_tree(elem)` to recompute all BinHex from value-* attrs, updates `entity.xml_element`, saves.
`_VA_TO_DTYPE` maps `value-*` attribute names to `_to_binhex` type strings for recomputation.
1.5s `QTimer` debounce on XML edits before auto-applying. Apply button for immediate apply.
`currentChanged` signal connected **after** all tab setup to prevent crash on `addTab`.

**Gotcha:** `currentChanged` fires during `addTab()` before the second tab's widgets exist — always connect this signal last.

**BinHex auto-recomputation on XML edits:** When the user edits a `value-*` attribute in the XML tab and the debounce fires (1.5s) or "Apply XML" is clicked, `_recompute_binhex_for_tree(new_elem)` walks every `<field>` and rewrites `field.text` (the BinHex) from the `value-*` attribute using the same encoders as the Editor tab (`_VA_TO_DTYPE` maps attribute name → dtype key). The updated element is then re-serialized back into the XML editor so the new BinHex is visible. Two caveats: (1) editing the raw BinHex directly without changing the `value-*` attribute will have the BinHex overwritten back to whatever the `value-*` computes to; (2) fields with no `value-*` attribute (bare BinHex fields) are skipped entirely and must be edited manually.

**Gotcha — XML tab stale after auto_save:** `auto_save()` calls `_auto_save_entity_changes()` which calls `_update_worldsector_xml_fcb_format()`. That function updates position fields and re-assigns `entity.xml_element = entity_elem` (the live tree element). This happens silently 1 second after any edit. If the user is sitting on the XML tab, the display doesn't update — the file is correct but the XML tab shows the pre-save state. Fix: `auto_save()` now calls `_refresh_xml_tab()` after a successful save when the XML tab is visible AND `_xml_debounce.isActive()` is False (guard prevents clobbering an in-progress XML edit).

**Gotcha — XML tab: header not updating on entity switch:** `populate_all_views` early-returns after `_refresh_xml_tab()` when the XML tab is active, skipping the `_update_header()` call that normally runs on the Editor tab path. Result: name, class, position, and ID in the header stay showing the previous entity. Fix: always call `_update_header(self.current_entity)` before the early return, so the header updates regardless of which tab is active.

### Entity editor — search bars

**Editor tab** (`self._editor_search` QLineEdit, always visible above the scroll area):
- `_apply_editor_search(text)` — hides QGroupBox items whose title and child QLabel texts (< 80 chars) don't contain the query; non-QGroupBox items (buttons) always stay visible.
- Auto re-applied at the end of `populate_all_views` so the filter persists across entity changes.
- Ctrl+F focuses this bar when on the Editor tab.

**XML tab** (`self._xml_find_bar` QWidget, hidden by default):
- Ctrl+F shows the bar and focuses `self._xml_find_input`.
- `_apply_xml_find(text)` — highlights all matches via `QTextEdit.ExtraSelection` with a yellow background; shows match count.
- `_xml_find_navigate(forward)` — uses `QPlainTextEdit.find()` with `QTextDocument.FindFlag.FindBackward` for reverse; wraps around at document boundaries.
- Enter → next match, Shift+Enter → previous match (handled in `keyPressEvent`).
- Esc closes the bar and clears highlights (also in `keyPressEvent`).
- ▲/▼ buttons and ✕ close button in the bar.

---

## Recent Work (April–May 2026)

### Main-file dirty detection — hash-based (May 2026)

**Bug 1 — false dirty (all main files always reconverted):** `save_all_xml_files_before_conversion` unconditionally set `xml_tree_modified = True` and `setattr(self, _modified_flags[file_type], True)` for every file on every save.

**Bug 2 — managers.xml FCBConverter timeout:** Because managers was always marked dirty, `_convert_main_xml_to_fcb` always tried to reconvert it. FCBConverter hangs (>120 s) when processing this level's managers XML; the file is never actually modified in normal use (0 PawnInteractionInfo entries matched), so it should never be queued for conversion.

**Fix:** Hash-based dirty detection, same pattern as landmarks.

- `self._main_clean_hashes = {}` (dict keyed by `'mapsdata'/'omnis'/'managers'/'sectorsdep'`) added in `__init__`
- Each load function (`parse_xml_file`, `load_omnis_data`, `load_managers_data`, `load_sectordep_data`) serializes the tree via BytesIO immediately after parsing and stores `str(hash(bytes))` as the clean hash
- `save_all_xml_files_before_conversion` computes a new hash for each tree before writing; only writes to disk and sets the modified flag when the hash differs from the stored clean hash; updates the stored hash on write
- Position sync (step 0) now float-compares existing `value-Vector3` values before overwriting — prevents format-only rewrites from triggering a false dirty hash change (same fix applied to landmarks in April 2026)

**Regression tests:** `tests/test_worlds_save_flags.py` — `TestHashDirtyDetection` class (6 tests covering unchanged → not dirty, changed → dirty, hash update after write, managers-specific case).

### 3D entity picking — ray-AABB raycasting (May 2026)

`select_entity_3d` in `canvas/map_canvas_gpu.py` was rewritten from a screen-space dot proximity test (20px threshold against projected origin) to proper 3D raycasting.

**New approach:**
- `gluUnProject` builds a world-space ray from camera through the click pixel (near z=0, far z=1)
- Module-level `_ray_aabb_intersect(ray_origin, ray_dir, box_min, box_max)` implements the slab method; returns distance `t` along the ray or `None` on miss
- Pass 1: entities with a loaded 3D model — iterates `model_loader.instance_batches` (already computed for the last rendered frame); uses `model.bounds_min/bounds_max` (GLTF local space) transformed to GL world space
- Pass 2: visible entities with no model — fallback 1.5-unit box at entity GL origin
- Returns the **closest** hit entity by `t`, not the first

**GLTF → GL bounds transform:** The renderer always applies `glRotatef(-90, 1, 0, 0)` before any entity rotation, converting GLTF (x,y,z) → GL (x, z, −y). The picking code applies the same transform to `bounds_min/bounds_max` before testing:
```
gl_min.x = pos[0] + bmin[0] * scale
gl_min.y = pos[1] + bmin[2] * scale   # GLTF z → GL y
gl_min.z = pos[2] - bmax[1] * scale   # GLTF -y → GL z
```
`np.minimum/maximum` then ensures min < max (swap safety).

**Upgraded to per-triangle raycasting (May 2026):** The AABB test now runs in model-local space (ray transformed by inverse of entity model matrix) so there's no rotation inflation. For any AABB hit, vectorised Möller-Trumbore (`_ray_triangle_mesh_intersect`) tests every triangle in the model's meshes. This gives pixel-exact selection — only geometry the ray actually passes through is hit. Three new module-level helpers: `_make_rot_x/y/z(deg)` (3×3 rotation matrices), `_ray_triangle_mesh_intersect(ray_o, ray_d, vertices, indices)` (vectorised numpy). Model matrix order matches the renderer: `R_x(-90) @ R_z(-rz) @ R_x(rx) @ R_y(ry)`. Ray direction is divided by scale (not normalised) so t_local == t_world for direct comparison across entities.

### Gizmo centre on multi-selection (`simplified_map_editor.py::on_entity_selected`)

`on_entity_selected` fires whenever any selection happens (box-select, CTRL+click, tree-click, etc.) and used to always call `update_gizmo_for_entity(entity)` with just the primary entity. This overwrote any group-centre the input handler had already set. Fix: when `canvas.selected` has more than one entity, `on_entity_selected` now calls `calculate_group_center` and passes a VirtualEntity at that centre to `update_gizmo_for_entity`.

### Ctrl+click multi-select in 2D (`canvas/input_handler.py`)

`handle_mouse_press_2d` checks `event.modifiers() & Qt.KeyboardModifier.ControlModifier`. When CTRL is held and an entity is clicked:
- If the entity is already in `canvas.selected`: the entity's whole linked group is **removed** from the selection.
- If the entity is not selected: its linked group is **appended** (no duplicates).
No drag starts on CTRL+click — it is selection-only. The gizmo always repositions to the centre of the current selection after either branch. A normal click (no CTRL) still replaces the selection as before.

### FCBConverter mode for load + save

**Load (FCB → XML) — `file_converter.py::convert_data_fcb_files`:**
- Calls `_run_batch_fcbconverter(worldsectors_path, "*.data.fcb")` — always includes `-fc2`
- Cache check still runs first: if xml exists AND file hash matches → skip (no batch needed)
- If any file is uncached the batch runs on the **whole folder** (not just uncached files); FCBConverter handles already-converted files harmlessly
- Progress dialog shows the full command including `-fc2` so it's visible to the user
- Missing XMLs after batch are logged as `[MISSING]` entries

**Save — worldsectors (XML → FCB) — `simplified_map_editor.py::_convert_worldsector_files_fixed`:**
- Iterates only `self._unified_dirty_xml_paths` (the set of `.converted.xml` files that actually changed)
- For each file: calls `self.file_converter.convert_converted_xml_back_to_fcb(target_fcb)` (120s timeout per file)
- `convert_converted_xml_back_to_fcb` runs FCBConverter on the single file, produces `_new.fcb`, which is renamed to the original `.fcb` by the caller
- After success: removes the `.converted.xml` file and clears it from `worldsectors_trees`
- **Rationale for per-file (not batch):** the worldsectors folder contains 48 worldsector files PLUS ~251 `landmarkfar_*` / `landmarknear_*` files. The old batch approach converted all ~299 files every save (300s timeout) even when only 1 was dirty. Per-file conversion processes only changed files.

**Save — main files (XML → FCB) — `simplified_map_editor.py::_convert_main_xml_to_fcb`:**
Kept as per-file (mapsdata, omnis, managers, sectorsdep may be in different folders). Uses `convert_xml_to_fcb` which internally calls `_fcb_cmd` → always `-fc2`.

**`_run_batch_fcbconverter` always appends `-fc2`** — no game-mode check, no conditional.

### -fc2 flag — always required, always present

Every FCBConverter call in the codebase uses `-fc2`:
- `_fcb_cmd(file_path)` → `[converter_path, file_path, "-fc2"]`
- `_run_batch_fcbconverter(folder, filter)` → `[converter_path, "-source=folder", "-filter=filter", "-fc2"]`
- `_convert_fcb_worker` → `[converter_path, fcb_path, "-fc2"]` (hardcoded in the module-level function)

Do **not** add a game-mode condition here. The `-fc2` flag must always be present regardless of `game_mode`.

### sectorsdep must be re-converted to FCB after XML changes

The game reads `.sectorsdep.fcb` (not the XML). When `create_sector.py` patches sector neighbour lists in `.sectorsdep.xml`, it must immediately re-convert to FCB. The fix lives in `tools/create_sector.py::convert_sectorsdep_to_fcb`: copies `.xml` → `.fcb.converted.xml` (temp), runs FCBConverter, renames `_new.fcb` → `.fcb`.

### Tools menu additions (`tools/`)

| Tool | File | Notes |
|------|------|-------|
| Create New Sector | `tools/create_sector.py` | Single or bulk; auto-fills from loaded level; emits `sectors_created` signal → `_load_new_worldsectors` auto-reloads |
| Enable All Sectors | `tools/enable_all_sectors.py` | `-fc2` always on; checkbox hidden from UI |
| Convert Entity Library FCB | inline `simplified_map_editor.py::open_convert_entitylibrary` | Select **only** `entitylibrary.fcb` or `entitylibrary_full.fcb` (exact name match, not substring); single-file or folder scan; uses fixed binary + batch mode `-source`/`-filter`; crash fixed in `tools/FCBConverterDefinitions.xml`; shows QThread progress dialog |
| Convert Entity Library XML to FCB | inline `simplified_map_editor.py::open_convert_entitylibrary_xml_to_fcb` | Select **only** `entitylibrary.fcb.converted.xml` or `entitylibrary_full.fcb.converted.xml` (exact name match); single-file invocation `FCBConverter.exe <xml> -fc2 -enablecompress`; renames `<base>_new.fcb` → `<base>.fcb`; shows same QThread progress dialog |

**`sectors_created` signal flow:** `CreateSectorWindow.sectors_created = pyqtSignal(list)` → connected to `editor._load_new_worldsectors(sector_ids)` in `open_create_sector`. New sector XMLs are parsed and added to `worldsectors_trees`; canvas redraws. No restart required.

### Menu bar restructure

- "View" renamed to **Canvas**; contains: Toggle 2D/3D, Show Sectors, Check Violations, Toggle Entities, Invert Mouse Pan, Light/Dark Mode
- "Export and Import" renamed to **Entity Tools**; Entity Editor moved to the top of this menu
- Lower toolbar removed entirely (`create_toolbar` is now `pass`)
- "Open All Sectors (Unified Mode)..." removed from File menu (unified mode auto-activates on load)

### Landmark entity bug — `_is_worldsector_entity` must check basename

**Bug:** `load_all_worldsectors` (step 7 of `load_complete_level`) filtered out landmark entities because their `source_file_path` contained the folder name `worldsectors/`, matching the old `'worldsector' in fp` check.

**Fix:** Changed to `os.path.basename(fp).startswith('worldsector')` — checks the filename, not the full path. Landmark files (`landmarkfar*`, `landmarknear*`) now survive the filter and remain in `self.entities` alongside the unified worldsector entities.

**Flow context:**
1. `load_level_objects_internal` loads ALL `*.data.fcb.converted.xml` (incl. landmarks) → `self.entities`
2. Step 7 `load_all_worldsectors` replaces worldsector entities with unified pool, **preserving** landmark entities
3. Final `self.entities` = world-data entities + landmark entities + all-sector worldsector entities

---

## Unified World Sector Editor (Complete)

### What it does

All worldsector files are loaded at once into a single unified entity pool. Users can freely move entities anywhere on the map. On save, entities are automatically redistributed to the correct sector files based on their `source_sector_id`. Unified mode auto-activates on every Avatar level load (FC2 excluded).

### Game file findings (sp_hellsgate_01_l)

Established by analysing real game files — these findings apply to Avatar worldsector files:

**Three file types in the worldsectors folder — only one matters:**
- `worldsector*.data.fcb` — actual gameplay entities (`CEntity`) — **the ones we edit**
- `landmarkfar_*.data.fcb` — `CSectorEntity` streaming triggers — leave untouched
- `landmarknear*.data.fcb` — `CSectorEntity` streaming triggers — leave untouched

**Entity IDs are globally unique across all worldsector files:**
- 3,126 entities across 48 worldsector files, zero ID collisions
- No namespacing or remapping needed when merging

**Sector grid formula:**
```
Sector ID = GY * 16 + GX
World bounds = [GX * 64, (GX+1) * 64)  ×  [GY * 64, (GY+1) * 64)
```
GX and GY are the `X` and `Y` fields in each WorldSector XML root. The sector size is exactly **64×64 world units**.

**Boundary is soft (~1% violations):**
~23 of 3,126 entities sit a few units outside their expected cell bounds. The split-back algorithm must use **"nearest sector"** fallback rather than strict containment.

**Mission layers are global, not per-sector:**
34 distinct layer names (e.g. `outside_entity` in 29 sectors, `main` in 16, `around_valkirye` in 25). Each entity belongs to a named layer — this is a game-logic mission state, not a spatial concept. Must be preserved as `entity.source_layer` through the round-trip.

**File structure per worldsector:**
```xml
<object name="WorldSector">
  <field name="Id" value-Int32="42"/>
  <field name="X"  value-Int32="10"/>
  <field name="Y"  value-Int32="2"/>
  <object name="MissionLayer">
    <field name="text_PathId" value-String="outside_entity"/>
    <field name="PathId" value-ComputeHash32="outside_entity"/>
    <object name="Entity">...</object>
  </object>
  <object name="MissionLayer">   <!-- multiple layers per sector -->
    ...
  </object>
</object>
```

### Dirty-sector tracking (only reconvert changed files)

FCBConverter takes seconds per file — reconverting all 48 sectors on every save is unusable.

**Dirty set:** `self.dirty_sectors: set[int]` of sector IDs on the canvas.
- Whenever `mark_entity_modified(entity)` fires, also call `mark_sector_dirty(entity)` → computes `floor(entity.x/64)` for GX, `floor(entity.y/64)` for GY, adds `GY*16+GX` to dirty set.
- When an entity crosses a sector boundary, both old and new sector IDs become dirty.

**Save loop:**
1. Compute `target_sector_id` for every entity via `floor(x/64)*GX + floor(y/64)*GY*16` formula
2. Build final dirty set = `dirty_sectors` ∪ {sectors where any entity's target ≠ source}
3. For each dirty sector: rebuild XML → hash check against `clean_hash[sector_id]` → if changed: write XML + run FCBConverter → update `clean_hash`
4. Update `entity.source_sector_id` for all entities to their new sector
5. Clear `dirty_sectors`

**Hash check:** At load time store `clean_hash[sector_id] = hash(xml_text)`. Before running FCBConverter on a rebuilt sector, compare new XML hash to stored hash. If equal (nothing actually changed), skip conversion.

### Implementation plan

#### Step 1 — Audit all existing per-sector code (do this first)

Before writing any new code, search the entire codebase for everything that touches the current per-sector system. Look for:

- `current_map` — where set, read, used as filter (canvas, entity browser, culling)
- `map_name` — on entities, in UI filters, in statistics panel
- `move_sector` / `Move Sector` / `moveSector` — UI button and underlying logic
- `worldsector` (case-insensitive) — file loading, saving references
- `MissionLayer` — any existing XML structure references
- `load_complete_level` — the load entry point in `simplified_map_editor.py`
- `_update_worldsector_xml` / `save_all_xml_files_before_conversion` / FCBConverter call sites — save paths
- Entity browser / sidebar — how it groups/filters by sector
- Any UI menus, buttons, dialogs that reference sectors or maps

**File audit priority:** `simplified_map_editor.py` (10k+ lines, most logic here), `canvas/map_canvas_gpu.py`, `data_models.py`, `entity_export_import.py`, `all_in_one_copy_paste.py`, `canvas/entity_renderer.py` (map-name-based culling).

**Document every finding before touching any file.**

---

##### Audit findings (April 2026)

###### `current_map`

- **`simplified_map_editor.py:560`** — initialized to `None` in `__init__`
- **`simplified_map_editor.py:2176, 2188, 2396, 2406, 2579, 2584`** — reset to `None` on every level load / close path
- **`simplified_map_editor.py:7547–7555`** — `zoom_to_entity` compares `entity.map_name` vs `current_map.name`; if different, switches `map_combo` to the entity's map
- **`canvas/map_canvas_gpu.py:409`** — initialized to `None` in canvas `__init__`
- **`canvas/map_canvas_gpu.py:1674–1680`** — `_get_map_filtered_entities` filters the entire entity list to `entity.map_name == current_map.name`; this is the hot-path filter used by the 2D and 3D renderers every frame
- **`canvas/map_canvas_gpu.py:3035–3038`** — `set_current_map(map_info)` sets it and marks `entities_modified = True`
- **`canvas/input_handler.py:364–365, 546–547`** — entity selection (click + box-select) skips entities whose `map_name` doesn't match `current_map`
- **`all_in_one_copy_paste.py:1899`** — paste loop skips entities from a different map

###### `map_name` (on Entity)

- **`data_models.py:47`** — `map_name: Optional[str] = None` field on `Entity` dataclass; `data_models.py:61` same on the object dataclass
- **`simplified_map_editor.py:1799, 1867, 1950, 2322`** — assigned via `self.determine_entity_map(entity)` during worldsector entity load
- **`simplified_map_editor.py:7214–7234`** — `determine_entity_map`: converts entity `(x, z)` to sector coords, checks each `map_info` bbox from `grid_config.maps`; returns the matching `map_info.name` or `None`
- **`simplified_map_editor.py:3562–3582, 10552`** — identical `_determine_object_map` for the object dataclass
- **`simplified_map_editor.py:7989–7999`** — entity browser "By Map" grouping: one `QTreeWidgetItem` header per unique `entity.map_name` (basename shown)
- **`simplified_map_editor.py:9655`** — `stat_map_label` in Statistics panel shows `entity.map_name`
- **`simplified_map_editor.py:8308`** — copied from entity to object when merging
- **`entity_export_import.py:432`** — serialized in export JSON
- **`all_in_one_copy_paste.py:217, 233, 475`** — saved and restored through the clipboard round-trip

###### `move_sector` / "Move Sector"

- **`simplified_map_editor.py:7086–7097`** — right-click context menu: "Move to Different Sector…" shown only when `entity.source_file_path` contains `'worldsector'`; calls `move_entity_to_sector_manually`
- **`simplified_map_editor.py:6481–6560`** — `move_entity_to_sector_manually`: prompts user with `QInputDialog` to pick a sector number, then moves the entity's XML element between sector trees. Sector list comes from `worldsectors_trees.keys()` via regex on filename — **not** position-based.

###### `worldsectors_trees` (the central sector store)

- **`simplified_map_editor.py:577`** — `self.worldsectors_trees = {}` in `__init__`
- Structure: `dict[str, ET.ElementTree]` mapping `.converted.xml` file path → parsed tree
- **`simplified_map_editor.py:4434–4477`** — `save_all_xml_files_before_conversion` iterates ALL trees and writes every one to disk — **no dirty tracking**, all files always saved
- **`canvas/map_canvas_gpu.py:3085–3096`** — `update_entity_xml` routes to `_update_worldsector_xml_fcb_format` for `.converted.xml` or `.data.xml` source files
- **`canvas/map_canvas_gpu.py:3102–`** — `_update_worldsector_xml_fcb_format` looks up the tree in `main_window.worldsectors_trees` and updates the entity's `hidPos` BinHex in-place
- **`simplified_map_editor.py:6281–6374`** — `_remove_entity_from_worldsector_fixed`: searches ALL MissionLayers in the source sector tree, removes entity XML element in-memory, writes tree immediately
- **`all_in_one_copy_paste.py:979–1009`** — `verify_entity_id_unique` and `verify_entity_name_unique` both iterate `worldsectors_trees` to check for collisions
- **`all_in_one_copy_paste.py:1148–1152`** — paste calls `_find_best_worldsector_for_entity` to pick where to add the new entity

###### `_find_best_worldsector_for_entity` — ✅ FIXED (position-based)

- **`all_in_one_copy_paste.py`** — now builds a `known_sectors` map from `worldsectors_trees` and uses `gx = floor(x/64)`, `gy = floor(y/64)`, `sector_id = gy*16+gx` to find the correct file; falls back to `available_files[0]` if out-of-bounds. Returns `(xml_path, sector_id)` tuple. Sets `source_sector_id`, `source_layer`, and marks `canvas.dirty_sectors` on success.
- **`simplified_map_editor.py:5712–5732`** — `_find_target_worldsector_file` still naive (`available_files[0]`). Only used by the old single-sector paste path; unified mode does not use it.

###### `MissionLayer`

- **Current code does NOT track per-entity MissionLayer assignment.** Entities don't have a `source_layer` attribute yet.
- **Removal** (`_remove_entity_from_worldsector_fixed`) — searches all MissionLayers in the file for the entity by name; no layer tracking needed.
- **Addition** (`all_in_one_copy_paste.py:1254–1300`) — `_add_entity_xml_to_sector` finds all MissionLayers, prefers `"outside_entity"`, falls back to `"main"`.
- **Export/import** (`entity_export_import.py:1063, 1717–1781, 2246`) — has a UI combo to let the user pick a target MissionLayer.
- **No existing `source_layer` field** — must be added to `Entity` dataclass (Step 2) and populated at load time (Step 3).

###### `load_complete_level` — worldsector load path

- **`simplified_map_editor.py:2865`** — entry point; only loads the **single** worldsector folder associated with the selected level
- Worldsector files are loaded via `load_level_objects` → populates `worldsectors_trees` from `worldsector*.data.fcb.converted.xml`; `landmarkfar_*` and `landmarknear*` are skipped
- `map_name` is assigned to each entity via `determine_entity_map` after load
- The new `load_all_worldsectors` (Step 3) will be a parallel path — `load_complete_level` stays untouched

###### Entity browser grouping

- **`simplified_map_editor.py:7263–7265`** — `group_combo` options: `["No Grouping", "By Map", "By Source", "By Type"]`
- "By Map" uses `entity.map_name` as the group key — this is the grouping that needs a "By Sector" variant in unified mode

###### `_get_map_filtered_entities` (rendering hot path)

- **`canvas/map_canvas_gpu.py:1668–1684`** — cache key is `(id(self.entities), map_name)`. If `map_name` is `None`, returns all entities unfiltered.
- **Unified mode fix is trivial:** set `canvas.current_map = None` before rendering — the `else: filtered = self.entities` branch already handles it.

###### Files that need changes for unified mode (summary)

| File | What changes |
|------|-------------|
| `data_models.py` | Add `source_sector_id` and `source_layer` fields |
| `simplified_map_editor.py` | Add `load_all_worldsectors`; extend `save_all_xml_files_before_conversion` with dirty-sector path; hide "Move Sector" when unified; add "Open All Sectors" menu item; update `stat_map_label`; update entity browser |
| `canvas/map_canvas_gpu.py` | `_get_map_filtered_entities`: skip filter when `unified_mode`; add `unified_mode` flag; `set_current_map` no-op in unified mode |
| `canvas/input_handler.py` | Skip `map_name` filter in selection when `unified_mode` |
| `all_in_one_copy_paste.py` | ✅ Skip `map_name` guard in paste; ✅ replaced naive `_find_best_worldsector_for_entity` with position-based lookup |

###### What does NOT need to change

- `_remove_entity_from_worldsector_fixed` — already searches all layers; works as-is
- `_update_worldsector_xml_fcb_format` — already looks up the tree from `worldsectors_trees`; works as-is
- `managers.xml` vPos sync — already game-mode agnostic
- `omnis.fcb` / `mapsdata.fcb` loading — not affected

---

#### Step 2 — Entity data model changes (`data_models.py`)

Add two new fields to the `Entity` dataclass:
```python
source_sector_id: int = -1    # sector ID (GY*16+GX) this entity was loaded from
source_layer: str = "main"    # MissionLayer name this entity belongs to
```

These must survive copy/paste, export/import. Do NOT add them to the XML — they are editor-only metadata.

**Implemented (April 2026):**
- `data_models.py` — `source_sector_id: int = -1` and `source_layer: str = "main"` added to `Entity` dataclass after `entity_type`
- `all_in_one_copy_paste.py` — both fields serialized in the copy dict (both `has_xml_element` branches) and restored on paste
- `entity_export_import.py` — both fields included in the optional metadata export block

#### Step 3 — Multi-sector load function

In `simplified_map_editor.py`, add `load_all_worldsectors(worldsectors_folder)`:
- Glob `worldsector*.data.fcb.converted.xml` (skip `landmarkfar_*` and `landmarknear*`)
- For each file: parse XML, extract GX/GY from WorldSector X/Y fields, compute sector_id = GY*16+GX
- For each MissionLayer inside: record `layer_name` from `text_PathId`
- For each Entity inside: create Entity dataclass, set `source_sector_id` and `source_layer`
- Store `clean_hash[sector_id] = hash(xml_text)` for dirty detection
- Merge all entities into the main canvas entity pool
- Set `canvas.unified_mode = True`

The existing `load_complete_level` (single-sector) must keep working unchanged — unified mode is opt-in.

**Implemented (April 2026):**
- `simplified_map_editor.py` — `load_all_worldsectors(worldsectors_folder, log_callback=None)` added after `load_level_objects_internal`
- `self.sector_clean_hashes = {}` added to `__init__` and reset at top of `load_complete_level`
- `canvas/map_canvas_gpu.py` — `self.unified_mode = False` added to canvas `__init__`; reset to `False` in `load_complete_level` reset block
- The function converts FCBs via `file_converter.convert_data_fcb_files`, parses each `worldsector*.data.fcb.converted.xml`, stores trees in `worldsectors_trees`, stores `sector_clean_hashes[sector_id] = hash(xml_text)`, creates `Entity` objects with `source_sector_id`/`source_layer` set, sets `canvas.unified_mode = True` and `canvas.current_map = None`
- Gotcha: the existing load path (`load_level_objects_internal` → `on_objects_loaded`) does NOT populate `worldsectors_trees` — trees are populated lazily in `_update_worldsector_xml_fcb_format`. `load_all_worldsectors` pre-populates all trees upfront, which is required for dirty-sector save (Step 6).

#### Step 4 — Dirty sector tracking

In `simplified_map_editor.py` or `canvas/map_canvas_gpu.py`:
```python
self.dirty_sectors: set[int] = set()

def mark_sector_dirty(self, entity):
    gx = int(entity.x // 64)
    gy = int(entity.y // 64)
    self.dirty_sectors.add(gy * 16 + gx)
    # Also dirty the source sector if entity has moved
    if entity.source_sector_id >= 0:
        self.dirty_sectors.add(entity.source_sector_id)
```

Hook `mark_sector_dirty` into `mark_entity_modified`.

**Implemented (April 2026):**
- `canvas/map_canvas_gpu.py` — `self.dirty_sectors: set = set()` added to canvas `__init__`
- `canvas/map_canvas_gpu.py` — `mark_sector_dirty(entity)` added after `mark_entity_modified`; marks `floor(x/64)`, `floor(y/64)` → `sector_id` dirty, plus `entity.source_sector_id` if set
- `canvas/map_canvas_gpu.py` — `mark_entity_modified` calls `self.mark_sector_dirty(entity)` when `self.unified_mode` is True
- `simplified_map_editor.py` — `canvas.dirty_sectors = set()` added to the `load_complete_level` reset block (alongside the existing `canvas.unified_mode = False`)

#### Step 5 — Sector XML rebuilder

New function `rebuild_sector_xml(sector_id, entities, gx, gy)`:
- Creates `WorldSector` root with Id/X/Y fields (including correct BinHex)
- Groups entities by `source_layer`
- For each layer group: creates `MissionLayer` block with `text_PathId` + `PathId` (ComputeHash32) fields + all Entity XML subtrees
- Returns the XML string

**PathId BinHex:** Compute `CRC32` hash of the layer name string using the existing `ComputeHash32` encoding logic (same as other hash fields).

**Implemented (April 2026):**
- `simplified_map_editor.py` — `import struct` added to stdlib imports
- `simplified_map_editor.py` — three module-level helpers added after `_get_str_val`: `_int32_to_binhex`, `_string_to_binhex`, `_compute_hash32_to_binhex` (same algorithms as `entity_editor.py`)
- `simplified_map_editor.py` — `rebuild_sector_xml(sector_id, gx, gy, entities)` added as a module-level function; returns `ET.ElementTree`; entity XML elements are deep-copied via `ET.tostring` + `ET.fromstring` so in-memory entities are untouched
- Note: hash algorithm is djb2-style (`h = (h<<5) + h + ord(ch)`) — same as `compute_hash32` in `entity_editor.py`

#### Step 6 — Dirty-only save

Replace / extend `save_all_xml_files_before_conversion`:
- If `canvas.unified_mode`: run dirty-sector save loop (Steps 3–4 in the tracking section above)
- Else: existing single-sector save (unchanged)

Show status: `"Saving... N of M sectors changed"` in status bar.

**Implemented (April 2026):**
- `simplified_map_editor.py` — `save_all_xml_files_before_conversion` section 3 split into unified/single-sector branches; unified branch delegates to `_save_unified_worldsectors`
- `simplified_map_editor.py` — `_save_unified_worldsectors(log_callback)` added (before `_sync_managers_vpos`):
  1. Builds `known_sectors` dict from `worldsectors_trees` (sector_id → gx, gy, xml_path)
  2. Computes `entity_target` (entity → target sector by `floor(x/64)`, `floor(y/64)`); out-of-bounds entities fall back to `source_sector_id` with status bar warning
  3. Builds `final_dirty` = `canvas.dirty_sectors` ∪ {sectors where entity moved between sectors}
  4. For each dirty sector: calls `rebuild_sector_xml`, serialises to string, compares hash to `sector_clean_hashes`; unchanged sectors skipped; changed sectors written to disk and added to `self._unified_dirty_xml_paths`
  5. Updates `entity.source_sector_id` and `entity.source_file_path` for all worldsector entities
  6. Clears `canvas.dirty_sectors`
- `simplified_map_editor.py` — `_convert_worldsector_files_fixed` extended: when `unified_mode`, only processes files in `self._unified_dirty_xml_paths` (zero FCBConverter calls when nothing changed)

#### Step 7 — UI changes

- New **"Open All Sectors"** button / menu item alongside existing "Open Level"
- Sector boundary overlay **always shown** in unified mode (already exists — make it the default)
- **Hide "Move Sector" button** when `unified_mode = True` (no longer needed)
- Status bar shows `"Unified mode — N sectors loaded"` instead of `"Map: worldsectorXX"`
- Entity browser: in unified mode, show sector ID as a secondary grouping (collapsible) instead of the primary filter
- Statistics panel `stat_map_label` → show `"Sector N (layer_name)"` in unified mode

#### Step 8 — Things that reference `current_map` / `map_name` and need updating

Based on the audit (Step 1), every place that currently filters by `current_map` or `map_name` needs to become "show all" in unified mode. The general pattern:

```python
# Old: filter by current_map
if entity.map_name != self.canvas.current_map.name:
    continue

# New: in unified mode, no filter (show all sectors)
if not getattr(self.canvas, 'unified_mode', False):
    if entity.map_name != self.canvas.current_map.name:
        continue
```

The NumPy vectorised culling in `_get_visible_entities` also needs to drop the map-name filter in unified mode.

**Implementation complete.** Three filter sites updated with `not getattr(..., 'unified_mode', False)` guard:

- `canvas/map_canvas_gpu.py` — `_get_map_filtered_entities`: added `unified_mode` check around the `map_name` filter; unified mode returns all entities unfiltered.
- `canvas/input_handler.py` (two sites) — box-selection loop (~line 362) and single-click pick loop (~line 545): same guard pattern so all entities are selectable across sector boundaries.
- `all_in_one_copy_paste.py` (~line 1903) — select-all paste loop: same guard so Ctrl+A in unified mode selects all entities regardless of map_name.

#### Step 9 — Mission layers (out of scope for v1, document for future)

In v1, each entity keeps its original `source_layer` even when moved to a new sector. A future enhancement could add a UI picker to change an entity's mission layer assignment. For now, moving to a new sector preserves the layer name — if the target sector didn't previously have that layer, it gets created on save.

**Implementation note (v1):** No code changes needed for Step 9. `source_layer` is already stored on every Entity (added in Step 2) and `rebuild_sector_xml` already groups entities by `source_layer` when building `MissionLayer` elements. The "out of scope" decision is implemented by design — no layer-picker UI was added.

### Post-implementation fixes and additions

The following bugs were discovered and fixed during testing after the 9-step plan was completed:

#### Duplicate entities on "Open All Sectors" (first fix — partial)
- **Root cause:** `on_objects_loaded` only tagged entities as `source_file = "worldsectors"` when the filename ended with `.data.xml`. Actual filenames end with `.data.fcb.converted.xml`, so the tag was never set. The dedup filter in `load_all_worldsectors` couldn't find and remove those entities, causing every worldsector entity to appear twice.
- **Fix:** `on_objects_loaded` now tags any entity whose source filename starts with `"worldsector"` (no extension check). `load_all_worldsectors` dedup filter also checks `source_file_path` for "worldsector" as a safety net.

#### Duplicate entities still appearing on every level load (second fix)
- **Root cause:** The source-file-based dedup above is fragile — any entity where `source_file` wasn't tagged correctly (e.g. `obj.source_file` was None, or the path format differed) would slip through the filter and remain in the pool alongside its fresh copy from `load_all_worldsectors`. This manifested as every entity appearing twice: moving/deleting one left a ghost at the original position.
- **Fix:** `load_all_worldsectors` step 3 now uses **ID-based dedup** instead. Builds `new_entity_ids = {e.id for e in new_entities}`, then filters `self.entities` to remove any entity whose ID is in that set before appending `new_entities`. This is robust regardless of how entities were tagged — if an entity ID is in the new set, any pre-existing copy is always removed. The log line now reports how many were replaced for debugging.

#### Rebuilt sector XML missing game-required metadata / wrong positions
- **Root cause:** `rebuild_sector_xml` built a minimal `WorldSector` skeleton from scratch, omitting all `hash` attributes and any extra fields present in the original file. Also, if `_update_worldsector_xml_fcb_format` failed to find an entity by name (e.g. unnamed entities), `entity.xml_element` would have stale coordinates.
- **Fix:** `rebuild_sector_xml` now accepts an `original_tree` parameter. It deep-clones the original tree (preserving all attributes), strips existing Entity elements from MissionLayers, then re-adds the correct entities. Entity positions are always written from `entity.x/y/z` directly (bypassing the stale xml_element issue). A `_coords_to_binhex` helper was added for float→BinHex Vector3 encoding.

#### Real-time stats/tree updates during drag not firing
- **Root cause:** The `position_update` signal was unreliable during drag. More critically, entity movement in the editor goes through the **gizmo** center-square drag path (`canvas/gizmo_renderer.py`), not the regular input handler drag path.
- **Fix:** Both drag paths now directly walk the parent chain and call `main_window.on_entity_position_updated(entity, (x, y, z))` on every mouse move frame. `on_entity_position_updated` was extended to also update `stat_map_label` showing `"Sector 33 → 17 (main)"` when the entity crosses a sector boundary. The "By Sector" tree rebuilds on drag-end if the entity landed in a different sector (in both input_handler and gizmo_renderer).

#### Unified mode required manual activation
- **Fix:** `load_complete_level` now auto-calls `load_all_worldsectors(worldsectors_path)` at step 7 (finalization) for Avatar levels. Since July 2026 FC2 is included too (all cell folders passed as a list — see "FC2 parity" section). The FCB conversion pass in `load_all_worldsectors` is effectively free since files were already converted earlier in the same load.

#### "No Sector" catch-all group in entity browser
- **Fix:** `_populate_tree_by_sector` now groups non-worldsector entities by `source_file` name (`omnis`, `managers`, `mapsdata`, `sectorsdep`, etc.) instead of dumping them all into a single "No Sector" header.

#### Entity browser not refreshing after save
- **Fix:** `save_level` now calls `update_entity_tree()` after `_convert_worldsector_files_fixed` completes, so sector assignments reflect the saved state.

#### Position column hidden in entity tree
- **Fix:** Column 2 ("Position") now has an explicit width of 140px set at widget creation time.

#### Save system correctness fixes (April 2026)

The following bugs were found and fixed after the initial unified save implementation:

##### Landmarks included in `known_sectors` — caused wrong sectors to be rebuilt
- **Root cause:** `_save_unified_worldsectors` built `known_sectors` from `worldsectors_trees` without filtering by filename. `landmarkfar_*` and `landmarknear_*` files have `X`/`Y` grid fields that collide with real worldsector IDs. These overwrote the correct worldsector entries in the dict, so landmarks were falsely marked dirty and rebuilt with the wrong entity data.
- **Fix:** Both the `known_sectors` build loop and the `ws_entities` filter now check `os.path.basename(xml_path).lower().startswith('worldsector')`. This excludes all landmark files from unified save entirely.

##### Entities "moving" between sectors on save (boundary entities)
- **Root cause:** Entity grouping used position-based sector assignment (`floor(x/64)`). `int(640//64) == 10` puts a boundary entity into sector 74 instead of 73, so the entity was written to the wrong sector file on every save.
- **Fix:** `_save_unified_worldsectors` now groups entities by `source_sector_id` (the sector they were loaded from), not by current position. Legitimate cross-sector moves are handled by `mark_sector_dirty` in `map_canvas_gpu.py`, which updates `entity.source_sector_id` when an entity is dragged to a new sector cell.

##### `mark_sector_dirty` now updates `source_sector_id`
- `canvas/map_canvas_gpu.py::mark_sector_dirty(entity)` — when the computed `new_sector_id` differs from `entity.source_sector_id`, both the old and new sector IDs are added to `dirty_sectors`, and `entity.source_sector_id` is updated to `new_sector_id`. This ensures that after a cross-sector drag, the entity is written to its new sector on save, not its original one.

##### Deletion not marking sector dirty
- **Root cause:** `_remove_entity_from_worldsector_fixed` removed the entity from the sector XML in-memory but did not add the sector to `canvas.dirty_sectors`, so the change was never written to FCB.
- **Fix:** In `all_in_one_copy_paste.py`, after a successful `_remove_entity_from_worldsector_fixed` call, `canvas.dirty_sectors.add(src_sid)` is called where `src_sid = entity.source_sector_id`.

##### mapsdata / omnis entity position changes not saving
- **Root cause:** For non-worldsector entities (source_file = `mapsdata`, `omnis`, `managers`, etc.), the XML tree was written to disk directly from `entity.xml_element`. But `entity.x/y/z` could be updated by canvas drag without `entity.xml_element.hidPos` being synced (that sync only happens via `_update_worldsector_xml_fcb_format` for worldsector files).
- **Fix:** `save_all_xml_files_before_conversion` (step 0, before writing any trees) now iterates all non-worldsector entities and writes `entity.x/y/z` back to the `hidPos` and `hidPos_precise` fields (both `value-Vector3` attribute and BinHex text) using `_coords_to_binhex`.

##### Double logging in `_save_unified_worldsectors`
- **Root cause:** The inner `_log` closure called both `log_callback(msg)` AND `print(msg)`. Since `log_callback` was already set to the outer `_log` which also called `print`, each message was printed twice.
- **Fix:** Inner `_log` now calls `log_callback(msg)` when available, `print(msg)` as fallback only (not both).

##### `file_converter.py` timeout raised to 120s
- `convert_converted_xml_back_to_fcb` now uses `timeout=120` (up from 30s). Large sector files (e.g. worldsector73 with 960 entities) were timing out at 30s. Replace both occurrences when editing.

##### New MissionLayer elements missing hash/type attributes → FCBConverter hang
- **Root cause:** `rebuild_sector_xml` created new `<object name="MissionLayer">` elements without the `hash` attribute, and its child `<field>` elements without `hash` or `type="BinHex"`. FCBConverter requires these to convert back to binary; without them it enters an infinite loop and times out at 120s. Triggered whenever a pasted entity had a `source_layer` that didn't already exist as a MissionLayer in the target sector's original tree.
- **Fix:** `rebuild_sector_xml` (`simplified_map_editor.py`, `if layer_elem is None:` branch) now always adds `hash="494C09F2"` to the object element and `hash`/`type="BinHex"` to both field elements. Known hashes: MissionLayer=`494C09F2`, text_PathId=`C56F9204`, PathId=`D0E30BF7`.
- **Test:** `tests/test_rebuild_sector_xml.py` — verifies the new MissionLayer element has correct attributes.

##### Paste/duplicate always wrote `source_layer = 'outside_entity'` regardless of copy source
- **Root cause:** `paste_entities` in `all_in_one_copy_paste.py` hardcoded `entity.source_layer = 'outside_entity'` after adding to the sector tree, overwriting whatever layer the source entity was in. This caused every pasted/duplicated entity to always land in the "outside_entity" layer — even if the original was in "main" — and triggered the missing-hash MissionLayer bug above.
- **Fix:** The hardcoded assignment was removed. `entity.source_layer` is now set once from the copy data (line ~482) and preserved throughout. If the target sector doesn't have that layer yet, `rebuild_sector_xml` creates it with correct attributes.

### Sector assignment edge cases

| Situation | Handling |
|-----------|---------|
| Entity within expected bounds | `floor(x/64)*GX + floor(y/64)*16` → exact sector |
| Entity 1–5 units outside bounds (~1% of entities) | Same formula — the 64-unit grid is the source of truth; the original files had these slightly out-of-bounds too |
| Entity moved far outside all known sector bounds | Fallback: keep in `source_sector_id`; warn in status bar |
| Entity moved to a grid position with no existing sector file | Fallback: keep in `source_sector_id`; warn. Creating new sector files is out of scope for v1 |
| New entity (pasted / created) with no `source_sector_id` | Assign via floor formula on first save; use `source_layer = "main"` |

### Do NOT change

- `landmarkfar_*` and `landmarknear*` files — streaming sector triggers, unrelated to entity editing
- `managers.xml` vPos sync logic — already game-mode agnostic; keep as-is
- `omnis.fcb` / `mapsdata.fcb` loading — separate from worldsectors, not affected
- ~~FC2 worldsector loading — deferred~~ **Implemented July 2026** — FC2 unified mode loads all 25 cell folders onto a global 80×80 sector grid; see the "FC2 parity — unified sectors, global sector grid, cell offsets (July 2026)" section for the invariants that must not be broken

---

## To Do Features

### 1. Create New Sector File ✅ COMPLETE

**What it does:** Lets the user create a brand-new `worldsectorN.data.fcb` for any sector that currently has no entity data (i.e. no `HasMainSectorData` entry in `sectorsdep`). The new file starts empty and becomes editable in the level editor like any existing sector.

**Background — file system understanding:**

The Avatar worldsector system has three layers:

| File | Location | Purpose |
|------|----------|---------|
| `worldsectorN.data.fcb` | `levels/<level>/generated/worldsectors/` | Actual gameplay entities — what you edit |
| `sectorN.desc.fcb` | `levels/<level>/generated/worldsectors/` | Per-sector streaming neighbor list + asset preload manifest |
| `<world>.sectorsdep.xml` | `worlds/<world>/generated/` | World-level registry: which sectors have which data files |

**Sector ID formula:** `Id = Y * 16 + X` where `X = Id % 16`, `Y = Id // 16`. Sector size is 64×64 world units.

**Three steps required to create sector N:**

**Step 1 — Create `worldsectorN.data.fcb.converted.xml`** (empty entity file):
```xml
<?xml version="1.0" encoding="utf-8"?>
<object hash="C1CB6D9A" name="WorldSector">
  <field hash="2ABD43F2" name="Id" value-Int32="N" type="BinHex">{N as LE int32 hex}</field>
  <field hash="B7B2364B" name="X" value-Int32="X" type="BinHex">{X as LE int32 hex}</field>
  <field hash="C0B506DD" name="Y" value-Int32="Y" type="BinHex">{Y as LE int32 hex}</field>
  <object hash="494C09F2" name="MissionLayer">
    <field hash="C56F9204" name="text_PathId" value-String="main" type="BinHex">6D61696E00</field>
    <field hash="D0E30BF7" name="PathId" value-ComputeHash32="main" type="BinHex">64CD28BF</field>
  </object>
</object>
```

**Step 2 — Convert to FCB** via FCBConverter:
- FCBConverter reads `worldsectorN.data.fcb.converted.xml`
- Produces `worldsectorN.data_new.fcb`
- Rename to `worldsectorN.data.fcb`

**Step 3 — Add `HasMainSectorData` to `sectorsdep.xml`:**
Find the `CWorldSector` entry with `SectorId=N` and insert:
```xml
<field hash="346F3F63" name="HasMainSectorData" type="BinHex">01</field>
```
after the `HasDescriptor` field. The `sectorsdep.xml` file is a plain XML (not FCB) — edit in place. Note: if the game reads a compiled `.fcb` version of this file, that also needs regenerating.

**Known field hashes (from analysed files):**
- `WorldSector` object hash: `C1CB6D9A`
- `Id` field hash: `2ABD43F2`
- `X` field hash: `B7B2364B`
- `Y` field hash: `C0B506DD`
- `MissionLayer` object hash: `494C09F2`
- `text_PathId` hash: `C56F9204`
- `PathId` hash: `D0E30BF7`
- `PathId` BinHex for `"main"`: `64CD28BF`
- `HasMainSectorData` field hash: `346F3F63`

**Standalone script:** `enable_all_sectors.py` in the project root already handles bulk `sectorN.desc.fcb` neighbor modifications. A `create_sector.py` companion script should handle the three steps above for any given sector ID.

**UI integration (future):** Right-click on an empty cell in the sector grid → "Create Sector Here" → runs the three steps, then reloads the level in unified mode.

---

### 2. Enable/Load/Render All Sectors ✅ IMPLEMENTED

**What it does:** Forces the engine to stream all 256 sector cells at once, so the entire map is active with no pop-in. Intended for testing — significant RAM cost.

**Background — the two-layer streaming system:**

The engine's sector streaming is controlled by two independent files:

**Layer 1 — `sectorN.desc.fcb` (neighbor list):**
Each sector lists which other sectors to stream in when the player is inside it. By default, edge sectors list ~15 neighbors; interior sectors list ~23–48. To force all sectors always loaded, every sector's `SectorDesc` must list all 255 others.

**Layer 2 — `<world>.sectorsdep.xml` (sector registry):**
The world-level master index. Controls whether the engine even knows a sector has entity data via `HasMainSectorData`. Only sectors with this flag will have their `worldsectorN.data.fcb` loaded. This is separate from streaming — it's the top-level capability declaration.

**`sectorN.desc.fcb` structure (relevant parts):**
```xml
<object name="Sector">                          <!-- root, Id/X/Y here -->
  <object name="SectorDesc">
    <field name="version" value-Int32="124"/>
    <object name="Sector">                      <!-- one entry per neighbor -->
      <field name="id" value-Int32="N"/>
      <field name="Flags" value-Int16="309"/>   <!-- 0x0135 = "stream me" -->
    </object>
    ...
  </object>
  <object name="MetaObjects"/>                  <!-- always empty -->
  <object name="NativeResources">              <!-- asset preload manifest -->
    <object name="Category">...</object>
  </object>
</object>
```

**`sectorsdep.xml` structure (per sector entry):**
```xml
<object name="CWorldSector">
  <field name="SectorId" value-Int32="N"/>
  <field name="HasDescriptor" type="BinHex">01</field>
  <field name="HasMainSectorData" type="BinHex">01</field>  <!-- only if entity file exists -->
  <field name="HasLandmarkFar" type="BinHex">01</field>     <!-- only if landmarkfar file exists -->
  <field name="HasNavMesh" type="BinHex">01</field>
  <field name="DetailMask" value-Int32="16777215"/>
  <field name="isSectorAccessible" value-Boolean="True"/>
</object>
```

**`Flags` values observed:**
- `309` (`0x0135`, BinHex `3501`) — standard "load this neighbor" flag, used on all but the last entry per sector
- `52` (`0x0034`, BinHex `3400`) — appears on the final entry in sparse sectors (possibly lower-priority/farther streaming distance)

**FCBConverter batch mode (from official docs):**
```
FCBConverter.exe -source=<folder> -filter=<pattern>   # batch convert all matching files
FCBConverter.exe -source=<folder> -filter=*.fcb -subfolders  # recurse subdirectories
```
The `-fc2` flag is supported for Far Cry 2 files (not in official docs but confirmed in codebase).

**Implementation — `tools/enable_all_sectors.py`:**

PyQt6 GUI tool. Four-phase pipeline (phase 3 only runs when the worlds/generated folder is supplied):
1. **FCB → XML** — single `FCBConverter.exe -source=<dir> -filter=sector*.fcb` call
2. **Modify XMLs** — Python loop rewrites every `sectorN.desc.fcb.converted.xml` SectorDesc to list all 255 other sectors
3. **XML → FCB** — single `FCBConverter.exe -source=<dir> -filter=sector*.converted.xml` call, then Python rename loop (`sectorN.desc_new.fcb` → `sectorN.desc.fcb`)

Reduces 512+ subprocess calls to 2. Progress bar tracks phase 2 (XML edits). Phase label shows current phase. FC2 checkbox appends `-fc2` to both FCBConverter calls.

**Level editor integration (`simplified_map_editor.py`):**
- `Tools` menu → `Enable All Sectors...` (above separator, above Water Editor)
- Handler: `open_enable_all_sectors()` — dynamically imports the script via `importlib`, opens `EnableAllSectorsWindow` as a floating window
- Auto pre-fills the worldsectors folder path from `self.worldsectors_path` if a level is already loaded

**`sectorsdep.xml` note:** sectors without a `worldsectorN.data.fcb` file genuinely have no entity data — adding `HasMainSectorData` to them without a corresponding file would cause engine errors. Only modify that file when also creating the entity file (see Feature 1).

---

### Ctrl+click multi-select overwritten by `on_entity_selected` (fixed April 2026)

`input_handler.handle_mouse_press_2d` correctly builds the multi-selection and sets `canvas.selected` before emitting `entitySelected`. But `on_entity_selected` in `simplified_map_editor.py` called `select_entity_with_children(entity)` and unconditionally set `canvas.selected = group` — replacing the multi-selection with just the newly-clicked entity's group.

**Fix:** in `on_entity_selected`, if `entity` is already present in `canvas.selected` AND `canvas.selected` has more entries than the entity's own group, it's an active Ctrl+multi-select — skip the `canvas.selected = group` assignment and only update `selected_entity` and the model preview.

### Worlds-file save bug — modification flags never set (fixed April 2026)

`_convert_main_xml_to_fcb` gates FCB conversion on `xml_tree_modified` (mapsdata) and `omnis_tree_modified`. Both flags were broken:

- **`xml_tree_modified`**: only set inside `_auto_save_main_file` (drag-move path in canvas). Entity editor edits never triggered it → mapsdata FCB not regenerated after editor-only changes.
- **`omnis_tree_modified`**: **never set to True anywhere**. `_auto_save_entity_changes` routes omnis entities (which have `source_file_path` set) to `_auto_save_worldsector_file`, which looks in `worldsectors_trees` — omnis paths are not there → silently returns False every time.

**Fix:** in `save_all_xml_files_before_conversion`, set `xml_tree_modified = True` immediately after writing mapsdata XML, and use a `_modified_flags` dict to `setattr` the correct flag after writing each of omnis/managers/sectorsdep. This mirrors the existing `managers_tree_modified = True` pattern that was already correct.

**Regression test:** `tests/test_worlds_save_flags.py`

### Omnis/managers entity position edits not persisting on drag (fixed May 2026)

**Root cause:** `update_entity_xml` in `canvas/map_canvas_gpu.py` only routed to `_update_worldsector_xml_fcb_format` when `source_file_path` ended in `.converted.xml`. Omnis/managers paths end in `.omnis.xml` / `.managers.xml` → fell through to `return False`. `_auto_save_entity_changes` then called `_auto_save_worldsector_file` which looks in `worldsectors_trees` — omnis/managers paths are never there → silently returned False. Entity position was updated in memory but never written to disk.

**Key insight:** `entity.xml_element` for omnis/managers entities is a **live reference** into `main_window.omnis_tree` / `main_window.managers_tree` (set at parse time in `load_omnis_data` / `load_managers_data`). No tree search is needed — just update in place.

**Fix in `canvas/map_canvas_gpu.py`:**
- `update_entity_xml`: when `source_file in ('omnis', 'managers')` → call `_update_entity_fcb_in_place(entity)`
- `_update_entity_fcb_in_place`: calls `_update_fcb_position_field` directly on `entity.xml_element` for both `hidPos` and `hidPos_precise`
- `_auto_save_entity_changes`: checks `source_file` before `source_file_path`; omnis/managers → `_auto_save_named_tree(entity)`
- `_auto_save_named_tree`: gets `main_window.{source_file}_tree`, writes to `entity.source_file_path`, sets `{source_file}_tree_modified = True`

### Omnis entity duplication on reload (fixed May 2026)

**Root cause:** `cache_parsed_xml` in `simplified_map_editor.py::parse_xml_file` stored `self.entities` by reference. After mapsdata was cached, `load_omnis_data` appended omnis entities to `self.entities`, mutating the cached list. On next reload, the cache returned the poisoned list (mapsdata + omnis entities already merged), then omnis was appended again → duplication.

**Fix:** Two-sided copy:
- Cache store: `self.cache.cache_parsed_xml(file_path, list(self.entities))` (was `self.entities`)
- Cache hit: `self.entities = list(cached_entities)` (was `self.entities = cached_entities`)

### Mini model viewer alpha/transparency (fixed May 2026)

**Root cause:** `ModelPreviewWidget._draw_model_meshes` in `simplified_map_editor.py` never checked `textures_has_alpha` or enabled `GL_ALPHA_TEST`, so meshes with cutout transparency (foliage, fences) rendered as fully opaque in the mini viewer.

**Fix:** Added per-mesh alpha check mirroring `canvas/model_loader.py`'s display list renderer:
- Check `model.textures_has_alpha.get(mesh.material_index, False)` per mesh
- If True: `glEnable(GL_ALPHA_TEST)` + `glAlphaFunc(GL_GREATER, 0.1)` before draw, `glDisable(GL_ALPHA_TEST)` after
- Only meshes whose source PNG had a real alpha channel (`mode in RGBA/LA/PA`) get the alpha test

### Omnis/mapsdata entity structural placement must match text_hidMissionLayerPath (fixed April 2026)

When duplicating or pasting entities from omnis/mapsdata/managers/sectorsdep files, the new entity must be inserted into the correct `MissionLayer` element **structurally** in the XML — not just have the right `text_hidMissionLayerPath` field value. The two must match or the game ignores the entity.

- `entity.source_layer` (set at parse time from the enclosing MissionLayer's `text_PathId`) is the authoritative layer name
- `_add_entity_to_main_level_file` in `all_in_one_copy_paste.py` finds the matching `<object name="MissionLayer">` by comparing `text_PathId` value-String to `entity.source_layer` and appends the entity there
- To identify which MissionLayer an entity actually belongs to in the file, look at its structural enclosing `<object name="MissionLayer">`, NOT the `text_hidMissionLayerPath` field inside the entity (which is metadata, not structure)

### Duplicate paste routes by source_file first (fixed April 2026)

Before this fix, paste/duplicate always routed new entities to a worldsector file even if the original came from omnis/mapsdata/etc. Fix: `paste_entities` in `all_in_one_copy_paste.py` checks `entity.source_file` first — if it is `mapsdata`, `omnis`, `managers`, or `sectorsdep`, it calls `_add_entity_to_main_level_file`; otherwise falls through to the worldsector path.

### Frustum culling bypass for non-worldsector entities (fixed April 2026)

Entities from omnis/mapsdata/managers/sectorsdep files must never be dropped by frustum or budget culling in 3D mode. Fix: `_get_map_filtered_entities` (canvas) builds `self._never_cull_entities_3d` — a list of all loaded entities whose `source_file != 'worldsectors'`. After the normal frustum+budget pass in `_get_visible_entities`, any entity from `_never_cull_entities_3d` that wasn't included is appended unconditionally.

### XBG geometry winding order is CW (confirmed)
XBG mesh faces are wound clockwise in OpenGL space. `render_batched_models` uses `glFrontFace(GL_CW)` + `glCullFace(GL_BACK)`. Do NOT switch to `GL_CCW` — tested and confirmed to cause missing faces. The per-material `TwoSided` flag is not read per-mesh; culling is controlled globally in `render_batched_models` instead (currently disabled — the full model is visible from all angles).

### 3D model face-culling caused angle-dependent disappearance (fixed April 2026)

`render_batched_models` in `canvas/model_loader.py` was calling `glFrontFace(GL_CW)`, overriding the main scene's `GL_CCW`. Standard glTF models use CCW winding; the CW setting caused exterior faces to be treated as back faces and culled at certain angles. Fix: replaced `glEnable(GL_CULL_FACE) + glCullFace(GL_BACK) + glFrontFace(GL_CW)` with `glDisable(GL_CULL_FACE)`.

### cx_Freeze exe — no multiprocessing from QThread (fixed April 2026)

`FileConverter.convert_folder` uses `_convert_multiprocessing` (Pool) when > 1 FCB file needs converting. In a frozen exe, `multiprocessing.Pool` spawned from inside a `QThread` (the `PatchFolderScanThread`) is unreliable on Windows — workers may hang or fail silently. Fix: in `convert_folder`, skip `_convert_multiprocessing` when `getattr(sys, 'frozen', False)` and always use `_convert_sequential` in the exe. Dev mode still uses multiprocessing.

**Note:** `convert_data_fcb_files` (worldsector batch conversion) uses FCBConverter's own batch mode (`-source=folder -filter=*.data.fcb`) — a single subprocess call, not Python multiprocessing. This path is fine in both dev and exe.

### FCBConverter subprocess — always hide the console window (fixed April 2026)

Every `subprocess.run` call that invokes FCBConverter was missing the `CREATE_NO_WINDOW` / `STARTF_USESHOWWINDOW` flags, causing a flash of cmd windows visible to the user. Fix: `FileConverter._hidden_window_kwargs()` returns the correct `startupinfo` + `creationflags` dict for Win32 (no-op on other platforms). All `subprocess.run` calls in `FileConverter` now spread `**self._hidden_window_kwargs()` into their kwargs. `_convert_fcb_worker` (the multiprocessing worker function) had its own inline version already and was left unchanged.

### Patch scan conversion progress in log box (fixed April 2026)

`convert_folder` and both conversion paths (`_convert_sequential`, `_convert_multiprocessing`) now accept a `log_callback` parameter. The scan thread (`PatchFolderScanner.run`) defines `_scan_log(msg)` which emits `self.progress_updated.emit(15, msg)` — a Qt queued signal to the main thread. The `on_progress` handler calls `progress_dialog.append_log(message)`, so each file converted appears in the log box as it completes.

- `_convert_sequential`: calls `log_callback` before each file starts
- `_convert_multiprocessing`: calls `log_callback` after each result comes back from `pool.imap` (worker processes can't call back directly — the hook is in the main scan thread's result loop)
- `convert_folder` passes `log_callback` through to whichever path is chosen; multiprocessing path in dev mode, sequential in frozen exe

## Terrain Editor (`canvas/terrain_editor_dialog.py`) — May 2026

Full heightmap sculpting tool for Avatar `.csdat` terrain files. Accessible via Tools → "⛰ Terrain Editor...". Opens as a non-modal window (re-uses the same instance on subsequent opens).

### Architecture

- **`TerrainData`** — in-memory state: `sectors_data` dict (sector_num → (65,65) float32), `combined` numpy array (sectors_y×65, sectors_x×65), `dirty_sectors` set, undo/redo stacks (cap 20).
- **`HeightmapEditor2D(QWidget)`** — left panel; draws the combined heightmap as a coloured elevation image; handles brush strokes via `mousePressEvent`/`mouseMoveEvent`; emits `stroke_at(hx, hy)` and `stroke_end()` signals; supports scroll-to-zoom + middle-drag-to-pan.
- **`TerrainPreview3D(QOpenGLWidget)`** — right panel; orbit camera (right-drag to rotate, middle-drag to pan, scroll to zoom); renders a stride-8 downsampled mesh (~130×130 verts) using legacy OpenGL client-state arrays; elevation colour ramp matches 2D view.
- **`TerrainEditorDialog(QDialog)`** — main window; toolbar (Load, Save, Undo, Redo); tools panel (Raise/Lower/Flatten/Smooth/Set, brush size + strength sliders, target height field).

### Live update flow
1. Brush stroke → modify `TerrainData.combined` numpy array in-place (Gaussian falloff, vectorised numpy).
2. Regenerate `QImage` from combined → update 2D view immediately.
3. `TerrainPreview3D.rebuild_mesh()` called → 3D view updates.
4. `QTimer` (100 ms debounce) calls `TerrainRenderer.update_from_heightmap(combined)` → main canvas terrain pixmap regenerated → `canvas.update()`.
5. File writes only happen on explicit "Save to CSDAT" — never during brushing.

### `TerrainRenderer.update_from_heightmap(array)`
Added to `canvas/terrain_renderer.py`. Replaces `combined_heightmap` and regenerates `terrain_pixmap` using the same elevation colour ramp as `_generate_terrain_image_procedural`. Does not re-read any files.

### Coordinate system
- Combined array row 0 = display top = high-Y world. Matches `_generate_terrain_image_procedural` layout.
- Brush at pixel (cx, cy) marks dirty sectors: `sector_row = sectors_y-1-display_row`, `sector_idx = sector_row*sectors_x + col`.
- On save: per-sector region extracted with `np.flipud` (undoes load-time flip), written as `uint16 = clip(h*128, 0, 65535)`. Unknown bytes at positions 2–3 of each 4-byte sample are preserved.

### Brush tools
All use Gaussian falloff (`sigma = radius/3`). Heights clamped to `[0, 511.99]`.
- **Raise/Lower**: `±alpha * 5.0` per stroke event.
- **Flatten**: lerp toward target height by `alpha`.
- **Smooth**: 3×3 mean filter blended by `alpha`.
- **Set**: stamp exact target height within mask.

### FC2 note
~~FC2 `.sdat` uses offset 592; this editor loads only `.csdat` (offset 708). FC2 editing not supported in this version.~~ **FC2 supported since July 2026:** `TerrainData(game_mode=...)` derives `.sdat`/592 vs `.csdat`/708, remaps FC2's global sd numbering (row stride 80) and Avatar multi-part numbering to local 0-based indices, and records `sector_files[local_idx] = path` at load so `save_dirty_sectors` writes each index back to the exact file it came from. `open_terrain_editor` / `show_terrain_editor` / `TerrainEditorDialog` all take `game_mode`. The live preview (`TerrainRenderer.update_from_heightmap`) applies FC2's extra −90° image rotation to match the canvas orientation. Tests: `tests/test_terrain_editor_fc2.py`.

### `open_terrain_editor` in `simplified_map_editor.py`
Keeps a `_terrain_editor_window` reference; re-uses the existing window on subsequent menu clicks instead of spawning a new dialog.

## Now Added

### Fix: `entity_export_import.py` import does not set `source_sector_id` or `source_layer` ✅ COMPLETE

**Priority:** Required for unified mode correctness — without this, imported entities break dirty-sector tracking and will be written to the wrong MissionLayer on save.

**File:** `entity_export_import.py`

**Where:** `import_single_entity` (around line 2226), immediately after:
```python
entity.source_file = "worldsectors"
entity.source_file_path = sector_file_path
```

**What to add:**

1. **`source_layer`** — the layer name for the selected MissionLayer. The dialog already tracks this in `self.available_layers` (a list of `{'index', 'name', 'entity_count'}` dicts populated by `on_sector_changed`). Use:
   ```python
   if hasattr(self, 'available_layers') and 0 <= target_layer_index < len(self.available_layers):
       entity.source_layer = self.available_layers[target_layer_index]['name']
   else:
       entity.source_layer = 'main'
   ```

2. **`source_sector_id`** — compute from the sector XML. Add a helper method `_get_sector_id_from_path(sector_file_path)` on the import dialog class:
   ```python
   def _get_sector_id_from_path(self, sector_file_path):
       """Read GX/GY from WorldSector XML and return GY*16+GX. Returns -1 on failure."""
       try:
           tree = self.parent_editor.worldsectors_trees.get(sector_file_path)
           if tree is None:
               tree = ET.parse(sector_file_path)
           root = tree.getroot()
           gx_field = root.find(".//field[@name='X']")
           gy_field = root.find(".//field[@name='Y']")
           if gx_field is not None and gy_field is not None:
               gx = int(gx_field.get('value-Int32', -1))
               gy = int(gy_field.get('value-Int32', -1))
               if gx >= 0 and gy >= 0:
                   return gy * 16 + gx
       except Exception:
           pass
       return -1
   ```
   Then call it:
   ```python
   entity.source_sector_id = self._get_sector_id_from_path(sector_file_path)
   ```

**Why it matters:**
- `source_sector_id = -1` (the default) means `mark_sector_dirty` in unified mode will dirty the wrong sector (or no sector) when this entity is moved — it would never be reconverted on save
- `source_layer = 'main'` (the default) is silently wrong if the user picked a different layer — the entity will be written to `main` on the next save instead of the chosen layer
- Both fields are already correctly set for entities loaded via `load_all_worldsectors`; this aligns the import path with the load path

**No other changes needed** — `import_single_entity`'s signature stays the same; both values are in scope.

---

## Feature Checklist

Tracks all planned and completed feature/fix tasks for the editor.

### Completed ✅

| # | Task | Notes |
|---|------|-------|
| 1 | Tall blue selection line in 3D mode | Vertical line rendered at selected entity position in 3D view |
| 2 | Double-click entity in list panel to focus in 3D mode | Moves camera to entity position and selects it in 3D |
| 3 | Fix child IDs for imported objects with children | Paste now remaps all child entity IDs through `id_mapping` |
| 4 | Fix removal of `CMissionComponent` container | Removal correctly strips the whole component block, not just inner fields |
| 7 | XML tab in entity editor | `QTabWidget` with Editor + XML tabs; bidirectional sync with 1.5s debounce |
| 9 | Fix freeze/crash when saving many modified files | Reverted worldsector save to per-file `convert_converted_xml_back_to_fcb` (120s timeout); only dirty sectors converted |
| 10 | Fix object import to use FCBConverter format (not Gibbed) | `import_single_entity_to_mapsdata` now inserts FCBConverter-format XML directly |
| 11 | Fix dirty-sector marking when moving entities across sectors | `mark_sector_dirty` updates `entity.source_sector_id` on cross-sector move; both old and new sectors dirtied |
| 12 | Fix mini 3D model preview lighting/textures | Preview widget lighting fixed to match 3D canvas |
| 13 | Entity browser: click-to-copy name/ID | Left-click Name column → copy name to clipboard; right-click ID column → copy ID to clipboard |
| 6 | Add 3D transform gizmo for moving objects in 3D | `canvas/gizmo_3d.py` — 3 translation axes (red/green/blue) + 3 rotation rings; left-click to start drag, right-click still pans camera; full undo/redo via `MoveCommand` / `Rotate3DCommand`; `Rotate3DCommand` added to `undo_redo.py` |
| 8 | Mass export for a level | Entity Tools → "Mass Export Level..."; exports one XML collection per unique entity type to `mass_exported_objects/<level_name>/<category>/<type>/`; dedupes by stripping trailing `_N`; bundles children/seated NPCs/initial users with parent; overwrites with confirmation |

### Pending ⏳

| # | Task | Notes |
|---|------|-------|
| 5 | Add terrain snapping toggle button | Toggle in toolbar/canvas menu; snaps moved entities to terrain height |
| 14 | ~~Render trigger volume boxes in 2D and 3D~~ | ✅ Done — `is_trigger_entity`/`get_trigger_size`/`draw_trigger_indicator_2d` in `entity_renderer.py`; `_render_triggers_3d` in `map_canvas_gpu.py`; yellow dashed wireframe from `CProximityTriggerComponent.vectorSize` half-extents |
| 16 | ~~Remove 2D camera reset after importing an object~~ | ✅ Done — `set_entities(..., center_view=False)` in import path (`entity_export_import.py`); same fix applied to `on_objects_loaded` and `toggle_objects` in `simplified_map_editor.py` |
| 17 | ~~Entity browser: sector grouping lost on search~~ | ✅ Done — `update_entity_tree` now dispatches to `_populate_tree_by_sector` when `canvas.unified_mode` is True, preserving sector headers during search |
| 18 | ~~Entity browser: groups not expanded~~ | ✅ Done — replaced top-level-only expand with recursive `expand_all` in `update_entity_tree`; expands sector headers, layer sub-headers, and all nested groups |
| 19 | ~~Double-click entity browser → canvas not focused~~ | ✅ Done — `on_entity_tree_double_clicked` now calls `self.canvas.setFocus()` after selecting; WASD/arrow keys work immediately in both 2D and 3D |

---

## sectorN.desc.fcb — NativeResources / MissionLayer System

### Structure

`sectorN.desc.fcb` is the sector descriptor file (distinct from `worldsectorN.data.fcb`). After FCBConverter conversion its XML contains three main blocks: `SectorDesc` (neighbour links), `MetaObjects`, and `NativeResources`.

`NativeResources` contains `Category` objects. The category name is **not** an XML attribute — it is stored in a child field:

```xml
<object name="Category">
  <field name="text_Id" value-String="Default" .../>
  <object name="MissionLayer">
    <field name="text_PathId" value-String="main" .../>
    <field name="PathId" value-ComputeHash32="main" .../>
    <field name="TypeIds">
      <Resource ID="CGeometryResource"/>
      ...
    </field>
    <field name="ResIds">
      <Resource ID="__Unknown\0000000000000000"/>
      ...
    </field>
  </object>
</object>
```

### Survey results (sp_hellsgate_01_l, 256 sectors)

| State | Count |
|-------|-------|
| No Default category (terrain/landmark-only) | 208 |
| Default + `main` MissionLayer already present | 15 |
| Default but missing `main` MissionLayer | 33 |

Of the 48 sectors with a Default category, 39 had exactly 1× `CGeometryResource` in `main`. The full canonical TypeIds list (used when auto-creating the layer) now includes all 17 resource types — see below.

### Correct XPath for category lookup

```python
# CORRECT — name is inside a child field, not an attribute
for cat in root.findall('.//object[@name="Category"]'):
    text_id = cat.find('field[@name="text_Id"]')
    if text_id is not None and text_id.get('value-String') == 'Default':
        ...
```

Do **not** use `field[@name="name"]` — that field does not exist in these elements.

### Canonical TypeIds list for `main` MissionLayer (desc.fcb format)

```python
_MAIN_LAYER_TYPES = [
    'CMaterialResource', 'CTextureResource', 'CParticlesEmitterParamResource',
    'CSoundResource', 'CAnimationResource', 'CMovementResource',
    'CStateMachineResource', 'CFrankensteinPoseResource', 'CGeometryResource',
    'CParticlesSystemParamResource', 'CResourceContainer', 'CSkeletonResource',
    'CAnimationPackageResource', 'CFaceAnimResource', 'CDominoBoxResource',
    'CPhysResource', 'CRealtreeResource',
]
```

This list goes in both `TypeIds` and `ResIds` (one `__Unknown\0000000000000000` per type in ResIds). In Python source, write the unknown path as `'__Unknown\\0000000000000000'` (double backslash = one at runtime).

### `_ensure_main_mission_layer(root) -> bool`

Defined identically in both `tools/enable_all_sectors.py` and `tools/create_sector.py`.

- Searches for a `Category` with `text_Id = "Default"` in the parsed XML tree
- If no Default category: returns `False` (no-op)
- If Default already has a `main` MissionLayer: returns `False` (no-op)
- Otherwise: appends a new `MissionLayer` element with the 17-type TypeIds/ResIds lists and returns `True`

After calling this function, **always** run `ET.indent(tree, space="  ")` before writing, or the new element will be serialised as a single unindented line. `ET.indent` is safe on FCBConverter XML — it only modifies `None`/whitespace-only `text`/`tail` and never touches BinHex content like `6D61696E00`.

### Where it is called

**`tools/enable_all_sectors.py`**
- `modify_xml(xml_path, fc2=False, add_main_layer=False) -> tuple[bool, bool]` — second return value is `True` if a layer was added
- GUI has `self.main_layer_check = QCheckBox("Add 'main' MissionLayer to Default categories that are missing one")` (unchecked by default)
- `Worker` receives `add_main_layer` bool from checkbox; calls `_ensure_main_mission_layer` per sector; counts and logs how many were added

**`tools/create_sector.py`**
- `patch_sector_desc_main_layer(worldsectors_dir, sector_id) -> tuple[bool, str]`
  - Finds `sectorN.desc.fcb` / `.converted.xml`; converts FCB → XML if only FCB present
  - Calls `_ensure_main_mission_layer`; if False, returns early
  - Writes XML (`ET.indent` then `tree.write`), converts back to FCB, renames `_new.fcb` → `.fcb`
- Called in `Worker.run()` as Step 2b (single-sector flow) and in `BulkWorker.run()` Phase 2b (after batch FCB conversion)

---

## Entity Import — MissionLayer Auto-Creation (`entity_export_import.py`)

### Two distinct MissionLayer formats

| File | Format | Has TypeIds/ResIds? |
|------|--------|---------------------|
| `sectorN.desc.fcb` | NativeResources resource hints | Yes (see above) |
| `worldsectorN.data.fcb` | Entity container | No — just `text_PathId`/`PathId`, then entity children |

The helper for entity data files is `_create_main_mission_layer(root)` (static method on `EntityImportDialog`). It appends a minimal MissionLayer with no TypeIds/ResIds and returns the new element.

### Where auto-creation fires

- `add_entity_to_sector_with_layer` — if `mission_layers` list is empty after scan, creates main layer instead of returning `False`
- `add_entity_xml_to_sector` — if `target_mission_layer is None` after lookup, creates main layer, sets `target_path_id = "main"`, continues
- `on_sector_changed` (single-import dialog) — if no layers found, adds `"main (will be created on import)"` item to the layer combo
- `assign_selected_to_worldsector` (Select WorldSector Target dialog) — if no layers, combo shows `"(no layers — click 'Add main layer')"` with `None` data

### "Add main layer" button in Select WorldSector Target

The dialog has an `add_layer_btn = QPushButton("Add main layer")` (fixed width 110 px) placed in an `QHBoxLayout` beside the layer combo. The button is:
- **Disabled** when the selected sector already has a `main` layer
- **Enabled** when the selected sector has no `main` layer
- On click: calls `_create_main_mission_layer(root)`, then calls `_reload_layers()` to refresh the combo (button disables itself after, since the layer now exists)

---

## TODO

### Canvas / 3D Mode

- **Terrain snapping toggle** ✅ — "TERRAIN SNAP" badge drawn in `_draw_3d_ui_overlays` (blue=on, dim=off); clicking badge toggles `canvas.terrain_snap_enabled`; 3D-only. `canvas.get_terrain_height_at(x,y)` wraps `TerrainRenderer.get_height_at_world()` (bilinear on `combined_heightmap`). Gizmo X/Y drag snaps `entity.z` exactly to terrain; Z drag clamps `entity.z = max(z, terrain_height)` (solid floor). Badge stored in `canvas._snap_badge_rect` for click detection in `mousePressEvent`.
- **Raycasting for 3D object selection** ✅ — replaced screen-projected handle hit-test with ray-AABB (GLTF bounds in model-local space) + per-triangle Möller-Trumbore test for loaded models; fallback 1.5-unit box for unloaded entities; returns closest hit by `t`. See `select_entity_3d` in `canvas/map_canvas_gpu.py`.
- **Pulsing yellow glow for selected object in 3D** ✅ — yellow tint rendered directly over the model's textures; `GL_COLOR_MATERIAL` disabled so display-list vertex colours are ignored; pure emission `(1.0, 0.85, 0.0)` × texture via `GL_MODULATE`; normal alpha blend at `GL_LEQUAL` depth; `sin(time*6)` pulse 0→100% intensity; glow rendered **before** beacon lines so the blue line always stays on top; `_glow_timer` (33ms) in `setup_canvas` drives repaints; `model_loader.render_selection_glow()` called from `_render_3d_selection_glow()`. Tune intensity in `map_canvas_gpu.py::_render_3d_selection_glow` (`glow_intensity = 0.60 + phase * 0.40` line)
- **Back-face culling for 3D models** ✅ — XBG geometry is CW winding. `render_batched_models` in `model_loader.py` now uses `glEnable(GL_CULL_FACE) + glCullFace(GL_BACK) + glFrontFace(GL_CW)`
- **Better occlusion culling for 3D models** — currently only frustum-culled; add a lightweight software occlusion pass (e.g. hierarchical Z-buffer or large-occluder pre-pass) to skip occluded models before upload
- **Interior anchor rendering** ✅ — when the camera is inside a loaded model's AABB, that entity plus all model entities whose world-space AABB overlaps it are exempted from frustum culling. Implemented in `_get_interior_exempt_entities()` in `canvas/map_canvas_gpu.py`; called from `_get_visible_entities()` (3D only). Two-pass vectorised numpy: Pass 1 transforms camera into each model's local space and checks inside AABB; Pass 2 finds all entities whose world AABB overlaps the anchor. Cache arrays stored in `_ic_*` attributes; rebuilt when `_interior_aabb_cache_key` changes (cleared by both `invalidate_position_cache` and `mark_entity_modified`). Disabled for scenes with >20K entities. Only applies to GLTF models with loaded bounds — unmodelled entities unaffected.
- **View/Edit modes for 3D** ✅ — `input_handler.edit_mode_3d` flag; Space toggles it in 3D (`toggle_edit_mode_3d`); gizmo hit/drag/release all gated on `edit_mode_3d`; entity selection blocked in view mode; green/amber badge drawn in `_draw_3d_ui_overlays` (same style as 2D)

### hidShapePoints Rendering ✅

Entities with `hidShapePoints` have `<Point>x,y,z</Point>` children (field hash `4073DD31`). All coordinates are absolute world coords. Pt0 always equals `hidPos`.

**Implemented:**
- `entity_renderer.get_shape_points(entity)` — cached parse; `has_shape_points(entity)` — bool check
- `draw_shape_outline_2d` — dashed cyan polygon in View mode; circle handles (gold=pt0 r=8, green=others r=6) in Edit mode; collected via `shape_list` in `render_entities_2d`
- `_render_shape_points_3d` — `GL_LINE_LOOP` polygon + `GL_POINTS` markers (gold pt0, cyan rest); depth test off so always visible; called after `_render_triggers_3d`
- Entity drag (`handle_mouse_move_2d`) calls `_shift_shape_points(entity, dx, dy)` so the whole polygon follows the entity; auto-saves via `_auto_save_entity_changes`
- Shape point drag: `_get_shape_point_at` hit-tests handles (RADIUS=14px); pt0 moves entity+all points; pt1+ moves only that point
- **Save on release:** `handle_mouse_release_2d` calls `_update_entity_xml` + `_auto_save_entity_changes` for ALL shape point drag indices, writing the mapsdata XML to disk immediately

**Still TODO:**
- ~~Add/remove `<Point>` elements via UI button~~ ✅
- ~~Undo/redo for shape point edits~~ ✅ — `ShapePointCommand` in `undo_redo.py`; snapshots taken at both press sites in `input_handler.py`; pushed on mouse release after auto-save

---

## 3D Renderer Internals

### Instance data tuple format (`model_loader.py`)

`prepare_batches` fills `self.instance_batches` — a `defaultdict(list)` keyed by model path. Each list entry is a **9-tuple**:
```
(entity, px, py, pz, rx, ry, rz, scale, is_selected)
  [0]    [1] [2] [3] [4] [5] [6]  [7]      [8]
```
Tuples replaced the old dict layout for ~2× lower allocation cost and reduced GC pressure. Any code that reads instance batches must use index access, not key names.

### Rotation / scale cache (`model_loader._entity_rs_cache`)

XML parsing for `hidAngles` / `hidScale` is done once per entity and cached in `_entity_rs_cache` (dict keyed by `id(entity)` → `(rx, ry, rz, scale)`). The cache entry is dropped by:
- `mark_entity_modified(entity)` — called after gizmo drag / angle write
- `invalidate_position_cache()` — called after any entity position change (belt-and-suspenders)

Do **not** read `hidAngles` inside any per-frame loop — always go through `_entity_rs_cache`.

### Display list pre-loading

Models are parsed and their OpenGL display lists created at **level load time** (inside `_load_complete_level_thread`) via `model_loader._create_opengl_resources(model)`, not on first render. This eliminates mid-render stalls. If a display list is still `None` at render time, `render_batched_models` prints a `⚠️ FREEZE SOURCE` warning and creates it as a fallback.

### Adaptive frustum FAR distance

`_get_visible_entities` scales FAR based on scene density:
- `>50K` entities → FAR = 500 (FC2 full world)
- `>15K` entities → FAR = 900 (FC2 per-cell)
- else → FAR = 1500 (Avatar / small levels)

`FRUSTUM_PADDING = 1.2` (was 3.0) — tighter fit means fewer false-positives. No per-frame entity budget cap; all in-frustum entities render.

### Bounding-sphere frustum culling (May 2026)

Frustum passes 3 & 4 (vertical/horizontal angle test) now use a **sphere-expanded** half-extent rather than a raw point test. Each entity gets a precomputed `_radii_3d` entry (`scale × half-diagonal(bounds_max − bounds_min)`) stored at load time in `_get_map_filtered_entities`; entities with no loaded model get radius 0 (same as before).

Per-frame: `|proj| <= half_frustum_at_depth + radius`. This prevents large models (big buildings, vehicles) from popping out the moment their origin crosses the frustum edge.

`_radii_3d` is a float32 numpy array aligned 1-to-1 with `_valid_entities_3d`. It is rebuilt whenever `invalidate_position_cache()` fires (same trigger as `_positions_3d`). Rotation is not needed — the bounding sphere radius is rotation-invariant.

### GC management during render

`_render_3d_opengl` disables GC gen-2 collection for the duration of `prepare_batches + render_batched_models` to prevent GC pauses mid-frame. Gen-0 is swept immediately after re-enabling. This is safe because the render loop creates many short-lived objects (numpy arrays, tuples) that should be collected eagerly, not during the next gen-2 sweep.

### Terrain rotation in 3D

**FC2 terrain orientation — NO rotation anywhere (July 2026, empirically proven).** The definitive test (scratchpad `fc2_terrain_alignment_solver.py` methodology): score entity `hidPos.z` against the terrain heightmap sampled at each entity's (x, y) under all 8 dihedral orientations. On fishing village (633 entities), the **raw file mapping wins decisively** — world x = heightmap column, world y = sector-number row (sector n at row n//stride, col n%stride), identity, no rotation/flip. Consequences:
- **3D** (`_render_terrain_model`): NO rotation for FC2 (or Avatar). The mesh pipeline (flip-v assembly in `create_combined_heightmap` + `PZ = row − height` + render `y → −z`) already composes to identity. The historical 180°/90° rotations (and the earlier "validated 180°" claim) were themselves the object/terrain misalignment.
- **2D/3D TILE pipeline is SHARED with Avatar — do NOT split it per game (July 2026, user-verified).** `get_sector_index_from_position` placement + sequential atlas counter + unrotated quadrants produce correct tile PIECES for FC2 too. A brief attempt at FC2-specific row-major placement / 2×2-global-block atlas mapping / per-tile rotation made every tile wrong and was fully reverted. The per-game difference lives ONLY in two orientation knobs: `TerrainRenderer._FC2_2D_QUARTER_TURNS` (final 2D whole-image rotation, N×−90°; 2 = original −180 total vs Avatar's single −90) and `TerrainExporter._FC2_3D_TEXTURE_TURNS` (finished 3D combined texture rotation; 2 = 180°, replacing the removed render-time mesh rotation — the mesh itself stays UNROTATED, that part is proven by entity heights). Iterate FC2 orientation by changing those two numbers, nothing else.
- **Cache**: `generate_terrain_cache_key` now globs `*.sdat` too and carries a `RENDER_VERSION` salt ("tv4") — the old `.csdat`-only glob gave FC2 a path-only key that never invalidated, which would have pinned stale wrongly-rotated images forever. Bump `RENDER_VERSION` whenever terrain assembly/orientation logic changes.
Tests: `tests/test_terrain_cache_key_fc2.py`.

**FC2 cell-name convention is transposed + inverted (July 2026, verified on all 50 retail cells).** In `w{n}_{letter}_{digit}`: the DIGIT is the world COLUMN (1→col 0 … 5→col 4) and the LETTER is the world ROW, INVERTED (a→row 4 = top, e→row 0). Corner ground truth from sd numbering: w1_e_1→sd0→(0,0), w1_e_5→sd64→(4096,0), w1_a_1→sd5120→(0,4096), w1_a_5→sd5184→(4096,4096). The old letter=col/digit=row mapping only agreed on symmetric cells (c_3), so world terrain cells were scattered. `_get_fc2_world_offset` now uses the corrected formula, but terrain loading prefers `_fc2_offset_from_sector_numbers` (derives the offset from the cell's own sd numbers: `wx=(min%stride)*64, wy=(min//stride)*64`, stride from the first gap) — ground truth, no naming convention. Contiguous-from-0 numbering (standalone MP maps) → (0,0); contiguous-from-nonzero → None (fall back to name). Also: the FC2 sector remap in `terrain_renderer.load_sdat_folder` AND `terrain_to_gltf.load_all_sectors` runs on GAP DETECTION (not `min_s > 0` — w1_e_1 starts at sd0 but is world-strided), per-folder FC2 remap state is reset at the top of `load_sdat_folder` (`_fc2_remapped` flag; stale state from a previous cell poisoned the next cell's atlas math), and `terrain_to_gltf` mirrors the FC2 2×2-block atlas mapping + row-major texture combine + DIRECT UVs (`u=NX, v=NY` — Avatar keeps its rotated UVs). Tests: `tests/test_fc2_cell_offsets.py` (mirrored helpers validated against all 50 real cells).

### Known issues / watch out

- `_render_shape_points_3d` must be called explicitly in `_render_3d_opengl`'s entity block — it was accidentally dropped once; it comes after `_render_triggers_3d`.
- `_interior_aabb_cache_key` and `_entity_rs_cache` must both be cleared when an entity moves or rotates. `invalidate_position_cache` and `mark_entity_modified` both do this — don't add a third path that skips them.
- `import time` / `import gc` inside `_render_3d_opengl` are lazy imports left from debugging; they're cheap after the first call (module already loaded) but could be moved to file-level imports when cleaning up.

---

## Worldsector XML indentation corruption (May 2026)

### Root cause — `ElementTree.clear()` wipes `.tail`

`_update_worldsector_xml_fcb_format` in `canvas/map_canvas_gpu.py` had:
```python
entity_elem.clear()
entity_elem.attrib.update(existing.attrib)
```
`ET.Element.clear()` resets **all** element state — attributes, children, text, AND `.tail`. `.tail` is the whitespace text that follows the closing tag of an element (i.e. `\n  ` between siblings). Wiping it collapses `</object>\n  <object>` into `</object><object>` on the same line. FCBConverter parses XML and is sensitive to this — it can fail or corrupt data when tags share a line.

**Fix:** save and restore `.tail` around every `clear()` call:
```python
_saved_tail = entity_elem.tail
entity_elem.clear()
entity_elem.tail = _saved_tail
```

### Rule — all worldsector XML writes must call `ET.indent` first

Even with `.tail` restored, XML written via `tree.write()` can develop inconsistent indentation over multiple edits (e.g. after inserting new elements). The safe pattern for every worldsector write:
```python
try:
    ET.indent(tree, space="  ")
except AttributeError:
    pass  # Python < 3.9
tree.write(xml_file_path, encoding='utf-8', xml_declaration=True)
```
`ET.indent` normalises all `text`/`tail` whitespace in the tree. It is safe to call on FCBConverter XML — it only touches whitespace, never BinHex content or attributes.

### Files and write paths that were fixed

| File | Function | What was fixed |
|------|----------|----------------|
| `canvas/map_canvas_gpu.py` | `_update_worldsector_xml_fcb_format` | Save/restore `.tail` around `entity_elem.clear()` |
| `canvas/map_canvas_gpu.py` | `_auto_save_worldsector_file` | Added `ET.indent` before `tree.write()` |
| `simplified_map_editor.py` | `save_all_xml_files_before_conversion` (worldsector loop) | Added `ET.indent` before `tree.write()` |
| `simplified_map_editor.py` | `_remove_entity_from_worldsector_fixed` | Added `ET.indent` before immediate `tree.write()` |
| `all_in_one_copy_paste.py` | `_remove_entity_from_worldsector_fixed` | Added `ET.indent` before immediate `tree.write()` |

### Python scoping gotcha — conditional `import` inside a function

`all_in_one_copy_paste.py` had a local `import xml.etree.ElementTree as ET` inside a conditional `if` block. Python scoping rules treat **any** assignment to a name inside a function as a local variable for the **entire** function. If the `if` branch is skipped, the name `ET` is still a local variable — but unbound. Accessing it then raises `UnboundLocalError: cannot access local variable 'ET' before assignment`, even though a module-level `ET` exists. The fix is to remove the local import and rely on the module-level one (line 5).

### entitylibrary.fcb — ArgumentException crash in FCBConverter

`entitylibrary.fcb` (without `_full`) crashed FCBConverter with:
```
System.ArgumentException: Destination array is not long enough to copy all the items in the collection.
   at System.BitConverter.ToInt32(Byte[] value, Int32 startIndex)
   at Gibbed.Dunia2.ConvertBinaryObject.Exporting.WriteNode(...)
```

**Root cause:** `tools/FCBConverterDefinitions.xml` had a file-specific rule for `entitylibrary.fcb` that used `action="External" FieldForName="Name"`. The External action internally calls `BitConverter.ToInt32` on the Name field regardless of its actual byte length. In `entitylibrary.fcb`, the Name field is stored as fewer than 4 bytes → crash.

**Fix applied:** Removed `action="External" FieldForName="Name"` from the `entitylibrary.fcb` file rule in `tools/FCBConverterDefinitions.xml`. The object hint is kept (so EntityPrototype is still named correctly) but falls back to Global type detection rules which have ByteLen guards.

```xml
<!-- Before (crashed): -->
<File name="$(?&lt;=(entitylibrary.fcb))">
    <object hash="" name="EntityPrototype" action="External" FieldForName="Name" />
</File>

<!-- After (fixed): -->
<File name="$(?&lt;=(entitylibrary.fcb))">
    <object hash="" name="EntityPrototype" />
</File>
```

**Tool:** "Convert Entity Library FCB..." in Tools menu — selects exactly `entitylibrary.fcb` or `entitylibrary_full.fcb` (single file or folder scan with exact name match). Uses fixed binary in batch mode. Companion tool "Convert Entity Library XML to FCB..." reverses the process: picks `entitylibrary.fcb.converted.xml` or `entitylibrary_full.fcb.converted.xml`, runs `FCBConverter.exe <xml> -fc2 -enablecompress` (single-file mode — batch mode does not handle XML→FCB), renames `_new.fcb` → target `.fcb`. Note: FCBConverter always prints "Compression disabled." by default (config-file setting); the `-enablecompress` flag overrides this so the output FCB is LZO-compressed matching original game files.

### FCBConverter freeze after Save Level — per-file mode + mtime skip

**Problem:** After saving, the editor called FCBConverter in batch mode (`-source=folder -filter=*.data.fcb`) on the entire worldsectors folder, which contains ~300 files (48 worldsector + ~251 landmark). Even when only 1 file changed, all 300 were processed, taking minutes.

**Fix in `file_converter.py` — two layers:**

1. **mtime-based skip:** if `xml_out` already exists AND is newer than the `.fcb` file, skip conversion entirely:
   ```python
   xml_up_to_date = (xml_exists and
                     os.path.getmtime(xml_out) >= os.path.getmtime(fcb_file))
   if xml_up_to_date or (xml_exists and cache.is_fcb_conversion_cached(fcb_file)):
       cached_count += 1
   else:
       files_to_convert.append(fcb_file)
   ```

2. **Per-file mode for small batches:** when ≤ 10 files need converting, call FCBConverter once per file instead of batch mode:
   ```python
   USE_BATCH_THRESHOLD = 10
   if len(files_to_convert) <= USE_BATCH_THRESHOLD:
       for fcb_file in files_to_convert:
           subprocess.run([self.fcb_converter_path, fcb_file, "-fc2"], ...)
   else:
       # batch mode for large counts
   ```

### 3D gizmo translation — ray-axis intersection approach (May 2026)

The old `_drag_translate` in `canvas/gizmo_3d.py` projected two GL points to screen, measured mouse movement along the screen direction, and divided by `pixels_per_unit`. This broke when the camera was close (small denominator) and pushed in the wrong direction when the camera was on the far side of the gizmo.

**New approach — closest point on axis via ray intersection:**

For each mouse position, cast a ray from the camera through that pixel into 3D space (`gluUnProject` at z=0 and z=1). Then find the point on the constraint axis (the infinite line through the entity in the drag direction) that is closest to that ray. The signed distance along the axis from the drag-start point to the current closest point is the delta. This is stable at any camera distance and correct from any camera angle.

Formula (closest point on axis `A` to ray `(ro, rd)`):
```
b = dot(rd, A_dir)
denom = 1 - b*b
t = (e_val - b * d_val) / denom
```
where `d_val = dot(rd, W)`, `e_val = dot(A_dir, W)`, and `W = ro - anchor`. Both the drag-start `t` and the current `t` are computed; `delta_gl = t_now - t_start`.

**Sign conventions after fix:**
- TRANS_X: `x = x0 + delta`
- TRANS_Y: `y = y0 + delta`
- TRANS_Z (height): `z = z0 + delta` (sign now comes naturally from the ray-axis math, not hardcoded)

---

## Crash Logging System (May 2026)

The frozen exe build (`base='Win32GUI'`) suppresses all console output — every `print()` call is silently discarded. To diagnose crashes in the exe, a crash logging system was added to `main.py`.

### Architecture

**`main.py` (module-level, before any GUI imports):**
- `CRASH_LOG_PATH` — log file written next to the exe (`build/Avatar_Level_Editor/crash_log.txt`)
- `_write_crash_log(text)` — appends to the log file, flushes immediately. Importable from other modules.
- `sys.excepthook = _excepthook` — catches all unhandled Python exceptions, writes a timestamped traceback, shows a `QMessageBox` if Qt is running
- `faulthandler.enable(file=_crash_log_file, all_threads=True)` — catches C-level crashes (segfaults, access violations) that Python exceptions cannot catch
- The log file handle is kept open for the process lifetime for `faulthandler`; do not close it

**`set_patch_folder.py`:**
- `_spf_log(msg)` — module-level helper; imports `main._write_crash_log` and writes a timestamped line
- `_log_to_crash_file = _spf_log` alias inside the `integrate_patch_manager` closure
- Checkpoints throughout `new_select_level` and `on_change_patch_folder` trace every step of the patch-folder change flow

---

## Patch Folder Change Flow — Critical Architecture (May 2026)

### `integrate_patch_manager` (called once at startup)

`set_patch_folder.py::integrate_patch_manager(main_window)` replaces `main_window.select_level` with a closure called `new_select_level`. The original `select_level` in `simplified_map_editor.py` is dead code after startup.

### `new_select_level` — the actual level selector

Guarded by `main_window._selecting_level` re-entrancy flag. Full flow:
1. If `patch_manager.levels_data` is empty → start `PatchFolderScanner` QThread, show `EnhancedProgressDialog`, busy-wait with `while not scan_completed[0]: QApplication.processEvents(); time.sleep(0.02)`
2. If `levels_data` already populated → skip scan entirely
3. Create and exec `LevelSelectorDialog`
4. If `patch_folder_was_changed[0]` is True → clear `levels_data` only if folder actually changed, reschedule via `QTimer.singleShot(100, lambda: main_window.select_level())`

### Patch folder change — same-folder safety

`folder_at_open` snapshot taken before `dialog.exec()`. Inside `on_patch_folder_change` closure:
```python
folder_changed = (patch_manager.patch_folder != folder_at_open)
if folder_changed:
    patch_manager.levels_data = {}
# Do NOT call dialog.accept() here — the dialog method does it
patch_folder_was_changed[0] = True
```
This prevents clearing `levels_data` (and triggering a full rescan) when the user picks the same folder that is already selected.

### Double-accept bug (fixed May 2026)

`LevelSelectorDialog.on_change_patch_folder` emits `patch_folder_change_requested` then calls `self.accept()`. The `on_patch_folder_change` closure in `new_select_level` must **NOT** also call `dialog.accept()`. Calling `accept()` twice on the same dialog corrupts Qt's nested event loop in frozen exes. Only the dialog method itself calls `accept()`.

### `QApplication.processEvents()` stack overflow — root cause and fix (May 2026)

**Root cause:** `QApplication.processEvents()` was called inside multiple signal handler methods. The busy-wait loop also calls `processEvents()` every 20ms. Nesting `processEvents()` inside a handler that was itself invoked by `processEvents()` creates unbounded recursion:

```
busy-wait loop: QApplication.processEvents()
  → fires progress_updated signal → on_progress
    → set_progress() → QApplication.processEvents()   ← nested!
      → fires log_message signal → append_log()
        → QApplication.processEvents()                 ← nested again!
          → fires another log_message → append_log()
            → ...                                      ← stack overflow
```

`faulthandler` caught this as `Windows fatal exception: stack overflow` with `append_log` (simplified_map_editor.py) repeating hundreds of frames deep.

**Fix:** Remove `QApplication.processEvents()` from every signal handler. It must only appear in the top-level busy-wait loop.

Removed from:
- `EnhancedProgressDialog.set_status` (simplified_map_editor.py)
- `EnhancedProgressDialog.set_progress` (simplified_map_editor.py)
- `EnhancedProgressDialog.append_log` (simplified_map_editor.py)
- `on_progress` closure in `new_select_level` (set_patch_folder.py)

**Rule to never break:** Never call `QApplication.processEvents()` inside a method that is itself triggered by `processEvents()`. Signal handlers are always called from within the event loop — adding `processEvents()` inside them causes re-entrant signal processing. When Qt signals are queued faster than they are consumed (e.g. a background scanner thread emitting dozens of `log_message` signals per second), this creates an infinitely deepening call stack and a guaranteed stack overflow.

---

## Landmark file creation and sector boundary display (May 2026)

### Create New Sector — landmark creation integrated into "Create All Missing Sectors"

`tools/create_sector.py` — `BulkWorker.run()` now does two scans in Phase 0:
1. `find_missing_sectors(ws, wg)` — sectors without a `worldsectorN.data.fcb`
2. `find_missing_landmarks(ws)` — **all 256 sector IDs** missing `landmarkfar_N.data.fcb` or `landmarknear{N}.data.fcb`

`lm_only` = sectors in the second set but not the first (already have worldsector data but missing landmark files). Phase 1 creates XMLs for both groups. Phase 2 batch-converts all three file types. Phase 3 patches sectorsdep.xml:
- New sectors → `patch_sectorsdep_bulk` (adds HasMainSectorData + both landmark flags)
- `lm_only` sectors → `patch_sectorsdep_landmarks_bulk` (adds **only** HasLandmarkNear/Far — never adds HasMainSectorData to sectors that don't have worldsector data)

**New helpers:**
- `find_missing_landmarks(worldsectors_dir)` → `list[tuple[int, list[str]]]` — scans 0–255, returns `(sector_id, ['far'|'near'|both])` for each sector missing landmark files
- `patch_sectorsdep_landmarks_bulk(worlds_generated_dir, sector_ids)` — landmark-only sectorsdep patcher; never touches HasMainSectorData

### Sector boundary label format (canvas/map_canvas_gpu.py)

`draw_sector_boundaries` previously stored a single `landmark` key per grid cell, so the second landmark file for a cell always overwrote the first. The grouping dict now uses separate `landmark_far` and `landmark_near` keys. Disambiguation uses `'landmarkfar' in fname.lower()`.

Label format in the purple box (bottom-left of the cell):
- Both files present → `LMN & LMF [N]`
- Far only → `LMF [N]`
- Near only → `LMN [N]`

### Import to landmark files — `landmark_trees` sync bug (entity_export_import.py)

**Root cause:** `_import_to_landmark_internal` calls `add_entity_to_sector_with_layer`, which loads the landmark file into `worldsectors_trees`. The landmark save step (step 4 of `save_all_xml_files_before_conversion`) reads from `self.landmark_trees` — a completely separate dict. On the next Save Level, `landmark_trees` (which had no knowledge of the import) wrote the old content back to disk, silently erasing the imported entity.

**Fix:** After a successful import loop, `_import_to_landmark_internal` syncs `worldsectors_trees[file_path]` → `landmark_trees[file_path]` and stores a `"..._dirty"` sentinel in `landmark_clean_hashes` to guarantee the save step writes the file on the next save.

**Rule:** Any code path that writes a landmark `.converted.xml` via `add_entity_to_sector_with_layer` (or any other means) MUST also update `parent_editor.landmark_trees[path]` and invalidate `parent_editor.landmark_clean_hashes[path]`, or the change will be overwritten on the next save.

**Import dialog supports all five file types:** Mapsdata, WorldSector, LandmarkFar, LandmarkNear, Omnis. Use the "Assign Selected →" buttons to set the target before clicking Import.

---

## Day/night cycle + bioluminescence (May 2026, Stage 1)

Optional time-of-day system layered on the 2-light sun rig. **ON by default since June 2026** (`canvas.day_night_enabled=True`, **paused at noon** so lighting stays stable while editing; the View-menu Enable checkbox is set checked to match — user request). Consequence: the atmosphere sky + F7 sun shadows (GDR path, sun up) are active out of the box. **F4** cycles OFF → ON(playing) → PAUSED → OFF.

- `time_of_day` ∈ [0,1) (0=midnight, .25=sunrise, .5=noon, .75=sunset); auto-advances in `_on_glow_tick` when playing.
- `_apply_day_night()` (called in `_render_3d_opengl` after the static rig, only when enabled) drives `GL_LIGHT0` (sun arc east→west, warm→orange-at-horizon→dim-blue-moon), `GL_LIGHT1` (sky fill), and `GL_LIGHT_MODEL_AMBIENT` (bright day → dim blue night) from `_daynight_factors()`. Because both render paths read `gl_LightSource`/`gl_LightModel`, **F1 and F2 both** get the cycle for free.
- `_sky_color()` sets the clear colour (day blue → dawn/dusk orange → night near-black). **Placeholder** until the real sky (next stages).
- **Bioluminescence:** `_night_factor` (0 day → 1 night) → `model_loader.night_factor` → `u_night` uniform in BOTH shaders, which **scales emission** (`emission * u_night`). So emissive materials glow at night, fade out by day. When the cycle is OFF, the canvas passes `night_factor=1.0` so emission looks normal (unchanged behaviour). User decision: ALL emissive materials are treated as bio.

**Night-sky dome (Stage 2, SHIPPED):** `canvas/night_sky.py` (`NightSky`) parses the binary `canvas/Night Sky/Night Sky.glb` itself (the text `.gltf` loader can't read GLB) — a STARSPHERE with 2 emissive primitives (Milky Way band: 50 verts; stars: 10,119 triangles) and 2 bufferView-embedded PNGs (milkyway 2048×256, star 16×16). GLB parse + accessor extraction are unit-verified GPU-free. It renders camera-centered, scaled to ~8000-unit radius (bigger than the map, stars at "infinity"), `-90°X` to match game→editor orientation, **additive blend** (`GL_ONE,GL_ONE` → black texels add nothing = transparent, Milky Way/stars glow), no depth write, no lighting, faded by `night_factor` (drawn only when `night_factor>0.01`, i.e. at night). Drawn as background before terrain in `_render_3d_opengl`. **GL render untested in-app** (data extraction verified).

**Daytime atmosphere (Stage 3, SHIPPED):** `canvas/sky_atmosphere.py` (`AtmosphereSky`) ports fgarlin's spectral sky to real-time desktop GL. It **takes the reference shaders from `canvas/sky_shader_sources.py` (embedded — see Assets below) and wraps them at runtime** (ShaderToy `mainImage`→`main`, `iResolution`/`iChannel0`→uniforms, `get_sun_direction`→`u_sun_dir`, strip `f` suffixes) so we run the author's exact maths — assembly is unit-verified GPU-free. Pipeline: transmittance LUT (Buffer A, RGBA16F FBO, sun-independent → built once) → sky-view LUT (Buffer B, recomputed per sun position) → fullscreen composite that builds the **editor camera** view ray, maps to (elevation, azimuth-relative-to-sun), samples the LUT, ACES-tonemaps, and adds a **sun disk + halo** (above horizon). Sun from `time_of_day`; the physics darkens the sky as the sun sets so it crossfades into the star dome. Drawn as background before terrain (and before the night dome). Failure (missing files / no float FBO / compile) → `_failed`, caller keeps the gradient `_sky_color`. **GL render untested in-app** (assembly verified).
   - **CRITICAL QOpenGLWidget gotcha:** Qt renders into its OWN FBO, not framebuffer 0. After the LUT-FBO passes, the composite binds `canvas.defaultFramebufferObject()` (passed in as `default_fbo`) — binding 0 would render the sky to nowhere. Same applies to any future FBO work.
   - **PERF — sky-view LUT cached by sun elevation (June 2026):** Buffer B (the expensive multiple-scattering pass) was re-rendered EVERY 3D frame. Its output depends only on sun elevation (it places the sun at a fixed azimuth; camera azimuth is handled in the composite), and day/night is paused at noon by default → the LUT is identical frame after frame, a constant per-frame GPU cost that capped FPS even on empty levels. `_sky_lut_needs_rebuild(sun_elev_sin)` (rounds to 5 dp) now gates the Buffer B render: rebuild on the first frame and whenever the sun actually moves (cycle playing), skip otherwise (reuse the cached `tex_sky`). The transmittance LUT was already once-only (`_trans_done`); the composite still runs every frame (camera ray changes). Regression: `tests/test_sky_lut_cache.py`. Reset `_sky_sun_key=None` would force a rebuild if ever needed (not currently called). Only the LUT pass is skipped — visuals are pixel-identical for a static sun.

### 3D viewport capped at ~40 FPS — render-timer vs vsync beat (June 2026)

**Symptom:** 3D mode sat at ~40 FPS on every level, even empty ones, on a 60Hz display. The F1 profiler showed the scene costs only **~2ms CPU / ~1.4ms GPU per frame** (`⏱️ FRAME 2.0ms CPU | GPU 1.4ms`), so it was NOT a rendering-cost problem — optimizing shaders/culling/sky does nothing for it.

**Root cause:** repaints are driven by the 16ms `movement_timer` (`setup_canvas`). 16ms beats against the 16.67ms (60Hz) refresh interval, so the vsync-blocked buffer swap lands ~1.5 vblanks apart → **40 FPS = 1.5 × 16.67ms** (the dead-giveaway signature). Pure frame-pacing, not load.

**Fix (two parts):**
1. **`main.py` — force vsync.** No `QSurfaceFormat` was ever set, so the swap interval was left to the AMD driver default → presentation wasn't cleanly vsync-paced (FPS wobbled **40 *and* 50**, neither a 60Hz fraction — the tell that the swap interval was unset). `main()` now does `_fmt = QSurfaceFormat.defaultFormat(); _fmt.setSwapInterval(1); QSurfaceFormat.setDefaultFormat(_fmt)` **before `QApplication(sys.argv)`** (mandatory ordering) so every GL context — incl. the canvas `QOpenGLWidget` — inherits swapInterval=1. The vsync-blocked swap is now the pacer → a clean refresh-rate cap. Modifies only the swap interval on the existing default format (depth/stencil behaviour preserved).
2. **`map_canvas_gpu.paintGL` — continuous repaint while moving.** At the END of `paintGL`, request the next frame (`self.update()`) while the camera is actively moving — 3D `camera_3d.needs_update()` or 2D `camera_controller.needs_update()`. With vsync on (part 1), a repaint is always pending the instant the swap returns, so the swap paces a steady 60. The loop self-terminates when the movement keys are released, so idle cost is unchanged. **Movement speed is untouched** — the 3D camera is still stepped at fixed `0.1`/tick by the 16ms timer (the 3D `Camera3D.update_movement` is fixed-step, NOT dt-based; the 2D `camera_controller` already is dt-based).

Part 2 alone (committed first) only lifted it to a wobbly 40-50 because the swap interval was still unset; part 1 supplies the clean pacing. **Not unit-tested** — startup GL config + GL/Qt paint-loop scheduling, GL-context + QApplication bound (`map_canvas_gpu.py` can't be imported headlessly), consistent with the rest of the canvas render code; verified in-app by the FPS counter. If a future display still wobbles, the fallback is an explicit fixed-rate render `QTimer` decoupled from movement (would require making `Camera3D.update_movement` dt-based first).

**Assets:** the night-sky GLB now lives at `canvas/assets/avatar/skybox/Night Sky.glb` (moved from `canvas/Night Sky/`). The atmosphere GLSL is **EMBEDDED** in `canvas/sky_shader_sources.py` (June 2026) — the loose `canvas/Night Sky/Shader toy/*.txt` files were never in git and got deleted from disk once, silently killing the spectral sky. `sky_atmosphere._read(name)` now returns `sky_shader_sources.SOURCES[name]`; there is NO runtime file dependency and nothing extra to bundle for frozen builds (`canvas.sky_shader_sources` is in setup.py packages). The embedded strings are byte-exact copies of the originals — do not hand-edit the GLSL there; all wrapping/adaptation stays in `sky_atmosphere.py`. Regression tests: `tests/test_sky_shader_sources.py`.

**Time-of-day UI (SHIPPED):** in the View-menu lighting widget (`simplified_map_editor.py`, after the sun sliders) — an **Enable** checkbox, **▶ Play/⏸ Pause** button, and a **Time slider** (0–1439 min, shows HH:MM). Wired to `canvas.set_day_night_enabled / set_daynight_playing / set_time_of_day`. A 200 ms `QTimer` polls `canvas.time_of_day` while playing so the slider/clock follow the auto-advancing cycle (signals blocked to avoid feedback). **F4 still works** as the quick toggle.

**Composite view ray (IMPORTANT):** the composite reconstructs the world ray from the **actual GL `u_view`/`u_proj` matrices** (`inverse(u_proj*u_view)` unprojecting NDC near/far), captured via `glGetFloatv` per frame and passed with `glUniformMatrix4fv(..., GL_FALSE, ...)` (glGet column-major round-trips). The earlier version rebuilt the ray from `camera_3d.forward/right/up`, which didn't match the projection → the sun "swam"/curved with camera motion. Using the real matrices locks the sky to the world. **Sun disk** = additive bright disk (~2°) + halo `* sun_col`, faded below the horizon (not a `mix`, which was invisible over the bright sky).

**Next stages (TODO):** tune atmosphere exposure/aerosol + verify the day↔night crossfade looks right. (~~bundle the shader `.txt` for frozen builds~~ — obsolete, sources are embedded in `canvas/sky_shader_sources.py` now.)

**Sun shadow mapping (Stage 1 — models cast & receive, SHIPPED untested):** `canvas/shadow_map.py` (`ShadowMap`) + a depth pass in the GPU-driven renderer. **F7** toggles it (default ON, but only active when **day/night is on AND the GPU-driven path is active (F2/F3) AND the sun is above the horizon** `_sun_elev_sin>0.05`). So the visible sequence is **F2 → F4 → (F7 already on)**.
   - **Mechanism:** one 2048² `GL_DEPTH_COMPONENT24` depth FBO. Per frame: `update_light_vp(cam_pos, cam_fwd, sun_dir)` fits an **ortho** light frustum to a 440-unit box centred ~110 units in front of the camera, looking down the sun direction (`half_size=220` is the tunable coverage↔resolution knob). Matrices are built **row-major** in numpy (`_look_at`, `_ortho`, `proj@view`) and uploaded with **`transpose=GL_TRUE`** (verified GPU-free: scene centre projects inside NDC, depth ordering correct).
   - **Cast:** `ShadowMap.begin()` binds the FBO + 2048 viewport + clears + `glPolygonOffset(2,4)`; `GPUDrivenRenderer.cast(light_vp)` runs a **depth-only MDI** of render-groups 0+1 (opaque + two-sided; skips blend) via a position-only `_GDR_DEPTH_VS` whose `modelRot` is **byte-identical** to the main vertex shader (so cast geo aligns with rendered geo); `end()` restores the widget FBO (`defaultFramebufferObject()` — the QOpenGLWidget gotcha) + viewport.
   - **Receive:** the GPU-driven fragment shader gets `v_wp` (world pos), `u_light_vp`, `u_shadow_tex` (regular `sampler2D` on **unit 4** — no conflict, materials are bindless), `u_shadows_on`. `sunVisibility()` projects `v_wp` into light space, does **3×3 PCF** with a slope-scaled bias, and attenuates **the sun (light 0) only** — ambient + sky-fill (light 1) stay, so nothing goes black.
   - **Frame sharing:** `_collect_frame()` builds the instance/command lists once; `cast()` caches it in `self._frame` and `_draw()` consumes it, so cast + render use the IDENTICAL instance layout. The cast runs in `_render_entities_3d` **between `prepare_batches` and `render_batched_models`** (`canvas._cast_sun_shadows`) so `instance_batches` is current (not the stale previous frame).
   - **Wiring:** `model_loader.set_shadow_inputs(tex, light_vp, on)` (per frame) + `cast_shadows(light_vp)` (delegates to `_gpu_driven.cast`, GPU-driven only). All GL guarded → any failure renders unshadowed, never blank.
   - **Stage 1 limits / NEXT:** **terrain does NOT receive yet** (it's fixed-function — Stage 2 needs a terrain shader so the ground shows shadows; that's the big visual). Masked foliage casts a solid (non-cutout) shadow for now. Likely tuning rounds: bias/acne, `half_size`, peter-panning. The universal (F1) path neither casts nor receives in Stage 1.

**Depth prepass / early-Z occlusion (F8, SHIPPED untested):** GPU-driven path only. A camera-space depth-only MDI (`_GDR_CAMDEPTH_VS/FS`, `invariant gl_Position` so depth is bit-identical) lays the nearest depth for every opaque/two-sided pixel BEFORE the color pass; the color pass then runs `GL_LEQUAL` with depth-write **off**, so fragments of objects hidden behind a wall are early-Z-rejected before the expensive material shader runs — regardless of MDI draw order. **The prepass FS alpha-tests masked materials** (same `tint.w==1` + `emissive.w` cutoff as the color pass) so foliage/grate cutout holes don't write depth (else objects behind the holes would wrongly vanish). Runs via `_pass()` under the camdepth program (binds per-draw material ids at binding 1). Toggle = `model_loader.gpu_depth_prepass` / `canvas._toggle_depth_prepass` / **F8**. **DEFAULT OFF** — in testing it gave no FPS gain and sometimes *lower* FPS: a prepass only pays off when GPU-**fragment-bound** (heavy overdraw of the expensive material shader), but it adds a full extra geometry pass, so on vertex/draw/CPU-bound scenes it's pure overhead. It does NOT reduce vertex/draw/CPU cost. **For "skip whole hidden objects" (the real goal) the right tool is GPU Hi-Z occlusion culling** (depth pyramid + a compute pass that zeroes/compacts occluded instances' draw commands) so hidden objects cost no vertex *or* fragment work — a larger feature, and only worth it once the F1 profiler confirms the scene is GPU-bound (not CPU `prepare`/`cull`-bound).

**Other render/perf changes (May 2026):**
   - **Terrain decimation** (`terrain_to_gltf.create_gltf`): the display mesh was a full-res heightfield (~736² ≈ 542k verts / 1.08M tris, built by a slow pure-Python double loop). Now **vectorised with NumPy + decimated** — each axis capped at `MAX_DIM=256` samples (stride = ⌈max(W,H)/256⌉, last row/col kept so sector edges meet) → 736² becomes 246² ≈ 60k verts / 120k tris (~9× fewer). UVs/winding unchanged; verified GPU-free that stride=1 reproduces the old loop byte-for-byte. Terrain *editing* uses its own mesh, so only display polys drop. (If terrain is disk-cached, regenerate to pick up the lower res.)
   - **Frustum cull reach** (`map_canvas_gpu._compute_visible_entities_3d`): FAR raised (Avatar 1500→2500, FC2-cell 900→1300, FC2-full 500→800) for longer view distance, `FRUSTUM_PADDING` 1.4→1.8 (less edge pop-in), behind-camera depth margin −50→−120 (big objects the camera sits on aren't culled). Denser scenes lean on the F8 prepass to stay cheap.
   - **Cull-sphere radius fix** (`map_canvas_gpu`, the `_radii_3d` build): the bounding-sphere radius is now the distance from the model **origin to the farthest AABB corner** (`scale * ‖per-axis max(|bmin|,|bmax|)‖`), not `½·diagonal`. The sphere is centred at the entity origin (`_off=0`, so `_positions_centered_3d == _positions_3d`). Why: meshes modelled far from their origin (e.g. a background whose origin is map-centre but geometry is ~1000 m away) had a tiny origin-centred sphere that didn't reach the mesh, so they **popped when the ORIGIN left the frustum** while the mesh was still on screen. Rotation about the origin preserves corner distance → rotation-invariant. Identical radius for origin-centred meshes (no regression); only inflates the rare offset meshes (verified GPU-free).
   - **`material_index = None` crash fix** (`gpu_driven_renderer.consolidate_geometry`): some maps have meshes with no material; `int(None)` threw → `consolidate_geometry` crashed → **the whole GPU-driven path silently fell back to the universal renderer** (`models` 44 ms vs ~2.7 ms, ~15 FPS on a 5.6k-entity map). Now coerced to 0, and `_build_material_table` falls back to that **model's own first material** (not global #0) so textures don't bleed across models. (Verified GPU-free.)
   - **Bone transforms: stays DISABLED** (`xbg_direct_loader.build_xbg_model` keeps `skip_skeleton=True`). Tried re-enabling (`skip_skeleton=False`) but it **corrupted model scale/rotation on reload** — the EDON skeleton / skin-remap parse path has a side effect on static vertex assembly — and it doesn't change static rendering anyway (nothing deforms the mesh here). Reverted. If skeleton data is ever genuinely needed, parse it into a side structure without touching the mesh parse.
   - **FPS counter:** EMA-smoothed frame-to-frame FPS computed at the top of `paintGL` (`self._fps`), drawn **top-right** in `_draw_3d_ui_overlays` (green ≥50, amber ≥30, red below).
   - **Instanced marker cubes** (`canvas/cube_batch.py`, `cubes` stage ~3.4 ms → ~0.1 ms): entities without a model drew a cube each via `glPushMatrix/glTranslatef/glCallList` (2000+ draws). Now ONE `glDrawArraysInstanced` — static unit-cube VBO + per-instance (offset xyz, colour rgb) buffer, `#version 330 compatibility` shader using `gl_ModelViewProjectionMatrix`, cheap derivative-based face shade so they still read as 3D (flat colour, not fixed-function lit). `canvas._use_cube_instancing` (default True) falls back to the display-list loop. Needs GL 3.3.
   - **Batched wireframe overlays** (`canvas/line_batch.py`, `prims`+`triggers`+`shape` ≈ 10 ms): trigger boxes, primitive cubes and shape-point polygons were per-entity immediate-mode `glBegin/glEnd`. A shared `LineBatch` accumulates world-space coloured segments + points across all three (`begin()` → `add_lines/add_points` → `flush()` = one `GL_LINES` draw + one `GL_POINTS` draw). Trigger/primitive **cube** wireframes are CPU-transformed to world space via `overlay_matrix` — which replicates the exact `T·Rx(-90)·Rz(-rz)·Rx(rx)·Ry(ry)·S` glRotate/glScale sequence (**verified GPU-free** against the stepwise transform). Shape points are already world-space. Caveats: line width is now uniform (selected entities are distinguished by colour, not thickness); **primitive spheres/cylinders stay immediate-mode** (rare, no batched geometry for them). `canvas._use_overlay_batch` (default True) falls back to immediate. Both renderers registered in `setup.py`.
   - **Model-preview window** (`ModelPreviewWidget` in `simplified_map_editor.py`): the turntable ran a 30 fps timer where **paintGL re-did the bounding-box pass every frame** — `np.concatenate`+min/max over *all* verts twice (fit-scale + per-entity centers). All static. Now `_rebuild_preview_cache` (GL-free; called from set_model/set_models) computes the fit-scale + per-model transforms ONCE into `self._render_plan`, and paintGL reuses it; the **per-frame mesh draw still goes through `_draw_model_meshes`** so textures/materials are unchanged. (NOTE: an earlier attempt baked each model into a **display list** — that DROPPED the textures, because client-array texcoord + texture-bind don't bake reliably together here; reverted to the cached-layout + immediate-draw approach.) **Preview-texture keying bug (fixed):** `_upload_preview_textures` did `if not raw or not mat_map: return` — but the **XBG direct path** (`_load_xbg_textures`, the path every Avatar model uses) keys `model.texture_raw_data` by **material index** and never sets `texture_material_map`, so `mat_map` was empty and the preview bailed → untextured models. The gltf path keys `texture_raw_data` by **image index** + sets `texture_material_map[mat_idx]=img_idx`. The preview now handles BOTH: `pairs = [(mi, raw[ii]) for mi,ii in mat_map.items()]` when a map exists, else `raw.items()` directly (XBG). Only diffuse is stored (`store_raw=True`), which is all the preview shows. Logs `[preview] uploaded N/M textures … (keying: direct|material-map)`. (The selection-glow pulse re-renders only the *selected* instance — already cheap; it just forces a main-canvas repaint at the 30 fps glow tick, fine now the main render is fast.)
   - **mip0 textures everywhere** (`texture_loader._prefer_mip0_textures`, called at the end of `load_material`): every texture slot now prefers its high-res `<name>_mip0.xbt` sibling when present (the engine's full-resolution top mip), matching the add-on's `materials.py` `versions['mip0'] or versions['regular']`. Done **per-slot** (`foo_d.xbt → foo_d_mip0.xbt`, idempotent) using `_resolve_texture_path`, so it's robust where the older shared-basename Pass 1 in `_fill_missing_textures_from_disk` wasn't (different basenames / failed `data`-folder walk). Centralised in `load_material`, so both the 3D view and the model-preview window (which reuses `model.texture_raw_data`) get mip0.
   - **CPU-adaptive parse workers** (`simplified_map_editor`, `_auto_parse_workers`): replaced the bare `multiprocessing.cpu_count()` with a robust helper — `max(2, min(os.cpu_count()-1, 16))`, guarded against `cpu_count()` being undeterminable — so the thread count auto-scales to whatever machine runs it (weak CPUs fewer, strong more). Logs `CPU auto-detect: N logical cores -> M parallel parse workers` at load.
   - **Parallel model-load speedup** (the longest level-load stage): the parse worker (`build_xbg_model`, run on a `ThreadPoolExecutor` in `simplified_map_editor`) was doing a numpy→`list`→numpy round-trip **per mesh**: `parse_mesh_vertices` vectorised then `.tolist()`, `compute_face_normals` `np.asarray()`→compute→`.tolist()`, then `build_xbg_model` `np.asarray()` again. On ~3M verts × hundreds of models that's millions of Python float objects created+reparsed — pure-Python, **GIL-held**, so the threads barely scaled. Fix: keep vertex data in **numpy end-to-end** via new `Mesh.vert_pos_arr / vert_uv_arr / vert_normal_arr` (set in `parse_mesh_vertices` + `compute_face_normals`, consumed by `build_xbg_model`); the legacy `vert_*_list` are the fallback (slow-loop / non-XBG paths). `_compute_tangents` was already vectorised. Consumers updated: `mesh.compute_face_normals` (prefers `vert_pos_arr`, writes `vert_normal_arr`, fallback loop runs off the numpy `v`), `xbg_parser` normal-gate, `xbg_direct_loader.build_xbg_model`. Worker cap raised **8 → 16** (`min(cpu_count-1, 16)`) — now worthwhile since more of the parse releases the GIL. Verified GPU-free (array path + list fallback both produce correct verts/normals/uvs/bounds). Only `canvas/{mesh,xbg_parser,xbg_direct_loader}.py` consume these fields.

## 3D Lighting — world-space 2-light sun rig (current)

**Sun indicator sphere REMOVED (June 2026):** the Blender-style blue sun sphere + parallel blue ray lines (`_render_light_source_sphere`, with its only-consumer helper `_get_map_center_gl`) was deleted from `canvas/map_canvas_gpu.py` along with its call site in `_render_3d_opengl` ("Sun position indicator sphere"). It was a visual debug aid for the old lighting setup. `_key_light_pos()` is NOT related to it and stays — the light rig uses it.

The current rig is a **2-light WORLD-SPACE sun setup** (an earlier camera-relative "studio rig" was replaced). Lights are set **after `gluLookAt`** so their positions are world-space — the sun stays fixed in the sky as the camera orbits, like a real sun. **Only `GL_LIGHT0` + `GL_LIGHT1` are enabled; `GL_LIGHT2` is explicitly disabled** (and never given color). The GLSL material shader's per-pixel light loop is bounded by `#define NUM_LIGHTS 2` to match — bumping the rig to 3 lights means bumping that define too, else the 3rd light won't show (and conversely, looping past the enabled count just burns ALU on a dead light).

### Light values (all three render sites use the same values)

| Light | Role | Position | Diffuse | Specular |
|-------|------|----------|---------|----------|
| GL_LIGHT0 | Sun — warm directional, high in the sky | `self._key_light_pos()` | `[0.90, 0.88, 0.82]` | `[0.50, 0.48, 0.44]` |
| GL_LIGHT1 | Sky fill — directional from straight above | `[0.0, 1.0, 0.0, 0.0]` | `[0.30, 0.33, 0.42]` | none |
| GL_LIGHT2 | **disabled** | — | — | — |

- **Global ambient:** `[0.38, 0.38, 0.42]` (keeps unlit faces visible without a fake bottom light)
- **Default material specular:** `[0.15, 0.15, 0.15]`, shininess `40`
- **`GL_NORMALIZE` enabled** — corrects normals on scaled models.
- **`GL_LIGHT_MODEL_LOCAL_VIEWER = GL_TRUE`** — accurate specular angle.
- World-space (not camera-relative): positions are set **after** `gluLookAt`. (In legacy GL, `glLightfv(..., GL_POSITION, ...)` bakes the position through the current MODELVIEW; setting it post-`gluLookAt` yields a world-space light. To make a light camera-relative instead, set it at identity MODELVIEW before `gluLookAt`.)

### Where lighting is set up

1. `canvas/map_canvas_gpu.py::_render_3d_opengl` — main 3D view (after `gluLookAt`, ~line 3007).
2. `canvas/map_canvas_gpu.py` — entity-browser thumbnail FBO render (two locations, ~5286/5394).
3. `simplified_map_editor.py::ModelPreviewWidget.initializeGL` — mini model viewer.

The GLSL fragment shader reads these same `gl_LightSource[0..NUM_LIGHTS-1]` + `gl_LightModel.ambient`, in eye space (OpenGL stores `gl_LightSource[i].position` transformed by the MODELVIEW at `glLightfv` time), so the shaded models match the rest of the scene. To retune lighting, change the `glLightfv` values; the shader follows.

---

## Direct XBG loading — no GLTF/.bin intermediates (Phase 1, May 2026)

The editor now reads `.xbg` models **directly** at runtime instead of converting them to `.gltf`+`.bin`+cooked textures in an on-disk model cache. This kills the disk cache (saves space) and removes the runtime `xbg2gltf.py` subprocess. There is NO model caching of any kind on disk — models are parsed into memory per session. **Geometry/material output is identical** to the old gltf round-trip — the gltf exporter wrote XBG verts/UVs raw (the −90°X correction is the render-time `glRotatef(-90,1,0,0)`), so feeding XBG data straight into `GLTFModel`/`GLTFMesh` produces the same numbers.

This was **Phase 1** (direct loading only). **Phase 2 (the GLSL per-pixel material pipeline — normal maps + spec + emission + animated UVs) is now implemented** — see the "GLSL material pipeline" section below. Normals stay geometry-computed (`mesh.compute_face_normals`) on purpose (authored XBG normals look wrong in-editor — user decision).

### How it works

- **`canvas/xbg_direct_loader.py`** — `build_xbg_model(xbg_path, GLTFModel, GLTFMesh, lod=0)`. **GL-free** (runs on the Phase-A worker threads, like `_parse_gltf` did): `XBGParser.parse(lod)` → fills `model.meshes` (one `GLTFMesh` per primitive, sharing the mesh's vertex/normal/uv arrays), `model.bounds_min/max` (true whole-model union — the old gltf path stored only the LAST mesh's bounds, a latent picking bug now fixed), and stashes `model.xbg_material_names` for the texture pass. Indices are `uint32` (the old path used float32, which only worked because the display-list path re-cast them). Static geometry only — bone weights/skeleton ignored.
- **`model_loader.load_static_xbg(xbg_path)`** — orchestrator: `build_xbg_model` → `_load_xbg_textures` → `_create_opengl_resources` → cache by `xbg_path`.
- **`model_loader._load_xbg_textures(model)`** — needs a GL context; mirrors `_load_embedded_textures` exactly (same filters, `GL_MODULATE` 1.5× brighten, mipmaps, OPAQUE→MASK alpha auto-promotion) but sources pixels from `texture_loader.load_material()` (XBM) + `convert_xbt_to_png_base64()` (XBT) instead of an embedded base64 PNG. Sets `model.textures` / `alpha_modes` / `emissive_factors` / `base_color_factors` keyed by the **XBG material index** (1:1 with `GLTFMesh.material_index`).
  - **`materials_directory` MUST be set or every model renders grey.** `_load_xbg_textures` resolves XBM/XBT from `self.materials_directory` (via the `TextureLoader`). It's set by **`model_loader.set_materials_directory(path)`**, called during level/path setup right after `set_models_directory` (e.g. `map_canvas_gpu` ~5210, `_configure_paths` ~2802, `set_patch_folder`, `game_paths_config`) with `{resource|patch}/graphics/_materials`. **Gotcha (fixed):** `set_materials_directory` used to be a no-op stub from the embedded-GLTF era ("not needed — using embedded GLTF textures") that silently dropped the path → `materials_directory` stayed `None` → all XBM/XBT lookups failed → **every model grey** while geometry + shaders + lighting all worked. The one-shot `_print_render_diagnostic()` (first 3D frame) surfaces this: `materials_dir : None` + `models w/ diffuse texture : 0/N`. The setter now stores the path **and rebuilds the `TextureLoader`** (in case it was created earlier with a `None` path and cached "not found"). Ordering is safe — setup sets the dir before models lazily load textures during render.

### The switch points (entity models route `.xbg`; terrain still uses gltf)

1. **`_extract_gltf_path_from_resource` STEP 0** — now finds the `.xbg` first and returns `(xbg_path, None)`. So `entity.model_file` is the **`.xbg` path**, and `models_cache`/`instance_batches` are keyed by it. The legacy STEP 1/2 gltf-find + `convert_xbg_to_gltf` is now a dead fallback (only reached for a path with no `.xbg`), kept for any genuinely-native `.gltf` asset.
2. **Phase A worker** (`simplified_map_editor.py::_phase_a_worker`) — `if path.endswith('.xbg')` → `build_xbg_model` (GL-free) instead of reading gltf JSON + `_parse_gltf`.
3. **Phase B** — `if getattr(_m, 'xbg_material_names', None) is not None` → `_load_xbg_textures` instead of `_load_embedded_textures`.
4. **`get_model_for_entity`** (late-load fallback) — `if model_file.endswith('.xbg')` → `load_static_xbg`.

**Terrain is unaffected** — `map_canvas_gpu.py` calls `load_static_gltf` with terrain gltf paths (`terrain_to_gltf.py`), which is out of scope and still uses the gltf path.

### Gotchas / still-TODO

- `entity.bin_file` is `None` for `.xbg` models; the Phase-A `_unique` bin-path default (`.replace('.gltf','.bin')`) yields a junk path but the `.xbg` worker branch ignores it.
- **Removed (the whole gltf pipeline is gone):** `canvas/xbg2gltf.py` + `canvas/gltf_exporter.py` (deleted), `model_loader.convert_xbg_to_gltf` / `_find_xbg_converter` / `_get_model_cache_dir` + the `__init__` converter fields (deleted), the STEP 1/2 gltf-find + conversion inside `_extract_gltf_path_from_resource` (deleted — only STEP 0 DIRECT XBG + the STEP 3 path-fallback recursion remain), the on-disk model cache dir (all references scrubbed June 2026: .gitignore entry, setup.py post-build cleanup block, code comments), and the `canvas.xbg2gltf` / `canvas.gltf_exporter` entries in `setup.py`. `load_static_gltf` / `_parse_gltf` / `_load_embedded_textures` are **kept** — terrain (`terrain_to_gltf.py` via `map_canvas_gpu`) still uses them.
- `build_xbg_model` was validated manually against a real game model (`npc_avatar_grace_body.xbg` → 10 meshes / 9 materials / correct bounds / 11.5K tris) — no committed `.xbg` fixture exists in-repo for an automated test.
- Phase 2 (GLSL per-pixel materials) is **mostly done** — see "GLSL material pipeline" below: normal maps + spec + emission + **animated UVs**. By decision, authored XBG normals are intentionally NOT used (face-averaged normals look better in-editor). Still TODO: the Unlit/Glass special looks (the shader treats everything as the lit aaa path).

---

## GLSL material pipeline (Phase 2) — per-pixel normal maps + spec + emission

Fixed-function OpenGL can't use Avatar's normal/spec maps, so models looked flat (diffuse-only — same as the old gltf path). Phase 2 adds a **GLSL 1.20 (compatibility) shader** that renders models per-pixel with the full XBM material, replacing the display-list path **when it compiles** and falling back to fixed-function otherwise.

### Files / flow

- **`canvas/model_shader.py`** — `ModelShader`: compiles/links the program, binds generic attribute locations — per-vertex `a_position@0, a_normal@1, a_uv@2, a_tangent@3` **and per-instance `a_inst_pos@4, a_inst_rot@5, a_inst_scale@6, a_inst_overlay@7`** (the instancing attribs, divisor 1) — caches uniform locations. `compile()` returns False on any compile/link failure. The vertex shader rebuilds each instance's world transform from the per-instance attribs (see the instancing bullet under "Performance").
- **`_load_xbg_textures`** (model_loader) now uploads **all four slots** (diffuse / normal[DXT5-GA-decoded] / specular / emission) and builds `model.mat_textures[mat_idx] = {slot: gl_id}` + `model.mat_params[mat_idx] = {tint, emissive, spec_color, shininess, alpha_mode(0/1/2), alpha_cutoff}`. It still sets `model.textures`/`alpha_modes`/etc. for the fixed-function fallback.
- **Tangents** — `xbg_direct_loader._compute_tangents` builds per-vertex tangents from positions+UVs (vectorised) → `GLTFMesh.tangents`. Needed for normal mapping; the shader gates on `u_has_normal` so meshes without tangents/normals are fine.
- **`render_batched_models`** is now a thin wrapper: `_ensure_shader()` → `_render_batched_models_shader()`, which runs **three instanced passes** — a **depth prepass** (non-blend, `DepthShader`, color masked off), an early-Z **color pass** (non-blend, `GL_LEQUAL`, depth-writes off), then a **blend pass** (see "Occlusion — depth prepass + early-Z"). Per model `_setup_instance_attribs` uploads the instance transforms; `_draw_mesh_instanced` sets per-material uniforms + binds the 4 textures to units 0-3 + issues one `glDrawElementsInstanced` for all copies; `_draw_mesh_depth` does the position-only prepass draw. The matrix stack carries the **view only**; the shader applies the per-instance model transform. The original renderer is preserved verbatim as **`_render_batched_models_fixed`**.

### The safety net (critical)

`render_batched_models` wraps the shader path in try/except: on **any** runtime error it prints, `glUseProgram(0)`, sets `self._model_shader_disabled = True`, and returns the **fixed-function** render for the rest of the session. A shader/GL bug degrades to the old diffuse-only look — it can **never blank the viewport**. Same for compile failures (`_ensure_shader` → False).

### Lighting consistency

The fragment shader reads the **same lights** the fixed-function path sets up — `gl_LightSource[0..NUM_LIGHTS-1]` (NUM_LIGHTS=2) + `gl_LightModel.ambient` (the 2-light world-space sun rig in `map_canvas_gpu._render_3d_opengl`; see "3D Lighting"). OpenGL stores `gl_LightSource[i].position` in **eye space** (transformed by the MODELVIEW at `glLightfv` time), and the shader works in eye space (`v_posES`, normal-mapped `N`), so model lighting matches the rest of the scene — just per-pixel + normal-mapped instead of per-vertex. To retune lighting, change the `glLightfv` values; the shader follows automatically.

### Gotchas

- **Compatibility profile only.** Uses `#version 120` + `gl_*` built-ins (matrices/lights). Generic attributes are bound to explicit locations (NOT the `gl_Vertex` aliases) to dodge the compat attribute-aliasing footgun. The editor's GL context is legacy, so this is fine; do NOT bump to a core profile without rewriting this.
- The **selection-glow** pass (`render_selection_glow`) stays fixed-function — `render_batched_models` ends with `glUseProgram(0)`, so glow runs shaderless (intended). Selection tint in the shader path is the per-instance `a_inst_overlay` attribute (→ `v_overlay`) lerping toward `u_overlay_color`, **not** a uniform/`glColor` — so selected and unselected copies still share one instanced draw.
- A material with an emission **texture** but no `IlluminationColor` gets `emissive=[1,1,1]` so the map shows (mirrors the old `_build_gltf_material`).
- `spec_color` is clamped to [0,1]; spec lives mostly in the spec MAP (per-pixel) so a flat fallback rarely over-shines.
- **Not runtime-tested** (no GL here) — validated by py_compile + GL-free tangent/parse checks on a real model, **plus** a standalone numpy proof that the shader's instance transform equals the old `glRotatef` order (2e-13) and that the vectorised normals match the loop (4e-16). The fallback makes a bad shader safe, but verify in-app: a textured, normal-mapped, specular-lit model that flies around smoothly = success; flat diffuse OR a ~2 FPS crawl = the shader/instancing fell back (check console for `[model_shader]`). **Instancing-specific things to eyeball in-app:** models land in the right place/orientation (transform), selected objects tint blue (per-instance overlay), animated-UV materials still scroll.
- **Authored XBG normals: intentionally NOT used.** Decision (user): the game's authored vertex normals look weird in the editor, so we keep the face-averaged `mesh.compute_face_normals` normals. Don't "fix" this by reading the XBG normal bytes.
- **Normal-convention debug toggles (F5/F6).** `model_loader.dbg_flip_green` / `dbg_flip_normal` → `u_flip_green` / `u_flip_normal` in BOTH shaders. F5 flips the normal-map green (Y) channel (DirectX↔OpenGL convention); F6 flips the base geometry normal (runtime, independent of the load-time `compute_face_normals` direction). Use them to find the visually-correct combo on a normal-mapped model, then bake the winner as the default (and reconcile `compute_face_normals` if F6 is the fix). Default: both OFF.
- **Geometry normals were INWARD — fixed (May 2026).** XBG is CW-wound, but `mesh.compute_face_normals` used `cross(e1,e2)` which yields **inward** normals for CW winding. The `if(dot(N,V)<0) N=-N` two-sided hack masked this in the diffuse term (always lit) but the normal map was then applied/flipped in an inverted frame → globally inverted bump detail ("weird normals"). Now uses `cross(e2,e1)` → outward (unit-verified: a CW tri facing the viewer → `+Z`). If bump detail STILL looks inverted after this, the remaining suspect is the normal-map **green-channel (Y) convention** — flip `nTS.y` in both fragment shaders (1 line each).
- **Normal-map TBN = screen-space derivatives (Schüler cotangent frame), May 2026.** Both the universal and GPU-driven fragment shaders now build the tangent frame per-fragment from `dFdx/dFdy(v_posES)` + `dFdx/dFdy(uv)` instead of a precomputed tangent + `cross(N,T)`. Reason: the editor's UV tangents had **no handedness sign**, so mirrored-UV regions inverted ("weird normals"). The derivative frame gets handedness automatically and needs no tangent attribute. **Verified the DXT5-GA decode matches the Blender addon** (`xbg-re-import/-Current/V11/script/modules/nodes.py` `normal_map`: X=Alpha, Y=Green, Z=√(1−X²−Y²), no Y-flip — same as `texture_loader._decode_dxt5_ga_normal_map`). The `tangents` attribute is still plumbed but now unused by lighting (could be removed).
- **Still TODO:** the Unlit additive / Glass looks (the shader treats everything as the lit aaa path — Unlit emissive/additive and Glass fresnel/reflection aren't special-cased yet).

### Animated UVs (Unlit / FX scroll)

`u_uv_offset` (vertex shader: `v_uv = a_uv + u_uv_offset`) is driven per-material per-frame:
- `_load_xbg_textures` reads `AnimType` / `USpeed` / `VSpeed` from `xbm.properties` into `mat_params`, and sets `model_loader.has_animated_materials = True` if any are nonzero.
- `_render_batched_models_shader` computes `anim_t = time.monotonic() - self._anim_t0` once per frame; `_draw_mesh_shader` sets `u_uv_offset` = `speed * anim_t` (AnimType 1/2 scroll) or `(cos·U, sin·V)` (AnimType 3 ping-pong).
- **Offset = `speed * time` directly — NO tiling pre-multiply and NO V-flip** (unlike the Blender add-on). The editor's `mesh.py` keeps raw game-space UVs and doesn't bake `DiffuseTiling`, so the Blender corrections don't apply here. (If a scroll ever looks like it's going the wrong way, flip the sign of `vspeed`/`uspeed` in `_draw_mesh_shader` — the OpenGL bottom-left texture origin vs the game's top-left could invert the *visual* direction; the math is otherwise faithful.)
- **Continuous repaint:** the canvas's always-on 30 FPS `_glow_timer` (`_on_glow_tick`) now repaints in 3D whenever something is selected OR `model_loader.has_animated_materials` — so the scroll plays without the user interacting. The flag resets in `clear_cache` (new level). Only the GLSL path animates; the fixed-function fallback is static.
- `clear_cache` deletes **all four** texture slots per material via `model.mat_textures` (was only freeing `model.textures` = diffuse — a leak for normal/spec/emission).

### Culling (performance)

- **Frustum / object culling already existed** (entity level): `map_canvas_gpu._get_visible_entities()` does a vectorised NumPy frustum cull (capped ~3000 survivors) and feeds only the visible list to `model_loader.prepare_batches()`, so off-screen entities never enter `instance_batches`. `_never_cull_entities_3d` (non-worldsector entities) bypass it. Nothing to add here.
- **Backface culling (added, shader path):** `_render_batched_models_shader` enables `glFrontFace(GL_CW)` + `glCullFace(GL_BACK)` + `glEnable(GL_CULL_FACE)` — XBG winding is CW so front faces are CW. **Per-material:** `_draw_mesh_shader` does `glDisable(GL_CULL_FACE)` for `mat_params['two_sided']` materials (foliage/cloth/flags) and `glEnable` otherwise; the shader's normal-flip lights those two-sided backfaces correctly. Restored to `glDisable(GL_CULL_FACE)` at the end of the pass.
  - The old "global CW cull caused missing faces" warning (XBG winding section) was about mixing **CCW glTF** models in — now everything is CW XBG, so `GL_CW`+`GL_BACK` is correct. The fixed-function fallback path still renders un-culled (left alone as the safe fallback); culling only applies on the GLSL path.

### Resource folder no longer converts to glTF

`set_patch_folder.py`'s "Set Resource Folder" flow **no longer prompts "Convert XBG Models?"** or runs a batch XBG→glTF conversion (that method `batch_convert_xbg_models` never existed after the pipeline removal anyway — the prompt was dead). It now just sets `materials_directory` + `models_directory` and reports the XBG count. `_index_models_directory` indexes `*.xbg` (was `*.gltf`) for a meaningful count — though the loader resolves paths by directory walk (`_find_xbg_case_insensitive`), so the index is diagnostic only.

### Performance — hardware instancing + VBOs (render) + fast loading

The first GLSL render path was correct but unusably slow (~1.1 s/frame — the profiler's `entities=1135` spike) because it re-transferred each mesh's vertex arrays from CPU **every draw, every frame** (client-side `glVertexAttribPointer`) and re-bound all material state per-instance-per-mesh. Fixed in two stages:

- **Per-mesh VBOs** (`_ensure_mesh_vbo`): each mesh's position/normal/uv/tangent + index buffer is uploaded to GPU `GL_STATIC_DRAW` buffers **once** (lazily, on first draw). Draws bind the buffer + `glVertexAttribPointer(..., ctypes.c_void_p(0))` — no CPU transfer. `clear_cache` frees them via `glDeleteBuffers`. (Got ~1135 ms → ~385 ms.)
- **Hardware instancing** (`_draw_mesh_instanced` + `_setup_instance_attribs`): every copy of a model now draws in **one `glDrawElementsInstanced`** call instead of one `glDrawElements`+`glPushMatrix` per object. This was the fly-around-speed fix — at ~5,675 visible mesh-instances the old per-instance loop issued ~170K PyOpenGL calls/frame (the 385 ms steady state); instancing collapses that to per-(model,mesh) material binds + a handful of draws.
  - **Per-instance data is attributes, not a CPU matrix.** `_setup_instance_attribs` packs each model's visible instances into `(pos3, rot3, scale, overlay)` = 8 float32 (`INSTANCE_STRIDE=32`), uploads to one shared `GL_DYNAMIC_DRAW` instance VBO (`self._instance_vbo`, orphaned+reuploaded per model per pass), and binds attribs **4-7** with `glVertexAttribDivisor(loc, 1)`.
  - **The transform is rebuilt in the vertex shader**, not on the CPU — `model_shader.modelRot()` replicates the legacy fixed-function order `T · Rx(-90) · Rz(-rz) · Rx(rx) · Ry(ry) · S` exactly (no column-major matrix juggling to get subtly wrong). **Proven** equal to the old `glRotatef` sequence to 2e-13 over 20K random cases. The fixed-function matrix stack now carries the **view only**, so `gl_ModelViewMatrix`=view and `gl_ModelViewProjectionMatrix`=proj·view.
  - **Selection overlay** moved from the `u_overlay` uniform to the per-instance `a_inst_overlay` attribute (`0.35` if selected) → `v_overlay`, so selected + unselected copies draw in the same instanced call.
  - **Attribs are torn down each frame** (`_disable_instance_attribs` clears divisors 4-7; the pass also disables 0-3) so nothing leaks into the fixed-function fallback. The whole shader path stays wrapped in the `render_batched_models` try/except → a bug degrades to fixed-function, never a blank viewport.
  - Requires `glDrawElementsInstanced` + `glVertexAttribDivisor` (GL 3.1/3.3, ARB_instanced_arrays); both import from `OpenGL.GL`. If unavailable the try/except falls back.

Loading was also slow. Four fixes (model load ~1.6 s → ~0.18 s on a 72k-vert character):

- **Skeleton skip** (`XBGParser.parse(skip_skeleton=True)`, used by `build_xbg_model`): static loads don't parse the EDON skeleton (100+ bones + world-transform compute) or run `_remap_skin_indices`. The chunk loop's `seek(back + chunk_info[1])` moves past the skipped bytes. We never deform, so skin data is unused.
- **Direct XBT→RGBA decode** (`texture_loader.decode_xbt_to_rgba`): **~51× faster** than `convert_xbt_to_png_base64`. The old path did XBT→temp-.dds-file→PIL→PNG-encode→base64→decode→RGBA (33 ms/texture); the new one is XBT→DDS-bytes→PIL(from BytesIO)→RGBA (0.6 ms/texture), with a temp-file fallback if a PIL build can't read DDS from memory. `_load_xbg_textures` uses it. (~36 textures/model, so this was the dominant load cost.)
- **Vectorised vertex parse** (`mesh.parse_mesh_vertices`): one bulk `g.read(count*stride)` + numpy slicing at fixed offsets (pos @0, uv @8, skin @16) instead of a Python per-vertex loop — ~2.8× (438→156 ms on the same model), bit-identical output (bounds match). Falls back to the per-vertex loop on any error.
- **Vectorised normals** (`mesh.compute_face_normals`): numpy cross-product + `np.add.at` scatter-add over all triangles instead of a Python per-triangle loop. **Proven** bit-identical to the loop (4e-16 over 200 random meshes, all unit-length) and verified on a real 33k-vert model (`banshee.xbg`, 5/5 meshes unit normals). Falls back to the loop on any error. (Authored XBG normals stay unused by decision — face-averaged look better in-editor.)

### PyOpenGL per-call error checking — disabled for speed (the big CPU-bound win)

`main.py` sets `OpenGL.ERROR_CHECKING = False` + `OpenGL.ERROR_LOGGING = False` **before the first `import OpenGL.*`** (the flags are read at import time — order matters, so they live at the very top of `main.py`, before `fix_frozen_paths` and any canvas import). By default PyOpenGL wraps **every** GL call with a `glGetError()` round-trip + array validation; a 3D frame issues tens of thousands of GL calls, so that per-call validation was the bulk of the CPU-bound `entities=~390 ms` render spikes (it also masked the instancing win — the call-count dropped but each call still paid the validation tax). Disabling it is the canonical PyOpenGL speedup (commonly 2-5×), no visual change.

- **Escape hatch:** run with `OPENGL_DEBUG=1` to keep full per-call checking (GL errors raise immediately again) while debugging.
- **Safety with checks off:** GL errors no longer raise, so the shader path can't rely on exceptions to fall back. `render_batched_models` instead runs **one** `glGetError()` per frame (gated by `self._gl_checks_on`, set from `OpenGL.ERROR_CHECKING` at init) and logs once if a real error slips through. Shader compile/link failures are still caught explicitly (`glGetShaderiv`/`glGetProgramiv`), so the fixed-function fallback still triggers for those.

### Occlusion — depth prepass + early-Z (the "only shade visible pixels" pass)

Before this, every opaque fragment ran the full material shader (up to 4 texture samples + normal-map TBN + 2-light Blinn-Phong) **even when fully hidden behind another object** — the depth test threw the result away *after* shading. In a dense/overdrawn scene most of that fragment work was wasted. The `_render_batched_models_shader` path now does a **depth prepass** so occluded fragments are killed *before* the expensive shader runs. Three passes (all instanced):

1. **Depth prepass** (non-blend meshes) — `_draw_mesh_depth` with the tiny `DepthShader` (position-only + alpha-mask discard). `glColorMask(FALSE×4)`, `glDepthMask(TRUE)`, `glDepthFunc(GL_LESS)`. Lays down nearest-surface depth; no shading, no color.
2. **Color pass** (non-blend) — full `ModelShader`. `glDepthMask(FALSE)` + `glDepthFunc(GL_LEQUAL)`, so a fragment shades **only if it's the front-most one at that pixel**; everything behind fails early-Z before the fragment shader. (Bonus: terrain renders first with `GL_LESS`, so entities behind terrain are culled here too.)
3. **Blend pass** (alpha-blend meshes) — unchanged: `GL_LEQUAL`, no depth writes, blending on.

**Why `invariant gl_Position` is load-bearing (do NOT remove it).** The prepass and color pass are *different programs*; with `GL_LEQUAL` + depth-writes-off, if the color pass computed even slightly **larger** depth than the prepass (FP variance between programs), the visible fragment would fail `LEQUAL` and punch a **hole**. To prevent that, both vertex shaders (a) compute `gl_Position` from the **same shared `_ROT_GLSL` source** (in `model_shader.py`) and (b) declare `invariant gl_Position;`. That guarantees byte-identical depth, so the visible fragment always passes. If holes/flicker ever appear on a non-conforming driver, the remedy is a small `glPolygonOffset` pushing the **prepass** slightly farther (so `D_color <= D_prepass` always) — not removing `invariant`.

**Masked materials** (`alpha_mode==1`) are included in the prepass, but the depth shader samples diffuse `.a` and `discard`s with the same `u_alpha_cutoff` + animated `u_uv_offset` as the color pass (`anim_t` is captured once and shared by both passes), so the carved silhouette matches. Two-sided cull state is also replicated per-mesh in `_draw_mesh_depth`. Opaque meshes skip the texture/UV entirely (position-only) for a cheap prepass.

**Safety net:** the depth program compiles via `_ensure_depth_shader()`, independent of the material shader. If it fails to compile/link it returns `None` and the color pass falls back to a plain `GL_LESS` depth-write fill (correct, just no overdraw savings) — the whole shader path is still wrapped in `render_batched_models`'s try/except → fixed-function. State is fully restored at pass end (`glColorMask` TRUE, `glDepthMask` TRUE, `glDepthFunc` GL_LESS) so the selection-glow / beacon-line / gizmo passes and next frame's terrain are unaffected.

**Bundled CPU trims (shipped with this):** `prepare_batches` now builds a `selected_ids` set once (was `entity in selected_entities` on a **list** → O(N×S) per frame; now O(1) per entity), and the 3 render passes categorise each model's meshes into non-blend/blend **once per frame** (was re-filtered per pass). Front-to-back order is preserved for free: `_get_visible_entities` returns entities distance-sorted, and `instance_batches` (insertion-ordered dict) keeps nearest-model-first, which still helps the prepass's own early-Z.

### Frustum culling must stay authoritative (the big flying win, May 2026)

Symptom: `⚡ CULL: 65/787 in frustum` but `3D Rendering: 709 visible` — the cull worked, then two post-cull overrides dragged ~640 off-screen objects back in, so the editor rendered ~10× what was on screen. Both fixed so **model-bearing entities are frustum-culled, period**:

- **`_get_interior_exempt_entities` now returns ANCHORS ONLY** (entities whose AABB the camera is literally inside), not every entity overlapping them. The old "overlap expansion" (pass 2) exploded in dense scenes: one big background prop the camera sits inside overlaps ~the whole level. Anchors are already kept by the frustum's inside-sphere bypass anyway, so this is safe.
- **`_never_cull_entities_3d` is now non-worldsector entities WITHOUT a model** — cheap markers (spawn points, managers) only. Model-bearing props (e.g. 110 omni `bkg_faketree` **models**) are no longer force-rendered; they cull by frustum like everything else.
- The `⚡ CULL` log now prints a breakdown: `N drawn = F frustum + I interior + M markers | total (culled)`. After the fix: `129 drawn = 70 frustum + 1 interior + 56 markers` (was 709). If objects visibly pop in/out at screen edges, raise `FRUSTUM_PADDING` in `_get_visible_entities`.

### Terrain VBO — stop re-sending 1.5M indices per frame (May 2026)

Large terrain meshes (>~display-list threshold) used **immediate mode = client-side vertex arrays re-sent from CPU every frame** (`glVertexPointer(..., mesh.vertices)` + `glDrawElements(..., mesh.indices)`). At 262k verts / 1.5M indices that's ~9 MB/frame marshalled through PyOpenGL — a big per-frame cost that the `entities=` profiler **doesn't even measure** (terrain draws before entities). `map_canvas_gpu._ensure_terrain_vbo(mesh)` now uploads pos/normal/uv + index to GPU `GL_STATIC_DRAW` buffers **once** (cached on `mesh._terr_vbo`); `_render_terrain_model`'s immediate-mode branch draws from them with offset pointers (fixed-function + VBO, compat-profile-safe), falling back to client arrays if buffer creation fails.

### CPU-bound vs GPU-bound — know which before optimizing

This editor is **CPU-bound on draw submission** (`entities=` is CPU time; `cull` is ~2.7ms). Consequences:
- **Depth prepass defaults OFF** (`model_loader._depth_prepass_enabled = False`). It's a GPU/overdraw optimization that costs a 2nd geometry submission (~40% more draw calls) — net-negative when CPU-bound. Flip it on only if you become GPU/fragment-bound.
- **Frame-time diagnostic:** `paintGL` prints `⏱️ 3D frame avg: X ms (~Y FPS)` every 60 frames, timing the WHOLE 3D frame (terrain + entities + grid + water) with a `glFinish()` for honesty. This is the true steady-state number; the `entities=`/`SPIKE` logs miss terrain. **Both `glFinish()` and this print are diagnostic — remove once tuning is done** (glFinish serializes CPU/GPU and caps overlap).
- VAO-based instancing was implemented (`_build_mesh_vao`, `_vao_enabled`) to collapse ~12 per-mesh attrib-pointer calls into one `glBindVertexArray`, **but is DISABLED by default** (`_vao_enabled=False`): enabling it made models vanish AND the fixed-function terrain render black — VAO / generic-attrib state leaking into the compat-profile fixed-function passes (terrain, cubes, glow) that bracket the entity pass. The manual per-draw attrib path is the proven one and only ~13 ms slower in dense scenes. The VAO code is kept (toggle) but **don't re-enable without debugging the state leak** (likely: the entity pass must fully restore fixed-function array state / leaves a generic attrib aliasing `gl_Vertex`, or the pass-end `glBindVertexArray(0)` is skipped on an exception path). Real remaining CPU lever: cut per-mesh material uniform/texture binds (no UBO in GLSL 1.20 — would need bumping the shader version or redundant-state skipping / material sort).
- **Escape-hatch toggles** if a perf change misbehaves: `model_loader._vao_enabled` (VAO instancing, default off) and `map_canvas_gpu._terrain_vbo_enabled` (terrain VBO, default on → set False to fall back to client arrays).

### Real-time render profiler + fragment-cost A/B (May 2026)

**Toggle with F1** (`keyPressEvent` → `_cycle_debug_mode`): cycles OFF → PROFILE → NO NORMAL MAPS → NO SPECULAR → NO EMISSION → UNLIT → OFF. Mode 0 (OFF) has **zero overhead** (`_prof=None` makes `_pf()` a no-op, no GPU query, no print). Any other mode enables the profiler print and, for modes 2-5, toggles one fragment feature so the GPU-ms delta vs PROFILE reveals that feature's per-pixel cost. While debug is on, `_on_glow_tick` keeps the 3D view repainting at ~30 FPS so numbers update even when idle.

When on, `paintGL` prints a per-stage breakdown every 60 frames so we can SEE where the frame time goes instead of guessing:
```
⏱️ FRAME 48.1ms CPU | GPU 9.2ms  (3575 drawn) | models=31.4  cubes=6.1  cull=3.2  prepare=2.8  terrain=1.1  ...
```
- **CPU per-stage**: `self._pf(key, t0)` accumulates ms into `self._prof` (reset each frame); `_render_3d_opengl` times terrain/grid/water/cull/srcfilter/prims/triggers/shape/overlays, and `_render_entities_3d` times prepare/models/cubes. `_accumulate_profile` rolls a 60-frame average and prints the biggest stages first. This is the actionable number — the editor is **CPU-submit bound**, so `models` (per-mesh material binds × unique models) dominates.
- **GPU total**: `_gpu_timer_begin/_end` bracket the frame in a `GL_TIME_ELAPSED` query (ping-pong of 2 queries, read 2 frames later so it never stalls). If GPU ms ≪ CPU ms → CPU-bound (the fragment shader, incl. normal/spec/lighting, is NOT the bottleneck). Fully wrapped — a missing `ARB_timer_query` just drops the GPU number.
- **Fragment-cost A/B switches** (answer "how much does normal-map / spec / lighting cost?"): individual shader ops can't be CPU-timed, so flip a switch and watch the GPU number move. `model_loader.dbg_no_normal / dbg_no_spec / dbg_no_emission` force the matching `u_has_*`=0 (CPU-side, no shader edit); `dbg_unlit` sets the `u_unlit` uniform which skips the per-light loop (the one small, GLSL-1.20-safe `if (u_unlit==0)` gate added to the fragment shader). The GPU-ms delta when you toggle one = that feature's per-pixel cost.
- All of this is **diagnostic** — strip the timing/queries (and ideally the `glFinish`-free frame timer) once tuning is done; the `glBeginQuery` bracketing adds negligible overhead but it's still debug scaffolding.
- GPU timer reads the result with the **32-bit** `glGetQueryObjectuiv` (not ui64): PyOpenGL's `GL_UNSIGNED_INT64_AMD` result converter is broken; ns fit in u32 up to ~4.3 s/frame.

### Bottleneck verdict + GPU-driven renderer plan (May 2026)

The F1 profiler settled it: a dense level is `FRAME ~103 ms CPU` with **`models ≈ 84 ms`**, and toggling normal-map/specular/emission/**unlit** (F1 modes) changed it by <1 ms → **100% CPU-bound on draw-call submission, GPU idle**. It's ~45k PyOpenGL calls/frame (≈1400 visible model-meshes × ~30 calls). OpenGL submission is single-threaded by spec, so more cores can't help (only ~7 ms of cull+prepare is even off-the-GL-thread-able). The fix is **fewer/cheaper GL calls**.

Direction chosen: **tiered renderer.** `canvas/gpu_driven_renderer.py` is the *fast lane* for modern GPUs — GL 4.3+ `glMultiDrawElementsIndirect` + SSBO, textures via **bindless** (NVIDIA: confirmed GL 4.6 + ARB_bindless_texture) or **texture arrays** (AMD/Intel without bindless). `detect_support()` returns `'bindless'|'texarray'|None`; on `None` (old/integrated) ModelLoader keeps its **universal PyOpenGL instanced path** — so the editor runs on all GPUs, just not GPU-driven on the weak ones. (Note: the weak GPUs then still hit the 84 ms path, so the universal VAO/bind-reduction wins are still worth doing for them later.)

**Staged build (each stage verifiable or behind a default-off toggle so the app never breaks):**
1. ✅ **DONE** `consolidate_geometry()` — packs all meshes into shared vertex/index arrays + a per-mesh draw table (`baseVertex/firstIndex/count`). GPU-free; the `__main__` self-test asserts `shared_index[firstIndex:+count]+baseVertex` reconstructs every mesh exactly (0.0 mismatch).
2. ✅ Upload shared GL buffers (VBO pos/normal + IBO) + VAO — in `GPUDrivenRenderer._ensure_built()`.
3. ✅ Per-frame: build the indirect draw-command buffer (`DRAW_CMD_DTYPE`) + per-instance transform SSBO from the frustum-culled `instance_batches` — `GPUDrivenRenderer._draw()`.
4. **v1 VALIDATED on RTX 5070 Ti** — one `glMultiDrawElementsIndirect` + GLSL **4.60 compatibility** shaders; transform via instance SSBO indexed by `gl_BaseInstance + gl_InstanceID` (proven `modelRot`), lit by the same `gl_LightSource[0..1]` rig. Flat-grey core confirmed: models render in correct positions/orientation, fast, in one call. Console: `MDI program compiled+linked OK`, `built: 1090 meshes, 6.7M verts`.
5. **v2 SHIPPED (bindless textures)** — `_build_material_table` makes every material's diffuse/normal/specular/emission textures **bindless-resident** (`glGetTextureHandleARB` + `glMakeTextureHandleResidentARB`) and packs a `Material[]` SSBO (`MAT_DTYPE`, 96 B std430 — verified). Each `MeshEntry.global_mat_id` indexes it; per frame a `drawMat[]` SSBO (binding 1, indexed by `gl_DrawID`) maps draw→material. Fragment shader samples `sampler2D(handle)` for full diffuse×tint + normal-map + spec + emission + alpha-mask, matching the regular shader. VAO now binds uv(2)+tangent(3) too. **Runtime-untested (no GPU here).**
6. **v3 SHIPPED (proper alpha/material state)** — MDI can't change blend/cull mid-call, so draws are binned into **3 render groups** (tagged on each `MeshEntry.render_group` from the material's `alpha_mode`/`two_sided`) and issued as 3 separate `glMultiDrawElementsIndirect` passes sharing the instance + material SSBOs: (0) opaque single-sided = cull-back + depth-write; (1) opaque two-sided (foliage/grates) = no-cull + depth-write + alpha-mask discard; (2) blend (glass/FX) = no-cull + blend + depth-test-only, after opaque. Fragment outputs `diffuse.a` for blend, `1.0` otherwise. Console prints the group counts at build. Matches the universal path's material handling. **Runtime-untested.**
7. **v4 SHIPPED (animated UVs) → FULL material parity with the universal path.** `Material` SSBO gained an `anim` vec4 (anim_type, uspeed, vspeed) → 112 B std430 (verified); a `u_time` uniform (set per frame from `anim_t`) drives the same scroll formula as the universal shader (`anim==3` → cos/sin, else `speed*time`). The GPU-driven path now matches the universal shader feature-for-feature: diffuse×tint, normal map, specular, emission, alpha-mask, alpha-blend, two-sided, animated UV, selection overlay.
   - **Still TODO (beyond the universal path too):** back-to-front sort for blend (draw-order — same as universal); additive (Unlit) blend mode (mat_params has no additive flag — both paths use standard alpha); the **texture-array** path for F3/AMD (no bindless). Bindless makes textures immutable + needs `glMakeTextureHandleNonResident` before `glDeleteTextures` (handle on `clear_cache`/reload).

**F2/F3 keys** (`map_canvas_gpu._set_render_tier`): toggle the forced tier on/off (mutually exclusive), printing the state; lets one machine test both the NVIDIA and AMD code paths. v1 is flat so both tiers look identical until textures land.

**Render tier is PERSISTED in `editor_config.json` (June 2026):** `_set_render_tier` saves `'render_tier': 'bindless'|'texarray'|null` (read-modify-write) and `_load_saved_render_tier` (canvas `__init__`, right after `ModelLoader()` is created) restores it on startup — so the user's F2/F3 GPU choice survives restarts; the GDR's own failure fallback covers a saved tier that doesn't match the hardware. **Gotcha fixed alongside:** `ThemeSettings._save_settings` (theme_settings.py) used to dump its startup snapshot over the whole config file, clobbering keys other components wrote later; it now merge-writes (re-reads the file, overlays its keys). Any new component writing to editor_config.json must do the same read-modify-write.

**IMPORTANT — the tier value is currently cosmetic:** `GPUDrivenRenderer._build_material_table` is bindless-only; pressing F3 ('texarray') still runs the bindless path. On GPUs whose driver exposes `GL_ARB_bindless_texture` (modern NVIDIA AND modern AMD Adrenalin) both keys work identically; on hardware without bindless the build fails → permanent universal fallback. The real texture-array material path (repack 2D textures into size-grouped `GL_TEXTURE_2D_ARRAY`s, store `(array, layer)` in the same uvec2 slots of `MAT_DTYPE`, non-bindless fragment shader variant) is **still TODO**.

## GPU-driven renderer — array-native frame assembly (June 2026)

The MDI draw collapsed GL submission, but the frame data feeding it was still built by three Python passes over thousands of objects per frame: `prepare_batches` (per-entity tuple build), `_collect_frame` (per-instance + per-mesh-entry appends + per-row structured fill), and the canvas's "which entities got models" tracking loop. In GPU-driven mode all three are now replaced by numpy:

**Per-frame flow (GPU-driven mode):**
1. `_get_visible_entities` (3D cull) stashes its survivor index array on `canvas._visible_idx_3d` (indices into `_valid_entities_3d`). Interior-exempt anchors are already in it via the inside-sphere bypass; never-cull markers have no models — neither needs adding.
2. `_render_entities_3d` calls `model_loader.prepare_gpu_frame(canvas, entities_sorted)` instead of `prepare_batches`. It assembles the instance SSBO contents + per-model-slot counts/offsets via `gpu_driven_renderer.assemble_frame()` (pure numpy) and stages them in `ml._gdr_frame`. Returns False → classic `prepare_batches` runs (universal path unchanged).
3. `GPUDrivenRenderer._build_frame()` turns counts/offsets into the per-group indirect command buffers via static **command templates** (`build_group_templates` — constant count/firstIndex/baseVertex/matId/slot columns, built once per geometry build) + `build_group_commands` (pure numpy select+fill). `cast()` (shadows) and `_draw()` share the same frame.

**Static row tables (`model_loader._gdr_row_*`):** one row per (entity, model) pair — kit parts add extra rows at the same transform, mirroring `prepare_batches`. Built by `_ensure_gdr_rows`, keyed on `canvas._pos_arrays_version` (bumped in `_get_map_filtered_entities` on every array rebuild). Positions are NOT stored in rows — they're gathered per frame from `canvas._positions_3d`, so drag updates flow through the existing position-cache machinery for free.

**Gotchas (don't break these):**
- `prepare_batches` sets `self._gdr_frame = None` at its top — any classic-path call drops a stale array frame. `render_batched_models`'s early-out is `if not self.instance_batches and self._gdr_frame is None` — restoring the old `if not self.instance_batches` guard would make array mode draw nothing.
- `_gdr_slots_version` bumps ONLY when the model-path list content changes — per-drag-frame row rebuilds keep the same paths, so the GDR's command templates are NOT rebuilt per frame. Don't key templates on `_gdr_rows_version` (that bumps every drag frame).
- Rotation/scale edits don't bump the position-array version → `mark_entity_modified` calls `ml.gdr_refresh_entity(entity)` (AFTER popping `_entity_rs_cache`) to patch that entity's rows in place.
- **Picking:** `select_entity_3d` iterates `instance_batches`, which array mode never fills. It now rebuilds batches at click time when `ml.gdr_drew_last` is True. Any new consumer of `instance_batches` must do the same.
- **Selection glow:** `render_selection_glow` was another `instance_batches` consumer — in array mode the yellow pulse silently vanished (only the shader's static blue tint remained; user noticed). It now takes `selected_entities` from the canvas and, when `gdr_drew_last`, builds the few selected transforms directly from `entity.x/z/-y` + `_get_entity_rs` (kit parts included). **It also needs `glPolygonOffset(-2,-2)`:** the model's depth comes from a shader while the glow re-renders fixed-function — depths aren't bit-identical, so without the offset the GL_LEQUAL glow only covered the model in patches.
- **Blue selection tint DISABLED (June 2026, user request):** selection is indicated by the pulsing yellow glow pass ONLY. The per-instance overlay value is hardwired to 0.0 at all four feed points — `_gdr_update_overlay` + the rebuild re-apply in `_ensure_gdr_rows` (model_loader, array mode), `_collect_frame` (gpu_driven_renderer, legacy mode), and `_setup_instance_attribs` (model_loader, universal shader). The shader plumbing (`v_overlay`, `mix(color, vec3(0.35,0.50,1.0), …)`, `a_inst_overlay`) is intact — to bring the tint back, restore 0.35 at those four sites.
- **Cube fallback:** when `gdr_drew_last`, `entities_with_models` is `ml._gdr_modelled_ids` (built with the rows; constant per level) instead of the per-frame instance walk.
- **Perf validation on the iGPU machine (June 2026):** after the overlay cache landed, the same 5,642-entity level profiles at **CPU 3.4–5.5 ms/frame** (was 11–19.4; `overlay3d=0.1`, `cull≈1–3` is now the largest CPU stage) with GPU 5.4–15.9 ms — GPU-bound everywhere, worst case (5,500 entities on screen) right at the 60 FPS budget. Remaining levers if a future level dips: F9 detail cull at 6px, F8 prepass, or a 3D render-scale option (not built).
- **3D overlay cache (June 2026) — the prims/triggers/shape fix:** profiling on the iGPU machine showed `shape=4-6 prims=3-5 triggers=1-3` ms/frame — the wireframe overlays were rebuilt per frame in Python though their geometry is **world-space (camera-independent)**. `_render_overlays_3d` now builds the packed LineBatch arrays ONCE over the FULL entity list (`snapshot()`), replays them per frame via `LineBatch.flush_packed()` ('overlay3d' profiler stage), and rebuilds only when the cache key changes (`_pos_arrays_version`, entities id/len, selection frozenset, `show_trigger_zones`) or `mark_entity_modified` clears `_ov_cache_key` (rotation edits don't bump the position version — don't remove that hook). Sphere/cylinder prims can't be line-batched: `_render_primitives_3d`'s batch path now STORES them in `_ov_sphere_cyl_pending` instead of drawing inline, and the caller draws via `_draw_sphere_cyl_prims` (cached path replays `_ov_cache_spherecyl` each frame). Classic per-frame path runs when a movie sequence is selected (preview moves entities without version bumps) or after a GL failure (`_use_overlay_cache=False`). Behavior change: overlays are no longer frustum-gated — distant wireframes beyond the old cull FAR now draw (GL clips off-screen ones).
- **Contribution culling (F9, GDR mode, June 2026):** `prepare_gpu_frame` drops model instances whose bounding sphere projects under `ml.gdr_min_pixel_size` px (default **4.0**; squared-compare against `canvas._radii_3d` + camera distance, VFOV 50 — no sqrt). The vertex-load lever for integrated GPUs ("AMD Radeon TM Graphics" = Ryzen iGPU — a user machine runs this; their 3M-vert level was GPU-bound at 40 FPS). F9 cycles OFF→3→6→10 px (first press from the 4.0 default lands on OFF for A/B comparison). Markers (radius 0) are unaffected. Universal/non-GDR path does not contribution-cull.
- **Marker cubes are numpy-gathered in GDR mode** (`_build_marker_cube_instances`, June 2026): cached per-entity color/marker arrays (keyed on entities-list id + valid count + modelled count + rel-cache key — deliberately NOT the position version, so drags don't rebuild) gathered by the cull's index array into the (M,6) CubeBatch instance array. Replaces the per-frame Python loop over all visible entities (~1500 markers ≈ 2-4 ms). Selected markers get the brightened color patched in afterwards (small loop). Any failure → classic loop.
- If the GDR fails mid-frame after `prepare_batches` was skipped, `render_batched_models` self-heals via `ml._gdr_fallback_args` (re-runs prepare_batches before the universal path). A permanently-failed GDR (`_failed`) makes `prepare_gpu_frame` return False so the classic path is the steady state.
- Instance layout = 8 float32 per instance `[pos.xyz, scale, rot.xyz, overlay]`, grouped by model slot in slot order — must match the shader's `Inst { vec4 posScale; vec4 rotOverlay; }` and the legacy `_collect_frame` layout.
- `gl_DrawID` indexes the per-draw material id; it was historically slower than baseInstance-derived indexing on old AMD drivers (g-truc "Surviving without gl_DrawID"). Modern drivers are fine; if AMD profiling ever shows poor MDI scaling, the workaround is duplicating instance data per mesh-draw so `gl_BaseInstance` can carry the material id.

**Tests:** `tests/test_gdr_frame_assembly.py` — assembly verified against naive reference loops; loads `gpu_driven_renderer.py` by file path because `canvas/__init__.py` imports the GL-heavy modules.

**Runtime-validated on AMD (June 2026):** smooth 60 FPS reported on a 5,642-entity Avatar level — build log: `795 meshes, 3.09M verts` consolidated, `699 materials, 1668 bindless textures resident`, render groups `572 opaque / 195 two-sided / 28 blend`. Confirms the GPU-driven v2-v4 material path (previously marked runtime-untested) works on AMD via **bindless** — the F3 "texture-array" tier label is cosmetic; `_build_material_table` ran the bindless path (AMD Adrenalin exposes `GL_ARB_bindless_texture`). Notes for log readers: `[gpu-driven] MDI program compiled + linked OK` prints **3×** (main + shadow-cast depth + camera depth-prepass programs — normal); `3D Rendering: … 0 models` is also normal in GDR mode (the MDI path returns 0 from `render_batched_models`; models ARE drawn).

## Binary-XML / `.ai.rml` converter — format crack (June 2026)

`tools/convert_avatar_xml.py` (gitignored, drag-and-drop) is a byte-exact bidirectional converter for **two** Dunia-1 formats. Validated byte-exact on **403/403** binary `.xml`/`.rml` game files and **29/29** BlackBox.AI `.ai.rml` brains (incl. the 6.5 MB `mercbrain` with 1668 class templates).

### Dunia binary-XML (`.xml`/`.rml`/`.game.xml`)
- Layout: `00 00` + VARINT(poolSize) + VARINT(nodeCount) + VARINT(attrCount) + node tree; the **string pool sits at the END** of the file (last `poolSize` bytes). Strings are UTF-8, NUL-terminated, deduplicated, in DFS-first-seen order (tag, node-type, then each attr name/value, then children).
- Node = `name_ref, type_ref, attr_count, child_count, [0x00, attr_name_ref, attr_val_ref, (0x00 between attrs)…], children…`. Every `_ref` is a byte offset into the pool. The per-node **type** string is almost always empty; when non-empty (rare) it's carried on the element as `avx_type="…"` (don't hand-edit).
- **VARINT escape threshold is `>= 0xFE`, NOT `>= 0xFF`** (the single most important gotcha). The game's **writer** reserves both `0xFE` and `0xFF`: any value ≥ 254 is written as `FF` + uint32-LE, so a one-byte field never exceeds `0xFD`. The **reader** only treats a leading `0xFF` as the escape marker (asymmetric but self-consistent). Concretely a pool offset of exactly **254** is stored as `FF FE 00 00 00`, not the single byte `FE`. Using a `0xFF` write-threshold silently corrupts any file that references offset 254 — it passed a 14-file sample by luck but broke 6/120 real files and 2/29 brains. Both `_vcnt()` and the encoder's `ref()` use `< 0xFE`.

### BlackBox.AI `.ai.rml` (29 AI "brain" behavior trees under `scripts/game/newbrains/`)
Detected by magic `04 00 00 00` (ver=4 LE) vs Dunia's `00 00`. Layout:
```
[0:16]   header  = uint32-LE  ver(=4), poolSize, tailSize, classCount
[16:S]   class-template table  (classCount entries: CRC32 + uint32 size + `size` inline bytes)
[..:S]   path/hash table       (node-path CRC32 lookups; inline path strings)
[S:end]  ── self-contained Dunia object ──  node tree (`00 00`+varint…) + shared string pool
```
- **`header.tailSize` (offset 8) == `len(file) - S` == size of the trailing Dunia object** (node tree + shared pool). So the editable brain is exactly `data[len-tailSize:]` — a standalone Dunia object the generic `decode()`/`encode()` already round-trips byte-exact. No need to parse the class/path tables to locate it.
- The decoded XML root is `<BlackBox.AI>` containing `<Brain>`/`<Task>` nodes with `<Selectable>/<Anchor>/<Exit>/<Parameter>/<Add>` children — fully human-readable & editable.
- The class/path **prefix `[0:S]` uses INLINE strings** (independent of the shared pool), so it's preserved **verbatim** as base64 in the `avx_ai_prefix` attribute (synthesized — filtered by `_real_attrs`, never pooled). On repack: `encode_ai_rml` = `b64decode(prefix)` + `encode(brain)`, patching only `header.tailSize` (offset 8) to `len(region)`.
- **On disk the prefix is a TRAILING XML COMMENT, not a root attribute** (user pref June 2026) — keeps the editable tree clean. `root_to_text()` pops `avx_ai_prefix` off the root and appends `<!-- avx_ai_prefix: <b64> -->` after `</BlackBox.AI>`; `text_to_root()` regex-extracts it (`_AI_PREFIX_COMMENT`) and reattaches it as the attribute before `encode_ai_rml`. ElementTree tolerates a comment after the root element and silently drops it on parse, hence the manual regex. The IN-MEMORY model still uses the `avx_ai_prefix` attribute — only the serialized form differs. **Do not delete the trailing comment** or repack can't be byte-exact. main() and any converter script must go through `root_to_text`/`text_to_root`, not raw `ET.tostring`/`fromstring`.
- **`header.poolSize` (offset 4) is a separate combined-allocation size tied to the prefix** — NOT equal to the brain object's own pool size (coincidentally equal only for `emptybrain`). It is **left untouched**. Consequence: pure round-trips & attribute-VALUE edits are byte-exact, but **structural brain edits are experimental** (the class/path prefix and `header.poolSize` are not regenerated — the game may reject a brain whose node set changed).

**Tests:** `tests/test_convert_avatar_xml.py` — pool-escape threshold (the 0xFE invariant), Dunia round-trip, `.ai.rml` detect + full round-trip + prefix preservation. (gitignored, like the tool.)

### `.ai.rml` prefix REGENERATION (SOLVED June 2026 — enables add/remove/value editing)
Goal: rebuild the opaque prefix purely from the node tree so edits (value + add/remove/rename) repack correctly. **Done** (one minor open item: blob-slice order for byte-exact *new* objects). Spec: `tools/ai_slice_spec.md`; impl: `tools/ai_prefix_regen.py`. Findings:
- **Class-template table = 100% regenerable from the node tree (verified 29/29 byte-exact).** Each addressable object (a direct child of `<BlackBox.AI>` with a `Class` attr — `Brain`/`Plan`/`Task`/`Scanner`/…) compiles to a `<Parameters>` Dunia object:
  - attributes = `Name=" "` (literal space), then `Looping`, `Independent`, then every top-level `<Parameter Name=X Value=Y>` as `X="Y"`.
  - **plus one CHILD element per parameter that has NESTED `<Parameter>` children.** The node tree nests them, e.g. `<Parameter Name="factValue" Value="integer"><Parameter Name="integer" Value="0"/></Parameter>` → child `<factValue integer="0"/>`; ref params nest `RefType`/`RefName` → `<startPos RefType="1" RefName=""/>`. This nested data is the ONLY reason it first looked like "engine knowledge" was needed — it's all in the tree; just traverse nested `<Parameter>`s. (~99% of `(param,value)→child` keys are deterministic; the nested params make it 100%.)
  - entries are **deduplicated by `(crc32(Class), templateBytes)`** keeping first-occurrence order over objects (two objects with identical compiled params but different Class stay distinct — e.g. Brain vs Plan both `Name=" " Looping="1" Independent="0"`). `classCount` == count of unique entries.
  - each entry = `crc32(Class)` (4) + `size` (4) + the `<Parameters>` Dunia object (its own mini string-pool; `C.encode` reproduces it byte-exact).
- **Path/hash table — full layout now mapped (June 2026); only the connection-slice byte-encoding remains.** Structure:
  ```
  [u32 blobSize]                     # size of the metadata blob that follows
  [blobSize bytes: metadata blob]    # each object owns a slice [B : B+C] (B,C from its path record below)
  [u32 valHashCount][N × crc32]      # hashes of referenced VALUES (e.g. the DefaultSelectable filter)
  [u32 recordCount]                  # == number of addressable objects
  [records...]                       # each: crc32(path)(4) + len(4) + path string + trailer[A(4) B(4) C(4)]
  ```
  - Each record's `(B,C)` = `(offset,size)` into the blob; the `(B,C)` slices **tile the entire blob with no gaps** (verified) — so it's fully deterministic. `crc32(path)` = `avatar_crc32` of the object's full `Name` path.
  - **SOLVED via a multi-agent workflow (June 2026).** The full byte-exact spec is in `tools/ai_slice_spec.md` and the implementation in `tools/ai_prefix_regen.py` (both gitignored). `regen_prefix(root, orig_data=d)` reproduces the entire prefix byte-exact on **29/29 files**, and full files (`prefix + C.encode(tail)`) reconstruct byte-exact 29/29 — all **19,675** object connection-slices regenerate exactly. Highlights:
    - **slice header:** root brain = `[0x00][X u16][markerFilterCode u16]` (X = ridx of its first Selectable's Task); headerless orphan (no Add-parent & not a Brain class) = no header; standard = `[0x04][ridx(parent) u16]` where parent is the `<Add>`-tree parent.
    - **membership entries** (container/Brain classes): per qualifying `<Selectable>`, `[0x00][ridx(Task) u16][code(Filter) u16]`.
    - **connection groups:** per source port (`<Anchor>/<Exit>/<Event>/<UserEvent>` with a connection, document order) `[srcType u8][code(portName) u16][connCount u16]` then `connCount × [ridx(Target) u16][code(TargetAnchor) u16][st2 u8]`. `srcType` 1=Anchor 2=Exit 3=Event/UserEvent; `st2` 1=descendant/sibling-clone, 2=other, 6=UserEvent-child.
    - **codes** are indices into the value-hash list: `code(name) = valHashes.index(crc32(name))` (NOT a positional port index — that earlier guess was wrong). `valHashes` = first-occurrence DFS list of crc32 of Selectable Filters + connected port Names + connection TargetAnchors.
    - **records** sorted ascending by `crc32(fullPath)` (this is ridx). `recordCount` == object count exactly (29/29, incl. mercbrain 10836). `header.poolSize = nodeStart − 12`; `tailSize = len(C.encode(tail))`.
  - **ONE open item:** the blob-slice ORDER (the `B` offsets — the order slices are concatenated) and the related `A`-trailer numbering class. All slice CONTENT/length is solved; only the concatenation order isn't a closed formula yet (it's a children-before-parent DFS variant; from-scratch reproduces 1/29). The game addresses each slice by its per-record `(B,C)` so order is almost certainly functionally free; byte-exact-to-original for *brand-new* objects is the only thing it blocks.
- **Integrated into `convert_avatar_xml.encode_ai_rml` (June 2026):** it now REGENERATES the prefix from the edited tree via `ai_prefix_regen.regen_prefix_for_edit(root, orig_prefix)` instead of preserving it verbatim — so edits actually take effect (a preserved prefix would keep stale class templates / connection slices). Order + A are reused from the original prefix (byte-exact when the object set/order is unchanged); add/remove appends new objects via the best-effort derived order (functionally valid). Verified: round-trip 29/29 byte-exact through the converter; value edits propagate into the regenerated prefix; node removal yields a self-consistent re-decodable file. Falls back to preserve-and-patch if `ai_prefix_regen` import fails. **In-game testing of add/remove output is still advisable** (to confirm the engine tolerates non-original blob order / A).

## Native FCB converter — replaced FCBConverter.exe (June 2026)

The editor no longer shells out to **FCBConverter.exe** for FCB↔XML. It uses our native pure-Python converter `tools/fcb_convert.py` (+ `fcb_names.csv`/`fcb_names_cache.pkl` name tables; both gitignored, like the old exe). Native is **faster than the exe** (warm 5.4s vs 16.7s on the 4 test files; the exe reloads its 509k-name list every run, ours memoizes via `fcb_convert.load_names()`), **byte-exact on round-trip** (the exe is not — it can't reproduce the game's dedup), and resolves **more names** (superset table).

**`fcb_convert.py` API:** `fcb_to_xml(data, names=None, defs=None) -> str` and `xml_to_fcb(xml_text) -> bytes`. It reproduces FCBConverter's XML exactly, INCLUDING the structural-field expansions the editor depends on — `hidDescriptor` → `<component class="GraphicComponent"|"GraphicKitComponent">` / `<object>/<resource>/<skeleton>/<slot>/<part>` (read by `canvas/model_loader.py`, `map_canvas_gpu.py`, `game_paths_config.py` for 3D model paths) and Array fields (`<Point>`, color arrays). Byte-exactness is preserved via a hidden `__rawhex` attribute + a leading `<!--fcb_meta ...-->` comment (header counts + dedup decision stream). **Edit-safe:** when the XML tree is edited (entities added/removed) the stale dedup is discarded and it fresh-encodes a valid FCB (verified).

**The migration (which files changed):**
- `file_converter.py` — added a module-level native engine: `_native_fcbconvert(cmd)` parses FCBConverter-style CLI args (single file or `-source=`/`-filter=` batch) and converts in-process; `_native_convert_one` writes `<x>.fcb.converted.xml` (FCB→XML) or `<stem>_new.fcb` (XML→FCB, matching the exe's naming). ALL `subprocess.run(FCBConverter…)` sites + the multiprocessing worker now call it. `__init__` force-sets `can_convert_fcb = conversion_enabled = True` (no exe needed). Public method signatures unchanged, so callers are untouched.
- `archetype_library.py` — `ensure_converted_xml()` converts the entitylibrary natively (`converter_exe` arg now ignored; cached `_ARCH_NAMES`).
- `simplified_map_editor.py` — the two entitylibrary `_Worker`s (FCB→XML, XML→FCB) call `_native_fcbconvert`. The `texconv` subprocess (textures) is unrelated — left alone.
- `setup.py` — left as-is: its `tools/*.exe` glob also bundles still-needed `texconv`/`ww2ogg`/`revorb`; FCBConverter.exe is now harmless unused weight (can be dropped from the bundle later for size — the name-table pkl is large, so a trimmed table is the real distribution concern).

**Gotchas:** the editor's many entity parsers (`data_models.py`, `all_in_one_copy_paste.py`, `entity_export_import.py`, …) read FCBConverter's XML format (`<field type="BinHex" value-*>`, `.converted.xml` names) — ours matches that exactly, so they were NOT changed. Name tables load once (memoized) and are shared across modules. Validated: worldsector FCB↔XML byte-exact round-trip through `FileConverter`, entitylibrary EntityPrototype/GraphicComponent xpath resolution, and an entity-removal edit re-encoding to a valid FCB.

## Entitylibrary streaming load — memory + speed (June 2026)

The render path loaded the entitylibrary `.converted.xml` with a full `ET.parse` in THREE places (`canvas/model_loader.py`, `canvas/map_canvas_gpu.py`, `canvas/game_paths_config.py`), each building the whole ElementTree just to extract `{prototype/hidName: model fileName}`. On Tantalus (`sp_drifting_sierra_fm_01`, the biggest map — two stacked levels) that entitylibrary is 3.6 MB FCB → **235 MB XML → ~1.9 GB ElementTree** (517k objects + 1.36M fields, each a Python object). Measured: ~10 s + ~1.9 GB RAM, three times.

Fixed with `model_loader.load_entity_patterns(xml_path)`: **streams** the file via `ET.iterparse(events=('end',))` and `el.clear()`s each `EntityPrototype` after extracting from it — peak RAM ≈ one prototype subtree (~0 MB delta) instead of the whole tree. Verified **byte-identical** output to the old full-parse on every game level (Tantalus, hellsgate 28 MB, etc.; differential test). All three sites call it; it **falls back to the full `ET.parse`** if streaming ever raises, so it cannot regress. `_entity_patterns_from_protos(protos)` holds the shared extraction (GraphicComponent first, then GraphicKitComponent overwrites — exact prior semantics).

Why it matters: removes the single biggest per-level memory spike (~1.9 GB → ~0) and is the prerequisite for any 32-bit build (a 32-bit process caps at ~2 GB; the old parse blew past that on Tantalus before any 3D/textures loaded). Also a prereq pattern for slimming the worldsector parses (`data_models.py`, `all_in_one_copy_paste.py`, `mp_spawn_creator.py`) if needed later — though those are the edit/save path, so they're higher-risk and were left alone.

## PyQt6 -> PyQt5 migration + 32-bit build (June 2026)

To support 32-bit Windows (PyQt6 ships no 32-bit wheels; PyQt5 does), the whole app moved from PyQt6 to PyQt5 (PyQt5 runs fine on 64-bit too, so it's one framework for both arches — same model as the AVATAR Save Editor). 26 app modules + setup.py converted: import prefixes PyQt6->PyQt5; relocated classes (QAction/QActionGroup/QShortcut QtGui->QtWidgets, QOpenGLWidget QtOpenGLWidgets->QtWidgets, QOpenGL buffer/shader/FBO QtOpenGL->QtGui); ~312 enums de-scoped to PyQt5's flat form (Qt.AlignmentFlag.AlignCenter -> Qt.AlignCenter, QFont.Weight.Bold -> QFont.Bold, etc.). `.exec()` left as-is (PyQt5 >=5.11 supports it). Validated headlessly: 26/26 modules import under PyQt5 (QT_QPA_PLATFORM=offscreen), 0 residual PyQt6 refs in tracked code, and an attribute-existence harness resolved 787 `Class.Leaf` Qt references with 0 missing. GUI behavior (3D viewport rendering, dialogs, menus, picking, textures) is NOT headless-verifiable -- the user must click-test. Test/tool files under the gitignored tests/, functional_tests/, tools/ still import PyQt6 but are not part of the shipped app.

setup.py is now arch-aware: `build_exe` resolves to `build/Avatar_Level_Editor_x64` or `_x86` from `sys.maxsize`, so a 32-bit build never overwrites the 64-bit one. Plugin source paths resolve PyQt5/Qt5/plugins (with PyQt5/Qt fallback) for platforms+imageformats; the post-build DLL strip keeps Qt5OpenGL.dll (needed by the 3D viewport). requirements.txt pins `numpy<2.0` (numpy 2.x dropped 32-bit wheels). `build_both_versions.bat` runs `python setup.py build` then `py -3-32 setup.py build` -- the 32-bit Python needs its own `py -3-32 -m pip install -r requirements.txt` first.

### PyQt5 runtime fix: event positions (QMouseEvent.position)

The PyQt6->PyQt5 migration was import- and enum-validated headlessly but could not exercise event-handler method calls. First GUI run crashed on mouse interaction: `'QMouseEvent' object has no attribute 'position'`. In Qt6 mouse/wheel events expose `position()`/`globalPosition()` (QPointF); in PyQt5 5.15 **QMouseEvent** has `localPos()`/`globalPos()` (not `position()`), while **QWheelEvent** DOES still have `position()`/`globalPosition()`. Fix: across the 8 GUI files, `event.position()` -> `event.localPos()` (43 sites, QPointF preserved so `.x()/.y()/.toPoint()` still work) and `event.globalPosition().toPoint()` -> `event.globalPos()` (3 context-menu sites). Left untouched: the one `event.position()` inside `terrain_editor_dialog.wheelEvent` (line 439 — valid on QWheelEvent), and `QTextCursor.position()` in entity_editor (not an event). Swept for other PyQt6-only runtime APIs (QFontDatabase static-vs-instance, QDesktopWidget, drag/drop `.position()`, `.exec_`) — none present. Lesson: after a Qt major-version migration, grep for event `.position()/.globalPosition()` method calls, not just imports/enums.

### PyQt5 fix: QPainter-on-QOpenGLWidget needs clean GL state (2D blank / 3D crash)

After the PyQt5 migration the canvas went blank in 2D and hard-crashed entering 3D. faulthandler pinned the 3D crash to a `Windows fatal exception: access violation` inside `painter.drawText` (`_draw_3d_ui_overlays`, map_canvas_gpu:4022) reached from `paintGL`. Root cause (one bug, both symptoms): the canvas does custom raw-GL rendering and THEN draws overlays/2D entities with `QPainter(self)` on the `QOpenGLWidget`. Our GL leaves a shader program / VAO / buffers / custom FBO / textures bound; PyQt5's QPainter GL paint-engine assumes a clean default state, so `drawText` access-violates (3D) and nothing composites (2D). PyQt6 tolerated the dirty state. Fix: `_reset_gl_state_for_qpainter()` rebinds `defaultFramebufferObject()` and unbinds program(0)/VAO(0)/buffers/textures + disables depth/cull, called immediately before every `QPainter(self)` on the canvas (the 2D path and the 3D HUD path). NOTE: with `OpenGL.ERROR_CHECKING=False` (the perf fast-path in main.py) a bad GL/interop state surfaces as a native segfault, not a Python exception — set `OPENGL_DEBUG=1` to convert such crashes into catchable tracebacks while debugging. Lesson: any module mixing raw GL with QPainter on a QOpenGLWidget must reset GL state first under PyQt5.

### PyQt5 fix: QWheelEvent uses position(), not localPos()

The previous event-position pass converted ALL `event.position()` -> `event.localPos()`, but that only protected methods literally named `wheelEvent`. Wheel events also flow through HELPER methods: `map_canvas wheelEvent -> input_handler.handle_wheel -> camera_controller.handle_wheel_zoom_2d`. The last one reads the event position and got wrongly converted, so 2D wheel-zoom crashed: `'QWheelEvent' object has no attribute 'localPos'`. In PyQt5 the two event types are MIRROR opposites: QMouseEvent has localPos() (not position()); QWheelEvent has position() (not localPos()). Fix: `camera_controller.py:175` back to `event.position()`. It is the only wheel-event-position site (the 3D branch of wheelEvent does nothing; map_canvas wheelEvent only delegates). Lesson: when fixing Qt event-position APIs, classify by the actual event TYPE reaching each method (follow the call chain), not by the method name.

### 3D gizmo-drag didn't move the rendered model (ghost) — missing position-cache refresh

In 3D edit mode, dragging an entity's gizmo showed a moving "ghost" but the actual model stayed put and vanished on release. Cause: `gizmo_3d._drag_translate` / `_drag_translate_xy` updated `ent.x/y/z` + XML + managers but never refreshed the cached `_positions_3d` array that the GPU-driven renderer and frustum culler draw from. `mark_entity_modified` only refreshes rotation/scale GDR rows; position-only moves are "covered by invalidate_position_cache" (the path keyboard-move and 2D-drag already use). The gizmo drag omitted it, so the baked mesh stayed at the old spot and the inconsistent partial refresh on release culled/dropped it. Fix: both 3D drag methods now call `canvas.invalidate_position_cache()` after updating positions, mirroring keyboard-move. NOTE: pre-existing gap from the GPU-driven renderer work, not a PyQt5 regression. If per-frame rebuild proves heavy on huge maps, switch to the lighter `patch_preview_positions({id:(x,y,z)})` fast path (but verify it also refreshes GDR modelled-mesh rows, not just marker/cull arrays).

## World Editor — in-editor `.game.xml` (WorldDescriptor) editing (July 2026)

New `world_editor.py` (`Tools ▸ 🌍 World Editor…`, `open_world_editor` in simplified_map_editor) edits a level's `<name>.game.xml` — the WorldDescriptor — in-app, no external tools. The dialog reuses the entity-editor style (dark theme, scroll area, per-tab search, debounced auto-save, `.bak` on first save). Tabs map the file's four top-level sections: `<Environment>` (Environment), `<Layers>` (Terrain Layers), `<Grids>` (Grids), `<MissionsDef>` (Missions), plus a raw-XML tab. Both games.

**Key format finding — the two games ship `.game.xml` differently.** Avatar's unpacked data folder has `.game.xml` as **plain UTF-8 text** (BOM + `<WorldDescriptor>`, ~107 elems) that the engine reads directly (verified on disk + in the decompile). Far Cry 2 ships `.game.xml` as the **compiled Dunia binary-XML** (`00 00` header). There is NO `.game.fcb` — the WorldDescriptor is never FCB. So the editor auto-detects: if bytes start with `\x00\x00` (or `is_ai_rml`), decode/encode via `tools/convert_avatar_xml.py`'s `decode()/encode()` (pure-Python, imported lazily via `_codec()`); otherwise parse/write text. `self._binary` tracks which, and `save()` re-emits the matching form. `convert_avatar_xml.decode()` adds a synthetic `avx_type` metadata attr (in `_META_ATTRS`) that `encode()` strips — the UI hides those attrs.

**Environment preset slots.** Slots like `SkyA/Sun/Lighting/Fog/Wind/Cloud/AdaptiveBloom/DepthOfField/AtmosphericScattering` hold a GUID that is a foreign key into the sibling `<name>.managers.xml` DataBaseItemManager (each `Template` = `text_Template` GUID + `text_NameId` + `text_hid_DTCTH_ClassName` like `CEnvironmentSky`). `_read_manager_presets()` streams managers.xml into `{class: [(nameid, guid)]}`; each slot renders as a **dropdown of that class's presets** (name shown, GUID stored) instead of a raw GUID. `SLOT_CLASS` maps slot attr name → CEnvironment class. CRITICAL: only render a dropdown when the attr name is a known slot AND the value is a GUID — otherwise Mission `GUID=` / layer-id GUIDs get turned into 400-item catalog combos (bug caught in testing). Non-GUID slot values (biome blocks store class-name literals like `Lighting="CEnvironmentLighting"`) fall through to a text field. Avatar splits slots across `<Corp>`/`<Avatar>` (RDA vs Na'vi look) child elements; FC2 has no Corp/Avatar — slots sit directly on `<Environment>`. Same SLOT_CLASS names cover both.

**Value handling:** all attribute values are kept as strings (never numerically coerced) so forms like `Start="500.0f"` (trailing `f`) and `Color="200,219,230"` survive round-trip. Special widgets: `r,g,b` → color swatch/picker; known 0/1 bool attrs → checkbox; else QLineEdit. Text saves write BOM+UTF-8 with no `<?xml?>` decl (matches the game's own files). `ET.indent`'s whitespace is harmless to binary `encode()` (it ignores element text/tail). Phase-2+ ideas (not built): live 3D preview from preset curves, editing preset params in managers.fcb, duplicate/create presets (needs GUID `ComputeHash32`).

**Global preset catalog (use presets from any map).** `tools/build_env_preset_catalog.py` scans every converted `<map>.managers.xml` across both games (use `os.walk`, NOT `glob **` — FC2's data lives under a `...MODDING` dot-directory that `glob` skips) and extracts every `CEnvironment*` Template (name+GUID+class+which maps define it), deduped by GUID, into `env_preset_catalog.json` at the repo root (`{categories: {class: [{name,guid,game,maps}]}, stats}`). Current build: 52 maps → 488 presets (50 Sky, 95 Fog, 93 Lighting, …). The World Editor loads it (`_preset_catalog()`) and each slot dropdown lists LOCAL presets (from this map's managers, resolve in-game now) first, then a divider, then every same-class preset from OTHER maps, labelled `name · sourceMap`. NOTE: Avatar and FC2 SHARE GUIDs for engine-default presets (e.g. `Default.Clear.Sky` `{1899F900-…}` appears in 47 maps across both games) — so `game` is just the first map that defined it; `maps` is the source of truth. Choosing a cross-map preset only writes the GUID; the World Editor's "⤵ Import used presets" button then copies the actual preset into this map's managers (see next).

**Cross-map preset import (`env_preset_copy.py`).** The World Editor header button **"⤵ Import used presets"** (`_sync_presets`) scans the Environment for GUIDs that are cross-map (in the catalog, not in the local managers), copies each preset's `<object name="Template">` subtree out of its source map's managers.xml into this map's DataBaseItemManager `<object name="Templates">` container, writes managers.xml, and rebuilds `managers.fcb`. A preset is a self-contained `Template` object (text_NameId + text_Template GUID + Template hash companion + nested Template class/knots), so copying is a subtree move. FCB rebuild uses `fcb_convert.xml_to_fcb`: its normal path replays a byte-exact **dedup decision stream** from a leading `<!--fcb_meta-->` comment that is tied to the ORIGINAL tree and CANNOT survive an edit — but `ET.tostring` drops the comment, so `xml_to_fcb` falls back to **encoding the modified tree from scratch** (valid, not byte-identical; the game reads it fine). Verified end-to-end: added a cross-map sky, rebuilt managers.fcb (~3 MB), reads back with the new GUID. `.bak` kept for managers.xml + .fcb. `fcb_convert` lives in the gitignored `tools/`; `_rebuild_fcb` adds `tools/` to sys.path.

**Terrain Layer XBT thumbnails.** Each `<Layer>` in the Terrain Layers tab shows live thumbnails of its `Texture` (diffuse), `NormalMap`, `SpecularMap`, `HeightMap` XBT files (`_build_layer_previews`, `_THUMB_PX=96`). The layer stores an engine-relative path like `graphics\...\rf_fernground_d.xbt`; `_resolve_texture()` finds it on disk by trying the canvas' `game_data_path`/`patch_folder`/`worlds_folder` then every ancestor of the .game.xml (Avatar resolves under `<data>/graphics/…`, FC2 under its own root — both worked). Decoding reuses `canvas.texture_loader.TextureLoader.decode_xbt_to_rgba(path, is_normal_map=…)` (XBT→DDS→PIL→RGBA, its own 32-entry cache, DXT5-GA unpack for normals), wrapped to a `QImage(Format_RGBA8888)`→scaled `QPixmap`; results cached in `self._thumb_cache` keyed `(rel, is_normal, size)` so tab rebuilds are instant. Editing a texture path live-refreshes its thumb via a 400 ms debounce (`_wire_texture_live`). Unresolved paths show a "not found" placeholder. NOTE: `TextureLoader.__init__` requires a `materials_path` but `decode_xbt_to_rgba` doesn't use it — we pass a best-effort `<root>/graphics/_materials`.

## In-game terrain texturing — splat-blended detail, 2D + 3D (July 2026)

Both the 2D map and the 3D viewport previously showed the flat baked *diffuse*
atlas per sector. They now composite the in-game look via the shared
`canvas/terrain_blend.py`: per sector, sample the `atlas*_mask` splat (RGB weights,
partition-of-unity), blend the first 3 `<Layers>` detail textures tiled by each
layer's `Tiling`, and modulate the baked diffuse (the game's own low-freq colour
anchor), so large-scale colour stays correct while high-freq tiled detail is added:
`out = diffuse * ((1-s) + s*detail/mean(detail))`, s=`DEFAULT_DETAIL_STRENGTH` 0.85.
`build_sector_tile(sdat_dir, atlas_num, sub_sector, layers, out_size, cache)` reads
`atlas{N}_{diffuse,mask,color}.xbt` from the sdat and composites one quadrant;
`load_layers(game_xml, data_roots)` pulls the detail textures from the map's
.game.xml (text or FC2-binary via convert_avatar_xml) resolved against data roots.

- **2D** (`terrain_renderer`): `set_blend_source(game_xml, data_roots)` + a bump from
  the 65px heightmap grid to `texture_tile_px=160` per sector in
  `_generate_terrain_image_textured` (terrain_pixmap is display-only, drawn scaled to
  world coords, so pixel res is decoupled — safe). Falls back to the diffuse quadrant
  on any error.
- **3D** (`terrain_to_gltf`): `TerrainExporter(..., blend_game_xml, blend_data_roots)`;
  `load_sector_texture` returns the composited tile and `create_combined_texture` bakes
  at `texture_tile_px` (160) instead of grid_size. UVs are 0..1 across the mesh so
  higher texel count needs NO geometry/UV/shader change — the existing single-diffuse
  fixed-function path just gets a detailed baked atlas. `generate_terrain_for_level`
  uses a fresh temp dir each call (no stale cache), so edits always re-bake.
- **Wiring**: editor `_apply_terrain_blend()` resolves the level's .game.xml
  (`_find_game_xml`) + data roots (`_terrain_data_roots`: game_data_path + worlds_folder
  ancestors — Avatar textures under `<data>/graphics`, FC2 under its own root), calls
  `terrain_renderer.set_blend_source` AND stores `canvas._terrain_blend_source`; the two
  `generate_terrain_for_level` call sites in `map_canvas_gpu` (single + FC2 cell) pass it
  through. Runs before terrain loads so the first bake is already blended.

Both games. Verified headlessly: 2D pixmap 650→1600px, 3D baked texture 650→1600px,
both showing rock along ridgelines + vegetation in flats (splat-driven) vs the old flat
diffuse. GUI look (in the actual 3D viewport) still needs a user click-test.

### Tiling fix — anti-aliased + seamless detail sampling (July 2026)

User feedback: the blended terrain still looked "harsh" even after the softening pass, and asked whether each map's own `Tiling` value was actually being used. Traced `load_layers()` on a map with different numbers (`z_anim_creatures.game.xml`, Tiling 10/20/20) — confirmed it WAS already reading each map's own per-layer values correctly (not a wrong-file or hardcoded-default bug). The real cause: **aliasing**. A real in-game terrain samples the tiled detail texture per-pixel with full GPU mipmapping; our 2D/3D bake is a single static image, so at `Tiling=16-20` repeats crammed into a ~160px sector tile (only ~8-10px per repeat), the old `_tile_sample` used **nearest-neighbour modulo indexing** — it discarded almost all of the source texture's pixels, producing exactly the harsh blotchy pattern reported.

Fix in `canvas/terrain_blend.py._tile_sample`: LANCZOS-downsample the source texture to its **per-repeat output footprint** (`cell = round(size / repeats)` — this is precisely a mip-level average) once, then **mirror-tile** that already band-limited patch across the output (`_mirror_tile`: alternate rows/columns flipped, à la GL_MIRRORED_REPEAT). Two-step reasoning:
1. Prefiltering before tiling = correct box-filtered average per output texel, without the cost of building a huge native-res tiled array (cell is tiny, e.g. 8-30px, so LANCZOS is cheap; `np.tile`/concat of the small cell is cheap).
2. Mirror (not plain wraparound) tiling is required because most of these detail textures are NOT seamless (opposite edges don't match) — plain `np.tile` left a visible **hard grid seam** at every repeat boundary (confirmed visually, spacing matched each layer's own cell size). Mirroring is seamless by construction: flip(A)'s first column always equals A's last column, so every tile boundary is pixel-identical on both sides — proven, not just visually smoother.

Cached per `(id(img), h, w, cell)` in `_TILE_PREFILTER_CACHE` (module-level, capped at 64 entries) since the same layer+Tiling recurs across every sector in one bake — safe because the `layers` list (and its image arrays) stays alive for the whole bake, so `id()` reuse can't happen mid-bake. Full 100-sector 2D bake: 1.3s; 3D bake: 1.1s (no meaningful perf regression). Verified: isolated tiled swatch went from a harsh moiré-like grid to smooth continuous variation; full map crops seam-free at the mirror boundaries (any faint residual banding traces to the underlying baked diffuse/mask atlas's own per-sector data, present before this change, not the tiling fix).

### Layer SELECTION rework — rule-based, not mask-channel-order (July 2026)

User feedback: even with tiling/aliasing fixed, the terrain still looked "layered wrong" — like some textures sat on top of ones that should be underneath. Root cause: `composite_sector` blended only the FIRST 3 `<Layers>` in raw XML document order, treating `atlas*_mask` R/G/B as their weights — a total guess with no evidence it matched the original artist's intent, and it silently dropped every layer past index 2 (mridge alone has 5; FC2 maps can have 44).

**Investigation.** Per user's request, re-mined the Ghidra decompile (`Downloads\Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE\...txt`, 68MB/2.6M lines) for the terrain layer/mask blend algorithm. Findings (Explore agent, exhaustive grep across the full dump):
- `MinSlope`, `MaxSlope`, `AltStart`, `AltEnd`, `ProjAxis`, `Projected`, `UniqueId` appear **zero times** as literal strings anywhere in the retail binary. Only `Tiling` and `SurfaceTypeID` survive into runtime, and both are generic material-layer properties (UV scale; physics/audio surface type) — not terrain-blend logic.
- The terrain shader technique lookup (`FUN_1042c920`, ~line 728131) confirms a max of **4** mask/parallax-driven layer slots (`SPEC_MASK_%d_LAYER`/`PARALLAX_%d_LAYER`/`PROJ_AXES_%d_LAYER` for d=1..4, technique name `"Terrain4Layers"`) — but the actual per-pixel blend math is compiled GPU shader bytecode, invisible to a CPU decompiler, so channel-to-layer mapping and blend priority are NOT recoverable from this artifact.
- **Conclusion (high confidence):** slope/altitude/projection rules are bake-time-ONLY — evaluated once by the original exporter to decide which layer wins each texel, baked into the mask/diffuse atlas, and never touched again at runtime. This means the "correct" channel↔layer mapping is lost information (the retail binary doesn't have it either) — but the RULES the exporter used are still sitting right there in the map's own `.game.xml`, and we have the map's own real heightmap. So instead of guessing the mapping, `terrain_blend.py` now reconstructs the same bake-time decision the original exporter made.

**New model (`rule_weights()` in `canvas/terrain_blend.py`).** Per sector, per output texel:
1. Compute real **slope** (degrees, via `np.gradient` on the heightmap in world meters — `meters_per_step` read from `<Grids><GridMapSectors Granularity=.../>` via `load_meters_per_step()`, falling back to 1.0 for the common Granularity=64/grid_size=65 case) and **altitude** (heightmap value normalised 0-255 against the WHOLE MAP's height range via `compute_height_range()` — not per-sector, since AltStart/AltEnd read like map-global calibration, e.g. `AltStart=0,AltEnd=0` on `Underwater_Z` clearly means "only at the map's lowest points").
2. For every layer (ALL of them now, not capped at 3 — up to `DEFAULT_MAX_LAYERS=12`, since we're no longer limited by mask channel count), gate its weight by `_smooth_gate()`: a soft step across `[MinSlope,MaxSlope]` and `[AltStart,AltEnd]`, feathered wider for `Smooth="1"` layers and narrower for `Smooth="0"` (cliffs cut in faster). A bound at the natural extreme (`MinSlope<=0`, `MaxSlope>=90`, etc.) means "no gate on that side."
3. **The mask is still needed** for layers whose rule is fully unrestricted (applies everywhere — e.g. mridge's `Default` and `Deadleaves` both have `MinSlope=0,MaxSlope=90,AltStart=0,AltEnd=255`, so rules alone cannot tell them apart). For that subgroup ONLY, `_layer_is_unrestricted()` flags them and the mask's R/G/B channels (in order) tie-break just those — capped at 3 (the mask's real information limit: `unrestricted[3:]` get zeroed rather than left at an uninformed flat weight, which would otherwise blend arbitrary extra layers in everywhere — this specifically matters for maps like FC2's `world1` where ALL 12 loaded layers are unrestricted).
4. All layer weights normalise together (sum to 1 per texel) in `composite_sector`; a texel matching nothing (shouldn't happen) falls back to the first/base layer. Layers whose weight is zero everywhere in a sector are skipped (`wi.max() <= 1e-4`), saving their tile-sample cost.

**API changes:** `load_layers()` now returns up to `DEFAULT_MAX_LAYERS=12` layers (was 3) with rule fields (`min_slope/max_slope/alt_start/alt_end/smooth`); unresolvable textures are dropped (not kept as alignment placeholders — no channel alignment to preserve anymore). New `load_meters_per_step()`, `compute_height_range()`, `rule_weights()`. `composite_sector`/`build_sector_tile` gained `heightmap=`/`world_min_h=`/`world_max_h=`/`meters_per_step=` kwargs; both renderers (`terrain_renderer._generate_terrain_image_textured`, `terrain_to_gltf.load_sector_texture`) now pass the sector's real heightmap array (`self.sectors_data[...]`, already loaded for the heightmap mesh) and the map-wide height range (computed once via `compute_height_range(sectors_data.values())`). Without a heightmap the old 3-channel mask-order path still runs as a defensive fallback (dead in practice — both callers always supply one).

**Verified:** mridge Rock_X weight map spatially matches the real slope map pixel-for-pixel (steep ridgelines only — visually confirmed side-by-side); Underwater_Z only activates near the map's lowest points; full 2D/3D re-bakes at mridge show coherent rock-on-ridges + a newly-visible Deadleaves tint in valleys (previously invisible, since it was outside the old 3-layer cap). FC2's `world1` (12 layers loaded, ALL rule-unrestricted) renders a coherent multi-biome map (river system, urban compound, roads, distinct jungle/mud/grass regions) instead of a flat blend. Performance unaffected: mridge 2D 1.4s / 3D 1.2s, FC2 2D (5x5 cell, 2560px) 4.0s.

**Known limitation (inherent to the data, not fixable from what we have):** for maps where MORE than 3 layers share an identical unrestricted rule, only 3 can be spatially distinguished (the mask's hard limit) — the rest are dropped rather than guessed. This is a real information ceiling, not a bug; the alternative (blending them in blindly) was empirically worse (see FC2 fix above).

### Dark spots / bad blending fix — self-normalized layers + a real brightness bug (July 2026)

User feedback: still darker patches and imperfect blending in both 2D and 3D after the rule-based rework. Two distinct bugs, both fixed in `canvas/terrain_blend.py`:

1. **Dead tuning constants — the real root cause of most of the darkness.** `DEFAULT_DETAIL_STRENGTH`/`DEFAULT_BRIGHTNESS` were defined at module scope and referenced only in comments/docs — `composite_sector`'s actual parameter defaults were separate hardcoded literals (`detail_strength=0.8, brightness=1.0`) that no caller ever overrode. Every "softening" tuning pass earlier in this session (0.85→0.55 detail strength, 1.2→1.1 brightness) silently never took effect in the real render path — only in my own test scripts, which passed the values explicitly and thus looked fine, giving false confidence. Fixed by making the constants the actual parameter defaults (`detail_strength=DEFAULT_DETAIL_STRENGTH, brightness=DEFAULT_BRIGHTNESS`) — single source of truth, no separate call-site wiring needed.

2. **Cross-layer darkening from a shared global mean.** The old detail-modulation divided the WEIGHTED SUM of all blended layers by ONE shared mean computed over the whole tile (`dmean = detail.mean()`). Wherever a locally darker layer (e.g. a rock cliff patch) sat in an otherwise much lighter tile (mostly grass), it was being compared against the brighter grass-dominated average and got crushed toward the 0.5 clamp floor — an artificial extra darkening exactly at layer boundaries, which read as "harsh"/"not blended". Fixed: each layer's sampled tile is now normalised to **its own mean** before weighting and summing (`tile / tile_mean`, each contributing an ~1.0-mean signal), so a layer's brightness is judged on its own texture, not its neighbours'. The final clamp (`np.clip(detail, 0.5, 1.6)`) now applies directly to this well-behaved weighted sum — the old outer `/dmean` step is gone entirely.

3. **The baked diffuse atlas is fundamentally dim** — measured mean ~(28,32,20)/255 (~11%) on real Avatar and FC2 atlases alike, almost certainly an unlit albedo reference meant to be relit by the engine's dynamic sun/sky pass in 3D. Neither our 2D map (no lighting at all) nor the 3D bake's raw texture bytes (lighting is applied later, per-vertex, by the existing fixed-function GL rig — not baked into the texture) compensate for that on their own. Measured several fixed multipliers directly (`brightness` 1.0→3.2, screenshot comparison) and picked **`DEFAULT_BRIGHTNESS = 2.3`** (raises the ~0.11 mean to a legible ~0.28-0.35) as a flat global constant — deliberately NOT per-sector auto-exposure, since that would normalise each sector's mean independently and introduce a visible sector-to-sector brightness checkerboard (a new, worse artifact) instead of one clean tunable number.

Also widened the `Smooth="0"` (cliff) transition feather (slope 1.5°→3.5°, altitude 3→8 units) — the original razor-thin feather made cliff edges look like an abrupt, unblended graphic seam rather than a natural line; still visibly sharper than `Smooth="1"` layers (6°/14), just not near-binary.

**Verified:** re-rendered mridge (2D + 3D) and FC2 world1 after all three fixes — clearly lit, correctly-toned terrain in both games; rock-on-ridges and Deadleaves-in-valleys distinction preserved from the rule-based rework; FC2's multi-biome coloring (river/mud/urban/dry-ground) reads cleanly. No perf regression.

### Brightness overcorrection walked back (July 2026)

Follow-up feedback: 2.3x brightness made the terrain look "too bright... fake" — the ORIGINAL overall exposure (before any of this session's brightness work) was fine; the only real complaint was unevenness between layers (fixed separately by the per-layer self-normalisation above). Root cause of the confusion: because `DEFAULT_DETAIL_STRENGTH`/`DEFAULT_BRIGHTNESS` were dead constants (see previous section), the look the user had approved of was actually produced by `composite_sector`'s old hardcoded literals — `detail_strength=0.8, brightness=1.0` — not by any of the tuning values documented earlier in this file. Reverted `DEFAULT_DETAIL_STRENGTH`/`DEFAULT_BRIGHTNESS` to `0.8`/`1.0` to match that actual approved baseline, keeping ONLY the per-layer self-normalisation fix (which doesn't change overall exposure, just removes the boundary-crushing artifact). Verified: mridge 2D/3D and FC2 world1 all re-rendered at the original moodier tone with no visible unevenness at layer boundaries.

**Lesson for future tuning passes on this file:** always verify a "tunable" constant is actually read by the function that matters (`grep` the call site, don't just trust the module-level docstring/comment) before treating a re-render as validation of the new value — this exact mistake (documenting and testing a value that a real call site never received) cost two extra round trips in this session.

### Visible tiling pattern fixed — mirror-tiling kaleidoscope symmetry (July 2026)

User feedback: "I can see a pattern in the terrain" in both 2D and 3D, and asked me to check whether we're using the whole `<Layers>` section of the .game.xml. Confirmed via raw XML dump that we already use every real attribute present (no `Opacity`/`Blend`/`Weight`/`Alpha` attribute exists anywhere in a `.game.xml` — `<Terrain DetailViewDistanceScale>` is an LOD setting, `<Color Name="Global">` in `<Layers>` carries no extra data) — so the pattern wasn't a missing-data problem.

Reproduced it directly by rendering one layer's `_tile_sample()` output in isolation at high zoom: a clearly visible repeating diamond/kaleidoscope grid. Root cause, found in two steps:
1. First suspected LANCZOS ringing (the sinc filter can ring when collapsing a real texture ~256px → ~10-40px per repeat cell) — switched the prefilter to `Image.BOX` (true area average, cannot ring). The pattern was fainter but **still clearly visible** — proving ringing wasn't the (only) cause.
2. The real cause: **mirror-tiling itself is structurally periodic.** `_mirror_tile`'s seamlessness guarantee depends on STRICTLY ALTERNATING flip states between neighbouring cells (that alternation is the only way two adjacent copies' shared edge can match without also matching the source's own opposite edges) — there is no way to keep mirror-tiling seamless without that alternation. But strict alternation means every 2×2 group of tiles is exactly mirror-symmetric about its center, and bilateral symmetry is one of the most perceptually salient patterns to the human visual system — visible regardless of how much real detail is inside each tile.

**Fix — replaced mirror-tiling with a proper "make seamless" texture prep + plain tiling:**
- `_feather_seam_edges()`: cross-fades each swatch's outer margin (default 15%) toward the AVERAGE of its two opposite edges (left↔right, then top↔bottom), so the two edge columns/rows converge to nearly the same value right at the tile boundary — the classic "make seamless" texture trick, done directly on the edges (no need to roll the image and fix a moved center seam, since we can blend the true edges directly).
- `_plain_tile()`: `np.tile` (true wraparound, no mirroring) of the now-edge-matched swatch — since the swatch's own edges already agree, plain tiling shows no seam AND, critically, no forced symmetry between neighbours (each repeat is identical, not alternately mirrored) — the difference between "looks like repeated real texture" (acceptable, expected even in real games at extreme close-up) and "looks like wallpaper" (kaleidoscope symmetry, definitely not expected).
- Also floored the prefilter swatch size at `_MIN_TILE_SWATCH_PX=64` (kept from the earlier pattern-diagnosis pass): collapsing all the way down to one blob per nominal repeat homogenises away all texture grain regardless of tiling method, so very high `Tiling` values now show fewer, larger, more detailed repeats than the nominal count — a deliberate trade-off for "looks like real ground" over exact repeat-count fidelity.

Verified: isolated boosted-brightness crops before/after show the kaleidoscope symmetry is gone, replaced by organic-looking grain; full mridge (2D+3D) and FC2 world1 re-renders show no perceptible pattern at map scale. No perf regression (bake times back to the earlier ~1.4-1.8s / ~5-7s baselines; the one 4.8s reading was noise, not caused by this change — confirmed by re-running).

### Swatch floor dialed back down — "spots too rough looking" (July 2026)

Follow-up feedback after the tiling-pattern fix: some spots now looked "too rough." Cause: `_MIN_TILE_SWATCH_PX` (floored to prevent the earlier collapse-to-blob pattern) was left at `64`, inherited unchanged from the mirror-tiling diagnosis pass. At production tile size (~160px/sector), flooring the swatch that high meant high-`Tiling` layers only fit 2-3 repeats across a sector instead of their nominal count — each repeat is correspondingly much LARGER, so the texture's natural grain reads as big blotchy/chunky patches rather than fine ground texture.

Swept swatch-floor values (16/24/32/48/64) side by side at production scale: clear trend, larger floor = visibly blotchier/rougher, smaller floor = finer grain. Lowered `_MIN_TILE_SWATCH_PX` to **24** — still well above a naive one-pixel-per-repeat collapse (which is what caused the ORIGINAL aliasing complaint this session started with), but small enough that repeats stay fine-grained at the resolution we actually bake at. The seamless-edge-feathering + plain-tiling fix (previous section) is independent of this floor value and still holds — lowering the floor doesn't reintroduce the mirror-symmetry kaleidoscope, since that was a property of the tiling METHOD, not the swatch size.

Verified: mridge (2D+3D) and FC2 world1 re-rendered — visibly finer, less blotchy texture; no regression of the earlier pattern fix. No perf change (smaller swatch is if anything cheaper to feather).

### Level scanner never paired worlds/ with levels/ for 9 of 10 real Avatar maps (July 2026)

User was walking through a level's folder layout (`z_anim_creatures`: `data\worlds\z_anim_creatures` has the `.game.xml`, `data\levels\z_anim_creatures\generated\sdat` has the terrain atlas/heightmap data) to confirm my understanding — which led to checking whether the editor's level scanner actually pairs these two folders correctly for every map, not just the one being discussed.

**Found a severe, pre-existing bug, unrelated to this session's terrain work.** `analyze_level_structure`'s Pattern-1 matcher (`simplified_map_editor.py`) paired `worlds/<name>` with `levels/<name>` by exact string match only (`worlds_levels.intersection(levels_levels)`). Checked the real folder listing under `ATGE\patch`: **9 of the 10 real Avatar levels name their `levels/` folder with a `_l` suffix** — `worlds/mp_mridge_df_01` pairs with `levels/mp_mridge_df_01_l`, not `levels/mp_mridge_df_01` — including every single-player campaign map (`sp_hellsgate_01`, `sp_bonusmap_01`, `sp_pascal_fm_01`, etc.) and the one multiplayer map. Only test/dev maps like `z_anim_creatures` (the one the user happened to pick as an example) match exactly.

Because of the exact-match requirement, every `_l`-suffixed level showed up as **two separate, permanently-incomplete entries**: one with `worlds_path` set and `levels_path=None` (world/environment data, no terrain), and another with `levels_path` set and `worlds_path=None` (terrain data, no environment) — verified directly by calling `analyze_level_structure` against the real `ATGE\patch` folder (`sme.SimplifiedMapEditor.__new__(...)`, skip `__init__`, since the scanning methods are pure path functions). Neither entry was ever `complete=True`, so **terrain/sdat data never loaded** when a user picked one of these maps through the normal level selector for 9 of 10 real levels — this predates the terrain-blend work earlier in this session (confirmed the `_l`-paired `generated/sdat` folder has real atlas data, 75 files for mridge, that was simply never reached).

**Fix:** `_resolve_levels_name(world_name)` tries the exact name first, then `f"{world_name}_l"`, before giving up. Iterate over `worlds/` names (the canonical "real level" set) and resolve each to its levels/ folder; any leftover `levels/` folder with no matching `worlds/` entry still gets a partial entry (unchanged fallback behavior). Verified: full re-scan of `ATGE\patch` now returns exactly 10 entries (was ~19, with duplicates), zero duplicate names, and `mp_mridge_df_01`/`sp_pascal_fm_01`/`sp_pascal_rf04`/`sp_sebastien_rb_02`/`z_dev_orouleau`/`z_anim_creatures` all correctly `complete=True`. The remaining `complete=False` maps (`sp_bonusmap_01`, `sp_gravesbog_rb_of_01`, `sp_hellsgate_01`, `sp_plainsofgoliath_of_fm_01`) are NOT a matching bug — checked their `worlds/<name>/generated/` folders directly and they genuinely only contain a bare `.game.xml` (no `mapsdata`/`managers`/`omnis`/`sectorsdep` files at all), which `validate_worlds_folder` correctly flags as incomplete data — that's accurate reporting of stripped-down/unused map data, not something to "fix".

### Multi-variant tiling — residual "not tiled correct" roughness after the swatch-floor tune (July 2026)

Follow-up feedback: some spots STILL looked "too rough... not tiled correct" after lowering the swatch floor to 24. Investigated with production-scale renders (not isolated debug crops) and found the swatch floor wasn't the (whole) story: `Rock_X`'s NATIVE cell size (Tiling=6 → `round(160/6)=27px`) is already ABOVE the 24px floor, so it was untouched by that fix — yet still showed an obvious repeating pattern zoomed in. Confirmed via a smooth (non-distorting) LANCZOS zoom that this wasn't a viewing artifact: with only ~6 repeats across a sector, ANY single swatch tiled identically 6 times is inherently perceptible as tiling to the human eye — bumping resolution (tried 160→256→320px) made each repeat sharper but did NOT reduce the countable repeat structure, confirming resolution alone can't fix a low-repeat-count problem.

**Fix — multiple swatch variants instead of one, non-alternating placement.** Sourced `_NUM_TILE_VARIANTS=6` swatches from DIFFERENT roll-offset crops of the same source texture (genuine spatial variation, not just re-filtering the same content), assigned to the tile grid via a fixed hash of `(row,col)` (`_variant_tile` — NOT alternating/checkerboard, to avoid reintroducing the earlier mirror-tiling kaleidoscope-symmetry problem). Correctness subtlety that had to be fixed: `_feather_seam_edges` previously blended each swatch toward ITS OWN left/right and top/bottom average — fine for one swatch, but for multiple DIFFERENT-crop variants their own averages differ (different crop = different average brightness/colour), so two adjacent DIFFERENT variants would NOT actually match at the border. Extended `_feather_seam_edges` with optional `h_target`/`v_target` (shared per-row/per-column edge profiles, computed once from variant 0 and passed to every variant) so ALL variants converge to the SAME edge values — any pair can now sit adjacent seamlessly. Swept variant counts (1/3/6/9) side by side: 1→3 already broke up the worst uniformity, 3→6 added meaningfully more organic variety, 6→9 was diminishing returns; 6 is the balance point. Falls back to a single variant (`_plain_tile`) when the source is too small to usefully crop (`min(h,w) < cell*2`).

**Honest limitation, not fully solved:** this is a genuine improvement (breaks "one tile repeated in a perfect grid" into "a non-periodic mix of a few tiles"), but it does NOT eliminate all visible repetition — a real in-game terrain samples the tiled texture per-pixel with live GPU mipmapping across a mesh the camera is never viewing edge-to-edge in one glance; our 2D map and 3D bake are a single STATIC flat image per sector, which is a fundamentally different representation with a real ceiling on how much a baked approach can hide repetition at low Tiling values (like Rock's 6). The definitive fix for the 3D viewport specifically would be a real terrain GLSL shader doing live per-pixel `uv * Tiling` sampling with GPU wrap/mipmap (identified as a real option during the earlier decompile investigation into `Terrain4Layers`) — not attempted here; current terrain is still drawn through the fixed-function pipeline with one baked texture. Flagged for the user as a bigger follow-up if true game-fidelity tiling is wanted, distinct from the baked-preview improvements made this session.

Verified: mridge (2D+3D) and FC2 world1 re-baked with no perf regression (mridge 2D 1.6s, 3D 2.1s; FC2 5×5-cell 2D 7.2s).

### .csdat byte investigation — real per-vertex normal data found; Rock_X/Rock_Y triplanar fix (July 2026)

User asked for a deep investigation into how terrain texturing actually works, specifically: (1) whether the mask R/G/B channels map to `<Layers>` by simple document order with black = an unlisted default texture, and (2) what the UNUSED second half of each terrain sample in `.csdat` files contains — described as an incomplete normal map plus something with an "elevation warping... like waves on a beach" quality.

**Confirmed a real, previously-unexamined data field.** `_load_single_sector` (`canvas/terrain_renderer.py`) reads a 65×65 grid of terrain samples at a fixed offset (708 Avatar / 592 FC2), 16900 bytes = 65×65×**4** — i.e. **4 bytes per sample**, but the loader only ever used bytes[0:2] (packed uint16 LE /128 = height in meters) and silently discarded bytes[2:4]. Dumped bytes[2] and bytes[3] directly from a real sector (`sd0.csdat`, mp_mridge) and tested them against a heightmap-derived tangent-space normal (`N = normalize(-dHeight/dx, -dHeight/dy, 1)`, standard `(v*0.5+0.5)*255` encoding):

- **byte[2] vs the predicted normal X component: correlation 0.979, mean absolute error 5.8 (on a 0-255 scale).** This is essentially an exact match — byte[2] IS the encoded X component of the real per-vertex surface normal the original exporter computed and shipped in the file.
- **byte[3]** correlates with slope/height (−0.73 / −0.45) and its contour pattern visually matches the slope map closely, but does NOT cleanly match Y or Z of the same normal under any axis/sign/gradient-step variant tested (best fit: Z-ish, corr 0.708, but with much higher error, and a histogram concentrated in only 36 distinct low values 0-102 vs byte[2]'s smooth 250-value spread) — **not solved**. Given the "waves on a beach" description, it may be a warp/blend weight or a different quantity entirely, not a plain normal component; needs more investigation (a good next probe: check other sectors/maps for whether byte[3]'s value range and distribution shape are consistent, and cross-reference against the decompile for any per-vertex struct near the terrain-sample reader).

**Concrete, actionable fix that came out of this.** `Rock_X` and `Rock_Y` (mridge) share an IDENTICAL slope/altitude rule (`MinSlope=55,MaxSlope=90`) and the SAME texture — they differ only in `ProjAxis` (0 vs 1, i.e. X-facing vs Y-facing cliff UV projection; confirmed via `grep ProjAxis` — the map's 5 layers are exactly 1×ProjAxis=0, 1×ProjAxis=1, 3×ProjAxis=2). These are triplanar-mapping siblings (the standard technique of projecting the same cliff texture along whichever world axis a steep face predominantly points, to avoid stretching) — NOT two independently mask-competing layers. The rule-based compositor (before this fix) gave both layers the exact same weight wherever the shared slope rule matched (since neither is "unrestricted", they never got the mask tie-break either), so they were blended ~50/50 everywhere both were active — mixing two different UV orientations of the same rock texture, which reads as blurry/incoherent rather than a clean cliff face — a real, now-fixed contributor to the "rough/not tiled correct" reports.

`rule_weights()` now detects sibling pairs sharing an identical `(min_slope,max_slope,alt_start,alt_end)` key with `ProjAxis` 0 and 1, and SPLITS their shared gate weight by which axis the local surface normal actually faces more (`|nx|/(|nx|+|ny|)` using the same heightmap-gradient normal validated against the real byte[2] data above — so this normal computation is now empirically grounded, not just a heuristic). `load_layers()` gained a `proj_axis` field. Verified: Rock_X's mean weight in a test sector went 0.271→0.124, Rock_Y 0.271→0.157 (same total steep-area coverage, now split instead of doubled-up); full re-bakes (mridge 2D/3D, FC2 world1) show no regression.

**On the R/G/B-document-order + black=default hypothesis:** checked the mask atlas directly — genuine near-black (R,G,B all <10) pixels exist (~5% of a sampled quadrant), consistent with a "default when black" mechanism existing. Did not find direct pixel-level correlation between mask R/G/B and csdat byte[2]/byte[3] in this same test (near-zero correlations both ways) — but that test aligned a 64×64 mask crop to a 65×65 heightmap grid via a naive resize with no confirmed coordinate-system match (rotation/flip/origin), so this is inconclusive, not a refutation. The current implementation still uses the rule-based (slope/altitude) layer-selection approach documented above (not raw document-order mask channels) since the Ghidra decompile confirmed those rules are bake-time-only and the mapping itself is genuinely unrecoverable from the retail binary — the rule-based approach remains the best-grounded reconstruction available, now improved by the triplanar fix. Revisiting the document-order hypothesis with a properly coordinate-aligned mask-vs-csdat comparison is a good next step if more texture accuracy is wanted.

### "Some sectors good, some bad" investigation — correlates with rock/cliff coverage, not a new bug (July 2026)

Follow-up feedback: some sectors look correctly tiled/blended, others don't, and the user couldn't pin down more specifically than that. Ran a systematic diagnostic instead of guessing:

1. **Ruled out a fallback/exception bug.** Swept all 100 sectors of mp_mridge calling `build_sector_tile` directly with real heightmaps — zero missing heightmaps, zero failed tiles, zero exceptions. Every sector goes through the identical rule-based code path; there is no silent per-sector degradation to the legacy mask-order fallback.
2. **Computed per-sector layer dominance.** By sector-wide average, ALL 100 sectors are "Default"-dominated (expected — Default is unrestricted, applies everywhere). This is too coarse to explain the complaint, since it hides LOCALIZED patches within a sector.
3. **Computed per-sector Rock coverage (mean Rock_X+Rock_Y weight) and compared the highest (51%) against the lowest (0.2%) sector directly.** The high-rock sector visibly shows more speckled/grainy character than the low-rock sector, at the same brightness. This is consistent, not a broken/random defect — it's the SAME `Tiling=6` low-repeat-count limitation already documented in the "Multi-variant tiling" section above (a swatch tiled only ~6 times inherently can't fully hide repetition in a static bake, regardless of variant diversity). Since rock/cliff coverage varies naturally sector-to-sector across real terrain, this reads exactly as "some sectors good, some bad" even though it's really "some sectors have more of the layer that's hardest to make look seamless."

**Applied one more safe, unconditional improvement:** bumped `texture_tile_px` 160→224 in both renderers (more absolute resolution per repeat for every layer, not just Rock; cost is negligible — 0.02-0.03s per tile, full-map bakes still 2-3s for Avatar / ~10s for FC2's 5×5 cells). Directly inspected the highest-rock sector at 160 vs 288px side by side — only a marginal, not dramatic, improvement; the countable repeat structure (Rock's fundamental ~6 repeats/sector) is unchanged, as established earlier — resolution helps sharpen detail but cannot fix a low-repeat-count problem.

**Conclusion communicated to the user:** this appears to be the SAME known baked-static-image ceiling already flagged (not a new, distinct bug) — surfacing as "some sectors" because those are the sectors with more cliff/rock terrain, which shows the least resolution of any layer (`Tiling=6`, the lowest of any layer in the map) baked into a flat preview. A genuinely complete fix requires live per-pixel GPU texture sampling (a real terrain shader for the 3D viewport) rather than further static-bake tuning — flagged as a distinct, larger scope of work if the user wants to pursue it.

### Decompile functions labeled — terrain init sequence confirms 65x65 grid + 3 data channels (July 2026)

User asked me to dig further into the decompiled engine functions and label them by what they actually do, to push on byte[3]'s unresolved identity. Traced the real terrain-system initialization sequence (not a script-binding shim — the earlier `CTerrain`/`GetSector` hit at line 656634 turned out to be a Lua-style scripting registration, a dead end for byte-level structure). Labeled functions, called in this order from `FUN_1046e630` (**InitTerrainSystem**, line 770433):

- **`FUN_1046d9e0` — BuildTerrainLODWeights** (line 769866). Iterates 3 LOD block sizes (`1<<1, 1<<2, 1<<3` = 2×2/4×4/8×8) over an 8×8 sub-grid, computing bilinear-style area-weighted interpolation factors and packed neighbour offsets (`row*0x41+col` — the same 65-stride indexing as our sector grid) into a short-array table. This is the engine's terrain LOD/mip blending weight table, unrelated to byte2/3 per-vertex meaning but confirms the 65-wide (0x41) stride is baked into the engine's own terrain math, not just our reverse-engineered guess.
- **`FUN_1046df40`** (line 770077, not fully read this pass) — called right after, likely a sibling LOD table (e.g. for a different axis or blend direction); not yet labeled precisely.
- **`FUN_1046e400` — RegisterTerrainDataChannels** (line 770294). Registers exactly **3 named terrain data channel descriptors** into a lookup table: `"TerrainHeights"` (format/type value 7), `"TerrainNormals"` (format/type value 4), `"TerrainParams"` (format/type value 5) — confirmed by tracing the loop's pointer arithmetic (`ppcVar2 = local_38+2` stepping by 4 for 3 iterations lands exactly on each name+value pair, including the 3rd landing on `local_10=5` for `"TerrainParams"`, which isn't adjacent in the literal array layout).
- **`FUN_1046e4f0` — InitTerrainChannelTable** (line 770345). Thin wrapper: calls `RegisterTerrainDataChannels` then two more setup calls.
- **`FUN_1046e580` — BuildTerrainSectorEdgeGrid** (line 770379). Iterates a full **65×65 grid** (`uVar6`/`uVar5` both 0..64, `iVar3 = uVar6*0x41+uVar5` — exactly our sector's row-major 65-stride indexing) and writes one packed 32-bit value per cell: low byte = column, next byte = row, high byte = an **edge classification flag** (3=left edge/col 0, 2=top edge/row 0, 1=right edge/col 64, 0=bottom edge/row 64, 0x7f=interior). This is a seam/boundary-awareness lookup table — the engine explicitly flags which grid cells sit on a shared sector edge, presumably to drive special-case handling (e.g. not re-deriving a normal from out-of-sector neighbours, or matching an adjacent sector's boundary data) — directly relevant to (and corroborating) this session's earlier seam-stitching work on the heightmap/texture side.

**What this confirms:** the engine's own internal terrain system is genuinely built around exactly the 65×65 grid we reverse-engineered from the `.csdat` file layout (16900 = 65×65×4 bytes), and it tracks **3 distinct terrain data channels** — Heights, Normals, and Params — as first-class, separately-named concepts. This is strong, independent corroboration that our byte-level split (bytes[0:2]=height, byte[2]=normal-X, byte[3]=???) is structurally the right shape: byte[3] is very likely this same "Params" channel, a real distinct piece of per-vertex terrain data, not noise or a coincidence.

**Still unresolved:** what "Params" actually encodes semantically. The channel's NAME string is referenced only once (at registration) — every other consumer reads it via a hash/index, not the literal string, so it can't be traced further by string search. The actual per-pixel/per-vertex CONSUMPTION of this channel (e.g. in the terrain shader) is compiled GPU shader bytecode, which — as established earlier this session — is not present in this CPU-code Ghidra dump. Fully resolving byte[3]'s exact meaning would need either the compiled shader bytecode itself (a different, more specialized reverse-engineering task) or more creative statistical probing of real `.csdat` data across many more sectors/maps.

### byte[3] cracked — real per-vertex underwater flag, wired into the compositor (July 2026)

Continuing the byte[3] investigation (previous two sections) statistically instead of via the decompile (GPU shader bytecode isn't in that dump). Pulled byte[3] from ALL 100 sectors of mp_mridge (422,500 samples) instead of just one:

- **The earlier single-sector slope correlation (-0.73) does NOT generalize** — pooled across all sectors it drops to a weak 0.10 (Pearson) / 0.09 (Spearman rank). That correlation was a coincidence of one sector's particular terrain shape, not a real relationship. Also ruled out curvature (Laplacian of height) as an explanation (corr 0.01-0.09).
- **The value distribution is cleanly bimodal**: max of the low cluster = 95, min of the high cluster = 224 — a completely empty gap from 96-223 with zero samples across all 422,500. This is a two-state flag, not a continuous quantity with noise.
- **The high cluster (>200) is a real per-vertex "underwater / at water level" flag.** Found it by mapping exactly which sectors/cells hit the high range: always a contiguous, diagonally-wedged region (e.g. sd17: rows 60-64 × cols 52-64, widening linearly toward the corner — literally shoreline-shaped, matching the user's "waves on a beach" description). Cross-referenced against each sector's own water-height field (offset 0xB0) and the SAME sector's height data: **`byte[3]>200` agrees with `height <= water_height` at 99.3-99.9% on 4 of 6 tested sectors** (99.9%, 99.9%, 99.5%, 99.3%; two sectors with more complex/gradual shorelines were weaker at 94.3% and 60.2%, likely because "underwater" there isn't purely a height threshold — e.g. actual water polygon coverage, not just low elevation). This is unambiguous: byte[3]'s high range is the ORIGINAL EXPORTER's own computed underwater/shoreline flag for that vertex, not something we invented.
- Dry-land sub-variation (the low range's internal 0-95 spread) does NOT correlate with height, distance-to-water, or slope in further testing — its exact meaning among "definitely not underwater" vertices is still unresolved, but doesn't block using the high-range flag.

**Wired directly into the compositor — a real fix, not just documentation.** `_load_single_sector` (`terrain_renderer.py`) and `load_heightmap_from_csdat` (`terrain_to_gltf.py`) now vectorised (numpy, was a Python double-loop) and BOTH return `(height_array, underwater_mask)` — the mask is `byte[3] > 150` (the exact midpoint of the empty 96-223 gap). Stored in a new parallel `self.sectors_underwater` dict (remapped alongside `sectors_data`/`water_data` in both the FC2 gap-detection and Avatar multi-part remap paths — verified these needed the same remap or the mask would desync from the renumbered heightmap). `terrain_blend.rule_weights()` gained an `underwater_mask` parameter: for any layer whose rule is clearly "underwater/beach" (`AltEnd<=10`, e.g. mridge's `Underwater_Z` with `AltStart=0,AltEnd=0`), this REPLACES the synthetic global-height-range altitude gate with the real per-vertex signal — the original exporter computed it per-sector against that sector's OWN water body, so unlike a single global min/max normalisation (the previous approach) it correctly handles multiple water bodies sitting at different absolute elevations across one map (this map alone has water at both 0.20 and 0.77 — a real gap the old global-normalized approach could get subtly wrong). Threaded through `composite_sector`/`build_sector_tile` (`**kw` passthrough) and both renderer call sites.

Verified: sector 17's loaded mask has exactly 54 true cells, matching the raw byte analysis exactly. Full re-bakes (mridge 2D/3D, FC2 world1) run cleanly with no regression; FC2's layers have no `AltEnd<=10` rule so the fix is inert there, as expected (Underwater_Z-style beach layers are an Avatar-specific pattern in the maps checked so far).

### Atlas orientation hypothesis tested and RULED OUT (July 2026)

Follow-up feedback, still describing "some sectors tiled correctly, some not" and pointing at "the mask, the green/blue channel." Investigated concretely rather than continuing to guess:

1. **Ruled out atlas-to-sector mapping bugs.** Checked `atlas_mapping` integrity directly: 100/100 sectors present, zero duplicate (atlas file, quadrant) assignments, every atlas file used exactly 4 times. The mapping itself is structurally sound.
2. **Found a real, measurable orientation signal — then proved it was a trap.** Cropped the raw mask atlas and compared its G+B channels against REAL slope computed from each sector's own `.csdat` heightmap (the ground truth), sweeping all 8 mirror/rotation combinations. `flip-horizontal + rot90` consistently won — roughly doubled the correlation (e.g. one sector: -0.10 → +0.63), and independently, the SAME transform also best-correlated the diffuse atlas's luminance against slope. This looked like a genuine bug: reading each sector's atlas quadrant in the wrong orientation relative to its own heightmap.
3. **Applied it, rendered the full map, and it was clearly wrong.** The previously smooth, continuous ridgelines flowing across sector boundaries fragmented into a hard, visible checkerboard — every sector became visibly disconnected from its neighbours. **Reverted immediately.** The per-sector correlation test had optimised something real but too narrow: how well ONE sector's crop aligns with ITS OWN heightmap in isolation — while completely ignoring whether ADJACENT sectors' crops stay mutually consistent with each other, which is what actually produces a coherent map. The untransformed crop is the one that tiles seamlessly across sector boundaries; that mutual consistency matters more than any single sector's local slope-correlation score.

**Net result: the atlas orientation is correct as it was.** This was a real, rigorous test of the user's "we're not reading the mask/channels correctly" hypothesis, and it came back negative — changing the crop orientation makes the map visibly WORSE (fragmented/discontinuous), not better. Combined with the earlier finding (rock/cliff-heavy sectors show more of the `Tiling=6` low-repeat-count limitation, itself not a bug), there is currently no further concrete lead pointing at a data-reading defect — the remaining "some sectors look better than others" perception most likely continues to trace to how much low-Tiling layer (Rock) coverage each sector happens to have, an inherent property of the real terrain, not something to "read" differently.

## XBG Importer addon (Quiet Joker's Blender addon) — format knowledge reference (July 2026)

The user's collaborator ("Quiet Joker") maintains a Blender addon — **XBG Importer v3.0.0**
(local copy studied at `C:\Users\sambe\Downloads\Github version`) — that fully cracked the
Dunia formats this editor consumes. The editor's `texture_loader.py` was ALREADY ported from
an older version of that addon ("V10 modules/materials.py"), so the material chain here is
the same lineage. Three deep-dive studies were run against the v3 addon (Avatar + FC2
modules) to extract everything portable. Key facts a future agent needs (full specs live in
the addon source itself; per-file pointers below):

### .xbg geometry decode (addon `modules/Avatar/import_mesh_avatar.py`, `binary_avatar.py`)

- **Scope guard:** HSEM version `0x0006002A` = Avatar 2009 / FC2 2008. Later games
  (FC3/4/5) are a DIFFERENT layout. Avatar and FC2 geometry decode are byte-identical.
- **Endianness:** chunk count u32 @ file offset 28; try `<I`/`>I`, the one in [1,255] wins
  (PS3 files are big-endian with byte-reversed FOURCCs; single-byte vertex fields are never
  swapped; the u16 index buffer follows file endianness).
- **Vertex layout is FLAG-DRIVEN**, not fixed-offset. SDOL's per-VB `vb_flags` is a bitmask;
  components appear in this fixed order, each adding its size when present:
  `POS_FLOAT 0x1(12B) | POS_INT16 0x2(8B) | POS_HALF 0x4(8B) → UV0 0x8(4B) → UV1 0x800 →
  UV2 0x1000 → BONE_WTS1 0x10(8B) → BONE_WTS2 0x20(8B) → NORMAL 0x40(4B) → COLOR 0x80(4B)
  → TANGENT 0x100(4B) → BINORMAL 0x200(4B) → UNK 0x400(4B)`.
  Common: `0x0BCA` = 32B static (pos@0 uv0@8 uv1@12 nrm@16 col@20 tan@24 bin@28),
  `0x0BDA` = 40B skinned (+8B bones@16, everything after shifts +8).
- **Authored normals/tangents/binormals are D3DCOLOR: UNSIGNED-normalized, BGRA order.**
  Decode per byte `b`: `v = b/255*2-1`, and XYZ come from bytes **(2,1,0)** (x=byte2!).
  4th byte of tangent/binormal = handedness flag (usually 0x80). NEVER negate normals.
  (Signed in-order decode — the obvious guess — scrambles axes; addon verified unsigned-BGRA
  on 470k+ vertices, alignment 0.97 vs 0.37.)
- **UV:** 2×int16, `U = uv_trans + raw*uv_scale`. The ADDON flips V (`1-(...)`) for Blender;
  this editor keeps game-space V (shaders assume it) — do NOT copy the flip. UV1/UV2
  sentinel `(-32768,-32768)` = channel unused for that vertex.
- **Vertex color:** 4×u8 BGRA → RGBA = bytes (2,1,0,3).
- **DNKS is read by BYTE BUDGET, not lod_count** (see the fix section below — this was a
  real editor bug). `header_data[0]`=material id (LTMR index), `[1]`=triangle count,
  `[5]`=per-submesh vertex count; `bone_data`=48×i16 palette (-1 unused).
- **Index decode:** count = DNKS `face_count*3` (NOT SDOL's derived idx_count); byte offset
  = `indice_section_offset + sdol_idx_offset*2`; drop triangles containing `0xFFFF`.
- **Skin remap ordering gotcha (addon bug fix #16):** on multi-block DNKS files
  (vehicles/destructible plants) the sequential shared-VB palette walk MUST process slices
  sorted by ascending `idx_offset` (true buffer order), not part-number-grouped order —
  `sub_idx` restarts per block, so part grouping interleaves blocks and drifts the walk.
- **Winding:** the addon reverses triangle winding for Blender and never negates normals.
  This editor keeps file-order winding (its `compute_face_normals` treats XBG as CW and
  computes outward normals via `cross(e2,e1)` — consistent with the authored normals).

### .xbm / .xbt material chain (addon `import_materials_avatar.py`, `import_xbt_avatar.py`)

- Chain: submesh → DNKS `header_data[0]` → LTMR material table index → short name →
  `<data>/graphics/_materials/<short_name>.xbm` (flat folder; the LTMR `.mat` dir path is
  discarded). Deterministic — no filename guessing anywhere.
- XBM: find `b'LTMD'`, skip +16 (chunk header) +9 (reserved); then materialName string,
  shaderTemplate string, then SIX positional groups (textures / f1 / f2 / f3 / f4 / int).
  Strings = u32 len + bytes + skip-one-NUL-if-present. Group 0 pairs are **(value, key)** —
  path first. There is NO template inheritance — shaderTemplate is just a shader name.
- Editor's `texture_loader.py` already matches this (same V10 lineage). v3 addon deltas
  worth porting: `heighttexture1 → height` slot (FC2 Road parallax — the ONLY FC2-vs-Avatar
  difference in the whole material chain), `alphatexture1[wrap] → alpha` slots, and the
  lowercase-retry fallback when resolving texture paths on disk (extracted packs sometimes
  flatten case).
- XBT: `TBX` magic (3 bytes), headerSize u32 @8, DDS payload = `data[headerSize:]` if
  32≤hs≤1024 else `data[32:]`; validate `DDS `; fallback scan offsets 64/128/256. Prefer
  `_mip0.xbt` sibling (full-res top mip). Editor already identical.

### .hkx collision (addon `hkx_native_avatar.py` — byte-identical to the FC2 copy)

- Havok 5.5.0-r1 32-bit LE packfile, optional 16-byte game wrapper before the 8-byte magic
  `57 E0 E0 57 10 C0 C0 10`. Sections table @64 (48B entries); `__data__` holds objects +
  three fixup tables (virtual = object enumeration w/ classname, local = array/string
  pointers, global = object-graph edges). Never dereference raw pointer bytes — always look
  up fixups by field offset.
- Shapes: box (halfExtents @+0x20), sphere (radius @+0x10), capsule/cylinder (A @+0x20,
  B @+0x30, radius @+0x10), convex vertices (**FourVectors SoA**: 48B chunks = x[4]y[4]z[4];
  vert j of chunk = `(v[j], v[4+j], v[8+j])` — easy to get wrong), triangle mesh (via
  `*MeshSubpartStorage` child: hkVector4 AoS verts @+0x08/count @+0x0c, u16 stride-4 indices
  (a,b,c,pad) @+0x14/count @+0x18), list (childInfo 16B entries via local fixup @+0x18,
  child ptr per entry via global fixup), MOPP (transparent wrapper — ignore bytecode,
  descend), translate/transform wrappers (compose into child transform).
- Rigid body: rotation columns @+0xE0/+0xF0/+0x100, translation @+0x110 (column-major);
  shape via global fixup @+0x10. `world_vertex = rb_xform @ shape_xform @ local_vertex`.
- **No axis swap or scale anywhere** — data is native Havok space (right-handed Z-up meters),
  which matches game space; the editor's usual -90°X render rotation applies as with models.
- The addon's `HkxFile` class is bpy-free (os+struct only); `walk_shape`/`rigid_bodies` only
  need their `mathutils.Matrix` uses swapped for numpy — i.e. it can be ported nearly
  verbatim into a standalone viewer.

### Also in the addon, not yet ported (future feature candidates)

- **.mab skeletal animation** (`import_mab_avatar.py`, ~99KB): full Dunia compressed rotation
  bitstream decode ("smallest-three" quaternion codec), constant + keyframed bone routing;
  facial animation (.lfa poses / .lfe expression curves); full cinematic scene import
  (cameras, anchors, timeline markers) in `mab_scene_avatar.py`.
- **.skeleton (LKS) import/export** (`import_lks_avatar.py` / `export_lks_avatar.py`).
- **HKX collision EXPORT with from-scratch MOPP bytecode compiler** (`mopp_avatar.py`) — the
  Havok spatial-index VM re-implemented; would let the editor WRITE edited collision.
- **Custom material/texture baking** (`export_materials_avatar.py`, `xbm_builder_avatar.py`,
  `dds_writer_avatar.py`): writes game-ready .xbt (DXT1/5) + .xbm from scratch — the
  authoritative reference for every LTMD field when the editor needs to WRITE materials.
- **Jiggle/procedural bones** (`jiggle_avatar.py`) — reverse-engineered spring-damper
  integrator; **LOD distance editor** (`lod_distance_avatar.py`); **bounds editors**.

## Model rendering fixes ported from the XBG Importer v3 addon (July 2026)

Task 1 of the addon-port series (see the format reference section above). Changes to the
shared Avatar+FC2 model pipeline (`canvas/mesh.py`, `canvas/xbg_parser.py`,
`canvas/xbg_direct_loader.py`):

1. **Flag-driven vertex decode** (`mesh.py`). `parse_mesh_vertices` previously assumed a
   fixed layout (pos int16 @0, uv @8, skin @16/20 at stride 40). Now
   `compute_component_offsets(vert_format_flags)` derives each component's offset from the
   SDOL format flags word and is trusted only when the computed stride matches the SDOL
   stride (else legacy fallback — same behavior as before). This also handles POS_FLOAT /
   POS_HALF position formats the old code would have silently mis-read.
2. **Authored normals decoded and used** (`mesh.py`, `xbg_parser.py`). The editor used to
   RECOMPUTE normals geometrically (`compute_face_normals`) for every model. It now decodes
   the file's own per-vertex normals — unsigned-normalized BGRA D3DCOLOR, `v = b/255*2-1`,
   xyz from bytes (2,1,0) — and only computes geometric normals when the vertex format has
   no NORMAL component. Verified on 33 real models (30 Avatar + 3 FC2): decoded normals are
   exactly unit-length (mean |len-1| = 0.0000) and align 0.94 mean with the geometric
   reference — low-align files (organic/smoothed meshes) are precisely where authored
   normals carry real smoothing information the recompute lost. Tangents (+ raw handedness
   byte) and vertex colors (BGRA→RGBA) are decoded too; `xbg_direct_loader` prefers authored
   tangents over the UV-derived computation. NOTE: the GLSL fragment shader builds its
   normal-mapping TBN from screen-space derivatives, so tangents only feed the (legacy)
   vertex attribute — the visible win is the lighting normals.
3. **DNKS byte-budget block parse** (`xbg_parser.py`). `_parse_dnks` read exactly
   `lod_count` (DIKS) blocks; the region is actually sized by `qq[2]` bytes and multi-block
   files have one block per (part × damage-state × LOD) group. Every sampled retail file
   happened to have DIKS lod_count == true block count (so no visible regression either
   way), but re-injected/modded files and the addon-documented FC2 multi-block cases (e.g.
   buggy: 85 blocks) would silently drop submesh materials/face counts past lod_count.
   Block names (PART_STATEnn_LODk damage-state convention) are now captured in
   `XBGData.dnks_block_names`. Also added the addon's `name_index` fallback when a SDOL
   `sub_idx` exceeds its DNKS block (re-injected files), and the addon's bug-fix #16:
   `_remap_skin_indices` sorts shared-VB slices by index offset (true buffer order) before
   the sequential palette walk — part-grouped order interleaves blocks on multi-block files
   and corrupts weights (skinned path only; static loads skip it).

**UV convention note:** the addon flips V (`1-v`) for Blender; this editor keeps game-space
V — do NOT port the flip. Winding likewise stays file-order (editor convention; addon
reverses for Blender and never negates normals — equivalent front-face outcome).

## Material-chain deltas ported from the XBG Importer v3 addon (July 2026)

Task 2 of the addon-port series. `canvas/texture_loader.py` was already the same lineage as
the addon (ported from its V10 `modules/materials.py`), so a line-by-line comparison against
v3 found only three real deltas, all now applied:

1. New slot mappings in `_TEX_CATEGORY_EXACT`: `heighttexture1 → height` (FC2 Road parallax
   — the ONLY FC2-vs-Avatar difference in the entire material chain) and
   `alphatexture1` / `alphatexture1wrap → alpha`.
2. `resolve_xbt_full_path` retries with the fully-lowercased relative path when the
   mixed-case engine path is missing on disk (extracted packs sometimes flatten case;
   only matters on case-sensitive mounts — harmless no-op on NTFS).
3. `find_diffuse_texture` now routes through `resolve_xbt_full_path` (shared fallback logic
   instead of a duplicate resolution path).

Everything else already matched v3 exactly: LTMD structured parse (+16/+9 skip, 6
positional groups, (value,key) pair order in group 0), heuristic regex fallback, TBX→DDS
extraction (headerSize @8, 32-byte fallback, 64/128/256 scan), `_mip0` preference, and the
sibling-slot disk synthesis. The per-submesh material KEYING was also already deterministic
(DNKS `header_data[0]` → LTMR index) — the "wrong texture on parts of vehicles/plants"
class of bug traces to the DNKS multi-block parse fixed in the previous section, not to the
material chain.

Verified end-to-end on real data: 20 random Avatar models → 42 referenced materials → 42
.xbm found+parsed → 42 diffuse slots → 42 diffuse .xbt files resolved on disk (0 misses).

## Collision viewing — native .hkx reader + 3D overlay (July 2026)

Task 3 of the addon-port series. The editor can now show real in-game collision shapes.

**`canvas/hkx_parser.py` (new, GL-free).** Port of the addon's Havok 5.5 packfile reader
(`hkx_native_avatar.py` read path; the FC2 copy is byte-identical so ONE module serves both
games). `HkxFile` parses the packfile (16-byte game wrapper auto-detected, sections table,
virtual/local/global fixup tables — never dereference raw pointer bytes, always resolve
through the fixup dicts), `rigid_bodies()`/`walk_shape()` flatten the shape graph with numpy
4×4 transforms (mathutils swapped out). All member offsets are documented in the module
docstring. Supported: box, sphere, capsule/cylinder, convex vertices (FourVectors SoA — the
48-byte x[4]y[4]z[4] chunk layout), triangle mesh (via *MeshSubpartStorage), list, MOPP
(transparent), translate/transform wrappers. `load_collision_wireframe(path)` bakes
rb_xform @ shape_xform and returns flat GL_LINES pairs (float32, capped at 120k segments,
cached by path+mtime with negative caching). `find_collision_for_model(xbg)` maps
`foo.xbg ↔ foo.hkx` (verified sibling convention in the game data).

- **Coordinate space:** raw Havok = game space (same as .xbg vertices) — NO axis swap or
  scale in the file; the entity's model transform applies unchanged.
- **Convex hull edges use scipy** (`scipy.spatial.ConvexHull`) with an AABB-box fallback —
  and setup.py EXCLUDES scipy from frozen builds, so release builds show convex shapes as
  their bounding boxes while dev runs show true hulls. Acceptable degradation; if exact
  hulls matter in frozen builds, remove 'scipy' from setup.py excludes (large size cost).

**Overlay integration (`canvas/map_canvas_gpu.py`).** `show_collision` flag (default off) +
`_render_collision_3d()`: draws SELECTED entities' collision as orange (1.0, 0.55, 0.1)
wireframes through the shared LineBatch (immediate-mode fallback included). Transform =
`overlay_matrix(entity.x, entity.z, -entity.y, *_get_entity_rs(entity), scale×3)` — the
exact model render sequence, so wireframes sit ON the model. Wired into BOTH
`_render_overlays_3d` paths; `show_collision` added to the overlay cache key (selection ids
were already in it, so selecting a different entity rebuilds correctly).

**UI (`simplified_map_editor.py`).** View → "Toggle Collision (Selected)" (checkable,
default off) → `_set_collision_visibility`. README updated. `canvas.hkx_parser` added to
setup.py packages (Rule 4).

### CS Camera preview fixes — placement + GDR-swallowed model pass (July 2026)

User feedback: the preview "does not work" and was NOT wanted as its own right-panel tab —
they wanted it as a SECTION in the main (Level Information) tab, between the two existing
sections, like the BW editor's. Two changes:

1. **Placement**: the widget now lives in a "CS Camera Preview" QGroupBox added to
   `create_side_panel`'s `dock_layout` BETWEEN the Level Info group and the Map Tools
   group (the former "CS Camera" tab in `right_tabs` is gone). Being always-visible in the
   main tab also means `isVisible()` gating no longer hides renders behind an unopened tab.
2. **Blank-preview root cause**: `render_camera_preview`'s model pass called
   `prepare_batches` + `render_batched_models`, but in GPU-driven tiers
   (`force_render_tier` set, e.g. render_tier=texarray) `render_batched_models` takes the
   GDR path — which draws the MAIN view's persistent instance buffers (or nothing at all
   in 2D mode) and IGNORES the classic batches the preview just prepared. Fix: temporarily
   clear `model_loader.force_render_tier` around the preview's model pass (restored in
   finally) so the universal per-instance path draws exactly the preview's subset.
3. The widget also gained a status line (last render outcome / exception text) so
   failures are visible instead of a silent black box.

If the preview is still blank after this, check the console for `[cs-preview]` lines and
the widget's status text — the failure will be named there.

### Two more right-panel bugs (July 2026)

**1. 2D sector/landmark/omnis boundary squares vanished while an entity was selected**
(user: "click on an object... squares go away, click off... they come back"). Root cause:
`_render_2d_opengl` drew every 2D layer (terrain, entities, movie paths, gizmo, selection
box, sector boundaries, mode indicator) inside ONE shared `try/finally` with no `except` —
an exception raised by any earlier stage (entities/gizmo/selection-box are the stages that
only run extra code paths once something is selected) aborted every draw call AFTER it for
that frame, including the sector-boundary squares near the end. `paintGL`'s outer
try/except caught it and printed a traceback, but the frame still rendered without the
squares; the very next frame (nothing selected, the extra code path not hit) rendered
clean again — exactly the flicker reported. Fix: each stage now runs through a local
`_stage(name, fn)` wrapper with its own try/except + traceback, so a failure in one stage
can never suppress the others — sector boundaries and the mode indicator now always
attempt to draw regardless of what breaks elsewhere in the frame. The original per-stage
exception (if one is still occurring) will now print as `[2d-render] <stage> failed: ...`
instead of a bare `Error in paintGL`, which pinpoints it immediately if it recurs.

**2. Stats-tab labels still forced a horizontal scrollbar despite `setWordWrap(True))`**
(follow-up to the July 2026 wrap fix above). Root cause: Qt's word wrap only breaks
BETWEEN words (at whitespace) — it cannot help with a long dotted archetype name
(`weapons.Avatar_MountedWeapons.DoveTurret`) or a backslash file path
(`graphics\av_vehicles_corp\dove_drivable\dove_turret.xbg`), since neither contains a
single space. Those single "words" kept the label's natural width wide regardless of the
wrap flag. Fix: new `SimplifiedMapEditor._softwrap(text)` inserts a U+200B (zero-width
space — an unconditional Unicode line-break opportunity, invisible when rendered) after
every `.`/`_`/`-`/`/`/`\`/`:` in values over 24 chars; applied to the Name/Type/Source/Map
stat labels before `setText`. ID and Angles/Position labels were already bounded (ID is
truncated to 22 chars + "..."; Angles/Position are `.2f`-formatted numbers) so left as-is.

**Follow-up fixes (same day):**
- **Sequences-tab link made self-syncing**: the user reported the tab "not linked" to the
  previewer. The widget's 20 fps tick now compares `editor.selected_movie_sequence` to its
  own state and calls `set_sequence` itself when they differ — the explicit hook in
  `_on_sequence_selected` remains but is no longer load-bearing, so creation-order issues
  or a swallowed exception can never sever the link. (Headless offscreen test confirmed
  the widget-side path: combo populates from real moviedata via the tick alone.)
- **Right-panel horizontal scrollbar killed**: a QLabel's minimum width follows its
  pixmap/text, so the preview image (up to 640px) + long unwrapped status text forced
  `dock_widget` wider than the dock → horizontal scrollbar on the whole Level Information
  scroll area. Fix: `image_label`/`status` get `QSizePolicy.Ignored` horizontally +
  word-wrap, and `_li_scroll.setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)` — with
  widgetResizable, content is forced to viewport width and wide children wrap instead of
  pushing a scrollbar. Vertical scrolling remains as-needed (three stacked sections
  legitimately exceed short windows).
- **Stats-tab labels were the remaining wideners** (user: content extended past the
  border on level load): Type/Source/Map/X,Y,Z/Angles value labels had no word wrap —
  long source-file paths set their minimum width. All stat value labels now wrap.
- **Static-camera fallback in the previewer**: survey across all 106 moviedata files
  (both games): only 156/568 sequences have a camera among their OWN animated nodes —
  most cutscenes are filmed by STATIC cameras that exist in NodeData but are not
  sequence nodes (no tracks). `camera_nodes()` now offers three tiers: sequence-animated
  cameras → all other camera NodeDefs "(static)" (rest pose — `camera_pose_at` already
  falls back to the NodeDef transform when the node has no tracks) → the sequence's own
  nodes "(node)". "No camera in this sequence" is now effectively unreachable on real
  data.

**Verified on real data:** 34/34 Avatar .hkx files parse (0 fail/0 empty) across all shape
classes ({StorageExtendedMesh: 42, Box: 26, ConvexVertices: 34, Sphere: 1, Capsule: 1}
in the sample); collision extents match the sibling model's vertex bounds at ratios
0.87–1.02 on spot-checked pairs (atv, extraction tower, rock arch), confirming both
geometry decode and transform composition. FC2 ships no loose .hkx in the currently
extracted MODDED folder, but the format/reader is identical (addon's FC2 module diffs
empty vs Avatar's).

## CS Camera preview — cutscene-camera POV in the right panel (July 2026)

Modeled on the Battalion Wars level editor's camera previewer
(`battalion-level-editor/widgets/camera_preview.py`, studied as the reference): a "CS
Camera" tab in the RIGHT side panel (`right_tabs`, next to Level Information / Object
Library) that renders the level THROUGH the selected sequence's cutscene camera, with a
camera picker + play/scrub transport.

**Camera conventions (empirical — do not "fix" without data).** moviedata camera NodeDefs
(names like `CameraCinematic_5`, matched on `'cam' in name.lower()`) store a quaternion
whose **forward axis is +Y in game space** and up is +Z. Determined by scoring all six
axis candidates across 101 real Avatar cutscene cameras against the direction from each
camera to its sequence's other nodes: +Y mean cos +0.58 (72% within 60° of the action),
every other axis ≈ 0, −Y exactly opposite. FC2 moviedata (66 files) has too few
camera-with-actor sequences to rescore (4 samples, no signal) — same engine/format, so the
Avatar convention is used for both; revisit only with real FC2 visual evidence. moviedata
has NO FOV track; `DEFAULT_FOV = 55°`.

**Rendering (`map_canvas_gpu.render_camera_preview(eye, look, up, fov, w, h)`).** Offscreen
QOpenGLFramebufferObject pass **in the main GL context** (no second context — every loaded
resource reused; the BW editor needed AA_ShareOpenGLContexts for its separate-widget
approach, we deliberately avoid that): scene only (terrain via the extracted
`_draw_terrain_tile(..., allow_shadow=False)`, water with flat-sky reflection,
entity models via the classic `prepare_batches` path over a 1500-unit-radius subset) — no
grid/overlays/gizmos/HUD. `self.camera_3d` is temporarily swapped for a posed clone so
water follows the preview camera; restored in `finally`. Clobbering
`instance_batches`/`_gdr_frame` is safe because the main paint re-prepares every frame; the
call comes from a Qt timer, never inside paintGL. NOTE: `_render_terrain_model` inside
`_render_3d_opengl` is now just an alias for the extracted `_draw_terrain_tile` method.

**Widget (`canvas/cs_camera_preview.py`).** `CSCameraPreviewWidget`: camera combo, POV image
label (16:9, FBO capped at 640px wide), ▶/■ + scrub slider + time label; 20 fps QTimer that
skips work when hidden or nothing changed (render key = seq/cam/time/size). Play drives the
existing Sequences-tab preview (`_movie_preview_start`) so entities animate in the main
view on the SAME wall clock; if that preview is already playing, the tab just follows it.
Scrubbing calls the new `editor._movie_apply_time(t)` — refactored out of
`_movie_preview_tick` — which saves original entity positions on first use so Reset works
from a scrub without ever pressing Play. Wired in `create_side_panel` (tab), and
`_on_sequence_selected` calls `cs_camera_preview.set_sequence(...)` on select/clear.

Verified headlessly: 239/239 camera nodes across all Avatar moviedata produce valid poses
(165 animate over their sequence); pose math unit-tested. The GL preview pass itself needs
a user click-test in the running editor (select a sequence → CS Camera tab).

## Vehicle part assembly + selection-glow crash fix (July 2026)

User report: "vehicles are not rendering correctly... not being assembled correctly", plus
an access-violation crash in `_render_3d_selection_glow` when selecting. Two separate,
PRE-EXISTING bugs (verified: the addon-port parser changes produce byte-identical geometry
to the old parser on every vehicle tested — positions, indices, UVs all diffed equal).

**1. Vehicle parts were never assembled (`xbg_parser._apply_part_transforms`, new).**
Vehicle .xbg files store each named rigid part around its OWN pivot — proven on
buggy_drivable: all four wheels' vertices are centered at the origin, and the EDON
skeleton's `WheelBack_L_State01` / `WheelFont_R_State01` / … bones sit at the four wheel
corners. The part↔bone link is BY NAME: DNKS block name minus the `_LODn` suffix equals
the bone name (case-insensitive; EDON bone names are truncated to their last 25 chars —
mirror that in the lookup). The editor loaded static models with the skeleton SKIPPED, so
every wheel/rotor/steering wheel rendered at the origin inside the chassis. Now: EDON is
always parsed (skip_skeleton only skips the skin-index remap), and after face processing
each UNSKINNED mesh (no BONE_WTS1 — skinned characters are already in model space) with a
name-matched, non-identity bone gets `v' = R·v + t` (authored normals/tangents rotated;
runs BEFORE the geometric-normal fallback so those compute from assembled positions).
Important non-findings: STATE01 parts are the REAL parts (the buggy has no state-00
wheels) — do NOT hide damage states; and `Z_`-prefixed parts (rotor blades) are normal
geometry. Verified: buggy wheels land on their bones (dist ≤ 0.18), samson/dragon/scorpion
parse clean, characters + props byte-identical with the step disabled, repeat-parse
deterministic, 40-file sweep 0 failures.

**2. Selection-glow access violation (`model_loader._render_glow_geometry`).** The glow
pass draws with CLIENT-side arrays. Two latent landmines: (a) a VAO / GL_ELEMENT_ARRAY_
BUFFER left bound by earlier passes turns the client index POINTER into a GPU-buffer
offset → access violation (glPushAttrib does NOT cover buffer bindings); (b) models from
the old cached-gltf path store `mesh.indices` as float32 — reinterpreted as uint32 they're
astronomical and the driver walks off the vertex array. Fixed: unbind VAO + both buffer
targets before drawing, and sanitize indices once per mesh (cast to uint32, drop
out-of-range, cache as `mesh._glow_indices`).

## .mab animation decoder ported (July 2026)

`canvas/mab_parser.py` (new, GL/bpy-free) — port of the addon's `import_mab` decode path.
Avatar + FC2 clips share codec version byte **0x4C** (duration f32 @0x84, 9-entry section
table @0x88; ALL stored section offsets are relative to byte 16). One module, both games.

Key format facts (full spec in the addon source; load-bearing details here):
- **Smallest-three quats, 6 bytes**: two 15-bit unsigned + one SIGNED 16-bit component
  (scale 4.315969e-05, bias 1/√2); FW/SW bit-15 pick the dropped component
  ((0,0)=x,(1,0)=y,(0,1)=z,(1,1)=w largest); s<0 → invalid/no-key. Reading the third word
  unsigned is a known community-port bug — keep it signed.
- **Routing is positional, no hashes**: 20-byte LSB-first masks @0x10 (constant bones) and
  @0x24 (animated bones), one bit per animation-skeleton (LKS) bone; stream track t = t-th
  set anim bit. `MabClip.resolve_bone_names(lks_names)` maps when names are available.
- **Keyframes**: groups of 8 frames; per group `[N primaries][N mask bytes, even-padded]
  [secondaries contiguous per bone]`; mask bit7 = sub-frame 0 (primary), flagged keys land
  at bit-position+1 (the addon's timing fix). fps is DERIVED: max decoded frame / duration.
- **Root motion**: UnkSec1 (dense 6-byte quats) + UnkSec2 (dense 3×f32 world translation)
  + Offsets track 0 (local bob/sway) composed as `pos + R(rot) @ offset`.
- **Spaces**: bone keys are ABSOLUTE bone-LOCAL rotations (not bind deltas) — pose via FK
  (world = parent_world @ local) substituting decoded locals; twist/helper bones are in
  NEITHER mask (engine-procedural, no data) — leave at rest.
- **Pose clips are real**: aim poses / corpse poses have duration 0, Keyframes n=0/fc=0,
  everything in the constants section — not a decode failure.

Verified on 240 random real clips (120 Avatar + 120 FC2): 240/240 clean, 419,073 rotation
keys decoded, all version 0x4C, unit quats, monotonic in-range frames. Not yet wired to
any playback UI — that's the follow-up (skinned preview needs skinning in the renderer).
Scene .mab extras (cameras/FOV cuts/timed events in Events/UnkSec4/UnkSec5) are NOT
decoded yet; the addon's `mab_scene_avatar.py` is the reference when cinematic import is
wanted.

### Global assembly audit + the mounted-weapons layer (July 2026)

**IMPLEMENTED (July 2026): mounted weapons now render.** `bake_vehicle_attachments.py`
(repo root, DEV-TIME tool — deliberately not in setup.py root_files: the app never imports
it; the runtime reads only the baked JSONs) streams a world's converted
`entitylibrary_full.fcb.converted.xml` (ET.iterparse, flat memory on 246MB files) and
writes `canvas/assets/<game>/vehicle_attachments.json`: vehicle model basename →
[{model, matrix (4×4 row-major game-space, relative to vehicle origin), kind, via}].
Rules encoded: gunner Seat (hidSeatType=2) BoneName = vehicle-side attach bone;
MountedWeaponEntry.archMountedWeapon → mount model; its archWeapon → gun model, attached
at the mount-skeleton bone matching the gun's root bone name, else the generic FC2 mount
names ('GunMount', 'WeaponPos', 'WeaponPlacement'), else any 'weapon' bone. Gotchas
learned: prototype Names COLLIDE across kinds (WeaponProperties.DoveTurretGun precedes
the real entity — merge, prefer the side with a model); archetype VARIANTS (Rover.M249 /
.Browning / .Mk19) mount different guns at the same point — dedupe per (kind, matrix) or
jeeps get three stacked guns. Baked: Avatar dove (turret+gun); FC2 rover / fishing_boat /
swampboat (mount+M249 each). Rendering: `xbg_direct_loader._merge_attachments` appends
the attachment models' meshes into the vehicle's GLTFModel at load (verts/normals/
tangents transformed by the baked matrix, material indices offset, bounds widened) — so
armed vehicles are complete on EVERY path (GDR, classic, CS preview, thumbnails) with
zero renderer changes. Verified: dove gun lands over the turret-arm end (the gunner seat
bone carries a 180° z-rotation — gunner faces rearward — which the matrix composition
reproduces); control props gain nothing. Re-bake when game data or the rule changes:
`python bake_vehicle_attachments.py <converted xml> --game avatar|fc2 --data-root <root>`.

**Audit: part→bone assembly is complete.** All 2,357 .xbg files across both games parsed
with 0 failures; of 2,980 unskinned named part meshes, 2,979 (100.0%) resolve to a bone.
The single miss is `scorpion_obsolete.xbg`, whose part name is literally
`SCORPION_BODY____…` (underscore-padded, bone equally mangled) — broken obsolete source
data, not an assembly bug.

**Mounted weapons (dove turret etc.) are a DIFFERENT layer — entity composition, not
in-file parts.** The dove's turret gun is two separate models: `dove_turret.xbg` (mount +
seat) and `dove_mounted_weapon.xbg` (the gun). The chain, recovered from a world's FULL
`entitylibrary_full.fcb` (convert with the native FCB converter — the editor's shipped
`entitylibrary_full.fcb.converted.xml` is a REDUCED extract that strips component data):
vehicle prototype → `<object name="MountedWeapons"> <object name="MountedWeaponEntry">
<field name="archMountedWeapon" value="weapons.Avatar_MountedWeapons.DoveTurret"/>` →
DoveTurret prototype (GraphicComponent → dove_turret.xbg, `hidNodeName Dove_Turret`, and
`archWeapon = …DoveTurretGun` → dove_mounted_weapon.xbg, plus FX bone bindings
FX_FIRE01–04). What the data does NOT state textually is which VEHICLE bone the turret
mounts to (the engine's runtime rule; plausibly the Turret_Arm bone on the dove — its
geometry reads right there — but that's an inference, not data). Implementing mounted-
weapon display needs either that rule (ask the addon author / dig the Ghidra decompile
for CMountedWeapon attach) or a per-vehicle mapping table. Companion `<model>.xml` files
in the graphics folders (e.g. `dove_mounted_weapon.xml`) are exporter descriptors (bones,
LODs, materials, bboxes) — useful reference, but they don't carry the attach point
either.

## Sequence-playback lag — root causes + fix (July 2026)

User report: "the playing of the sequences causes massive amounts of lag". Four
independent costs stacked; all four are now fixed.

**1. The 3D overlay cache was killed by SELECTION, not by playback (the dominant one).**
`_render_overlays_3d`'s gate was literally `movie_active = bool(mw.selected_movie_sequence)`
— so clicking any row in the Sequences tab dropped the whole level back to the classic
per-frame prims/triggers/shape rebuild. Cost, from this repo's own June 2026 perf
validation (same 5,642-entity level): **CPU 3.4–5.5 ms/frame cached vs 11–19.4 ms
uncached** (`shape=4-6 prims=3-5 triggers=1-3`). Now the gate is `self._movie_overlay_stale`,
set by the new `canvas.set_preview_entities(entities)`: the cached wireframes only go
stale if a MOVING entity actually owns overlay geometry (`is_primitive_object` /
`is_trigger_entity` / `has_shape_points`). Cutscene actors are characters, cameras and
props and normally own none → the cache stays on for the whole preview. `show_collision`
(off by default, draws only for SELECTED entities) is OR'd in at the gate rather than
baked into the flag, because it can be toggled after registration.

**2. The preview timer out-ran paintGL.** The tick was 16 ms and every tick ended in
`canvas.update()`; on a heavy level a frame can't retire in 16 ms, so repaints queued
faster than they were served and the event loop backed up (that's why it reads as
whole-UI lag, not just a lower FPS). Now: 33 ms tick, plus back-pressure —
`paintGL` bumps a monotonic `canvas._paint_seq` (**before** its `use_gpu_rendering`
early-out, so a non-GPU canvas still reports progress), and `_movie_preview_tick` skips
a tick while `_paint_seq` hasn't moved since its last `update()`. Bounded at 3
consecutive skips so a canvas that never paints can't freeze playback.

**3. The CS Camera tab rendered the scene a second time at 20 fps.**
`render_camera_preview` is a full pass (terrain + water + `prepare_batches`
over every entity within 1500 units) ending in `fbo.toImage()` — a `glReadPixels` that
stalls the pipeline the main view is filling. The 20 fps tick still updates the
transport/slider; the POV re-render is now throttled to `PLAY_RENDER_MIN_S = 0.1`
(10 fps) *while animating only*. Scrub / camera-change / sequence-change still render
immediately.

**4. Three O(N) Python scans per tick.** Measured on synthetic entities (5,642 / 25k /
50k): 2.9 / 12.5 / 25.7 ms **per tick**. All three are now O(k) or cached:
- `_movie_apply_time` rebuilt the `id -> entity` dict every tick → `_movie_entity_map()`
  caches it, keyed on `(id(entities), len(entities))`.
- `patch_preview_positions` scanned BOTH full position arrays → `set_preview_entities`
  precomputes row indices (`_preview_rows_3d/_2d`, keyed to `_pos_arrays_version` so an
  array rebuild invalidates them) and the fast path patches by index. The old full-scan
  code is kept as the fallback for callers that never registered.
- `movie_renderer._draw_ghost_nodes_2d/3d` rebuilt `{e.id for e in entities}` on every
  paint → `_loaded_entity_ids(canvas)`, cached on the canvas by list identity + length.

**Gotcha — registration must follow the moving set.** The fast patch path silently skips
ids with no registered row, so `_movie_apply_time` re-registers every tick with
`saved | updates` (a set compare over the handful of sequence nodes, no-op when
unchanged). Without that, switching sequences mid-scrub leaves the new actors' culling
positions frozen while `entity.x/y/z` moves. `_movie_preview_stop` deregisters
(`set_preview_entities(None)`) **after** its restore patch — deregistering first would
drop the rows that patch needs.

**Validating a change here:** press **F1** in the 3D canvas (cycles to `PROFILE`) and
watch the `⏱️ FRAME …ms CPU | overlay3d=… shape=… prims=…` line printed every 60 frames.
`overlay3d≈0.1` means the cache is live; `shape`/`prims`/`triggers` appearing at all means
something knocked it out.

## setup.py packaging debt cleared (July 2026)

A rule-4 audit during the sequence-lag task found **13 modules missing from
`setup.py`** — none of which produce a build-time error, so frozen builds would
have raised ImportError at runtime:

- `packages`, canvas: `god_rays`, `rtx_loader`, `terrain_blend`,
  `terrain_shadow_shader`, `vegetation_renderer`, `volumetric_rays`
  (`rtx_loader` + `vegetation_renderer` have since been deleted — see below)
- `packages`, root: `archetype_library`, `entity_library_browser`,
  `env_preset_copy`, `movie_data`, `object_library`, `ui_style_utils`,
  `world_editor`
- `root_files` (the include_files copy list): `entity_library_browser.py`,
  `env_preset_copy.py`, `ui_style_utils.py`, `world_editor.py`

All added. `bake_vehicle_attachments.py` and `check_exe_arch.py` are standalone
dev scripts the app never imports and stay unpackaged (`check_exe_arch.py` is
still copied via `root_files`).

`tests/test_setup_packages.py` now enforces this automatically, so the manual
audit command in rule 4 is a fallback rather than the only line of defence. New
standalone scripts that genuinely aren't part of the app go in that test's
`DEV_ONLY` set.

## .rtx vegetation rendering REMOVED (July 2026)

`canvas/rtx_loader.py` and `canvas/vegetation_renderer.py` are **deleted**. Do not
re-add a vegetation draw without solving the perf problem below first.

**Why.** The renderer drew every vegetation instance in the level, every frame,
with no frustum cull, no distance cull, no LOD and no hardware instancing —
`_ensure_batch` baked each instance's full geometry into the VBO, so 13,465 palm
ferns became 13,465 duplicated copies of one 8-triangle mesh. Measured on real
Avatar data by replaying the parse + `load_rtx` decode offline:

| level | instances | tris/frame | verts/frame | VBO |
|---|---|---|---|---|
| `sp_hellsgate_01_l` | 69,893 | 998,098 | 2,994,294 | 71.9 MB |
| `sp_hometree_l` | 33,611 | 698,528 | 2,095,584 | 50.3 MB |
| `sp_gravesbog_rb_of_01_l` | 0 | 0 | 0 | 0 |

For scale, the whole entity-model scene is ~3.09M verts and was already GPU-bound
at 40 FPS on the iGPU machine — vegetation roughly DOUBLED the vertex load. It was
drawn twice per frame once the CS camera preview existed (main pass + FBO pass),
and `show_vegetation` was read as `getattr(self, 'show_vegetation', True)` with no
initializer and no menu item, so there was no way to turn it off.
`_build_crc_table` also walked the entire data root at every level load (1.7 s,
149 `.rtx` files) to build the reverse-CRC lookup.

**What was removed:** both modules, the `VegetationRenderer` import + construction
in `map_canvas_gpu`, both `render()` call sites (main `_render_3d_opengl` and
`render_camera_preview`), the `_pf('vegetation')` profiler stage, the
`parse_level` hook at the end of level load in `simplified_map_editor`, and the
two `setup.py` entries.

**The decoder worked — the draw strategy didn't.** `rtx_loader` decoded all 18
models referenced by hellsgate into real triangle meshes with zero billboard-card
fallbacks. If vegetation is ever revived, recover that file from git history
(`git show <commit>^:canvas/rtx_loader.py`) rather than re-deriving the format,
and give the renderer frustum + distance culling and real instancing (one mesh
copy + a per-instance transform buffer) before wiring it into the frame.

**Not related:** the `avatar_vegetation_*` keys in `entity_renderer.py` /
`map_canvas_gpu.py` are entity-type name mappings for props and stay.

## 2D mode: instanced squares + fence indicator removed (July 2026)

**Fence indicator gone (user request).** The red line + red endpoint circles drawn
for `SO.corp_fence_security_*` entities are removed: `draw_fence_indicator_optimized`,
`is_fence_object`, the `is_fence` cache field, the `fence_list` accumulator and its
draw loop. `any_extra` is now `is_primitive or is_trigger or has_shape`. The
`"fence"` keywords in `type_patterns` / `determine_entity_type` are UNRELATED —
they classify such entities as `Structure` for colouring and stay.

**Every 2D square is now ONE instanced draw call.** `canvas/quad_batch.py`
(`QuadBatch`, modelled on `cube_batch.py`) draws all entity squares with a single
`glDrawArraysInstanced`: a static 4-vertex unit quad plus a per-frame instance
buffer of `[cx, cy, half, rot, r, g, b, border_px]` (8 floats, `INSTANCE_FLOATS`).
The black outline is computed in the fragment shader from the quad's local
coordinates — no second pass, no extra geometry. Called between
`QPainter.beginNativePainting()` / `endNativePainting()` so it composites over the
QPainter-drawn terrain and under the gizmo/overlays.

**The per-frame Python loop is gone.** `EntityRenderer._ensure_style_array(canvas)`
builds an `(N,5)` float32 array `[r, g, b, rot_rad, source_class]` aligned to
`canvas._valid_entities_2d`, ONCE per level, and `_get_visible_entities`'s 2D branch
stashes its cull result as `canvas._visible_idx_2d`. A frame is then a numpy gather
plus one draw. Measured per-frame CPU for the instance build vs the old
per-entity `QRectF` + style-group loop (which did not even include the
`drawRects` calls):

| entities | instance build | old QRectF loop | |
|---|---|---|---|
| 5,000 | 0.25 ms | 8.33 ms | 33× |
| 15,000 | 0.49 ms | 23.72 ms | 49× |
| 50,000 | 2.47 ms | 107.04 ms | 43× |

`MAX_2D_BUDGET` was raised 15,000 → 250,000 accordingly; it is now a
pathological-data backstop, not a normal-operation limit, so every real level
renders **all** its squares.

**Things that will break this if you touch them:**
- `_visible_idx_2d` MUST stay sorted ascending — the selection and extras lookups
  use `np.searchsorted` against it. `np.where` output already is; keep it that way.
- `classify_source` / `source_mask` mirror `_filter_entities_by_source`'s branch
  order — **landmark is tested FIRST** because a landmark file also carries
  `source_file == 'worldsectors'`. `tests/test_quad_batch_2d.py` checks all 16
  toggle combinations against a copy of the list filter; keep them in sync.
- `_render_2d_instanced` validates everything BEFORE drawing and returns False
  without painting, so the QPainter fallback (still intact below it) can run
  cleanly. Don't add a draw call above those guards.
- `invalidate_entity_cache` does NOT bump `cache_version`, so it marks the
  entity's ROW dirty (`_style_dirty`) instead. Bumping `_style_epoch` there would
  rebuild all N rows on every mouse-move frame of a 2D drag. A full rebuild only
  happens for an entity that has no row yet.
- Positions come from `canvas._positions_2d`, not live `entity.x/.y`. That is safe
  because `_get_visible_entities` calls `_get_map_filtered_entities` first and the
  2D drag path calls `invalidate_position_cache()` (input_handler ~line 373), so
  the array is rebuilt before the cull. If a new drag path skips that call, squares
  will freeze mid-drag.
- The instance layout is read by two `glVertexAttribPointer` calls at a 32-byte
  stride (floats 0-3 and 4-7). Changing `build_instances`' column order without
  changing the shader draws garbage — that's what the layout test guards.

## Free GPU wins: terrain tile culling + reflection early-out (July 2026)

User asked for more performance with NO new settings or sliders, so these are
all same-output optimisations — nothing here changes what the frame looks like.

**1. Terrain tiles are frustum-culled (`_visible_terrain_tiles`).** Terrain drew
tile-by-tile with no culling whatsoever: every tile's full mesh (often 1.5M+
indices) went down every frame in the MAIN pass and again in the mirrored
water-reflection pass. On FC2's 5x5 grid that is 25 full tiles per pass no matter
where the camera points. Now each tile gets a world bounding sphere
(`_tile_sphere`, computed once from the mesh vertices and cached on the model as
`_tile_sphere_local`, offset per frame) tested by `_sphere_in_view`.

- `_sphere_in_view` deliberately reuses the ENTITY cull's near/vertical/
  horizontal sphere-expanded tests at VFOV 50 (the `gluPerspective` the main pass
  sets), so terrain and entities agree about what is on screen.
- **No FAR test** — terrain must stay visible to the projection's own far plane.
- `pad=1.35` widens the frustum; a tile is drawn unless provably off-screen. A
  false cull is a hole in the world, so every failure path returns True.
- The reflection pass culls against MIRRORED centres (`mirror_y=plane_y`).
- **Single-tile levels are skipped entirely** (`len(tiles) <= 1` returns the list
  unchanged), and the separate `self.terrain_model` singular path is untouched —
  one tile spans the whole level, so the camera is nearly always inside it and
  the test would never pay off. **This means Avatar single-cell levels get no
  benefit from this change; it is an FC2 multi-cell win.**
- `_cast_terrain_depth` (shadow map) is deliberately NOT culled this way — it
  renders from the LIGHT's frustum, and off-screen geometry legitimately casts
  shadows into view. Don't "fix" that.

**2. The reflection pass is skipped when no water is on screen
(`_water_on_screen`).** It is a complete mirrored re-render of terrain + models,
and it ran whenever the level contained water ANYWHERE — look away from a lake,
or stand above it, and you still paid a whole extra scene pass whose texture
nothing sampled. `water_plane_renderer` now caches the world bounding sphere of
all its quads as `_water_bounds` alongside the water VBO (same rebuild
signature), and the canvas frustum-tests it. Returns True when bounds are unknown
(first frame, before the water VBO exists) so the reflection is never wrongly
withheld; levels with no water at all are still short-circuited by
`_water_plane_height() is None` as before.

**3. `_water_plane_height()` is cached.** It walked every sector of every cell
and built a `Counter` EVERY frame to find one float. Now keyed on
`(id(terrain_renderer), water_plane_renderer._water_vbo_sig)` — the answer only
changes when the water geometry does.

**Still on the table, deliberately NOT done:** a render-scale option (render the
scene at 50-85% into an FBO and upscale) is by far the biggest remaining GPU
lever, but it trades image quality, so it needs to be a user choice rather than a
silent default. The depth prepass (F8) still defaults OFF — it is an
exact-same-image optimisation but a real trade (a cheap depth pass to cut
overdraw in the expensive shading pass), so it needs measuring per-scene before
being flipped, not guessing.

## moviedata sequences now ROTATE, not just move (July 2026)

User report: previewed cutscene objects slid along their path frozen at their
authored angle — "they move, but they don't rotate, the pitch/yaw doesn't do
anything". Cause: `_movie_apply_time` only applied `pos_at(t)`. The ParamId-2
quaternion track was fully parsed (`rot_at` even slerps it) and then thrown
away. **291 of 532 Avatar sequences and 550 of 747 nodes animate rotation**
(3,730 RotKeys) — including the Samson intro/outro sequences.

**`movie_data.quat_to_editor_angles(q)`** (pure stdlib, unit-tested) converts a
track quaternion `(w, x, y, z)` to the `(rotation_x, rotation_y, rotation_z)`
degrees that `model_loader._get_entity_rs` feeds both render paths.

Derivation — both paths compose the SAME transform (the GDR shader's `modelRot`
and the classic `glRotatef` sequence, which the shader comment says must stay
identical):

    p' = Rx(-90) · Rz(-rz) · Rx(rx) · Ry(ry) · p

`Rx(-90)` maps (x,y,z)→(x,z,-y), i.e. it is ONLY the game(Z-up)→GL(Y-up) flip.
So the game-space rotation is `Rz(az)·Rx(ax)·Ry(ay)` — a **ZXY** euler
decomposition — and the editor's convention is `rx = ax`, `ry = ay`,
`rz = (360 - az) % 360` (the same Z negation `_get_entity_rs` applies to
`hidAngles`).

**Quaternion component order is (w, x, y, z)** — confirmed on 333 moviedata
NodeDef ↔ world-entity pairs: 84.7% of decoded eulers match the entity's stored
`hidAngles` within 0.5° under (w,x,y,z) versus **0%** under (x,y,z,w). The
non-matching 15% are equivalent euler branches or NodeDef rest poses that
genuinely differ from the entity's current world angles — comparing MATRICES,
the decode round-trips at 1e-15.

**GOTCHA — the gimbal-lock branch is sign-dependent.** At pitch ±90 the Y and Z
axes are degenerate and Y folds into Z, but the matrix gives `cos/sin(c+b)` at
**+90** and `cos/sin(c−b)` at **−90**. Using the −90 form at +90 mirrors the
object's yaw. Six real keys in `sp_pascal_fm_01_l/FM01_Plateforme_SkyAttack_1`
hit exactly this and were wrong by 1.9 in matrix terms until fixed:
`az = atan2(m02 if sa > 0 else -m02, m00)`. There is a regression test.

**Verified on real data:** across every Avatar level — 3,730 raw RotKeys plus 21
interpolated slerp samples per node, 15,280 rotations total — the worst angular
error between what the editor renders and the authored quaternion is
**0.000153°** (the 6-significant-digit floor of the XML itself).

**Applying it without dirtying the level:** `canvas.patch_preview_rotations(
[(entity, rx, ry, rz), …])` writes the override straight into
`model_loader._entity_rs_cache` and calls `gdr_refresh_entity` (which re-reads
through that same cache, so the GDR row tables pick it up too). **No XML is
touched**, so a preview can never dirty the file — the same guarantee the
position preview has. `clear_preview_rotations(entities)` pops the entries so
the entities read their real angles again, and `_movie_preview_stop` calls it
**unconditionally** (even for `restore=False`) so a preview can't leave an
object mis-rotated. Both also clear `_ov_cache_key`, because rotation feeds the
cached wireframe overlays and rotation edits don't bump the position version.

**Fallback:** a node whose rotation track has no keys falls back to its NodeDef
`Rotate` rest pose, so it uses its scene orientation rather than whatever the
entity's XML currently says.

**Repaint:** `_movie_apply_time` now calls `canvas.update()` when EITHER
positions or rotations changed — a door that only swings has no position track
and would otherwise never trigger a repaint.

**Not done:** 2D-mode squares still use their XML rotation during playback. 2D
only draws rotation at all when a rotation gizmo is active, so it is cosmetic
there; the style array's rotation column would need patching to match.
