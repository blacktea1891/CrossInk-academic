add_executable(AtomicFileTest
  AtomicFileTest.cpp
  ${REPO_ROOT}/src/util/AtomicFile.cpp
)

target_include_directories(AtomicFileTest PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/fakes
  ${REPO_ROOT}/src/util
)

target_link_libraries(AtomicFileTest PRIVATE
  crosspoint_test_common
  GTest::gtest_main
)

gtest_discover_tests(AtomicFileTest)
