#include <gtest/gtest.h>

#include <cmath>

#include "PageTagProgress.h"

TEST(PageTagProgress, FindsSameLocationAfterLayoutChange) {
  const float stored = page_tags::midpointProgress(25.0f / 100.0f, 100);
  EXPECT_TRUE(page_tags::progressFallsOnPage(stored, 12.0f / 50.0f, 50));
  EXPECT_FALSE(page_tags::progressFallsOnPage(stored, 13.0f / 50.0f, 50));
}

TEST(PageTagProgress, IncludesFinalProgressInLastPage) {
  EXPECT_TRUE(page_tags::progressFallsOnPage(1.0f, 9.0f / 10.0f, 10));
}

TEST(PageTagProgress, RejectsInvalidInputs) {
  EXPECT_FALSE(page_tags::progressFallsOnPage(0.5f, 0.5f, 0));
  EXPECT_FALSE(page_tags::progressFallsOnPage(NAN, 0.5f, 10));
  EXPECT_FLOAT_EQ(page_tags::midpointProgress(0.5f, 0), 0.0f);
}
