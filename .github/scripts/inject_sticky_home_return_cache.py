from pathlib import Path


def block(*lines: str) -> str:
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Sticky-only experiment: keep the expensive full-screen carousel snapshot keyed
# only by static/layout state. Reading progress and stats are tiny dynamic footer
# content, so redraw that footer after restoring a frame instead of invalidating
# and rewriting every cached Home frame after each reader session.

# ---------------------------------------------------------------------------
# LyraCarouselTheme: expose a tiny dynamic-footer redraw helper. It clears only
# the footer area below the dots, then renders the current reading time/progress.
# ---------------------------------------------------------------------------
header_path = Path("src/components/themes/lyra/LyraCarouselTheme.h")
header = header_path.read_text()
header = replace_once(
    header,
    block(
        '  void drawCarouselBorder(GfxRenderer& renderer, Rect coverRect, const std::vector<RecentBook>& recentBooks,',
        '                          int centerIdx, bool inCarouselRow) const override;',
    ),
    block(
        '  void drawCarouselBorder(GfxRenderer& renderer, Rect coverRect, const std::vector<RecentBook>& recentBooks,',
        '                          int centerIdx, bool inCarouselRow) const override;',
        '  void drawCarouselDynamicFooter(GfxRenderer& renderer, Rect coverRect,',
        '                                 const std::vector<RecentBook>& recentBooks, int centerIdx,',
        '                                 const BookReadingStats* stats, float progressPercent) const;',
    ),
    "carousel dynamic footer declaration",
)
header_path.write_text(header)

cpp_path = Path("src/components/themes/lyra/LyraCarouselTheme.cpp")
cpp = cpp_path.read_text()
footer_method = block(
    '',
    'void LyraCarouselTheme::drawCarouselDynamicFooter(GfxRenderer& renderer, Rect coverRect,',
    '                                                    const std::vector<RecentBook>& recentBooks, int centerIdx,',
    '                                                    const BookReadingStats* stats, float progressPercent) const {',
    '  const int bookCount = static_cast<int>(recentBooks.size());',
    '  if (bookCount <= 0 || centerIdx < 0 || centerIdx >= bookCount) return;',
    '',
    '  const Rect centerCoverSlotRect = computeCenterCoverSlotRect(renderer, coverRect, recentBooks);',
    '  const Rect centerCoverRect = shrinkCenterCoverRect(centerCoverSlotRect);',
    '  const int dotsY = centerCoverSlotRect.y + centerCoverSlotRect.height + 8;',
    '  constexpr int footerLabelFontId = UI_10_FONT_ID;',
    '  const int footerLabelLineHeight = renderer.getLineHeight(footerLabelFontId);',
    '  const bool hasStats = (stats != nullptr && stats->sessionCount > 0);',
    '  const bool hasProgress = progressPercent >= 0.0f;',
    '  const int infoY = dotsY + kDotSize + kFooterTopGap;',
    '  const int footerMaxWidth =',
    '      std::max(0, renderer.getScreenWidth() - 2 * LyraCarouselMetrics::values.contentSidePadding);',
    '  const int footerWidth = std::min(footerMaxWidth, centerCoverRect.width);',
    '  const int footerX = centerCoverRect.x + (centerCoverRect.width - footerWidth) / 2;',
    '  const int clearHeight = footerLabelLineHeight + kFooterLabelToBarGap + kFooterProgressBarHeight +',
    '                          kFooterPercentTopGap + footerLabelLineHeight + 6;',
    '  if (footerWidth > 0 && clearHeight > 0) {',
    '    renderer.fillRect(footerX, infoY, footerWidth, clearHeight, false);',
    '  }',
    '',
    '  if (hasStats) {',
    '    char buf[48];',
    '    formatCompactReadingTime(stats->totalReadingSeconds, buf, sizeof(buf));',
    '    const auto timeLabel =',
    '        renderer.truncatedText(footerLabelFontId, buf, footerWidth, EpdFontFamily::REGULAR);',
    '    renderer.drawText(footerLabelFontId, footerX, infoY, timeLabel.c_str(), true, EpdFontFamily::REGULAR);',
    '  }',
    '',
    '  if (hasProgress) {',
    '    const int progressBarY = infoY + (hasStats ? footerLabelLineHeight + kFooterLabelToBarGap : 0);',
    '    const float clampedProgress = std::clamp(progressPercent, 0.0f, 100.0f);',
    '    const int filledWidth =',
    '        std::clamp(static_cast<int>((clampedProgress / 100.0f) * footerWidth), 0, footerWidth);',
    '    char progressLabel[16];',
    '    snprintf(progressLabel, sizeof(progressLabel), "%.0f%%", clampedProgress);',
    '    renderer.fillRectDither(footerX, progressBarY, footerWidth, kFooterProgressBarHeight, Color::LightGray);',
    '    if (filledWidth > 0) {',
    '      renderer.fillRect(footerX, progressBarY, filledWidth, kFooterProgressBarHeight, true);',
    '    }',
    '    const int progressLabelW =',
    '        renderer.getTextWidth(footerLabelFontId, progressLabel, EpdFontFamily::REGULAR);',
    '    const int progressLabelY = progressBarY + kFooterProgressBarHeight + kFooterPercentTopGap;',
    '    renderer.drawText(footerLabelFontId, footerX + footerWidth - progressLabelW, progressLabelY, progressLabel, true,',
    '                      EpdFontFamily::REGULAR);',
    '  }',
    '}',
    '',
)
cpp = replace_once(
    cpp,
    block(
        '// ---------------------------------------------------------------------------',
        '// Horizontal icon-only menu row — anchored to bottom of screen',
        '// ---------------------------------------------------------------------------',
    ),
    footer_method
    + block(
        '// ---------------------------------------------------------------------------',
        '// Horizontal icon-only menu row — anchored to bottom of screen',
        '// ---------------------------------------------------------------------------',
    ),
    "carousel dynamic footer implementation",
)
cpp_path.write_text(cpp)


# ---------------------------------------------------------------------------
# HomeActivity: use a static carousel cache key and refresh only dynamic footer.
# ---------------------------------------------------------------------------
home_path = Path("src/activities/home/HomeActivity.cpp")
home = home_path.read_text()

home = replace_once(
    home,
    'constexpr uint16_t CAROUSEL_CACHE_VERSION = 5;',
    'constexpr uint16_t CAROUSEL_CACHE_VERSION = 6;',
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
    '  // Reading progress/stat contents are intentionally excluded from the full-frame cache key.',
    '  // They are redrawn as a tiny dynamic footer after a static frame is restored.',
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
        '  // Global/stat values do not alter carousel geometry. Menu visibility is already',
        '  // represented above by appendCarouselMenuStateToKey().',
        '  keyHash = fnvHash64(key);',
    ),
    "remove global dynamic carousel key state",
)

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
    '    LOG_INF("HOME", "[HOMERET] static cache miss");',
    '  }',
)
home = replace_once(home, old_enter_cache, new_enter_cache, "Home return cache profiler")

old_fast_header = block(
    '      // Cached carousel frames include the header; redraw it so dynamic values',
    '      // like battery percentage and clock are current for every restored frame.',
    '      GUI.drawHeader(renderer, Rect{0, metrics.topPadding, pageWidth, metrics.homeTopPadding}, nullptr);',
    '      GUI.drawCarouselBorder(renderer, Rect{0, metrics.homeTopPadding, pageWidth, metrics.homeCoverTileHeight},',
    '                             recentBooks, centerIdx, inCarouselRow);',
)
new_fast_header = block(
    '      // Cached carousel frames include the header; redraw it so dynamic values',
    '      // like battery percentage and clock are current for every restored frame.',
    '      GUI.drawHeader(renderer, Rect{0, metrics.topPadding, pageWidth, metrics.homeTopPadding}, nullptr);',
    '',
    '      // Reading time/progress change on every reader session. Keep the expensive',
    '      // full-frame snapshot static and redraw only this small footer region.',
    '      const BookReadingStats* liveFrameStats = nullptr;',
    '      float liveFrameProgress = -1.0f;',
    '      if (bookStatsCached && centerIdx >= 0 && centerIdx < kMaxCachedBooks) {',
    '        liveFrameStats = hasAnyBookStats(cachedBookStats[centerIdx]) ? &cachedBookStats[centerIdx] : nullptr;',
    '        liveFrameProgress = cachedBookProgress[centerIdx];',
    '      } else if (centerIdx == getHighlightedBookIndex()) {',
    '        liveFrameStats = hasAnyBookStats(currentBookStats) ? &currentBookStats : nullptr;',
    '        liveFrameProgress = currentBookProgressPercent;',
    '      }',
    '      static_cast<const LyraCarouselTheme&>(GUI).drawCarouselDynamicFooter(',
    '          renderer, Rect{0, metrics.homeTopPadding, pageWidth, metrics.homeCoverTileHeight}, recentBooks, centerIdx,',
    '          liveFrameStats, liveFrameProgress);',
    '      LOG_INF("HOME", "[HOMERET] dynamic footer center=%d progress=%d", centerIdx,',
    '              liveFrameProgress >= 0.0f ? static_cast<int>(liveFrameProgress + 0.5f) : -1);',
    '',
    '      GUI.drawCarouselBorder(renderer, Rect{0, metrics.homeTopPadding, pageWidth, metrics.homeCoverTileHeight},',
    '                             recentBooks, centerIdx, inCarouselRow);',
)
home = replace_once(home, old_fast_header, new_fast_header, "Home restored-frame dynamic footer")

home_path.write_text(home)
