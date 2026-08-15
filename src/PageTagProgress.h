#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace page_tags {

inline float midpointProgress(const float pageProgress, const uint16_t pageCount) {
  if (pageCount == 0) return 0.0f;
  const float midpoint = pageProgress + 0.5f / static_cast<float>(pageCount);
  return std::clamp(midpoint, 0.0f, 1.0f);
}

inline bool progressFallsOnPage(const float storedProgress, const float pageProgress, const uint16_t pageCount) {
  if (pageCount == 0 || !std::isfinite(storedProgress)) return false;
  const float pageEnd = pageProgress + 1.0f / static_cast<float>(pageCount);
  return storedProgress >= pageProgress && (storedProgress < pageEnd || (pageEnd >= 1.0f && storedProgress <= 1.0f));
}

}  // namespace page_tags
