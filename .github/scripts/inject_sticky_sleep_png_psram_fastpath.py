from pathlib import Path


def block(*lines: str) -> str:
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Sticky-only follow-up to the validated Home PNG PSRAM path. Sleep full-cover
# generation still calls Epub::generateCoverBmp(), which extracts the original
# PNG to cover_src.png on SD before decoding it. Reuse the RAM input adapter
# injected by inject_sticky_home_png_psram_fastpath.py so Sleep can stream the
# EPUB item directly into PSRAM and generate only the final cover BMP on SD.
# Any allocation/stream/decode failure falls back to the original SD source path.

header_path = Path("lib/PngToBmpConverter/PngToBmpConverter.h")
header = header_path.read_text()
header = replace_once(
    header,
    block(
        '  static bool pngFileToBmpStream(FsFile& pngFile, Print& bmpOut, bool crop = true);',
        '  static bool pngFileToBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth, int targetMaxHeight,',
    ),
    block(
        '  static bool pngFileToBmpStream(FsFile& pngFile, Print& bmpOut, bool crop = true);',
        '  static bool pngMemoryToBmpStream(const uint8_t* pngData, size_t pngSize, Print& bmpOut, bool crop = true);',
        '  static bool pngFileToBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth, int targetMaxHeight,',
    ),
    "PNG full-cover RAM method declaration",
)
header_path.write_text(header)

cpp_path = Path("lib/PngToBmpConverter/PngToBmpConverter.cpp")
cpp = cpp_path.read_text()
cpp = replace_once(
    cpp,
    block(
        'bool PngToBmpConverter::pngFileToBmpStream(FsFile& pngFile, Print& bmpOut, bool crop) {',
        '  // Use runtime display dimensions (swapped for portrait cover sizing)',
        '  const int targetWidth = display.getDisplayHeight();',
        '  const int targetHeight = display.getDisplayWidth();',
        '  FilePngInput input(pngFile);',
        '  return pngInputToBmpStreamInternal(input, bmpOut, targetWidth, targetHeight, false, crop, false);',
        '}',
        '',
        'bool PngToBmpConverter::pngFileToBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth,',
    ),
    block(
        'bool PngToBmpConverter::pngFileToBmpStream(FsFile& pngFile, Print& bmpOut, bool crop) {',
        '  // Use runtime display dimensions (swapped for portrait cover sizing)',
        '  const int targetWidth = display.getDisplayHeight();',
        '  const int targetHeight = display.getDisplayWidth();',
        '  FilePngInput input(pngFile);',
        '  return pngInputToBmpStreamInternal(input, bmpOut, targetWidth, targetHeight, false, crop, false);',
        '}',
        '',
        'bool PngToBmpConverter::pngMemoryToBmpStream(const uint8_t* pngData, const size_t pngSize, Print& bmpOut,',
        '                                                const bool crop) {',
        '  if (!pngData || pngSize == 0) return false;',
        '  const int targetWidth = display.getDisplayHeight();',
        '  const int targetHeight = display.getDisplayWidth();',
        '  MemoryPngInput input(pngData, pngSize);',
        '  return pngInputToBmpStreamInternal(input, bmpOut, targetWidth, targetHeight, false, crop, false);',
        '}',
        '',
        'bool PngToBmpConverter::pngFileToBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth,',
    ),
    "PNG full-cover RAM method implementation",
)
cpp_path.write_text(cpp)


epub_path = Path("lib/Epub/Epub.cpp")
epub = epub_path.read_text()
old_png_cover = block(
    '  if (FsHelpers::hasPngExtension(coverImageHref)) {',
    '    std::string coverPngPath;',
    '    if (!ensureCachedCoverImage(coverImageHref, coverPngPath)) {',
    '      return false;',
    '    }',
    '',
    '    FsFile coverPng;',
    '    if (!Storage.openFileForRead("EBP", coverPngPath, coverPng)) {',
    '      return false;',
    '    }',
    '',
    '    FsFile coverBmp;',
    '    if (!Storage.openFileForWrite("EBP", getCoverBmpPath(cropped), coverBmp)) {',
    '      coverPng.close();',
    '      return false;',
    '    }',
    '    releaseReaderSdFontCachesBeforeCoverDecode(renderer, readerFontId, "cover PNG decode");',
    '    const bool success = PngToBmpConverter::pngFileToBmpStream(coverPng, coverBmp, cropped);',
    '    // Explicitly close() files before leaving the converter path.',
    '    coverPng.close();',
    '    coverBmp.close();',
    '',
    '    if (!success) {',
    '      LOG_ERR("EBP", "Failed to generate BMP from PNG cover image");',
    '      Storage.remove(getCoverBmpPath(cropped).c_str());',
    '    }',
    '    return success;',
    '  }',
)
new_png_cover = block(
    '  if (FsHelpers::hasPngExtension(coverImageHref)) {',
    '    releaseReaderSdFontCachesBeforeCoverDecode(renderer, readerFontId, "cover PNG decode");',
    '',
    '    if (psramHeapAvailable()) {',
    '      size_t sourceSize = 0;',
    '      if (getItemSize(coverImageHref, &sourceSize) && sourceSize > 0) {',
    '        auto sourceBuffer = makePsramByteBufferNoThrow(sourceSize);',
    '        if (sourceBuffer) {',
    '          LOG_INF("SLP", "[SLPCOVER] PNG RAM start source=%s bytes=%lu crop=%d", coverImageHref.c_str(),',
    '                  static_cast<unsigned long>(sourceSize), cropped ? 1 : 0);',
    '          HomeFixedBufferPrint ramSink(sourceBuffer.get(), sourceSize);',
    '          const uint32_t streamStartMs = millis();',
    '          const bool streamed = readItemContentsToStream(coverImageHref, ramSink, 16384);',
    '          const uint32_t streamMs = millis() - streamStartMs;',
    '          const bool complete = streamed && ramSink.bytesWritten() == sourceSize;',
    '          LOG_INF("SLP", "[SLPCOVER] PNG RAM stream ok=%d bytes=%lu/%lu time=%lums", complete ? 1 : 0,',
    '                  static_cast<unsigned long>(ramSink.bytesWritten()), static_cast<unsigned long>(sourceSize),',
    '                  static_cast<unsigned long>(streamMs));',
    '',
    '          if (complete) {',
    '            FsFile coverBmp;',
    '            if (Storage.openFileForWrite("EBP", getCoverBmpPath(cropped), coverBmp)) {',
    '              const uint32_t decodeStartMs = millis();',
    '              const bool success = PngToBmpConverter::pngMemoryToBmpStream(',
    '                  sourceBuffer.get(), sourceSize, coverBmp, cropped);',
    '              const uint32_t decodeMs = millis() - decodeStartMs;',
    '              coverBmp.close();',
    '              LOG_INF("SLP", "[SLPCOVER] PNG RAM decode ok=%d decode=%lums total=%lums", success ? 1 : 0,',
    '                      static_cast<unsigned long>(decodeMs),',
    '                      static_cast<unsigned long>(streamMs + decodeMs));',
    '              if (success) return true;',
    '              Storage.remove(getCoverBmpPath(cropped).c_str());',
    '            } else {',
    '              LOG_INF("SLP", "[SLPCOVER] output open failed; falling back to SD source");',
    '            }',
    '          } else {',
    '            LOG_INF("SLP", "[SLPCOVER] RAM stream incomplete; falling back to SD source");',
    '          }',
    '        } else {',
    '          LOG_INF("SLP", "[SLPCOVER] RAM alloc failed bytes=%lu; falling back to SD source",',
    '                  static_cast<unsigned long>(sourceSize));',
    '        }',
    '      } else {',
    '        LOG_INF("SLP", "[SLPCOVER] source size unavailable; falling back to SD source");',
    '      }',
    '    }',
    '',
    '    LOG_INF("SLP", "[SLPCOVER] RAM fast path unavailable/failed; using cached SD source");',
    '    std::string coverPngPath;',
    '    if (!ensureCachedCoverImage(coverImageHref, coverPngPath)) {',
    '      return false;',
    '    }',
    '',
    '    FsFile coverPng;',
    '    if (!Storage.openFileForRead("EBP", coverPngPath, coverPng)) {',
    '      return false;',
    '    }',
    '',
    '    FsFile coverBmp;',
    '    if (!Storage.openFileForWrite("EBP", getCoverBmpPath(cropped), coverBmp)) {',
    '      coverPng.close();',
    '      return false;',
    '    }',
    '    const bool success = PngToBmpConverter::pngFileToBmpStream(coverPng, coverBmp, cropped);',
    '    // Explicitly close() files before leaving the converter path.',
    '    coverPng.close();',
    '    coverBmp.close();',
    '',
    '    if (!success) {',
    '      LOG_ERR("EBP", "Failed to generate BMP from PNG cover image");',
    '      Storage.remove(getCoverBmpPath(cropped).c_str());',
    '    }',
    '    return success;',
    '  }',
)
epub = replace_once(epub, old_png_cover, new_png_cover, "Sleep/full-cover PNG PSRAM fast path")
epub_path.write_text(epub)
