from pathlib import Path


def block(*lines: str) -> str:
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Sticky-only Run #27 experiment.
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

home_path.write_text(home)
