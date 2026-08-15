#include "AtomicFile.h"

#include <HalStorage.h>
#include <Logging.h>

namespace AtomicFile {

std::string temporaryPath(const std::string& targetPath) { return targetPath + ".tmp"; }

std::string backupPath(const std::string& targetPath) { return targetPath + ".bak"; }

bool prepare(const std::string& targetPath, const char* logTag) {
  const std::string tempPath = temporaryPath(targetPath);
  if (!Storage.exists(tempPath.c_str())) return true;
  if (Storage.remove(tempPath.c_str())) return true;
  LOG_ERR(logTag, "Failed to remove stale temporary file: %s", tempPath.c_str());
  return false;
}

bool commit(const std::string& targetPath, const char* logTag) {
  const std::string tempPath = temporaryPath(targetPath);
  const std::string previousPath = backupPath(targetPath);
  const bool hadCurrent = Storage.exists(targetPath.c_str());

  if (hadCurrent && Storage.exists(previousPath.c_str()) && !Storage.remove(previousPath.c_str())) {
    LOG_ERR(logTag, "Failed to remove stale backup: %s", previousPath.c_str());
    return false;
  }
  if (hadCurrent && !Storage.rename(targetPath.c_str(), previousPath.c_str())) {
    LOG_ERR(logTag, "Failed to preserve current file: %s", targetPath.c_str());
    return false;
  }
  if (Storage.rename(tempPath.c_str(), targetPath.c_str())) return true;

  LOG_ERR(logTag, "Failed to install temporary file: %s", targetPath.c_str());
  if (hadCurrent && !Storage.rename(previousPath.c_str(), targetPath.c_str())) {
    LOG_ERR(logTag, "Failed to restore backup after replace failure: %s", previousPath.c_str());
  }
  return false;
}

bool rollback(const std::string& targetPath, const bool hadCurrent, const char* logTag) {
  const std::string previousPath = backupPath(targetPath);
  if (Storage.exists(targetPath.c_str()) && !Storage.remove(targetPath.c_str())) {
    LOG_ERR(logTag, "Failed to remove transaction target during rollback: %s", targetPath.c_str());
    return false;
  }
  if (!hadCurrent) return true;
  if (Storage.rename(previousPath.c_str(), targetPath.c_str())) return true;
  LOG_ERR(logTag, "Failed to restore transaction backup: %s", previousPath.c_str());
  return false;
}

}  // namespace AtomicFile
