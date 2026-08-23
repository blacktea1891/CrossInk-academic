#pragma once

#include <cstdint>

struct MemoryBudgetTestEsp {
  uint32_t freeHeap = 1024U * 1024U;
  uint32_t maxAllocHeap = 1024U * 1024U;

  uint32_t getFreeHeap() const { return freeHeap; }
  uint32_t getMaxAllocHeap() const { return maxAllocHeap; }
};

inline MemoryBudgetTestEsp ESP;
