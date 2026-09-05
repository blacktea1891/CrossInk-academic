from pathlib import Path
import re


def block(*lines: str) -> str:
    return "\n".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Sticky-only experiment: bypass the extracted-PNG SD file on a reader cache miss.
# The shared source remains unchanged until hardware measurements validate the path.
# The existing file extractor stays intact as the compatibility fallback.

# ---------------------------------------------------------------------------
# PngToFramebufferConverter: derive an openRAM() entry point from the existing
# file-backed decoder so all validation, scaling, dithering, and PXC behavior is
# identical for the experiment.
# ---------------------------------------------------------------------------
header_path = Path("lib/Epub/Epub/converters/PngToFramebufferConverter.h")
header = header_path.read_text()
header = replace_once(
    header,
    '#pragma once\n\n#include "ImageToFramebufferDecoder.h"',
    '#pragma once\n\n#include <cstddef>\n\n#include "ImageToFramebufferDecoder.h"',
    "PNG header cstddef include",
)
header = replace_once(
    header,
    block(
        '  bool decodeToFramebuffer(const std::string& imagePath, GfxRenderer& renderer, const RenderConfig& config) override;',
        '',
        '  bool getDimensions(const std::string& imagePath, ImageDimensions& dims) const override {',
    ),
    block(
        '  bool decodeToFramebuffer(const std::string& imagePath, GfxRenderer& renderer, const RenderConfig& config) override;',
        '  bool decodeMemoryToFramebuffer(const std::string& imagePath, uint8_t* imageData, size_t imageSize,',
        '                                 GfxRenderer& renderer, const RenderConfig& config);',
        '',
        '  bool getDimensions(const std::string& imagePath, ImageDimensions& dims) const override {',
    ),
    "PNG RAM method declaration",
)
header_path.write_text(header)

cpp_path = Path("lib/Epub/Epub/converters/PngToFramebufferConverter.cpp")
cpp = cpp_path.read_text()
cpp = replace_once(
    cpp,
    block('#include <cstdlib>', '#include <new>'),
    block('#include <climits>', '#include <cstdlib>', '#include <new>'),
    "PNG climits include",
)

fn_start = cpp.find('bool PngToFramebufferConverter::decodeToFramebuffer(')
fn_end = cpp.find('\nbool PngToFramebufferConverter::supportsFormat(', fn_start)
if fn_start < 0 or fn_end < 0:
    raise SystemExit("PNG decodeToFramebuffer boundaries not found")

file_fn = cpp[fn_start:fn_end]
ram_fn, substitutions = re.subn(
    r'bool PngToFramebufferConverter::decodeToFramebuffer\(const std::string& imagePath, GfxRenderer& renderer,\s*'
    r'const RenderConfig& config\) \{',
    'bool PngToFramebufferConverter::decodeMemoryToFramebuffer(const std::string& imagePath, uint8_t* imageData,\n'
    '                                                          const size_t imageSize, GfxRenderer& renderer,\n'
    '                                                          const RenderConfig& config) {',
    file_fn,
    count=1,
)
if substitutions != 1:
    raise SystemExit(f"PNG RAM signature: expected one substitution, found {substitutions}")

ram_fn = replace_once(
    ram_fn,
    block(
        '  const uint32_t profileOpenStartMs = millis();',
        '  int rc = png->open(imagePath.c_str(), pngOpenWithHandle, pngCloseWithHandle, pngReadWithHandle, pngSeekWithHandle,',
        '                     pngDrawCallback);',
        '  const uint32_t profileOpenMs = millis() - profileOpenStartMs;',
        '  if (rc != PNG_SUCCESS) {',
        '    LOG_ERR("PNG", "Failed to open PNG: %d", rc);',
        '    delete png;',
        '    return false;',
        '  }',
    ),
    block(
        '  if (!imageData || imageSize == 0 || imageSize > static_cast<size_t>(INT_MAX)) {',
        '    LOG_ERR("PNG", "Invalid RAM PNG input: bytes=%u", static_cast<unsigned>(imageSize));',
        '    delete png;',
        '    return false;',
        '  }',
        '',
        '  const uint32_t profileOpenStartMs = millis();',
        '  int rc = png->openRAM(imageData, static_cast<int>(imageSize), pngDrawCallback);',
        '  const uint32_t profileOpenMs = millis() - profileOpenStartMs;',
        '  if (rc != PNG_SUCCESS) {',
        '    LOG_ERR("PNG", "Failed to open RAM PNG: %d", rc);',
        '    delete png;',
        '    return false;',
        '  }',
    ),
    "PNG openRAM path",
)
ram_fn = ram_fn.replace(
    '"[IMGPROF] PNG %dx%d -> %dx%d open=%lums setup=%lums decode=%lums draw=%lums gray=%lums process=%lums "',
    '"[IMGPROF] PNG source=ram %dx%d -> %dx%d open=%lums setup=%lums decode=%lums draw=%lums gray=%lums process=%lums "',
    1,
)
cpp = cpp[:fn_end] + '\n\n' + ram_fn + cpp[fn_end:]
cpp_path.write_text(cpp)


# ---------------------------------------------------------------------------
# ImageBlock: on an EPUB PNG cache miss, allocate one exact-size PSRAM buffer,
# stream the ZIP entry into it, decode synchronously, then release it. If any
# step fails, execution falls through to the existing SD extraction/file path.
# Only fully-on-screen images use this experiment because the existing reader
# only creates a persistent PXC for those images; without that cache a partial
# image would be re-inflated from the EPUB on each grayscale render pass.
# The allocation is transient and runtime-sized, so stack/static storage is not
# suitable; PSRAM keeps the multi-megabyte compressed source out of internal DRAM.
# ---------------------------------------------------------------------------
image_header_path = Path("lib/Epub/Epub/blocks/ImageBlock.h")
image_header = image_header_path.read_text()
image_header = replace_once(
    image_header,
    '#include "Block.h"\n\nclass ImageBlock final : public Block {',
    '#include "Block.h"\n\nclass Epub;\n\nclass ImageBlock final : public Block {',
    "ImageBlock Epub forward declaration",
)
image_header = replace_once(
    image_header,
    '  static void setExtractor(void* context, ExtractFn fn);',
    '  static void setExtractor(Epub* context, ExtractFn fn);',
    "ImageBlock typed extractor setter",
)
image_header = replace_once(
    image_header,
    '  static void* extractContext;',
    '  static Epub* extractContext;',
    "ImageBlock typed extractor context",
)
image_header_path.write_text(image_header)

image_path = Path("lib/Epub/Epub/blocks/ImageBlock.cpp")
image = image_path.read_text()
image = replace_once(
    image,
    block('#include "ImageBlock.h"', '', '#include <Arduino.h>'),
    block('#include "ImageBlock.h"', '', '#include "Epub.h"', '', '#include <Arduino.h>'),
    "ImageBlock Epub include",
)
image = replace_once(
    image,
    block('#include <algorithm>', '#include <cstdlib>', '#include <utility>'),
    block('#include <algorithm>', '#include <climits>', '#include <cstdlib>', '#include <cstring>', '#include <utility>'),
    "ImageBlock utility includes",
)
image = replace_once(
    image,
    '#include "Epub/converters/ImageDecoderFactory.h"',
    block('#include "Epub/converters/ImageDecoderFactory.h"', '#include "Epub/converters/PngToFramebufferConverter.h"'),
    "ImageBlock PNG converter include",
)
image = replace_once(
    image,
    block(
        'void* ImageBlock::extractContext = nullptr;',
        'ImageBlock::ExtractFn ImageBlock::extractFn = nullptr;',
        '',
        'void ImageBlock::setExtractor(void* context, ExtractFn fn) {',
    ),
    block(
        'Epub* ImageBlock::extractContext = nullptr;',
        'ImageBlock::ExtractFn ImageBlock::extractFn = nullptr;',
        '',
        'void ImageBlock::setExtractor(Epub* context, ExtractFn fn) {',
    ),
    "ImageBlock typed context implementation",
)
image = replace_once(
    image,
    block('namespace {', '', 'std::string getCachePath(const std::string& imagePath) {'),
    block(
        'namespace {',
        '',
        'class FixedBufferPrint final : public Print {',
        ' public:',
        '  FixedBufferPrint(uint8_t* data, const size_t capacity) : data_(data), capacity_(capacity) {}',
        '',
        '  size_t write(uint8_t value) override { return write(&value, 1); }',
        '',
        '  size_t write(const uint8_t* buffer, const size_t size) override {',
        '    if (!data_ || !buffer || written_ > capacity_ || size > capacity_ - written_) return 0;',
        '    std::memcpy(data_ + written_, buffer, size);',
        '    written_ += size;',
        '    return size;',
        '  }',
        '',
        '  size_t bytesWritten() const { return written_; }',
        '',
        ' private:',
        '  uint8_t* data_;',
        '  size_t capacity_;',
        '  size_t written_{0};',
        '};',
        '',
        'std::string getCachePath(const std::string& imagePath) {',
    ),
    "ImageBlock fixed PSRAM sink",
)

ram_fast_path = block(
    '  if (fullyOnScreen && !imageAlreadyExtracted && !sourcePath.empty() && extractContext && psramHeapAvailable() &&',
    '      PngToFramebufferConverter::supportsFormat(imagePath)) {',
    '    const uint32_t ramPathStartMs = millis();',
    '    size_t sourceSize = 0;',
    '    if (extractContext->getItemSize(sourcePath, &sourceSize) && sourceSize > 0 &&',
    '        sourceSize <= static_cast<size_t>(INT_MAX)) {',
    '      auto sourceBuffer = makePsramByteBufferNoThrow(sourceSize);',
    '      if (sourceBuffer) {',
    '        LOG_INF("IMG", "[IMGPROF] EPUB PNG RAM start source=%s bytes=%lu", sourcePath.c_str(),',
    '                static_cast<unsigned long>(sourceSize));',
    '        FixedBufferPrint ramSink(sourceBuffer.get(), sourceSize);',
    '        const uint32_t streamStartMs = millis();',
    '        const bool streamed = extractContext->readItemContentsToStream(sourcePath, ramSink, 4096);',
    '        const uint32_t streamMs = millis() - streamStartMs;',
    '        const bool complete = streamed && ramSink.bytesWritten() == sourceSize;',
    '        LOG_INF("IMG", "[IMGPROF] EPUB PNG RAM stream ok=%d bytes=%lu/%lu time=%lums", complete ? 1 : 0,',
    '                static_cast<unsigned long>(ramSink.bytesWritten()), static_cast<unsigned long>(sourceSize),',
    '                static_cast<unsigned long>(streamMs));',
    '',
    '        if (complete) {',
    '          RenderConfig ramConfig;',
    '          ramConfig.x = x;',
    '          ramConfig.y = y;',
    '          ramConfig.maxWidth = width;',
    '          ramConfig.maxHeight = height;',
    '          ramConfig.useGrayscale = true;',
    '          ramConfig.useDithering = true;',
    '          ramConfig.performanceMode = false;',
    '          ramConfig.useExactDimensions = true;',
    '          ramConfig.cachePath = cachePath;',
    '',
    '          PngToFramebufferConverter ramDecoder;',
    '          const uint32_t ramDecodeStartMs = millis();',
    '          const bool decoded = ramDecoder.decodeMemoryToFramebuffer(',
    '              imagePath, sourceBuffer.get(), sourceSize, renderer, ramConfig);',
    '          const uint32_t ramDecodeMs = millis() - ramDecodeStartMs;',
    '          LOG_INF("IMG", "[IMGPROF] EPUB PNG RAM decode ok=%d decode=%lums total=%lums", decoded ? 1 : 0,',
    '                  static_cast<unsigned long>(ramDecodeMs),',
    '                  static_cast<unsigned long>(millis() - ramPathStartMs));',
    '          if (decoded) return;',
    '          LOG_INF("IMG", "[IMGPROF] EPUB PNG RAM decode failed; falling back to SD source");',
    '        } else {',
    '          LOG_INF("IMG", "[IMGPROF] EPUB PNG RAM stream incomplete; falling back to SD source");',
    '        }',
    '      } else {',
    '        LOG_INF("IMG", "[IMGPROF] EPUB PNG RAM alloc failed bytes=%lu; falling back to SD source",',
    '                static_cast<unsigned long>(sourceSize));',
    '      }',
    '    } else {',
    '      LOG_INF("IMG", "[IMGPROF] EPUB PNG RAM size unavailable/unsupported bytes=%lu; falling back to SD source",',
    '              static_cast<unsigned long>(sourceSize));',
    '    }',
    '  }',
    '',
)
image = replace_once(
    image,
    '  if (!sourcePath.empty() && extractFn && !imageAlreadyExtracted) {',
    ram_fast_path + '  if (!sourcePath.empty() && extractFn && !imageAlreadyExtracted) {',
    "ImageBlock PSRAM PNG fast path",
)
image_path.write_text(image)
