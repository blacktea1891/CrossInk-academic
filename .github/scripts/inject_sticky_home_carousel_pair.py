from pathlib import Path


def block(*lines: str) -> str:
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Sticky-only follow-up to inject_sticky_home_png_psram_fastpath.py.
# Lyra carousel needs two cached BMP sizes for the same EPUB cover (center + side).
# Reuse one inflated PNG PSRAM buffer across both conversions instead of inflating
# the same multi-megabyte ZIP member twice. Other Home themes and fallback paths
# remain unchanged.

# ---------------------------------------------------------------------------
# Epub public helper used only by the injected Sticky carousel call site.
# ---------------------------------------------------------------------------
header_path = Path("lib/Epub/Epub.h")
header = header_path.read_text()
header = replace_once(
    header,
    block(
        '  bool generateAdaptiveThumbBmp(int width, int height, const GfxRenderer* renderer = nullptr,',
        '                                int readerFontId = 0) const;',
    ),
    block(
        '  bool generateAdaptiveThumbBmp(int width, int height, const GfxRenderer* renderer = nullptr,',
        '                                int readerFontId = 0) const;',
        '  bool generateCarouselThumbPair(int centerWidth, int centerHeight, int sideWidth, int sideHeight,',
        '                                 bool centerMissing, bool sideMissing, const GfxRenderer* renderer = nullptr,',
        '                                 int readerFontId = 0) const;',
    ),
    "Epub carousel pair declaration",
)
header_path.write_text(header)


# ---------------------------------------------------------------------------
# Epub implementation. The previous Home injector already supplies
# HomeFixedBufferPrint, psram allocation helpers, and RAM PNG decoder support.
# ---------------------------------------------------------------------------
epub_path = Path("lib/Epub/Epub.cpp")
epub = epub_path.read_text()
anchor = block(
    'bool Epub::generateAdaptiveThumbBmp(int width, int height, const GfxRenderer* renderer, const int readerFontId) const {',
    '  return generateThumbBmpInternal(width, height, true, renderer, readerFontId);',
    '}',
    '',
    'std::string Epub::getCachedCoverImagePath(const std::string& coverImageHref) const {',
)
implementation = block(
    'bool Epub::generateAdaptiveThumbBmp(int width, int height, const GfxRenderer* renderer, const int readerFontId) const {',
    '  return generateThumbBmpInternal(width, height, true, renderer, readerFontId);',
    '}',
    '',
    'bool Epub::generateCarouselThumbPair(const int centerWidth, const int centerHeight, const int sideWidth,',
    '                                     const int sideHeight, const bool centerMissing, const bool sideMissing,',
    '                                     const GfxRenderer* renderer, const int readerFontId) const {',
    '  if (!centerMissing && !sideMissing) return true;',
    '',
    '  auto fallback = [&]() {',
    '    bool success = true;',
    '    if (centerMissing) success = generateThumbBmp(centerWidth, centerHeight, renderer, readerFontId) && success;',
    '    if (sideMissing) success = generateThumbBmp(sideWidth, sideHeight, renderer, readerFontId) && success;',
    '    return success;',
    '  };',
    '',
    '  if (!bookMetadataCache || !bookMetadataCache->isLoaded()) {',
    '    LOG_ERR("HOME", "[HOMEPROF] PNG RAM pair cache not loaded; falling back");',
    '    return fallback();',
    '  }',
    '',
    '  const std::string coverImageHref = bookMetadataCache->coreMetadata.coverItemHref;',
    '  if (coverImageHref.empty() || !FsHelpers::hasPngExtension(coverImageHref) || !psramHeapAvailable()) {',
    '    return fallback();',
    '  }',
    '',
    '  size_t sourceSize = 0;',
    '  if (!getItemSize(coverImageHref, &sourceSize) || sourceSize == 0) {',
    '    LOG_INF("HOME", "[HOMEPROF] PNG RAM pair size unavailable; falling back");',
    '    return fallback();',
    '  }',
    '',
    '  auto sourceBuffer = makePsramByteBufferNoThrow(sourceSize);',
    '  if (!sourceBuffer) {',
    '    LOG_INF("HOME", "[HOMEPROF] PNG RAM pair alloc failed bytes=%lu; falling back",',
    '            static_cast<unsigned long>(sourceSize));',
    '    return fallback();',
    '  }',
    '',
    '  const uint32_t pairStartMs = millis();',
    '  LOG_INF("HOME", "[HOMEPROF] PNG RAM pair start source=%s bytes=%lu center=%d side=%d", coverImageHref.c_str(),',
    '          static_cast<unsigned long>(sourceSize), centerMissing ? 1 : 0, sideMissing ? 1 : 0);',
    '  HomeFixedBufferPrint ramSink(sourceBuffer.get(), sourceSize);',
    '  const uint32_t streamStartMs = millis();',
    '  const bool streamed = readItemContentsToStream(coverImageHref, ramSink, 16384);',
    '  const uint32_t streamMs = millis() - streamStartMs;',
    '  const bool complete = streamed && ramSink.bytesWritten() == sourceSize;',
    '  LOG_INF("HOME", "[HOMEPROF] PNG RAM pair stream ok=%d bytes=%lu/%lu time=%lums", complete ? 1 : 0,',
    '          static_cast<unsigned long>(ramSink.bytesWritten()), static_cast<unsigned long>(sourceSize),',
    '          static_cast<unsigned long>(streamMs));',
    '  if (!complete) return fallback();',
    '',
    '  releaseReaderSdFontCachesBeforeCoverDecode(renderer, readerFontId, "carousel PNG pair decode");',
    '',
    '  auto decodeThumb = [&](const int width, const int height, const char* label) {',
    '    const std::string thumbPath = getThumbBmpPath(width, height);',
    '    FsFile thumbBmp;',
    '    if (!Storage.openFileForWrite("EBP", thumbPath, thumbBmp)) {',
    '      LOG_ERR("HOME", "[HOMEPROF] PNG RAM pair %s output open failed", label);',
    '      return false;',
    '    }',
    '    const uint32_t decodeStartMs = millis();',
    '    const bool success = PngToBmpConverter::pngMemoryTo1BitBmpStreamWithSize(',
    '        sourceBuffer.get(), sourceSize, thumbBmp, width, height, false);',
    '    const uint32_t decodeMs = millis() - decodeStartMs;',
    '    thumbBmp.close();',
    '    LOG_INF("HOME", "[HOMEPROF] PNG RAM pair %s ok=%d decode=%lums elapsed=%lums", label, success ? 1 : 0,',
    '            static_cast<unsigned long>(decodeMs), static_cast<unsigned long>(millis() - pairStartMs));',
    '    if (!success) Storage.remove(thumbPath.c_str());',
    '    return success;',
    '  };',
    '',
    '  bool success = true;',
    '  if (centerMissing) success = decodeThumb(centerWidth, centerHeight, "center") && success;',
    '  if (sideMissing) success = decodeThumb(sideWidth, sideHeight, "side") && success;',
    '  LOG_INF("HOME", "[HOMEPROF] PNG RAM pair done ok=%d total=%lums", success ? 1 : 0,',
    '          static_cast<unsigned long>(millis() - pairStartMs));',
    '  return success;',
    '}',
    '',
    'std::string Epub::getCachedCoverImagePath(const std::string& coverImageHref) const {',
)
epub = replace_once(epub, anchor, implementation, "Epub carousel pair implementation")
epub_path.write_text(epub)


# ---------------------------------------------------------------------------
# Lyra carousel: replace its two sequential EPUB thumbnail calls with the pair
# helper. XTC and all non-carousel paths remain untouched.
# ---------------------------------------------------------------------------
home_path = Path("src/activities/home/HomeActivity.cpp")
home = home_path.read_text()
old = block(
    '            bool success = true;',
    '            if (centerMissing)',
    '              success = epub.generateThumbBmp(LyraCarouselTheme::kCenterThumbW, LyraCarouselTheme::kCenterThumbH,',
    '                                              &renderer, SETTINGS.getReaderFontId()) &&',
    '                        success;',
    '            if (sideMissing)',
    '              success = epub.generateThumbBmp(LyraCarouselTheme::kSideCoverW, LyraCarouselTheme::kSideCoverH, &renderer,',
    '                                              SETTINGS.getReaderFontId()) &&',
    '                        success;',
)
new = block(
    '            const bool success = epub.generateCarouselThumbPair(',
    '                LyraCarouselTheme::kCenterThumbW, LyraCarouselTheme::kCenterThumbH, LyraCarouselTheme::kSideCoverW,',
    '                LyraCarouselTheme::kSideCoverH, centerMissing, sideMissing, &renderer, SETTINGS.getReaderFontId());',
)
home = replace_once(home, old, new, "Lyra EPUB carousel pair call")
home_path.write_text(home)

print("Sticky Home carousel PNG pair reuse injected successfully")
