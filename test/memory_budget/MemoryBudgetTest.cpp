#include <gtest/gtest.h>

#include <MemoryBudget.h>

TEST(MemoryBudget, UsesBothHeapDimensionsForGeneralRequirements) {
  EXPECT_TRUE(MemoryBudget::hasHeap({100, 80}, 100, 80));
  EXPECT_FALSE(MemoryBudget::hasHeap({99, 80}, 100, 80));
  EXPECT_FALSE(MemoryBudget::hasHeap({100, 79}, 100, 80));
}

TEST(MemoryBudget, KeepsTextLayoutGateConservativeOnFreeHeap) {
  EXPECT_TRUE(MemoryBudget::hasHeapForEpubTextLayoutStart(
      {MemoryBudget::EPUB_TEXT_LAYOUT_MIN_FREE, 1}));
  EXPECT_FALSE(MemoryBudget::hasHeapForEpubTextLayoutStart(
      {MemoryBudget::EPUB_TEXT_LAYOUT_MIN_FREE - 1, 1024 * 1024}));
}

TEST(MemoryBudget, SelectsSmallerJpegBudgetForInlineImages) {
  const auto jpeg = MemoryBudget::epubInlineImageRequirementForSource("chapter/cover.JPEG");
  const auto png = MemoryBudget::epubInlineImageRequirementForSource("chapter/cover.png");

  EXPECT_EQ(jpeg.minFree, MemoryBudget::EPUB_INLINE_JPEG_MIN_FREE);
  EXPECT_EQ(jpeg.minMaxAlloc, MemoryBudget::EPUB_INLINE_JPEG_MIN_MAX_ALLOC);
  EXPECT_EQ(png.minFree, MemoryBudget::EPUB_INLINE_IMAGE_MIN_FREE);
  EXPECT_EQ(png.minMaxAlloc, MemoryBudget::EPUB_INLINE_IMAGE_MIN_MAX_ALLOC);
}

TEST(MemoryBudget, ReleasesFontCachesBeforeImageDecodeWhenFragmented) {
  EXPECT_FALSE(MemoryBudget::shouldReleaseSdFontCachesForEpubInlineImage(
      {MemoryBudget::EPUB_INLINE_IMAGE_SD_FONT_RELEASE_MIN_FREE,
       MemoryBudget::EPUB_INLINE_IMAGE_SD_FONT_RELEASE_MIN_MAX_ALLOC}));
  EXPECT_TRUE(MemoryBudget::shouldReleaseSdFontCachesForEpubInlineImage(
      {MemoryBudget::EPUB_INLINE_IMAGE_SD_FONT_RELEASE_MIN_FREE - 1,
       MemoryBudget::EPUB_INLINE_IMAGE_SD_FONT_RELEASE_MIN_MAX_ALLOC}));
  EXPECT_TRUE(MemoryBudget::shouldReleaseSdFontCachesForEpubInlineImage(
      {MemoryBudget::EPUB_INLINE_IMAGE_SD_FONT_RELEASE_MIN_FREE,
       MemoryBudget::EPUB_INLINE_IMAGE_SD_FONT_RELEASE_MIN_MAX_ALLOC - 1}));
}

TEST(MemoryBudget, OptionalRebuildRequiresContiguousHeap) {
  ESP.freeHeap = 96U * 1024U;
  ESP.maxAllocHeap = 48U * 1024U;
  EXPECT_TRUE(MemoryBudget::hasHeapForOptionalEpubRebuild("TEST", "chapter prefetch", 4));

  ESP.maxAllocHeap = 48U * 1024U - 1;
  EXPECT_FALSE(MemoryBudget::hasHeapForOptionalEpubRebuild("TEST", "chapter prefetch", 4));
}
