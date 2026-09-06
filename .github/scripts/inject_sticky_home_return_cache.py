from pathlib import Path


def block(*lines: str) -> str:
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Sticky-only diagnostic after the first Reader->Home cache experiment exposed an
# intermittent ipc1 stack-canary panic. Keep the safe part of that experiment
# (exclude reading progress/stat contents from the full-frame key), but do NOT
# inject the dynamic footer redraw. Instead log the static key/header and the
# recent-book order so we can distinguish dynamic-stat invalidation from the
# Reader's intentional recent-book promotion.

home_path = Path("src/activities/home/HomeActivity.cpp")
home = home_path.read_text()

home = replace_once(
    home,
    'constexpr uint16_t CAROUSEL_CACHE_VERSION = 5;',
    'constexpr uint16_t CAROUSEL_CACHE_VERSION = 7;',
    "carousel cache version bump",
)

old_dynamic_cover_key = block(
    '  const std::string cachePath = getRecentBookCachePath(book);',
    '  if (!cachePath.empty()) {',
    '    appendHashedFileStateToKey(key, cachePath + "/progress.bin");',
    '    if (FsHelpers::hasEpubExtension(book.path) || FsHelpers::hasXtcExtension(book.path)) {',
    '      appendHashedFileStateToKey(key, cachePath + "/stats_v5.bin");',
    '    }',
    '  } else {',
    '    key += "no-cache-path";',
    "    key += '\\0';",
    '  }',
)
new_dynamic_cover_key = block(
    '  // Reading progress/stat contents are intentionally excluded from this diagnostic static key.',
)
home = replace_once(home, old_dynamic_cover_key, new_dynamic_cover_key, "remove per-book dynamic carousel key state")

home = replace_once(
    home,
    block(
        '  for (const auto& book : recentBooks) {',
        '    appendCarouselCoverStateToKey(key, book);',
        '  }',
        '  appendHashedFileStateToKey(key, "/.crosspoint/global_stats.bin");',
        '  appendSyncedStatsStateToKey(key);',
        '  keyHash = fnvHash64(key);',
    ),
    block(
        '  for (const auto& book : recentBooks) {',
        '    appendCarouselCoverStateToKey(key, book);',
        '  }',
        '  // Global/stat values are diagnostic-dynamic and excluded here. Menu visibility',
        '  // remains represented by appendCarouselMenuStateToKey().',
        '  keyHash = fnvHash64(key);',
    ),
    "remove global dynamic carousel key state",
)

old_valid = block(
    'bool hasValidCarouselDiskCache(const std::vector<RecentBook>& recentBooks, const GfxRenderer& renderer,',
    '                               const bool hasOpdsServers, const bool hasReadingStats, const bool hasBookmarks,',
    '                               const bool hasClippings) {',
    '  const int bookCount = static_cast<int>(recentBooks.size());',
    '  if (bookCount <= 0) return false;',
    '',
    '  std::string cacheKey;',
    '  uint64_t cacheKeyHash = 0;',
    '  buildCarouselCacheKey(recentBooks, hasOpdsServers, hasReadingStats, hasBookmarks, hasClippings, cacheKey,',
    '                        cacheKeyHash);',
    '',
    '  FsFile cacheFile;',
    '  if (!Storage.openFileForRead("HOME", CAROUSEL_CACHE_PATH, cacheFile)) {',
    '    return false;',
    '  }',
    '',
    '  CarouselCacheHeader header{};',
    '  const bool readOk = readCarouselCacheHeader(cacheFile, header);',
    '  cacheFile.close();',
    '  return readOk && isCarouselCacheHeaderValid(header, cacheKeyHash, bookCount, renderer);',
    '}',
)
new_valid = block(
    'bool hasValidCarouselDiskCache(const std::vector<RecentBook>& recentBooks, const GfxRenderer& renderer,',
    '                               const bool hasOpdsServers, const bool hasReadingStats, const bool hasBookmarks,',
    '                               const bool hasClippings) {',
    '  const int bookCount = static_cast<int>(recentBooks.size());',
    '  if (bookCount <= 0) return false;',
    '',
    '  std::string cacheKey;',
    '  uint64_t cacheKeyHash = 0;',
    '  buildCarouselCacheKey(recentBooks, hasOpdsServers, hasReadingStats, hasBookmarks, hasClippings, cacheKey,',
    '                        cacheKeyHash);',
    '  LOG_INF("HOME", "[HOMERET] key=%" PRIu64 " books=%d menu=%d%d%d%d", cacheKeyHash, bookCount,',
    '          hasOpdsServers ? 1 : 0, hasReadingStats ? 1 : 0, hasBookmarks ? 1 : 0, hasClippings ? 1 : 0);',
    '  for (int i = 0; i < bookCount; ++i) {',
    '    LOG_INF("HOME", "[HOMERET] order[%d]=%" PRIu64, i, fnvHash64(recentBooks[i].path));',
    '  }',
    '',
    '  FsFile cacheFile;',
    '  if (!Storage.openFileForRead("HOME", CAROUSEL_CACHE_PATH, cacheFile)) {',
    '    LOG_INF("HOME", "[HOMERET] disk cache missing");',
    '    return false;',
    '  }',
    '',
    '  CarouselCacheHeader header{};',
    '  const bool readOk = readCarouselCacheHeader(cacheFile, header);',
    '  cacheFile.close();',
    '  const bool valid = readOk && isCarouselCacheHeaderValid(header, cacheKeyHash, bookCount, renderer);',
    '  LOG_INF("HOME", "[HOMERET] header read=%d version=%u key=%" PRIu64 " count=%u valid=%d", readOk ? 1 : 0,',
    '          static_cast<unsigned>(header.version), header.keyHash, static_cast<unsigned>(header.frameCount),',
    '          valid ? 1 : 0);',
    '  return valid;',
    '}',
)
home = replace_once(home, old_valid, new_valid, "static carousel key diagnostics")

old_enter_cache = block(
    '  if (isCarouselTheme &&',
    '      hasValidCarouselDiskCache(recentBooks, renderer, hasOpdsServers, hasReadingStats, hasBookmarks, hasClippings)) {',
    '    preRenderCarouselFrames(false);',
    '  }',
)
new_enter_cache = block(
    '  const uint32_t homeReturnCacheStartMs = millis();',
    '  const bool carouselDiskCacheValid =',
    '      isCarouselTheme &&',
    '      hasValidCarouselDiskCache(recentBooks, renderer, hasOpdsServers, hasReadingStats, hasBookmarks, hasClippings);',
    '  if (carouselDiskCacheValid) {',
    '    preRenderCarouselFrames(false);',
    '    LOG_INF("HOME", "[HOMERET] static cache restore ready=%d time=%lums", carouselFramesReady ? 1 : 0,',
    '            static_cast<unsigned long>(millis() - homeReturnCacheStartMs));',
    '  } else if (isCarouselTheme) {',
    '    LOG_INF("HOME", "[HOMERET] static cache miss time=%lums",',
    '            static_cast<unsigned long>(millis() - homeReturnCacheStartMs));',
    '  }',
)
home = replace_once(home, old_enter_cache, new_enter_cache, "Home return cache profiler")

home_path.write_text(home)
