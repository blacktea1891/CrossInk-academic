from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


gfx_path = Path("lib/GfxRenderer/GfxRenderer.cpp")
gfx = gfx_path.read_text()

helper_anchor = '''void appendShapedRtlTokens(const char* text, std::string& shapedOut) {
  std::string token;
  std::string visual;
  forEachShapedRtlToken(text, token, visual, [&shapedOut](const char* shaped) { shapedOut += shaped; });
}
}  // namespace
'''
helper_replacement = '''void appendShapedRtlTokens(const char* text, std::string& shapedOut) {
  std::string token;
  std::string visual;
  forEachShapedRtlToken(text, token, visual, [&shapedOut](const char* shaped) { shapedOut += shaped; });
}

// UI strings can be redirected from the built-in Latin font to an SD-backed
// CJK fallback. Unlike reader pages, UI screens do not have a PrewarmScope,
// so preload the redirected string before measurement/drawing. Otherwise
// getFallbackCodepoint() can see only the currently resident mini table and
// replace valid CJK glyphs with U+FFFD before the SD miss path gets a chance.
void prewarmSdFallbackGlyphs(const GfxRenderer& renderer, const int fallbackFontId, const char* text,
                             const EpdFontFamily::Style style, const bool metadataOnly) {
  if (text == nullptr || *text == '\\0') return;
  const auto& sdFonts = renderer.getSdCardFonts();
  const auto it = sdFonts.find(fallbackFontId);
  if (it == sdFonts.end() || it->second == nullptr) return;

  const uint8_t styleMask = static_cast<uint8_t>(1u << (static_cast<uint8_t>(style) & 0x03));
  it->second->prewarm(text, styleMask, metadataOnly, /*includeKerning=*/false);
}
}  // namespace
'''
gfx = replace_once(gfx, helper_anchor, helper_replacement, "CJK prewarm helper")

width_anchor = '''  std::string visualBuffer;
  const char* textCursor = resolveVisualText(text, visualBuffer, baseDir);
  if ((style & EpdFontFamily::SMALL_CAPS) != 0) {
'''
width_replacement = '''  std::string visualBuffer;
  const char* textCursor = resolveVisualText(text, visualBuffer, baseDir);

  // A redirected SD fallback must expose the string's glyph metrics before
  // getTextDimensions() walks the font. This is the UI equivalent of the
  // reader's page prewarm and prevents valid CJK codepoints becoming U+FFFD.
  if (resolvedFontId != fontId) {
    prewarmSdFallbackGlyphs(*this, resolvedFontId, textCursor, style, /*metadataOnly=*/true);
  }

  if ((style & EpdFontFamily::SMALL_CAPS) != 0) {
'''
gfx = replace_once(gfx, width_anchor, width_replacement, "CJK width prewarm")

draw_anchor = '''  std::string visualBuffer;
  const char* textCursor = resolveVisualText(text, visualBuffer, baseDir);

  const auto fontIt = fontMap.find(resolvedFontId);
'''
draw_replacement = '''  std::string visualBuffer;
  const char* textCursor = resolveVisualText(text, visualBuffer, baseDir);

  // UI draw calls bypass the reader's PrewarmScope. Batch-load the SD
  // fallback glyph bitmaps now so the render loop sees the real CJK glyphs.
  if (resolvedFontId != fontId) {
    prewarmSdFallbackGlyphs(*this, resolvedFontId, textCursor, style, /*metadataOnly=*/false);
  }

  const auto fontIt = fontMap.find(resolvedFontId);
'''
gfx = replace_once(gfx, draw_anchor, draw_replacement, "CJK draw prewarm")

rotated_anchor = '''  // Route CJK-bearing strings to the fallback font (see resolveTextFontId).
  const int resolvedFontId = resolveTextFontId(fontId, text, style);
  const auto fontIt = fontMap.find(resolvedFontId);
'''
rotated_replacement = '''  // Route CJK-bearing strings to the fallback font (see resolveTextFontId).
  const int resolvedFontId = resolveTextFontId(fontId, text, style);
  if (resolvedFontId != fontId) {
    prewarmSdFallbackGlyphs(*this, resolvedFontId, text, style, /*metadataOnly=*/false);
  }
  const auto fontIt = fontMap.find(resolvedFontId);
'''
gfx = replace_once(gfx, rotated_anchor, rotated_replacement, "CJK rotated prewarm")

gfx_path.write_text(gfx)


epub_path = Path("lib/Epub/Epub.cpp")
epub = epub_path.read_text()
old_release = '''void releaseReaderSdFontCachesBeforeCoverDecode(const GfxRenderer* renderer, const int readerFontId,
                                                const char* reason) {
  if (!renderer) return;
  if (readerFontId <= 0) return;
  if (!renderer->isSdCardFont(readerFontId)) return;

  const auto before = MemoryBudget::snapshot();
  if (!MemoryBudget::shouldReleaseSdFontCachesForEpubInlineImage(before)) return;

  if (!renderer->releaseSdCardFontForLowMemory(readerFontId)) return;

  const auto after = MemoryBudget::snapshot();
  LOG_DBG("EBP", "Released SD font caches before %s: free=%u->%u maxAlloc=%u->%u", reason, before.freeHeap,
          after.freeHeap, before.maxAllocHeap, after.maxAllocHeap);
}
'''
new_release = '''void releaseReaderSdFontCachesBeforeCoverDecode(const GfxRenderer* renderer, const int readerFontId,
                                                const char* reason) {
  if (!renderer) return;

  const auto before = MemoryBudget::snapshot();
  if (!MemoryBudget::shouldReleaseSdFontCachesForEpubInlineImage(before)) return;

  // CJK UI fallback sizes are independent SD-card font objects. UI rendering can
  // leave their mini glyph/bitmap arenas resident before Home generates cover
  // thumbnails. Releasing only the reader font does not recover that heap, so
  // clear every registered SD font cache before the image decoder's peak.
  size_t released = 0;
  for (const auto& entry : renderer->getSdCardFonts()) {
    if (entry.second != nullptr && renderer->releaseSdCardFontForLowMemory(entry.first)) {
      ++released;
    }
  }
  if (released == 0) return;

  const auto after = MemoryBudget::snapshot();
  LOG_DBG("EBP", "Released %u SD font caches before %s: free=%u->%u maxAlloc=%u->%u",
          static_cast<unsigned>(released), reason, before.freeHeap, after.freeHeap, before.maxAllocHeap,
          after.maxAllocHeap);
  (void)readerFontId;
}
'''
epub = replace_once(epub, old_release, new_release, "CJK cover font-cache release")
epub_path.write_text(epub)

print("Applied INKademic 1.7.2 CJK UI fallback/prewarm fixes")
