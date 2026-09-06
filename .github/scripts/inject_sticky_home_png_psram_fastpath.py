from pathlib import Path


def block(*lines: str) -> str:
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Sticky-only experiment: Home thumbnail generation currently extracts a full
# PNG cover from the EPUB to SD before reading it back through PngToBmpConverter.
# For large covers this tiny-write extraction dominates latency. Add a RAM input
# adapter to the existing converter, stream the EPUB item into PSRAM, and decode
# the exact same thumbnail directly from RAM. Any failure falls back to the
# existing persistent cover_src.png path unchanged.

# ---------------------------------------------------------------------------
# PngToBmpConverter: generalize the private decoder input from HalFile to a tiny
# read/seek interface, then expose a RAM-backed 1-bit thumbnail entry point.
# The image processing, scaling, dithering, and BMP output code stays identical.
# ---------------------------------------------------------------------------
header_path = Path("lib/PngToBmpConverter/PngToBmpConverter.h")
header = header_path.read_text()
header = replace_once(
    header,
    '#pragma once\n\n#include <HalStorage.h>\n',
    '#pragma once\n\n#include <cstddef>\n#include <cstdint>\n\n#include <HalStorage.h>\n',
    "PNG-to-BMP header size types",
)
header = replace_once(
    header,
    block(
        'class PngToBmpConverter {',
        '  static bool pngFileToBmpStreamInternal(FsFile& pngFile, Print& bmpOut, int targetWidth, int targetHeight, bool oneBit,',
        '                                         bool crop = true, bool adaptiveContain = false);',
        '',
        ' public:',
    ),
    block(
        'class PngToBmpConverter {',
        ' public:',
    ),
    "PNG-to-BMP private file-only decoder declaration",
)
header = replace_once(
    header,
    block(
        '  static bool pngFileTo1BitBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth, int targetMaxHeight,',
        '                                             bool adaptiveContain = false);',
    ),
    block(
        '  static bool pngFileTo1BitBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth, int targetMaxHeight,',
        '                                             bool adaptiveContain = false);',
        '  static bool pngMemoryTo1BitBmpStreamWithSize(const uint8_t* pngData, size_t pngSize, Print& bmpOut,',
        '                                               int targetMaxWidth, int targetMaxHeight,',
        '                                               bool adaptiveContain = false);',
    ),
    "PNG-to-BMP RAM method declaration",
)
header_path.write_text(header)

cpp_path = Path("lib/PngToBmpConverter/PngToBmpConverter.cpp")
cpp = cpp_path.read_text()
cpp = replace_once(
    cpp,
    block('#include <algorithm>', '#include <cstdint>', '#include <cstdio>', '#include <cstring>'),
    block('#include <algorithm>', '#include <cstddef>', '#include <cstdint>', '#include <cstdio>', '#include <cstring>'),
    "PNG-to-BMP cstddef include",
)
cpp = replace_once(
    cpp,
    block(
        '// Read a big-endian 32-bit value from file',
        'bool readBE32(FsFile& file, uint32_t& value) {',
        '  uint8_t buf[4];',
        '  if (file.read(buf, 4) != 4) return false;',
        '  value = (static_cast<uint32_t>(buf[0]) << 24) | (static_cast<uint32_t>(buf[1]) << 16) |',
        '          (static_cast<uint32_t>(buf[2]) << 8) | buf[3];',
        '  return true;',
        '}',
    ),
    block(
        'class PngInput {',
        ' public:',
        '  virtual ~PngInput() = default;',
        '  virtual int read(void* buffer, size_t size) = 0;',
        '  virtual bool seekCur(int64_t offset) = 0;',
        '};',
        '',
        'class FilePngInput final : public PngInput {',
        ' public:',
        '  explicit FilePngInput(FsFile& file) : file_(file) {}',
        '  int read(void* buffer, const size_t size) override { return file_.read(buffer, size); }',
        '  bool seekCur(const int64_t offset) override { return file_.seekCur(offset); }',
        '',
        ' private:',
        '  FsFile& file_;',
        '};',
        '',
        'class MemoryPngInput final : public PngInput {',
        ' public:',
        '  MemoryPngInput(const uint8_t* data, const size_t size) : data_(data), size_(size) {}',
        '',
        '  int read(void* buffer, const size_t size) override {',
        '    if (!buffer || !data_ || pos_ > size_) return 0;',
        '    const size_t available = size_ - pos_;',
        '    const size_t count = size < available ? size : available;',
        '    if (count == 0) return 0;',
        '    memcpy(buffer, data_ + pos_, count);',
        '    pos_ += count;',
        '    return static_cast<int>(count);',
        '  }',
        '',
        '  bool seekCur(const int64_t offset) override {',
        '    if (offset < 0) {',
        '      const uint64_t amount = static_cast<uint64_t>(-(offset + 1)) + 1;',
        '      if (amount > pos_) return false;',
        '      pos_ -= static_cast<size_t>(amount);',
        '      return true;',
        '    }',
        '    const uint64_t amount = static_cast<uint64_t>(offset);',
        '    if (amount > static_cast<uint64_t>(size_ - pos_)) return false;',
        '    pos_ += static_cast<size_t>(amount);',
        '    return true;',
        '  }',
        '',
        ' private:',
        '  const uint8_t* data_;',
        '  size_t size_;',
        '  size_t pos_{0};',
        '};',
        '',
        '// Read a big-endian 32-bit value from either a file or RAM source.',
        'bool readBE32(PngInput& file, uint32_t& value) {',
        '  uint8_t buf[4];',
        '  if (file.read(buf, 4) != 4) return false;',
        '  value = (static_cast<uint32_t>(buf[0]) << 24) | (static_cast<uint32_t>(buf[1]) << 16) |',
        '          (static_cast<uint32_t>(buf[2]) << 8) | buf[3];',
        '  return true;',
        '}',
    ),
    "PNG-to-BMP generic input adapter",
)
cpp = replace_once(
    cpp,
    '  FsFile* file;\n',
    '  PngInput* file;\n',
    "PNG decode context generic input",
)
cpp = replace_once(
    cpp,
    block(
        'bool PngToBmpConverter::pngFileToBmpStreamInternal(FsFile& pngFile, Print& bmpOut, int targetWidth, int targetHeight,',
        '                                                   bool oneBit, bool crop, bool adaptiveContain) {',
    ),
    block(
        'static bool pngInputToBmpStreamInternal(PngInput& pngFile, Print& bmpOut, int targetWidth, int targetHeight,',
        '                                        bool oneBit, bool crop, bool adaptiveContain) {',
    ),
    "PNG-to-BMP generic decoder signature",
)
cpp = replace_once(
    cpp,
    block(
        'bool PngToBmpConverter::pngFileToBmpStream(FsFile& pngFile, Print& bmpOut, bool crop) {',
        '  // Use runtime display dimensions (swapped for portrait cover sizing)',
        '  const int targetWidth = display.getDisplayHeight();',
        '  const int targetHeight = display.getDisplayWidth();',
        '  return pngFileToBmpStreamInternal(pngFile, bmpOut, targetWidth, targetHeight, false, crop);',
        '}',
        '',
        'bool PngToBmpConverter::pngFileToBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth,',
        '                                                   int targetMaxHeight, bool adaptiveContain) {',
        '  return pngFileToBmpStreamInternal(pngFile, bmpOut, targetMaxWidth, targetMaxHeight, false, true, adaptiveContain);',
        '}',
        '',
        'bool PngToBmpConverter::pngFileTo1BitBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth,',
        '                                                       int targetMaxHeight, bool adaptiveContain) {',
        '  return pngFileToBmpStreamInternal(pngFile, bmpOut, targetMaxWidth, targetMaxHeight, true, true, adaptiveContain);',
        '}',
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
        'bool PngToBmpConverter::pngFileToBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth,',
        '                                                   int targetMaxHeight, bool adaptiveContain) {',
        '  FilePngInput input(pngFile);',
        '  return pngInputToBmpStreamInternal(input, bmpOut, targetMaxWidth, targetMaxHeight, false, true, adaptiveContain);',
        '}',
        '',
        'bool PngToBmpConverter::pngFileTo1BitBmpStreamWithSize(FsFile& pngFile, Print& bmpOut, int targetMaxWidth,',
        '                                                       int targetMaxHeight, bool adaptiveContain) {',
        '  FilePngInput input(pngFile);',
        '  return pngInputToBmpStreamInternal(input, bmpOut, targetMaxWidth, targetMaxHeight, true, true, adaptiveContain);',
        '}',
        '',
        'bool PngToBmpConverter::pngMemoryTo1BitBmpStreamWithSize(const uint8_t* pngData, const size_t pngSize,',
        '                                                         Print& bmpOut, const int targetMaxWidth,',
        '                                                         const int targetMaxHeight, const bool adaptiveContain) {',
        '  if (!pngData || pngSize == 0) return false;',
        '  MemoryPngInput input(pngData, pngSize);',
        '  return pngInputToBmpStreamInternal(input, bmpOut, targetMaxWidth, targetMaxHeight, true, true, adaptiveContain);',
        '}',
    ),
    "PNG-to-BMP file and RAM wrappers",
)
cpp_path.write_text(cpp)


# ---------------------------------------------------------------------------
# Epub Home thumbnail path: try EPUB -> PSRAM -> existing PNG thumbnail decoder
# first. Only the small final BMP is written to SD. If anything fails, keep the
# existing ensureCachedCoverImage() file path as the fallback.
# ---------------------------------------------------------------------------
epub_path = Path("lib/Epub/Epub.cpp")
epub = epub_path.read_text()
epub = replace_once(
    epub,
    '#include "Epub.h"\n\n#include <ArduinoJson.h>',
    '#include "Epub.h"\n\n#include <Arduino.h>\n#include <ArduinoJson.h>',
    "Epub Arduino timing include",
)
epub = replace_once(
    epub,
    block('namespace {', 'constexpr int kDefaultThumbHeight = 180;'),
    block(
        'namespace {',
        'class HomeFixedBufferPrint final : public Print {',
        ' public:',
        '  HomeFixedBufferPrint(uint8_t* data, const size_t capacity) : data_(data), capacity_(capacity) {}',
        '  size_t write(uint8_t value) override { return write(&value, 1); }',
        '  size_t write(const uint8_t* buffer, const size_t size) override {',
        '    if (!data_ || !buffer || written_ > capacity_ || size > capacity_ - written_) return 0;',
        '    std::memcpy(data_ + written_, buffer, size);',
        '    written_ += size;',
        '    return size;',
        '  }',
        '  size_t bytesWritten() const { return written_; }',
        '',
        ' private:',
        '  uint8_t* data_;',
        '  size_t capacity_;',
        '  size_t written_{0};',
        '};',
        '',
        'constexpr int kDefaultThumbHeight = 180;',
    ),
    "Home fixed PSRAM sink",
)

old_png_branch = block(
    '  } else if (FsHelpers::hasPngExtension(coverImageHref)) {',
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
    '    FsFile thumbBmp;',
    '    if (!Storage.openFileForWrite("EBP", thumbPath, thumbBmp)) {',
    '      coverPng.close();',
    '      return false;',
    '    }',
    '    int THUMB_TARGET_WIDTH = width;',
    '    int THUMB_TARGET_HEIGHT = height;',
    '    releaseReaderSdFontCachesBeforeCoverDecode(renderer, readerFontId, "thumbnail PNG decode");',
    '    const bool success = PngToBmpConverter::pngFileTo1BitBmpStreamWithSize(coverPng, thumbBmp, THUMB_TARGET_WIDTH,',
    '                                                                           THUMB_TARGET_HEIGHT, adaptiveContain);',
    '    // Explicitly close() files before leaving the converter path.',
    '    coverPng.close();',
    '    thumbBmp.close();',
    '',
    '    if (!success) {',
    '      LOG_ERR("EBP", "Failed to generate thumb BMP from PNG cover image");',
    '      Storage.remove(thumbPath.c_str());',
    '    }',
    '    return success;',
)

new_png_branch = block(
    '  } else if (FsHelpers::hasPngExtension(coverImageHref)) {',
    '    int THUMB_TARGET_WIDTH = width;',
    '    int THUMB_TARGET_HEIGHT = height;',
    '    releaseReaderSdFontCachesBeforeCoverDecode(renderer, readerFontId, "thumbnail PNG decode");',
    '',
    '    if (psramHeapAvailable()) {',
    '      size_t sourceSize = 0;',
    '      if (getItemSize(coverImageHref, &sourceSize) && sourceSize > 0) {',
    '        auto sourceBuffer = makePsramByteBufferNoThrow(sourceSize);',
    '        if (sourceBuffer) {',
    '          LOG_INF("HOME", "[HOMEPROF] PNG RAM start source=%s bytes=%lu", coverImageHref.c_str(),',
    '                  static_cast<unsigned long>(sourceSize));',
    '          HomeFixedBufferPrint ramSink(sourceBuffer.get(), sourceSize);',
    '          const uint32_t streamStartMs = millis();',
    '          const bool streamed = readItemContentsToStream(coverImageHref, ramSink, 16384);',
    '          const uint32_t streamMs = millis() - streamStartMs;',
    '          const bool complete = streamed && ramSink.bytesWritten() == sourceSize;',
    '          LOG_INF("HOME", "[HOMEPROF] PNG RAM stream ok=%d bytes=%lu/%lu time=%lums", complete ? 1 : 0,',
    '                  static_cast<unsigned long>(ramSink.bytesWritten()), static_cast<unsigned long>(sourceSize),',
    '                  static_cast<unsigned long>(streamMs));',
    '',
    '          if (complete) {',
    '            FsFile thumbBmp;',
    '            if (Storage.openFileForWrite("EBP", thumbPath, thumbBmp)) {',
    '              const uint32_t decodeStartMs = millis();',
    '              const bool success = PngToBmpConverter::pngMemoryTo1BitBmpStreamWithSize(',
    '                  sourceBuffer.get(), sourceSize, thumbBmp, THUMB_TARGET_WIDTH, THUMB_TARGET_HEIGHT, adaptiveContain);',
    '              const uint32_t decodeMs = millis() - decodeStartMs;',
    '              thumbBmp.close();',
    '              LOG_INF("HOME", "[HOMEPROF] PNG RAM decode ok=%d decode=%lums total=%lums", success ? 1 : 0,',
    '                      static_cast<unsigned long>(decodeMs),',
    '                      static_cast<unsigned long>(streamMs + decodeMs));',
    '              if (success) return true;',
    '              Storage.remove(thumbPath.c_str());',
    '            } else {',
    '              LOG_INF("HOME", "[HOMEPROF] PNG RAM thumbnail output open failed; falling back to SD source");',
    '            }',
    '          } else {',
    '            LOG_INF("HOME", "[HOMEPROF] PNG RAM stream incomplete; falling back to SD source");',
    '          }',
    '        } else {',
    '          LOG_INF("HOME", "[HOMEPROF] PNG RAM alloc failed bytes=%lu; falling back to SD source",',
    '                  static_cast<unsigned long>(sourceSize));',
    '        }',
    '      } else {',
    '        LOG_INF("HOME", "[HOMEPROF] PNG RAM size unavailable; falling back to SD source");',
    '      }',
    '    }',
    '',
    '    LOG_INF("HOME", "[HOMEPROF] PNG RAM fast path unavailable/failed; using cached SD source");',
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
    '    FsFile thumbBmp;',
    '    if (!Storage.openFileForWrite("EBP", thumbPath, thumbBmp)) {',
    '      coverPng.close();',
    '      return false;',
    '    }',
    '    const bool success = PngToBmpConverter::pngFileTo1BitBmpStreamWithSize(coverPng, thumbBmp, THUMB_TARGET_WIDTH,',
    '                                                                           THUMB_TARGET_HEIGHT, adaptiveContain);',
    '    // Explicitly close() files before leaving the converter path.',
    '    coverPng.close();',
    '    thumbBmp.close();',
    '',
    '    if (!success) {',
    '      LOG_ERR("EBP", "Failed to generate thumb BMP from PNG cover image");',
    '      Storage.remove(thumbPath.c_str());',
    '    }',
    '    return success;',
)
epub = replace_once(epub, old_png_branch, new_png_branch, "Home PNG thumbnail PSRAM fast path")
epub_path.write_text(epub)
