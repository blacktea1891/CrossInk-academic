from pathlib import Path


def block(*lines: str) -> str:
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_first(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count < 1:
        raise SystemExit(f"{label}: expected at least one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# ImageBlock: cache -> lazy extraction -> source open -> decoder boundaries.
# ---------------------------------------------------------------------------
path = Path("lib/Epub/Epub/blocks/ImageBlock.cpp")
text = path.read_text()
text = replace_once(
    text,
    block('#include "ImageBlock.h"', '', '#include <FontCacheManager.h>'),
    block('#include "ImageBlock.h"', '', '#include <Arduino.h>', '#include <FontCacheManager.h>'),
    "ImageBlock Arduino include",
)
text = replace_once(
    text,
    block('  // Try to render from cache first', '  std::string cachePath = getCachePath(imagePath);'),
    block(
        '  const uint32_t pipelineStartMs = millis();',
        '  // Try to render from cache first',
        '  std::string cachePath = getCachePath(imagePath);',
        '  const uint32_t cacheStartMs = millis();',
    ),
    "ImageBlock pipeline start",
)
text = replace_once(
    text,
    block(
        '  if (renderFromCache(renderer, cachePath, x, y, width, height)) {',
        '    return;  // Successfully rendered from cache',
        '  }',
        '',
        '  if (!sourcePath.empty() && extractFn && !Storage.exists(imagePath.c_str())) {',
        '    if (!extractFn(extractContext, sourcePath.c_str(), imagePath.c_str())) {',
        '      LOG_ERR("IMG", "Lazy extraction failed: %s", sourcePath.c_str());',
        '    }',
        '  }',
    ),
    block(
        '  if (renderFromCache(renderer, cachePath, x, y, width, height)) {',
        '    return;  // Successfully rendered from cache',
        '  }',
        '  const uint32_t cacheDoneMs = millis();',
        '  LOG_INF("IMG", "[IMGPIPE] cache miss cache_check=%lums path=%s source=%s",',
        '          static_cast<unsigned long>(cacheDoneMs - cacheStartMs), imagePath.c_str(), sourcePath.c_str());',
        '',
        '  const uint32_t existsStartMs = millis();',
        '  const bool imageAlreadyExtracted = Storage.exists(imagePath.c_str());',
        '  const uint32_t existsDoneMs = millis();',
        '  LOG_INF("IMG", "[IMGPIPE] source exists=%d check=%lums elapsed=%lums", imageAlreadyExtracted ? 1 : 0,',
        '          static_cast<unsigned long>(existsDoneMs - existsStartMs),',
        '          static_cast<unsigned long>(existsDoneMs - pipelineStartMs));',
        '',
        '  if (!sourcePath.empty() && extractFn && !imageAlreadyExtracted) {',
        '    const uint32_t extractStartMs = millis();',
        '    LOG_INF("IMG", "[IMGPIPE] extract start source=%s dest=%s", sourcePath.c_str(), imagePath.c_str());',
        '    const bool extracted = extractFn(extractContext, sourcePath.c_str(), imagePath.c_str());',
        '    const uint32_t extractDoneMs = millis();',
        '    LOG_INF("IMG", "[IMGPIPE] extract done ok=%d time=%lums elapsed=%lums", extracted ? 1 : 0,',
        '            static_cast<unsigned long>(extractDoneMs - extractStartMs),',
        '            static_cast<unsigned long>(extractDoneMs - pipelineStartMs));',
        '    if (!extracted) {',
        '      LOG_ERR("IMG", "Lazy extraction failed: %s", sourcePath.c_str());',
        '    }',
        '  }',
    ),
    "ImageBlock cache/extraction path",
)
text = replace_once(
    text,
    block('  // Check if image file exists', '  FsFile file;'),
    block('  // Check if image file exists', '  const uint32_t openStartMs = millis();', '  FsFile file;'),
    "ImageBlock source open start",
)
text = replace_once(
    text,
    block('  size_t fileSize = file.size();', '  file.close();', '', '  if (fileSize == 0) {'),
    block(
        '  size_t fileSize = file.size();',
        '  file.close();',
        '  const uint32_t openDoneMs = millis();',
        '  LOG_INF("IMG", "[IMGPIPE] source ready bytes=%u open=%lums elapsed=%lums", static_cast<unsigned>(fileSize),',
        '          static_cast<unsigned long>(openDoneMs - openStartMs),',
        '          static_cast<unsigned long>(openDoneMs - pipelineStartMs));',
        '',
        '  if (fileSize == 0) {',
    ),
    "ImageBlock source open done",
)
text = replace_once(
    text,
    '  ImageToFramebufferDecoder* decoder = ImageDecoderFactory::getDecoder(imagePath);',
    block(
        '  const uint32_t decoderLookupStartMs = millis();',
        '  ImageToFramebufferDecoder* decoder = ImageDecoderFactory::getDecoder(imagePath);',
        '  const uint32_t decoderLookupDoneMs = millis();',
        '  LOG_INF("IMG", "[IMGPIPE] decoder lookup found=%d lookup=%lums elapsed=%lums", decoder ? 1 : 0,',
        '          static_cast<unsigned long>(decoderLookupDoneMs - decoderLookupStartMs),',
        '          static_cast<unsigned long>(decoderLookupDoneMs - pipelineStartMs));',
    ),
    "ImageBlock decoder lookup",
)
text = replace_once(
    text,
    '  bool success = decoder->decodeToFramebuffer(imagePath, renderer, config);',
    block(
        '  const uint32_t decodeStartMs = millis();',
        '  LOG_INF("IMG", "[IMGPIPE] decode start elapsed=%lums",',
        '          static_cast<unsigned long>(decodeStartMs - pipelineStartMs));',
        '  bool success = decoder->decodeToFramebuffer(imagePath, renderer, config);',
        '  const uint32_t decodeDoneMs = millis();',
        '  LOG_INF("IMG", "[IMGPIPE] decode done ok=%d time=%lums total=%lums", success ? 1 : 0,',
        '          static_cast<unsigned long>(decodeDoneMs - decodeStartMs),',
        '          static_cast<unsigned long>(decodeDoneMs - pipelineStartMs));',
    ),
    "ImageBlock decoder call",
)
path.write_text(text)


# ---------------------------------------------------------------------------
# Epub: destination-file open -> ZIP stream -> flush -> close.
# ---------------------------------------------------------------------------
epub_path = Path("lib/Epub/Epub.cpp")
epub = epub_path.read_text()
epub = replace_once(
    epub,
    block('#include "Epub.h"', '', '#include <ArduinoJson.h>'),
    block('#include "Epub.h"', '', '#include <Arduino.h>', '#include <ArduinoJson.h>'),
    "Epub Arduino include",
)
marker = 'bool Epub::extractItemToFile(const std::string& itemHref, const std::string& destPath) const {'
marker_pos = epub.find(marker)
if marker_pos < 0:
    raise SystemExit("extractItemToFile marker not found")
head, tail = epub[:marker_pos], epub[marker_pos:]
tail = replace_once(
    tail,
    block(marker, '  FsFile out;', '  if (!Storage.openFileForWrite("EBP", destPath, out)) {'),
    block(
        marker,
        '  const uint32_t profileStartMs = millis();',
        '  const uint32_t destOpenStartMs = millis();',
        '  FsFile out;',
        '  if (!Storage.openFileForWrite("EBP", destPath, out)) {',
    ),
    "Epub destination open start",
)
tail = replace_once(
    tail,
    block('    return false;', '  }', '', '  const bool success = readItemContentsToStream(itemHref, out, 4096);'),
    block(
        '    return false;',
        '  }',
        '  const uint32_t destOpenDoneMs = millis();',
        '  LOG_INF("EBP", "[IMGPIPE] epub dest open=%lums elapsed=%lums",',
        '          static_cast<unsigned long>(destOpenDoneMs - destOpenStartMs),',
        '          static_cast<unsigned long>(destOpenDoneMs - profileStartMs));',
        '',
        '  const uint32_t streamStartMs = millis();',
        '  const bool success = readItemContentsToStream(itemHref, out, 4096);',
        '  const uint32_t streamDoneMs = millis();',
        '  LOG_INF("EBP", "[IMGPIPE] epub stream done ok=%d time=%lums elapsed=%lums", success ? 1 : 0,',
        '          static_cast<unsigned long>(streamDoneMs - streamStartMs),',
        '          static_cast<unsigned long>(streamDoneMs - profileStartMs));',
    ),
    "Epub stream timing",
)
tail = replace_once(
    tail,
    block('  out.flush();', '  out.close();'),
    block(
        '  const uint32_t flushStartMs = millis();',
        '  out.flush();',
        '  const uint32_t flushDoneMs = millis();',
        '  const uint32_t closeStartMs = millis();',
        '  out.close();',
        '  const uint32_t closeDoneMs = millis();',
        '  LOG_INF("EBP", "[IMGPIPE] epub flush=%lums close=%lums total=%lums",',
        '          static_cast<unsigned long>(flushDoneMs - flushStartMs),',
        '          static_cast<unsigned long>(closeDoneMs - closeStartMs),',
        '          static_cast<unsigned long>(closeDoneMs - profileStartMs));',
    ),
    "Epub flush/close timing",
)
epub_path.write_text(head + tail)


# ---------------------------------------------------------------------------
# ZipFile: metadata/open, compressed SD reads, inflate CPU, output SD writes.
# ---------------------------------------------------------------------------
zip_path = Path("lib/ZipFile/ZipFile.cpp")
zip_text = zip_path.read_text()
zip_text = replace_once(
    zip_text,
    block('  uint8_t* readBuf = nullptr;', '  size_t readBufSize = 0;', '};'),
    block(
        '  uint8_t* readBuf = nullptr;',
        '  size_t readBufSize = 0;',
        '  uint32_t profileReadUs = 0;',
        '  uint32_t profileReadCalls = 0;',
        '  size_t profileReadBytes = 0;',
        '};',
    ),
    "ZipInflateCtx counters",
)
zip_text = replace_first(
    zip_text,
    block('  const size_t bytesRead = ctx->file->read(ctx->readBuf, toRead);', '  ctx->fileRemaining -= bytesRead;'),
    block(
        '  const uint32_t profileReadStartUs = micros();',
        '  const size_t bytesRead = ctx->file->read(ctx->readBuf, toRead);',
        '  ctx->profileReadUs += micros() - profileReadStartUs;',
        '  ctx->profileReadCalls++;',
        '  ctx->profileReadBytes += bytesRead;',
        '  ctx->fileRemaining -= bytesRead;',
    ),
    "ZIP compressed read timing",
)

start = zip_text.find('bool ZipFile::readFileToStream(')
end = zip_text.find('\nstd::unique_ptr<ZipFileStreamReader>', start)
if start < 0 or end < 0:
    raise SystemExit("readFileToStream boundaries not found")
fn = zip_text[start:end]
fn = replace_once(
    fn,
    block(
        'bool ZipFile::readFileToStream(const char* filename, Print& out, const size_t chunkSize, const bool allowEarlyStop) {',
        '  const ScopedOpenClose zip{*this};',
        '  if (!zip) return false;',
        '',
        '  FileStatSlim fileStat = {};',
        '  if (!loadFileStatSlim(filename, &fileStat)) return false;',
        '',
        '  const long fileOffset = getDataOffset(fileStat);',
        '  if (fileOffset < 0) return false;',
    ),
    block(
        'bool ZipFile::readFileToStream(const char* filename, Print& out, const size_t chunkSize, const bool allowEarlyStop) {',
        '  const uint32_t profileStartMs = millis();',
        '  const uint32_t zipOpenStartMs = millis();',
        '  const ScopedOpenClose zip{*this};',
        '  if (!zip) return false;',
        '  const uint32_t zipOpenDoneMs = millis();',
        '',
        '  FileStatSlim fileStat = {};',
        '  const uint32_t statStartMs = millis();',
        '  if (!loadFileStatSlim(filename, &fileStat)) return false;',
        '  const uint32_t statDoneMs = millis();',
        '',
        '  const uint32_t offsetStartMs = millis();',
        '  const long fileOffset = getDataOffset(fileStat);',
        '  if (fileOffset < 0) return false;',
        '  const uint32_t offsetDoneMs = millis();',
    ),
    "ZIP setup timing",
)
fn = replace_once(
    fn,
    block('  const auto deflatedDataSize = fileStat.compressedSize;', '  const auto inflatedDataSize = fileStat.uncompressedSize;'),
    block(
        '  const auto deflatedDataSize = fileStat.compressedSize;',
        '  const auto inflatedDataSize = fileStat.uncompressedSize;',
        '  LOG_INF("ZIP", "[IMGZIP] entry=%s method=%u compressed=%lu uncompressed=%lu chunk=%u open=%lums stat=%lums offset=%lums",',
        '          filename, static_cast<unsigned>(fileStat.method), static_cast<unsigned long>(deflatedDataSize),',
        '          static_cast<unsigned long>(inflatedDataSize), static_cast<unsigned>(chunkSize),',
        '          static_cast<unsigned long>(zipOpenDoneMs - zipOpenStartMs),',
        '          static_cast<unsigned long>(statDoneMs - statStartMs),',
        '          static_cast<unsigned long>(offsetDoneMs - offsetStartMs));',
    ),
    "ZIP entry metadata",
)
fn = replace_once(
    fn,
    '    size_t remaining = inflatedDataSize;',
    block(
        '    size_t remaining = inflatedDataSize;',
        '    uint32_t storedReadUs = 0;',
        '    uint32_t storedWriteUs = 0;',
        '    uint32_t storedChunks = 0;',
        '    size_t storedBytes = 0;',
    ),
    "ZIP stored counters",
)
fn = replace_once(
    fn,
    '      const size_t dataRead = file.read(buffer, remaining < chunkSize ? remaining : chunkSize);',
    block(
        '      const uint32_t readStartUs = micros();',
        '      const size_t dataRead = file.read(buffer, remaining < chunkSize ? remaining : chunkSize);',
        '      storedReadUs += micros() - readStartUs;',
        '      storedChunks++;',
        '      storedBytes += dataRead;',
    ),
    "ZIP stored read timing",
)
fn = replace_once(
    fn,
    '      if (out.write(buffer, dataRead) != dataRead) {',
    block(
        '      const uint32_t writeStartUs = micros();',
        '      const size_t dataWritten = out.write(buffer, dataRead);',
        '      storedWriteUs += micros() - writeStartUs;',
        '      if (dataWritten != dataRead) {',
    ),
    "ZIP stored write timing",
)
fn = replace_once(
    fn,
    block('    free(buffer);', '    return true;'),
    block(
        '    free(buffer);',
        '    LOG_INF("ZIP", "[IMGZIP] stored done read=%lums write=%lums total=%lums chunks=%lu bytes=%u",',
        '            static_cast<unsigned long>(storedReadUs / 1000U),',
        '            static_cast<unsigned long>(storedWriteUs / 1000U),',
        '            static_cast<unsigned long>(millis() - profileStartMs),',
        '            static_cast<unsigned long>(storedChunks), static_cast<unsigned>(storedBytes));',
        '    return true;',
    ),
    "ZIP stored summary",
)
fn = replace_once(
    fn,
    block('    bool success = false;', '    size_t totalProduced = 0;', '', '    while (true) {'),
    block(
        '    bool success = false;',
        '    size_t totalProduced = 0;',
        '    uint32_t inflateTotalUs = 0;',
        '    uint32_t deflateWriteUs = 0;',
        '    uint32_t inflateCalls = 0;',
        '',
        '    while (true) {',
    ),
    "ZIP deflate counters",
)
fn = replace_once(
    fn,
    '      const InflateStream::Status status = inflate.readAtMost(outputBuffer, chunkSize, &produced);',
    block(
        '      const uint32_t inflateStartUs = micros();',
        '      const InflateStream::Status status = inflate.readAtMost(outputBuffer, chunkSize, &produced);',
        '      inflateTotalUs += micros() - inflateStartUs;',
        '      inflateCalls++;',
    ),
    "ZIP inflate timing",
)
fn = replace_once(
    fn,
    '        if (out.write(outputBuffer, produced) != produced) {',
    block(
        '        const uint32_t writeStartUs = micros();',
        '        const size_t dataWritten = out.write(outputBuffer, produced);',
        '        deflateWriteUs += micros() - writeStartUs;',
        '        if (dataWritten != produced) {',
    ),
    "ZIP deflate write timing",
)
fn = replace_once(
    fn,
    block(
        '    free(outputBuffer);',
        '    free(fileReadBuffer);',
        '    return success;  // inflate destructor frees the decompressor state + window',
    ),
    block(
        '    const uint32_t inflateCpuUs = inflateTotalUs >= ctx.profileReadUs ? inflateTotalUs - ctx.profileReadUs : 0;',
        '    LOG_INF("ZIP", "[IMGZIP] deflate done ok=%d zip_read=%lums inflate_cpu=%lums write=%lums total=%lums read_calls=%lu inflate_calls=%lu bytes=%u",',
        '            success ? 1 : 0, static_cast<unsigned long>(ctx.profileReadUs / 1000U),',
        '            static_cast<unsigned long>(inflateCpuUs / 1000U),',
        '            static_cast<unsigned long>(deflateWriteUs / 1000U),',
        '            static_cast<unsigned long>(millis() - profileStartMs),',
        '            static_cast<unsigned long>(ctx.profileReadCalls), static_cast<unsigned long>(inflateCalls),',
        '            static_cast<unsigned>(ctx.profileReadBytes));',
        '    free(outputBuffer);',
        '    free(fileReadBuffer);',
        '    return success;  // inflate destructor frees the decompressor state + window',
    ),
    "ZIP deflate summary",
)
zip_text = zip_text[:start] + fn + zip_text[end:]
zip_path.write_text(zip_text)


# ---------------------------------------------------------------------------
# Reader: section page load -> renderContents -> prewarm -> grayscale strips.
# ---------------------------------------------------------------------------
reader_path = Path("src/activities/reader/EpubReaderActivity.cpp")
reader = reader_path.read_text()
reader = replace_once(
    reader,
    block(
        "    // Unified page read: the in-progress build's in-RAM table if it has reached the page,",
        '    // otherwise the on-disk file (finalized section, or a partial from a previous session).',
        '    auto p = section->loadPage(section->currentPage);',
    ),
    block(
        "    // Unified page read: the in-progress build's in-RAM table if it has reached the page,",
        '    // otherwise the on-disk file (finalized section, or a partial from a previous session).',
        '    const uint32_t pageLoadStartMs = millis();',
        '    LOG_INF("ERS", "[IMGFLOW] page load start page=%d", section->currentPage);',
        '    auto p = section->loadPage(section->currentPage);',
        '    LOG_INF("ERS", "[IMGFLOW] page load done ok=%d time=%lums", p ? 1 : 0,',
        '            static_cast<unsigned long>(millis() - pageLoadStartMs));',
    ),
    "reader page load timing",
)
reader = replace_once(
    reader,
    block(
        '    const int renderFontId = activeSectionFontId != 0 ? activeSectionFontId : SETTINGS.getReaderFontId();',
        '    renderContents(std::move(p), renderFontId, layout.marginTop, layout.marginRight, layout.marginBottom,',
        '                   layout.marginLeft, /*updatePanel=*/true);',
        '    lastRenderCompleteMs = millis();',
    ),
    block(
        '    const int renderFontId = activeSectionFontId != 0 ? activeSectionFontId : SETTINGS.getReaderFontId();',
        '    const uint32_t renderDispatchStartMs = millis();',
        '    LOG_INF("ERS", "[IMGFLOW] renderContents dispatch");',
        '    renderContents(std::move(p), renderFontId, layout.marginTop, layout.marginRight, layout.marginBottom,',
        '                   layout.marginLeft, /*updatePanel=*/true);',
        '    LOG_INF("ERS", "[IMGFLOW] renderContents returned time=%lums",',
        '            static_cast<unsigned long>(millis() - renderDispatchStartMs));',
        '    lastRenderCompleteMs = millis();',
    ),
    "reader render dispatch timing",
)
reader = replace_once(
    reader,
    block(
        'void EpubReaderActivity::renderContents(std::unique_ptr<Page> page, const int fontId, const int orientedMarginTop,',
        '                                        const int orientedMarginRight, const int orientedMarginBottom,',
        '                                        const int orientedMarginLeft, const bool updatePanel) {',
        '  // Font prewarm: scan pass accumulates text, then prewarm, then real render',
        '  auto* fcm = renderer.getFontCacheManager();',
        '  auto scope = fcm->createPrewarmScope();',
        '  page->renderText(renderer, fontId, orientedMarginLeft, orientedMarginTop);  // scan pass',
        '  scope.endScanAndPrewarm();',
    ),
    block(
        'void EpubReaderActivity::renderContents(std::unique_ptr<Page> page, const int fontId, const int orientedMarginTop,',
        '                                        const int orientedMarginRight, const int orientedMarginBottom,',
        '                                        const int orientedMarginLeft, const bool updatePanel) {',
        '  const uint32_t renderContentsStartMs = millis();',
        '  LOG_INF("ERS", "[IMGFLOW] renderContents start");',
        '  // Font prewarm: scan pass accumulates text, then prewarm, then real render',
        '  auto* fcm = renderer.getFontCacheManager();',
        '  auto scope = fcm->createPrewarmScope();',
        '  const uint32_t scanStartMs = millis();',
        '  page->renderText(renderer, fontId, orientedMarginLeft, orientedMarginTop);  // scan pass',
        '  const uint32_t scanDoneMs = millis();',
        '  scope.endScanAndPrewarm();',
        '  const uint32_t prewarmDoneMs = millis();',
        '  LOG_INF("ERS", "[IMGFLOW] render prewarm scan=%lums prewarm=%lums elapsed=%lums",',
        '          static_cast<unsigned long>(scanDoneMs - scanStartMs),',
        '          static_cast<unsigned long>(prewarmDoneMs - scanDoneMs),',
        '          static_cast<unsigned long>(prewarmDoneMs - renderContentsStartMs));',
    ),
    "reader renderContents prewarm timing",
)
reader = replace_once(
    reader,
    block('  const bool pageHasImages = page->hasImages();',
          '  const bool pageHasImagesNeedingDecode = pageHasImages && page->hasImagesNeedingDecode();'),
    block(
        '  const uint32_t imageProbeStartMs = millis();',
        '  const bool pageHasImages = page->hasImages();',
        '  const bool pageHasImagesNeedingDecode = pageHasImages && page->hasImagesNeedingDecode();',
        '  LOG_INF("ERS", "[IMGFLOW] image probe has=%d decode=%d time=%lums elapsed=%lums",',
        '          pageHasImages ? 1 : 0, pageHasImagesNeedingDecode ? 1 : 0,',
        '          static_cast<unsigned long>(millis() - imageProbeStartMs),',
        '          static_cast<unsigned long>(millis() - renderContentsStartMs));',
    ),
    "reader image probe timing",
)
reader = replace_once(
    reader,
    block(
        '  if (needsAnyGrayscale) {',
        '    ensureGrayscaleStripScratch();',
        '  }',
        '  if (runTiledGrayscalePass(renderer, *page, fontId, orientedMarginLeft, orientedMarginTop, foregroundBlack,',
    ),
    block(
        '  if (needsAnyGrayscale) {',
        '    const uint32_t scratchStartMs = millis();',
        '    ensureGrayscaleStripScratch();',
        '    LOG_INF("ERS", "[IMGFLOW] grayscale scratch time=%lums elapsed=%lums",',
        '            static_cast<unsigned long>(millis() - scratchStartMs),',
        '            static_cast<unsigned long>(millis() - renderContentsStartMs));',
        '  }',
        '  LOG_INF("ERS", "[IMGFLOW] tiled pass dispatch elapsed=%lums",',
        '          static_cast<unsigned long>(millis() - renderContentsStartMs));',
        '  if (runTiledGrayscalePass(renderer, *page, fontId, orientedMarginLeft, orientedMarginTop, foregroundBlack,',
    ),
    "reader tiled dispatch timing",
)
reader = replace_once(
    reader,
    block(
        '      renderer.beginStripTarget(buffer + static_cast<size_t>(y) * displayWidthBytes, y, rows);',
        '      renderer.clearScreen(0x00);',
        '      if (needsTextGrayscale) {',
        '        page.render(renderer, fontId, marginLeft, marginTop, foregroundBlack);',
        '      } else {',
        '        page.renderImages(renderer, fontId, marginLeft, marginTop);',
        '      }',
        '      renderer.endStripTarget();',
    ),
    block(
        '      renderer.beginStripTarget(buffer + static_cast<size_t>(y) * displayWidthBytes, y, rows);',
        '      renderer.clearScreen(0x00);',
        '      const uint32_t stripRenderStartMs = millis();',
        '      if (needsTextGrayscale) {',
        '        page.render(renderer, fontId, marginLeft, marginTop, foregroundBlack);',
        '      } else {',
        '        page.renderImages(renderer, fontId, marginLeft, marginTop);',
        '      }',
        '      LOG_INF("EPS", "[IMGTILE] direct strip y=%d rows=%d render=%lums", y, rows,',
        '              static_cast<unsigned long>(millis() - stripRenderStartMs));',
        '      renderer.endStripTarget();',
    ),
    "reader direct tiled strip timing",
)
reader = replace_once(
    reader,
    block(
        '      renderer.beginStripTarget(scratch, y, rows);',
        '      renderer.clearScreen(0x00);',
        '      if (needsTextGrayscale) {',
        '        page.render(renderer, fontId, marginLeft, marginTop, foregroundBlack);',
        '      } else {',
        '        page.renderImages(renderer, fontId, marginLeft, marginTop);',
        '      }',
        '      renderer.endStripTarget();',
    ),
    block(
        '      renderer.beginStripTarget(scratch, y, rows);',
        '      renderer.clearScreen(0x00);',
        '      const uint32_t stripRenderStartMs = millis();',
        '      if (needsTextGrayscale) {',
        '        page.render(renderer, fontId, marginLeft, marginTop, foregroundBlack);',
        '      } else {',
        '        page.renderImages(renderer, fontId, marginLeft, marginTop);',
        '      }',
        '      LOG_INF("EPS", "[IMGTILE] scratch strip y=%d rows=%d render=%lums", y, rows,',
        '              static_cast<unsigned long>(millis() - stripRenderStartMs));',
        '      renderer.endStripTarget();',
    ),
    "reader scratch tiled strip timing",
)
reader_path.write_text(reader)

print("Sticky image latency profiler injected successfully")
