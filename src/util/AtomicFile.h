#pragma once

#include <string>

namespace AtomicFile {

std::string temporaryPath(const std::string& targetPath);
std::string backupPath(const std::string& targetPath);

// Removes an abandoned temporary file before a new write starts. The backup
// is deliberately retained as the last known-good generation.
bool prepare(const std::string& targetPath, const char* logTag);

// Replaces targetPath with its already-synced temporary file. If a current
// generation exists, it becomes the persistent .bak generation.
bool commit(const std::string& targetPath, const char* logTag);

// Restores the persistent backup after a related multi-file transaction
// fails. If there was no previous generation, removes the newly installed
// target instead.
bool rollback(const std::string& targetPath, bool hadCurrent, const char* logTag);

}  // namespace AtomicFile
