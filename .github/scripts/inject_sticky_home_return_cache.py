from pathlib import Path


def block(*lines: str) -> str:
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Sticky-only Run #27 experiment, plus Run #30 diagnostics.
#
# Sticky intentionally keeps only one full carousel framebuffer in internal RAM.
# The old path treated that 1/1 RAM allocation as a "full" cache and then
# synchronously rendered every remaining book into a three-frame SD snapshot.
# That is the ~4.5s `built SD cache for 3 book(s)` pause seen on every
# Reader->Home cache miss.
#
# Keep only the currently-visible center frame synchronous. If the user later
# moves the carousel to another center book, recycle the same RAM slot and
# render that frame on demand. Do not reintroduce the unstable dynamic-footer
# overlay from Run #25.
#
# Run #30 adds diagnostics only: render-task stack high-water marks, ESP heap
# integrity checks, phase markers around Lyra's first render/warmup, and a
# 64-byte tail guard after each carousel framebuffer. The guard is outside the
# 800x480 framebuffer and must never be touched by normal rendering.

home_path = Path("src/activities/home/HomeActivity.cpp")
home = home_path.read_text()

# Force the experiment to start from a cache miss rather than accidentally
# accepting a full-frame snapshot produced by an older test build.
home = replace_once(
    home,
    'constexpr uint16_t CAROUSEL_CACHE_VERSION = 5;',
    'constexpr uint16_t CAROUSEL_CACHE_VERSION = 8;',
    "carousel cache version bump",
)

# Profile only the one frame that Home actually needs first.
home = replace_once(
    home,
    block(
        '  loadOrRender(initialBookIdx, 0);',
        '  gCarouselCache.lastCenterIdx = initialBookIdx;',
    ),
    block(
        '  const uint32_t initialFrameStartMs = millis();',
        '  loadOrRender(initialBookIdx, 0);',
        '  LOG_INF("HOME", "[HOMELAZY] initial center=%d disk=%d time=%lums", initialBookIdx,',
        '          diskCacheValid ? 1 : 0, static_cast<unsigned long>(millis() - initialFrameStartMs));',
        '  gCarouselCache.lastCenterIdx = initialBookIdx;',
    ),
    "profile initial carousel frame",
)

# A one-frame Sticky RAM cache is not a complete bookCount-frame snapshot.
# Therefore do not enter buildCarouselCacheFile(), whose loop renders and writes
# all books synchronously. This is the core Run #27 change.
home = replace_once(
    home,
    '  const bool hasFullFrameCache = gCarouselCache.frameCount >= targetFrameCount;',
    '  const bool hasFullFrameCache = gCarouselCache.frameCount >= bookCount;',
    "require every book frame before full snapshot build",
)

home = replace_once(
    home,
    block(
        '    } else {',
        '      LOG_INF("HOME", "carousel: skipping SD cache build in degraded frame cache mode");',
        '    }',
        '  }',
        '  return showedProgressPopup;',
        '}',
    ),
    block(
        '    } else {',
        '      LOG_INF("HOME", "[HOMELAZY] defer full SD snapshot ram=%d books=%d current=%d",',
        '              gCarouselCache.frameCount, bookCount, initialBookIdx);',
        '    }',
        '  }',
        '  return showedProgressPopup;',
        '}',
    ),
    "log deferred full carousel snapshot",
)

# Existing fast path only knows how to page a missing center from a *valid* SD
# snapshot. When no valid snapshot exists, recycle the one RAM slot and render
# the newly-selected center lazily instead of falling back to the generic Home
# renderer.
old_missing_frame = block(
    '    if (frameBuffer && slotIdx < 0 && gCarouselCache.keyHash != 0 && bookCount > 0) {',
    '      const int evictSlot = chooseCarouselEvictionSlot(centerIdx, bookCount);',
    '      if (evictSlot >= 0 && loadCarouselFrameFromDisk(gCarouselCache.keyHash, bookCount, centerIdx, evictSlot)) {',
    '        slotIdx = evictSlot;',
    '      }',
    '    }',
)
new_missing_frame = block(
    '    if (frameBuffer && slotIdx < 0 && bookCount > 0) {',
    '      const int evictSlot = chooseCarouselEvictionSlot(centerIdx, bookCount);',
    '      if (evictSlot >= 0) {',
    '        bool loadedFromDisk = false;',
    '        if (gCarouselCache.keyHash != 0) {',
    '          loadedFromDisk = loadCarouselFrameFromDisk(gCarouselCache.keyHash, bookCount, centerIdx, evictSlot);',
    '        }',
    '        if (loadedFromDisk) {',
    '          slotIdx = evictSlot;',
    '          LOG_INF("HOME", "[HOMELAZY] nav center=%d source=disk", centerIdx);',
    '        } else {',
    '          const uint32_t lazyFrameStartMs = millis();',
    '          renderCarouselFrame(centerIdx, evictSlot);',
    '          slotIdx = gCarouselCache.findFrameSlot(centerIdx);',
    '          LOG_INF("HOME", "[HOMELAZY] nav center=%d source=live ready=%d time=%lums", centerIdx,',
    '                  slotIdx >= 0 ? 1 : 0, static_cast<unsigned long>(millis() - lazyFrameStartMs));',
    '        }',
    '      }',
    '    }',
)
home = replace_once(home, old_missing_frame, new_missing_frame, "lazy carousel navigation frame")

# ---------------------------------------------------------------------------
# Run #30 Lyra corruption diagnostics.
# ---------------------------------------------------------------------------
home = replace_once(
    home,
    '#include <Xtc.h>\n\n#include <algorithm>',
    '#include <Xtc.h>\n\n#include <esp_heap_caps.h>\n#include <freertos/FreeRTOS.h>\n#include <freertos/task.h>\n\n#include <algorithm>',
    "Lyra diagnostic includes",
)

home = replace_once(
    home,
    'constexpr uint32_t CAROUSEL_FRAME_MIN_MAX_ALLOC_AFTER_ALLOC = 24U * 1024U;\n',
    'constexpr uint32_t CAROUSEL_FRAME_MIN_MAX_ALLOC_AFTER_ALLOC = 24U * 1024U;\n'
    'constexpr size_t CAROUSEL_FRAME_GUARD_BYTES = 64;\n'
    'constexpr uint8_t CAROUSEL_FRAME_GUARD_VALUE = 0xD7;\n',
    "carousel diagnostic guard constants",
)

home = replace_once(
    home,
    '      gCarouselCache.frames[i] = static_cast<uint8_t*>(malloc(bufferSize));',
    '      gCarouselCache.frames[i] = static_cast<uint8_t*>(malloc(bufferSize + CAROUSEL_FRAME_GUARD_BYTES));',
    "carousel frame tail guard allocation",
)

home = replace_once(
    home,
    block(
        '      if (!gCarouselCache.frames[i]) {',
        '        LOG_ERR("HOME", "preRenderCarouselFrames: malloc failed for frame %d while allocating %d frame(s)", i,',
        '                attemptFrameCount);',
        '        allocFailed = true;',
        '        break;',
        '      }',
        '      if (!hasHeapForCarouselFrameCache()) {',
    ),
    block(
        '      if (!gCarouselCache.frames[i]) {',
        '        LOG_ERR("HOME", "preRenderCarouselFrames: malloc failed for frame %d while allocating %d frame(s)", i,',
        '                attemptFrameCount);',
        '        allocFailed = true;',
        '        break;',
        '      }',
        '      memset(gCarouselCache.frames[i] + bufferSize, CAROUSEL_FRAME_GUARD_VALUE, CAROUSEL_FRAME_GUARD_BYTES);',
        '      if (!hasHeapForCarouselFrameCache()) {',
    ),
    "initialize carousel frame tail guard",
)

home = replace_once(
    home,
    'CarouselCache gCarouselCache;\n}  // namespace\n',
    block(
        'CarouselCache gCarouselCache;',
        '',
        'bool checkCarouselFrameGuards(const GfxRenderer& renderer, const char* phase) {',
        '  const size_t bufferSize = renderer.getBufferSize();',
        '  bool ok = true;',
        '  for (int slot = 0; slot < HomeActivity::kCarouselFrameCount; ++slot) {',
        '    const uint8_t* frame = gCarouselCache.frames[slot];',
        '    if (!frame) continue;',
        '    for (size_t i = 0; i < CAROUSEL_FRAME_GUARD_BYTES; ++i) {',
        '      if (frame[bufferSize + i] != CAROUSEL_FRAME_GUARD_VALUE) {',
        '        LOG_ERR("HOME", "[LYRADIAG] frame guard CORRUPT phase=%s slot=%d offset=%u value=%u", phase, slot,',
        '                static_cast<unsigned>(i), static_cast<unsigned>(frame[bufferSize + i]));',
        '        ok = false;',
        '        break;',
        '      }',
        '    }',
        '  }',
        '  return ok;',
        '}',
        '',
        'void logLyraDiagPhase(const GfxRenderer& renderer, const char* phase) {',
        '  const UBaseType_t stackHighWater = uxTaskGetStackHighWaterMark(nullptr);',
        '  const bool heapOk = heap_caps_check_integrity_all(false);',
        '  const bool guardOk = checkCarouselFrameGuards(renderer, phase);',
        '  LOG_INF("HOME", "[LYRADIAG] phase=%s stack_hwm=%u heap=%d guard=%d free=%u maxAlloc=%u", phase,',
        '          static_cast<unsigned>(stackHighWater), heapOk ? 1 : 0, guardOk ? 1 : 0, ESP.getFreeHeap(),',
        '          ESP.getMaxAllocHeap());',
        '}',
        '}  // namespace',
    ) + '\n',
    "Lyra diagnostic helpers",
)

home = replace_once(
    home,
    'void HomeActivity::render(RenderLock&&) {\n  if (quickActionsPopup.processRender(renderer, mappedInput)) {',
    block(
        'void HomeActivity::render(RenderLock&&) {',
        '  if (static_cast<CrossPointSettings::UI_THEME>(SETTINGS.uiTheme) ==',
        '      CrossPointSettings::UI_THEME::LYRA_CAROUSEL) {',
        '    logLyraDiagPhase(renderer, "render_enter");',
        '  }',
        '  if (quickActionsPopup.processRender(renderer, mappedInput)) {',
    ),
    "Lyra render entry diagnostics",
)

slow_cover_draw = block(
    '  GUI.drawRecentBookCover(renderer, Rect{0, metrics.homeTopPadding, pageWidth, homeCoverTileHeight}, recentBooks,',
    '                          selectorIndex, coverRendered, coverBufferStored, bufferRestored,',
    '                          std::bind(&HomeActivity::storeCoverBuffer, this),',
    '                          hasAnyBookStats(currentBookStats) ? &currentBookStats : nullptr, currentBookProgressPercent);',
)
home = replace_once(
    home,
    slow_cover_draw,
    block(
        '  if (isCarouselTheme) logLyraDiagPhase(renderer, "before_first_cover_draw");',
        slow_cover_draw,
        '  if (isCarouselTheme) logLyraDiagPhase(renderer, "after_first_cover_draw");',
    ),
    "Lyra first cover draw diagnostics",
)

home = replace_once(
    home,
    block(
        '  if (!recentsLoaded && !recentsLoading) {',
        '    recentsLoading = true;',
        '    loadRecentCovers(metrics.homeCoverHeight);',
        '  }',
        '',
        '  if (carouselWarmupPending && !carouselFramesReady) {',
    ),
    block(
        '  if (!recentsLoaded && !recentsLoading) {',
        '    if (isCarouselTheme) logLyraDiagPhase(renderer, "before_load_recent_covers");',
        '    recentsLoading = true;',
        '    loadRecentCovers(metrics.homeCoverHeight);',
        '    if (isCarouselTheme) logLyraDiagPhase(renderer, "after_load_recent_covers");',
        '  }',
        '',
        '  if (carouselWarmupPending && !carouselFramesReady) {',
    ),
    "Lyra recent cover diagnostics",
)

home = replace_once(
    home,
    block(
        '    carouselWarmupPending = false;',
        '    const bool showedWarmupProgress = preRenderCarouselFrames(true);',
        '    if (carouselFramesReady || showedWarmupProgress) {',
    ),
    block(
        '    carouselWarmupPending = false;',
        '    if (isCarouselTheme) logLyraDiagPhase(renderer, "before_carousel_warmup");',
        '    const bool showedWarmupProgress = preRenderCarouselFrames(true);',
        '    if (isCarouselTheme) logLyraDiagPhase(renderer, "after_carousel_warmup");',
        '    if (carouselFramesReady || showedWarmupProgress) {',
    ),
    "Lyra warmup diagnostics",
)

home = replace_once(
    home,
    '  LOG_INF("HOME", "carousel: frame cache capacity %d/%d", frameCount, targetFrameCount);\n  return true;',
    block(
        '  LOG_INF("HOME", "carousel: frame cache capacity %d/%d", frameCount, targetFrameCount);',
        '  checkCarouselFrameGuards(renderer, "after_alloc");',
        '  logLyraDiagPhase(renderer, "after_frame_alloc");',
        '  return true;',
    ),
    "carousel allocation diagnostics",
)

home = replace_once(
    home,
    block(
        '  memcpy(gCarouselCache.frames[slotIdx], frameBuffer, renderer.getBufferSize());',
        '  gCarouselCache.frameBookIdx[slotIdx] = bookIdx;',
        '  carouselFrames[slotIdx] = gCarouselCache.frames[slotIdx];',
        '}',
    ),
    block(
        '  memcpy(gCarouselCache.frames[slotIdx], frameBuffer, renderer.getBufferSize());',
        '  gCarouselCache.frameBookIdx[slotIdx] = bookIdx;',
        '  carouselFrames[slotIdx] = gCarouselCache.frames[slotIdx];',
        '  checkCarouselFrameGuards(renderer, "after_render_frame");',
        '  logLyraDiagPhase(renderer, "after_render_frame");',
        '}',
    ),
    "carousel rendered frame guard diagnostics",
)

home_path.write_text(home)

# Render-task diagnostics are intentionally generic: a healthy ActivityManager
# render stack combined with an ipc1 canary panic strongly points away from a
# normal Home call-depth overflow and toward memory corruption or an IPC-task
# specific path.
activity_path = Path("src/activities/ActivityManager.cpp")
activity = activity_path.read_text()
activity = replace_once(
    activity,
    '#include <Memory.h>\n\n#include <algorithm>',
    '#include <Memory.h>\n\n#include <esp_heap_caps.h>\n#include <freertos/FreeRTOS.h>\n#include <freertos/task.h>\n\n#include <algorithm>',
    "render diagnostic includes",
)
activity = replace_once(
    activity,
    block(
        '    if (currentActivity) {',
        '      HalPowerManager::Lock powerLock;  // Ensure we don\'t go into low-power mode while rendering',
        '      currentActivity->render(std::move(lock));',
        '    }',
    ),
    block(
        '    if (currentActivity) {',
        '      const UBaseType_t stackBefore = uxTaskGetStackHighWaterMark(nullptr);',
        '      const bool heapBefore = heap_caps_check_integrity_all(false);',
        '      LOG_INF("ACT", "[RENDERDIAG] enter activity=%s stack_hwm=%u heap=%d", currentActivity->name.c_str(),',
        '              static_cast<unsigned>(stackBefore), heapBefore ? 1 : 0);',
        '      HalPowerManager::Lock powerLock;  // Ensure we don\'t go into low-power mode while rendering',
        '      currentActivity->render(std::move(lock));',
        '      const UBaseType_t stackAfter = uxTaskGetStackHighWaterMark(nullptr);',
        '      const bool heapAfter = heap_caps_check_integrity_all(false);',
        '      LOG_INF("ACT", "[RENDERDIAG] exit activity=%s stack_hwm=%u heap=%d", currentActivity->name.c_str(),',
        '              static_cast<unsigned>(stackAfter), heapAfter ? 1 : 0);',
        '    }',
    ),
    "render task stack and heap diagnostics",
)
activity_path.write_text(activity)
