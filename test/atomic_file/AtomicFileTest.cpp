#include <gtest/gtest.h>

#include <HalStorage.h>

#include "AtomicFile.h"

FakeStorage Storage;

class AtomicFileTest : public testing::Test {
 protected:
  void SetUp() override { Storage.reset(); }
};

TEST_F(AtomicFileTest, CommitKeepsPreviousGenerationAsBackup) {
  Storage.files = {"/data.bin", "/data.bin.tmp"};

  ASSERT_TRUE(AtomicFile::commit("/data.bin", "TEST"));
  EXPECT_TRUE(Storage.exists("/data.bin"));
  EXPECT_TRUE(Storage.exists("/data.bin.bak"));
  EXPECT_FALSE(Storage.exists("/data.bin.tmp"));
}

TEST_F(AtomicFileTest, FailedInstallRestoresCurrentGeneration) {
  Storage.files = {"/data.bin", "/data.bin.tmp"};
  Storage.failRenameFrom = "/data.bin.tmp";
  Storage.failRenameTo = "/data.bin";

  EXPECT_FALSE(AtomicFile::commit("/data.bin", "TEST"));
  EXPECT_TRUE(Storage.exists("/data.bin"));
  EXPECT_FALSE(Storage.exists("/data.bin.bak"));
  EXPECT_TRUE(Storage.exists("/data.bin.tmp"));
}

TEST_F(AtomicFileTest, MultiFileRollbackRestoresPreviousGeneration) {
  Storage.files = {"/data.bin", "/data.bin.tmp"};
  ASSERT_TRUE(AtomicFile::commit("/data.bin", "TEST"));

  ASSERT_TRUE(AtomicFile::rollback("/data.bin", true, "TEST"));
  EXPECT_TRUE(Storage.exists("/data.bin"));
  EXPECT_FALSE(Storage.exists("/data.bin.bak"));
}

TEST_F(AtomicFileTest, PrepareRefusesToOverwriteUnremovableTemporaryFile) {
  Storage.files = {"/data.bin.tmp"};
  Storage.failRemovePath = "/data.bin.tmp";

  EXPECT_FALSE(AtomicFile::prepare("/data.bin", "TEST"));
  EXPECT_TRUE(Storage.exists("/data.bin.tmp"));
}
