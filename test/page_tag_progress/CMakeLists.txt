add_executable(PageTagProgressTest
  PageTagProgressTest.cpp
)

target_include_directories(PageTagProgressTest PRIVATE
  ${REPO_ROOT}/src
)

target_link_libraries(PageTagProgressTest PRIVATE
  crosspoint_test_common
  GTest::gtest_main
)

gtest_discover_tests(PageTagProgressTest)
