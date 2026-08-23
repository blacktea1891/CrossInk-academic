add_executable(memory_budget_test MemoryBudgetTest.cpp)
target_include_directories(memory_budget_test PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/stubs
  ${CMAKE_CURRENT_SOURCE_DIR}/../../lib/MemoryBudget
)
target_link_libraries(memory_budget_test PRIVATE crosspoint_test_common GTest::gtest_main)
gtest_discover_tests(memory_budget_test)
